"""
Critic — (a) 층 규칙 위반은 결정적으로 반려, (b) 근거 충분성은 LLM 판정(제안자와 다른 모델),
(c) 같은 노드의 새 주장이 기존 주장과 상충하는지 판정해 conflict 플래그.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLM
from ..schema import ClaimBase, CriticStatus, Edge, NodeBase
from ..store import KBStore
from .linker import layer_ok

CRITIC_SYSTEM = "You are the Critic agent of a technology-roadmap knowledge base. You judge whether proposed links are supported by evidence, and whether claims conflict. Be strict but fair. JSON only."
EDGE_USER = """Judge each proposed link. Accept only if the evidence text supports the stated relation in the stated direction (or it is a well-established, explicitly stated dependency). Reject if the evidence is absent, merely co-occurring, or contradicts. Hold if plausible but the text is insufficient.

Proposed links:
{items}

Keep each reason under 25 words.

Return JSON: {{"verdicts": [{{"edge_id": str, "verdict": "accept"|"reject"|"hold", "reason": str}}]}}"""

CONFLICT_USER = """A knowledge-base row "{label}" has these earlier claims (date: text):
{old}

New claim ({doc_date}): {new}

Does the new claim CONFLICT with any earlier claim (same quantity/milestone with a different value or date that cannot both be true, or an explicit contradiction)? A later revision of a target counts as a conflict (flag it). A different quantity or a refinement does not.

Return JSON: {{"conflicts": [{{"claim_id": str, "reason": str}}]}}"""


class Verdict(BaseModel):
    edge_id: str
    verdict: Literal["accept", "reject", "hold"]
    reason: str = ""


class VerdictsOut(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


class ConflictOut(BaseModel):
    conflicts: list[dict] = Field(default_factory=list)


class Critic:
    def __init__(self, llm: LLM, model: str, kb: KBStore):
        self.llm, self.model, self.kb = llm, model, kb

    def judge_edges(self, proposals: list[tuple[Edge, str]]) -> list[tuple[Edge, str]]:
        """반환: 판정이 적용된 (edge, reason) 목록."""
        results: list[tuple[Edge, str]] = []
        to_llm: list[tuple[Edge, str]] = []
        for edge, quote in proposals:
            ok, why = layer_ok(edge.type, self.kb.nodes[edge.src], self.kb.nodes[edge.dst])
            if not ok:
                edge.critic_status, edge.critic_reason = CriticStatus.REJECTED, why
                results.append((edge, why))
            elif not quote.strip():
                edge.critic_status, edge.critic_reason = CriticStatus.REJECTED, "근거 인용 없음"
                results.append((edge, edge.critic_reason))
            else:
                to_llm.append((edge, quote))
        if to_llm:
            items = "\n".join(
                f"- edge_id={e.id}: [{self.kb.nodes[e.src].label}] --{e.type.value}--> [{self.kb.nodes[e.dst].label}]"
                f"{' (if ' + e.condition + ')' if e.condition else ''}\n  evidence: \"{q[:400]}\""
                for e, q in to_llm)
            out = self.llm.structured(self.model, CRITIC_SYSTEM, EDGE_USER.format(items=items), VerdictsOut,
                                      purpose="critic_edges", max_tokens=2500)
            vmap = {v.edge_id: v for v in out.verdicts}
            for e, q in to_llm:
                v = vmap.get(e.id)
                if v is None:
                    e.critic_status, e.critic_reason = CriticStatus.HOLD, "판정 누락"
                else:
                    e.critic_status = {"accept": CriticStatus.ACCEPTED, "reject": CriticStatus.REJECTED, "hold": CriticStatus.HOLD}[v.verdict]
                    e.critic_reason = v.reason
                results.append((e, e.critic_reason or ""))
        return results

    def check_conflict(self, node: NodeBase, new_claim: ClaimBase, older: list[ClaimBase]) -> list[tuple[str, str]]:
        comparable = [c for c in older if c.type == new_claim.type or c.type in ("statement",) or new_claim.type == "statement"]
        if not comparable:
            return []
        old = "\n".join(f"- {c.id} ({c.doc_date}): {c.text}" for c in comparable[-8:])
        out = self.llm.structured(self.model, CRITIC_SYSTEM,
                                  CONFLICT_USER.format(label=node.label, old=old, doc_date=new_claim.doc_date, new=new_claim.text),
                                  ConflictOut, purpose="critic_conflict", max_tokens=800)
        valid = {c.id for c in comparable}
        return [(c.get("claim_id"), c.get("reason", "")) for c in out.conflicts if c.get("claim_id") in valid]
