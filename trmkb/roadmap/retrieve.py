"""
trmkb.roadmap.retrieve — KB 사용 연산 (계획서 §2.3-b). 3막 Advanced Roadmap 의 컨텍스트를 만든다.

연산은 결정적(코드)이다. LLM 은 Generator 에서만 쓴다.
  op7 priority   : 노드 우선순위 = 주장 수 + 링크 차수 (+ 수치 주장 가중) → 층별 상위 N 선택
  op2 trend      : 행(layer:category) 요약 + 행 안 주장 타임라인(측도 변화 = 지표 교체)
  op1 grounding  : 선택 노드의 근거 청크 (evidence id 로 인용 가능)
  op4 link       : 수락된 층간 엣지, why→what→how 사슬
  op5 timing     : ES/LS, 선행 관계, infeasible 플래그
  op3 opportunity: 구조적 공백 — drives 받는 what 없는 why, requires/enables 없는 what, open_question/decision 이슈
  op6 issue      : 위험·장벽과 threatens 대상

컨텍스트의 모든 항목은 id 를 달고 나가며, id → 연산 매핑(ops_by_ref)으로 생성 로드맵의 produced_by 를 채운다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..schema import CriticStatus, IssueNode, Layer, NODE_LAYER, NodeBase, NodeType, RelationType, RoadmapOp
from ..store import KBStore


@dataclass
class Context:
    text: str
    ops_by_ref: dict[str, list[RoadmapOp]] = field(default_factory=dict)
    selected_node_ids: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def tag(self, ref: str, op: RoadmapOp) -> None:
        lst = self.ops_by_ref.setdefault(ref, [])
        if op not in lst:
            lst.append(op)


def priority(kb: KBStore, n: NodeBase) -> float:
    claims = kb.claims_for(n.id)
    numeric = sum(1 for c in claims if getattr(c, "value_num", None) is not None or c.type in ("spec", "market_size"))
    timed = sum(1 for c in claims if c.time.start is not None)
    return len(claims) + 1.5 * kb.degree(n.id) + 0.5 * numeric + 0.5 * timed + (2 if "conflict" in n.flags else 0)


def select_nodes(kb: KBStore, per_layer: dict[Layer, int]) -> list[NodeBase]:
    out: list[NodeBase] = []
    for layer, k in per_layer.items():
        nodes = sorted(kb.nodes_by_layer(layer), key=lambda n: -priority(kb, n))
        # 행(category) 다양성: 행마다 최소 1개 먼저
        seen_rows: set[str] = set()
        first: list[NodeBase] = []
        rest: list[NodeBase] = []
        for n in nodes:
            key = n.category or "uncategorized"
            (first if key not in seen_rows else rest).append(n)
            seen_rows.add(key)
        out += (first + rest)[:k]
    return out


def _fmt_time(n: NodeBase) -> str:
    if n.es is None:
        return "t=?"
    return f"t={n.es:.1f}" + (f"–{n.ls:.1f}" if n.ls and n.ls != n.es else "")


def _claim_line(c) -> str:
    extra = ""
    if getattr(c, "measure", None):
        extra = f" [{c.measure}={c.value}{(' ' + c.unit) if getattr(c, 'unit', None) else ''}]"
    elif getattr(c, "dims", None):
        extra = " [" + ", ".join(f"{k}={v}" for k, v in list(c.dims.items())[:5]) + "]"
    t = f" ({c.time.raw})" if c.time.raw else ""
    return f"{c.doc_date.year}/{c.modality.value}{extra}: {c.text[:200]}{t}"


def build_context(kb: KBStore, *, per_layer: dict[Layer, int] | None = None, max_claims_per_node: int = 3,
                  max_evidence_per_node: int = 1, max_rows: int = 30, max_chars: int = 70_000,
                  summary_chars: int = 300) -> Context:
    per_layer = per_layer or {Layer.WHY: 14, Layer.WHAT: 20, Layer.HOW: 24, Layer.RESOURCE: 10, Layer.CROSS: 16}
    ctx = Context(text="")
    sel = select_nodes(kb, per_layer)
    sel_ids = {n.id for n in sel}
    ctx.selected_node_ids = [n.id for n in sel]
    parts: list[str] = []

    # ---- op2: row summaries (행 요약 + 측도 변화)
    parts.append("## [op2] Roadmap rows — summaries and claim trajectories")
    rows: dict[str, list[NodeBase]] = defaultdict(list)
    for n in sel:
        rows[f"{NODE_LAYER[NodeType(n.type)].value}:{n.category or 'uncategorized'}"].append(n)
    # 행 우선순위 = 행 안 노드 우선순위 합 (why/what/how 행을 cross 행보다 우대)
    def row_rank(key: str) -> float:
        base = sum(priority(kb, n) for n in rows[key])
        return base * (0.6 if key.startswith("cross:") else 1.0)
    for key in sorted(rows, key=lambda k: -row_rank(k))[:max_rows]:
        s = kb.summaries.get(key)
        line = f"- row {key}" + (f" — {s.text[:summary_chars]}" if s else "")
        parts.append(line)
        for n in rows[key]:
            measures = kb.measures_for(n.id)
            if len({m for _, m in measures}) > 1:
                seq = " → ".join(f"{d.year}:{m}" for d, m in measures)
                parts.append(f"  - metric change on {n.id} ({n.label}): {seq}")
                ctx.tag(n.id, RoadmapOp.TREND)
        ctx.tag(key, RoadmapOp.TREND)

    # ---- op1 + op5: nodes with claims, evidence, timing
    parts.append("\n## [op1/op5] Nodes (id | layer/type | label | timing | flags) with claims and evidence ids")
    for n in sel:
        layer = NODE_LAYER[NodeType(n.type)].value
        flags = f" flags={','.join(n.flags)}" if n.flags else ""
        kind = f"/{n.kind.value}" if isinstance(n, IssueNode) else ""
        parts.append(f"- {n.id} | {layer}/{n.type}{kind} | {n.label} | {_fmt_time(n)}{flags} | row={n.category or '-'}")
        ctx.tag(n.id, RoadmapOp.GROUNDING)
        if n.es is not None:
            ctx.tag(n.id, RoadmapOp.TIMING)
        for c in kb.claims_for(n.id)[-max_claims_per_node:]:
            parts.append(f"    claim {c.id}: {_claim_line(c)}" + (" [CONFLICT]" if c.conflicts_with else ""))
            ctx.tag(c.id, RoadmapOp.GROUNDING)
        for ev in kb.evidence_for_node(n.id)[:max_evidence_per_node]:
            parts.append(f"    evidence {ev.id} (doc {ev.doc_id[:28]}): \"{ev.text[:220]}\"")
            ctx.tag(ev.id, RoadmapOp.GROUNDING)

    # ---- op4: accepted links among selected nodes + why→what→how chains
    parts.append("\n## [op4] Accepted links (src → dst, relation, condition)")
    acc = [e for e in kb.edges.values() if e.critic_status == CriticStatus.ACCEPTED and e.src in sel_ids and e.dst in sel_ids]
    for e in acc[:150]:
        cond = f" if {e.condition}" if e.condition else ""
        lag = f" lag={e.lag_years}y" if e.lag_years else ""
        parts.append(f"- {e.id}: {e.src} --{e.type.value}--> {e.dst}{cond}{lag}")
        ctx.tag(e.id, RoadmapOp.LINK); ctx.tag(e.src, RoadmapOp.LINK); ctx.tag(e.dst, RoadmapOp.LINK)
    chains = _chains(kb, sel_ids)
    if chains:
        parts.append("Chains why → what → how:")
        for a, b, c in chains[:25]:
            parts.append(f"- {a} ({kb.nodes[a].label}) → {b} ({kb.nodes[b].label}) → {c} ({kb.nodes[c].label})")
            for x in (a, b, c):
                ctx.tag(x, RoadmapOp.LINK)

    # ---- op5: precedes order and infeasible
    prec = [e for e in kb.edges.values() if e.critic_status == CriticStatus.ACCEPTED and e.type == RelationType.PRECEDES]
    if prec:
        parts.append("\n## [op5] Temporal order (precedes) and feasibility flags")
        for e in prec[:60]:
            parts.append(f"- {e.src} ({kb.nodes[e.src].label}, {_fmt_time(kb.nodes[e.src])}) precedes {e.dst} ({kb.nodes[e.dst].label}, {_fmt_time(kb.nodes[e.dst])})")
            ctx.tag(e.src, RoadmapOp.TIMING); ctx.tag(e.dst, RoadmapOp.TIMING)
    infeasible = [n for n in kb.nodes.values() if "infeasible" in n.flags]
    for n in infeasible[:20]:
        parts.append(f"- INFEASIBLE: {n.id} ({n.label}) needs a technology whose earliest start is later than its own ({_fmt_time(n)})")
        ctx.tag(n.id, RoadmapOp.TIMING)

    # ---- op3: structural gaps
    gaps = structural_gaps(kb)
    parts.append("\n## [op3] Structural gaps (opportunities for new roadmap items)")
    for kind, n, note in gaps[:30]:
        parts.append(f"- gap/{kind}: {n.id} ({NODE_LAYER[NodeType(n.type)].value}/{n.type} \"{n.label}\") — {note}")
        ctx.tag(n.id, RoadmapOp.OPPORTUNITY)

    # ---- op6: issues
    issues = [n for n in kb.nodes.values() if n.type == "issue"]
    issues.sort(key=lambda n: -priority(kb, n))
    parts.append("\n## [op6] Issues (risks, barriers, decisions, open questions) and what they threaten")
    for n in issues[:25]:
        targets = [kb.nodes[e.dst].label for e in kb.out_edges(n.id, accepted_only=True) if e.type in (RelationType.THREATENS, RelationType.ADDRESSED_BY, RelationType.DECIDED_OVER)]
        parts.append(f"- {n.id} [{n.kind.value if isinstance(n, IssueNode) else 'issue'}] {n.label}" + (f" → {', '.join(targets[:4])}" if targets else ""))
        ctx.tag(n.id, RoadmapOp.ISSUE)

    # 연산 태그 전파: 노드에 붙은 연산을 그 노드의 근거·주장 id 에도 붙인다 (Generator 는 주로 evidence id 를 인용하므로)
    for n in sel:
        ops = ctx.ops_by_ref.get(n.id, [])
        for ev in kb.evidence_for_node(n.id):
            for op in ops:
                ctx.tag(ev.id, op)
        for c in kb.claims_for(n.id):
            for op in ops:
                ctx.tag(c.id, op)
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (context truncated)"
    ctx.text = text
    ctx.stats = {"selected_nodes": len(sel), "rows": len(rows), "accepted_links": len(acc), "chains": len(chains),
                 "gaps": len(gaps), "issues": min(len(issues), 25), "chars": len(text)}
    return ctx


def _chains(kb: KBStore, ids: set[str]) -> list[tuple[str, str, str]]:
    out = []
    for e1 in kb.edges.values():
        if e1.critic_status != CriticStatus.ACCEPTED or e1.type != RelationType.DRIVES or e1.src not in ids:
            continue
        for e2 in kb.out_edges(e1.dst, accepted_only=True):
            if e2.type in (RelationType.REQUIRES,) and NODE_LAYER[NodeType(kb.nodes[e2.dst].type)] == Layer.HOW:
                out.append((e1.src, e1.dst, e2.dst))
        for e2 in kb.in_edges(e1.dst, accepted_only=True):
            if e2.type == RelationType.ENABLES and NODE_LAYER[NodeType(kb.nodes[e2.src].type)] == Layer.HOW:
                out.append((e1.src, e1.dst, e2.src))
    return out


def structural_gaps(kb: KBStore) -> list[tuple[str, NodeBase, str]]:
    """why 있고 what 없음 / what 있고 how 없음 / 열린 질문·결정."""
    gaps: list[tuple[str, NodeBase, str]] = []
    for n in sorted(kb.nodes.values(), key=lambda n: -priority(kb, n)):
        layer = NODE_LAYER[NodeType(n.type)]
        if layer == Layer.WHY and n.type == "driver":
            if not any(e.type == RelationType.DRIVES and e.critic_status == CriticStatus.ACCEPTED for e in kb.out_edges(n.id)):
                gaps.append(("why-without-what", n, "driver with no product/opportunity responding to it"))
        elif layer == Layer.WHAT and n.type == "opportunity":
            has_how = any(e.type == RelationType.REQUIRES and e.critic_status == CriticStatus.ACCEPTED for e in kb.out_edges(n.id)) or \
                      any(e.type == RelationType.ENABLES and e.critic_status == CriticStatus.ACCEPTED for e in kb.in_edges(n.id))
            if not has_how:
                gaps.append(("what-without-how", n, "product/opportunity with no supporting technology linked"))
        elif isinstance(n, IssueNode) and n.kind.value in ("open_question", "decision", "assumption"):
            gaps.append((f"issue/{n.kind.value}", n, (kb.claims_for(n.id)[-1].text[:160] if kb.claims_for(n.id) else n.description[:160])))
    return gaps
