"""
Linker — 이 문서에서 생성·갱신된 노드와 이웃 후보 사이의 층간 링크를 제안한다 (문서당 1회 호출).

허용 관계 (층 규칙):
  drives: why→what | requires: what→how, how→how, what→what(상위→하위) | enables: how→what, resource→any
  precedes: 같은 층 (시간 순서, lag) | part_of: 같은 층 | competes_with: actor/how/what↔ 동류
  threatens: issue→any | addressed_by: issue→(action 주장을 가진 노드) | provides: actor→how/resource/what
  endorsed_by: what/why→actor | decided_over: issue(decision)→선택안/기각안
why→how 직결은 금지(Critic이 반려).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLM
from ..schema import Derivation, Edge, Layer, NodeBase, NodeType, NODE_LAYER, RelationType, Agent
from ..store import KBStore
from .embed import Index

LINKER_SYSTEM = "You are the Linker agent of a technology-roadmap knowledge base. Propose typed, evidence-backed links between knowledge-base rows. JSON only."
LINKER_USER = """Document "{title}" ({doc_date}) touched these rows (id | layer/type | label — description):
{touched}

Candidate related rows already in the knowledge base:
{cands}

Relation rules (direction matters): drives why→what; requires what→how or how→how or what→what; enables how→what, how→how or resource→any;
precedes same layer (earlier→later, give lag_years if stated); part_of same layer (part→whole); threatens issue→any;
addressed_by issue→the row whose action addresses it; provides actor→how/resource/what; competes_with between peers;
decided_over issue(decision)→chosen option (also list rejected in condition). NEVER link why directly to how.
When a technology/capability (how) supports a product, milestone or target (what), use enables how→what — never requires how→what.
Do not propose links between two rows that are the same thing under different names.

Propose only links that the document text supports or clearly implies. For each give an evidence_quote (verbatim from the document excerpts below), an argument scheme tag (e.g. "means-end", "cause-effect", "temporal", "part-whole", "authority"), optional condition ("if ...") and lag_years.

Document excerpts:
\"\"\"{excerpts}\"\"\"

Return JSON: {{"edges": [{{"src": id, "dst": id, "type": str, "scheme": str, "condition": str|null, "lag_years": number|null, "evidence_quote": str, "rationale": str}}]}}"""

ALLOWED = {
    RelationType.DRIVES: {(Layer.WHY, Layer.WHAT)},
    RelationType.REQUIRES: {(Layer.WHAT, Layer.HOW), (Layer.HOW, Layer.HOW), (Layer.WHAT, Layer.WHAT)},
    RelationType.ENABLES: {(Layer.HOW, Layer.WHAT), (Layer.HOW, Layer.HOW), (Layer.RESOURCE, Layer.WHY), (Layer.RESOURCE, Layer.WHAT),
                           (Layer.RESOURCE, Layer.HOW), (Layer.RESOURCE, Layer.RESOURCE), (Layer.RESOURCE, Layer.CROSS)},
}
SAME_LAYER = {RelationType.PRECEDES, RelationType.PART_OF, RelationType.COMPETES_WITH}
CROSS_SRC = {RelationType.THREATENS, RelationType.ADDRESSED_BY, RelationType.PROVIDES, RelationType.DECIDED_OVER}


def layer_ok(rel: RelationType, src: NodeBase, dst: NodeBase) -> tuple[bool, str]:
    ls, ld = NODE_LAYER[NodeType(src.type)], NODE_LAYER[NodeType(dst.type)]
    if ls == Layer.WHY and ld == Layer.HOW:
        return False, "why→how 층 위반"
    if rel in ALLOWED:
        return ((ls, ld) in ALLOWED[rel]), f"{rel.value} {ls.value}→{ld.value} 허용 안 됨"
    if rel in SAME_LAYER:
        return (ls == ld), f"{rel.value}는 같은 층만"
    if rel == RelationType.THREATENS:
        return (src.type == "issue"), "threatens는 issue에서만"
    if rel == RelationType.ADDRESSED_BY:
        return (src.type == "issue"), "addressed_by는 issue에서만"
    if rel == RelationType.PROVIDES:
        return (src.type == "actor"), "provides는 actor에서만"
    if rel == RelationType.ENDORSED_BY:
        return (dst.type == "actor"), "endorsed_by는 actor로만"
    if rel == RelationType.DECIDED_OVER:
        return (src.type == "issue"), "decided_over는 issue에서만"
    return True, ""


class EdgeOut(BaseModel):
    src: str
    dst: str
    type: str
    scheme: str | None = None
    condition: str | None = None
    lag_years: float | None = None
    evidence_quote: str = ""
    rationale: str = ""


class LinkerOut(BaseModel):
    edges: list[EdgeOut] = Field(default_factory=list)


class Linker:
    def __init__(self, llm: LLM, model: str, kb: KBStore, index: Index, *, k_neighbors: int = 4, max_cands: int = 18):
        self.llm, self.model, self.kb, self.index = llm, model, kb, index
        self.k, self.max_cands = k_neighbors, max_cands

    def propose(self, touched: list[NodeBase], *, doc_id: str, title: str, doc_date, excerpts: str) -> list[tuple[Edge, str]]:
        if not touched:
            return []
        touched_ids = {n.id for n in touched}
        cand_ids: dict[str, float] = {}
        for n in touched:
            for cid, s in self.index.search(f"{n.label}. {n.description}", k=self.k + 1, filt=lambda i, m: i not in touched_ids):
                cand_ids[cid] = max(cand_ids.get(cid, 0), s)
        cands = [self.kb.nodes[c] for c, _ in sorted(cand_ids.items(), key=lambda x: -x[1])[: self.max_cands] if c in self.kb.nodes]
        fmt = lambda n: f"- {n.id} | {NODE_LAYER[NodeType(n.type)].value}/{n.type} | {n.label} — {(n.description or '')[:140]}"  # noqa: E731
        out = self.llm.structured(self.model, LINKER_SYSTEM,
                                  LINKER_USER.format(title=title, doc_date=doc_date, touched="\n".join(fmt(n) for n in touched),
                                                     cands="\n".join(fmt(n) for n in cands) or "(none)", excerpts=excerpts[:9000]),
                                  LinkerOut, purpose="linker", max_tokens=3000)
        edges: list[tuple[Edge, str]] = []
        for e in out.edges:
            if e.src not in self.kb.nodes or e.dst not in self.kb.nodes or e.src == e.dst:
                continue
            try:
                rel = RelationType(e.type.strip().lower())
            except ValueError:
                continue
            if self.kb.find_edge(e.src, e.dst, rel):
                continue
            edge = Edge(src=e.src, dst=e.dst, type=rel, derivation=Derivation.DERIVED, condition=e.condition,
                        lag_years=e.lag_years, scheme=e.scheme, proposed_by=Agent.LINKER, created_by_doc=doc_id)
            edges.append((edge, e.evidence_quote or e.rationale))
        return edges
