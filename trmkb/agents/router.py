"""
Router — 후보 노드를 기존 역량 행에 병합할지, 새로 만들지, 보류할지 결정하고 어느 구조에 쓸지 정한다.

  유사도 ≥ merge_hi  → 병합 (결정적)
  merge_lo ≤ 유사도 < merge_hi → LLM 판단 (후보 ≤3개 제시)
  유사도 < merge_lo  → 신규

병합·신규 모두: evidence(①) 기록, claim 타임라인(③) 추가, 행 요약 dirty(②), 시간이 있으면 time_index(⑤).
모든 판단은 RouterDecision 으로 router_log.jsonl 에 남는다 (연구의 핵심 관찰 대상).
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from ..llm import LLM
from ..schema import (
    ActionClaim, ActorNode, ActorRole, CapabilityClaim, CapabilityNode, ClaimBase, ComparisonClaim, ComponentNode,
    DriverNode, EnablerKind, EnablerNode, IssueKind, IssueNode, MarketSizeClaim, MaturityClaim, MilestoneNode, Modality,
    NeedNode, NodeBase, NodeType, NODE_LAYER, OpportunityNode, PriorityClaim, RouterDecision, SpecClaim, Stage,
    StakeholderType, StatementClaim, SteepCategory, StructureTarget, VisionNode,
)
from ..store import KBStore
from .embed import Index
from .reader import Proposal, claim_time

NODE_CLS = {"driver": DriverNode, "need": NeedNode, "vision": VisionNode, "opportunity": OpportunityNode,
            "milestone": MilestoneNode, "capability": CapabilityNode, "component": ComponentNode,
            "enabler": EnablerNode, "actor": ActorNode, "issue": IssueNode}

ROUTER_SYSTEM = "You are the Router agent of a technology-roadmap knowledge base. Decide whether a newly extracted item is the same knowledge-base row as an existing one. JSON only."
ROUTER_USER = """New item ({node_type}): label "{label}", category "{category}", description: {description}
Evidence: "{quote}"

Existing candidate rows:
{cands}

Rules: merge only if the new item refers to the SAME capability/product/driver/entity (not merely related, not a sub-part, not a different generation unless the row is explicitly the family). If it is a component of a candidate, choose create. If undecidable from the text, choose hold.

Return JSON: {{"decision": "merge"|"create"|"hold", "target_id": str|null, "reasoning": str (under 30 words)}}"""


class RouterOut(BaseModel):
    decision: Literal["merge", "create", "hold"]
    target_id: str | None = None
    reasoning: str = ""


def _enum_or_none(enum_cls, v):
    if v is None:
        return None
    try:
        return enum_cls(str(v).strip().lower().replace(" ", "_"))
    except ValueError:
        return None


def build_node(p: Proposal, doc_id: str) -> NodeBase:
    cls = NODE_CLS[p.node_type]
    kw = dict(label=p.label, description=p.description, category=(p.category or "").strip().lower() or None, created_by_doc=doc_id)
    if cls is DriverNode:
        kw["steep"] = _enum_or_none(SteepCategory, p.steep)
    elif cls is NeedNode:
        kw["stakeholder_type"] = _enum_or_none(StakeholderType, p.stakeholder_type)
    elif cls is EnablerNode:
        kw["kind"] = _enum_or_none(EnablerKind, p.enabler_kind)
    elif cls is ActorNode:
        roles = [r for r in (_enum_or_none(ActorRole, x) for x in (p.actor_roles or [])) if r]
        kw["roles"] = roles
    elif cls is IssueNode:
        kw["kind"] = _enum_or_none(IssueKind, p.issue_kind) or IssueKind.RISK
    elif cls is MilestoneNode:
        kw["milestone_stage"] = _enum_or_none(Stage, p.milestone_stage)
    return cls(**kw)


def build_claim(p: Proposal, node_id: str, doc_id: str, doc_date: date, evidence_id: str | None) -> ClaimBase | None:
    c = p.claim
    if c is None:
        return None
    base = dict(node_id=node_id, text=c.text, speaker=c.speaker, modality=_enum_or_none(Modality, c.modality) or Modality.PLANNED,
                time=claim_time(c, doc_date), doc_id=doc_id, doc_date=doc_date, evidence_id=evidence_id)
    t = c.claim_type
    if t == "capability_claim" and c.measure and c.value:
        num = None
        try:
            num = float(str(c.value).replace(",", "").replace("%", "").split()[0])
        except (ValueError, IndexError):
            pass
        return CapabilityClaim(measure=c.measure, value=str(c.value), value_num=num, unit=c.unit, **base)
    if t == "spec":
        return SpecClaim(dims=c.dims or {}, segment=c.segment, stage=_enum_or_none(Stage, c.stage), **base)
    if t == "market_size":
        return MarketSizeClaim(volume=c.volume, unit_price=c.unit_price, total=c.total, segment=c.segment, year=c.year, **base)
    if t == "maturity":
        return MaturityClaim(trl=c.trl if c.trl and 1 <= c.trl <= 9 else None, stage=_enum_or_none(Stage, c.stage), **base)
    if t == "comparison":
        return ComparisonClaim(vs_label=c.vs_label, dims=c.dims or {}, **base)
    if t == "action":
        return ActionClaim(responsible_actor=c.responsible_actor, due=claim_time(type(c)(text="", time_raw=c.due), doc_date) if c.due else None, **base)
    if t == "priority":
        return PriorityClaim(score=0.0, method="mention", **base)
    return StatementClaim(**base)


class Router:
    def __init__(self, llm: LLM, model: str, kb: KBStore, index: Index, *, merge_hi: float = 0.80, merge_lo: float = 0.55):
        self.llm, self.model, self.kb, self.index = llm, model, kb, index
        self.merge_hi, self.merge_lo = merge_hi, merge_lo
        self.dirty_rows: set[str] = set()
        # 기존 노드 색인
        self.index.add_many([(n.id, _node_text(n), {"type": n.type, "layer": NODE_LAYER[NodeType(n.type)].value})
                             for n in kb.nodes.values()])

    def route(self, p: Proposal, *, doc_id: str, quote: str) -> tuple[RouterDecision, NodeBase, bool]:
        """반환: (판단, 대상 노드, 신규 여부)."""
        q = f"{p.label}. {p.description}"
        same_type = lambda id, m: m["type"] == p.node_type  # noqa: E731
        cands = self.index.search(q, k=3, filt=same_type)
        decision: Literal["merge", "create", "hold"]
        target: str | None = None
        reasoning = ""
        # 유형이 달라도 사실상 같은 항목(라벨 동일 또는 매우 높은 유사도)은 병합 (how/what 중복 방지)
        any_type = self.index.search(q, k=1)
        exact = next((n for n in self.kb.nodes.values() if n.label.lower() == p.label.lower()), None)
        if exact is not None:
            cands = [(exact.id, 1.0)] + [c for c in cands if c[0] != exact.id]
        elif any_type and any_type[0][1] >= 0.92 and (not cands or any_type[0][0] != cands[0][0]):
            cands = [any_type[0]] + cands
        if cands and cands[0][1] >= self.merge_hi:
            decision, target, reasoning = "merge", cands[0][0], f"sim {cands[0][1]:.2f} ≥ {self.merge_hi}"
        elif cands and cands[0][1] >= self.merge_lo:
            cand_txt = "\n".join(f"- id={cid} (sim {s:.2f}): {self.kb.nodes[cid].label} — {self.kb.nodes[cid].description[:160]}"
                                 for cid, s in cands if s >= self.merge_lo)
            out = self.llm.structured(self.model, ROUTER_SYSTEM,
                                      ROUTER_USER.format(node_type=p.node_type, label=p.label, category=p.category or "",
                                                         description=p.description, quote=quote[:300], cands=cand_txt),
                                      RouterOut, purpose="router", max_tokens=700)
            decision, reasoning = out.decision, out.reasoning
            target = out.target_id if out.decision == "merge" and out.target_id in self.kb.nodes else None
            if decision == "merge" and target is None:
                decision = "create"
        else:
            decision, reasoning = "create", f"best sim {cands[0][1]:.2f} < {self.merge_lo}" if cands else "no candidates"
        if decision == "hold":
            decision = "create"   # 보류는 신규로 두되 사유를 남김 (후속 care 단계에서 병합 검토)
            reasoning = "HOLD→create: " + reasoning

        structures = [StructureTarget.EVIDENCE, StructureTarget.GRAPH, StructureTarget.SUMMARY]
        if decision == "merge":
            node = self.kb.nodes[target]
            if p.label.lower() != node.label.lower() and p.label not in node.aliases:
                node.aliases.append(p.label)
            if not node.description and p.description:
                node.description = p.description
            if not node.category and p.category:
                node.category = p.category.strip().lower()
            self.kb.upsert_node(node)
            new = False
        else:
            node = build_node(p, doc_id)
            self.kb.upsert_node(node)
            self.index.add(node.id, _node_text(node), type=node.type, layer=NODE_LAYER[NodeType(node.type)].value)
            new = True
        if p.claim and (p.claim.time_start is not None or p.claim.time_raw):
            structures.append(StructureTarget.TIME_INDEX)
        rd = RouterDecision(doc_id=doc_id, proposal_label=p.label, proposal_type=NodeType(p.node_type), decision=decision,
                            target_node_id=node.id, candidates=[(c, round(s, 3)) for c, s in cands], structures=structures,
                            reasoning=reasoning)
        self.kb.log_router(rd)
        self.dirty_rows.add(row_key(node))
        return rd, node, new


def _node_text(n: NodeBase) -> str:
    return f"{n.label}. {n.description or ''}".strip()


def row_key(n: NodeBase) -> str:
    return f"{NODE_LAYER[NodeType(n.type)].value}:{n.category or 'uncategorized'}"
