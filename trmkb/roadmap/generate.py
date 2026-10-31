"""
trmkb.roadmap.generate — 로드맵 생성기 (1막 initial / 3막 advanced 공용).

고정되는 것: 기업 소개(BRIEF), 지평, 출력 스키마, 지시문, 모델, 온도.
바뀌는 것: context 블록 하나 (initial=None, advanced=KB 연산 결과 §2.3-b).
prompt_hash 는 context 를 제외한 고정 부분의 해시 → 두 조건이 같은 프롬프트임을 증명.

출력은 RoadmapOut(LLM용 단순 스키마) → trmkb.schema.Roadmap 으로 변환.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLM
from ..schema import Layer, RelationType, Roadmap, RoadmapEdge, RoadmapNode, RoadmapOp

DEFAULT_MODEL = "openai/gpt-4.1"   # knowledge cutoff 2024-06 → 2025-06 가속 로드맵을 모름 (사전지식 오염 최소)
HORIZON = (2025.0, 2030.0)
COMPANY = "IonQ"

# 2024-12-31 시점의 공개 상식 수준 소개. 두 조건에 동일하게 투입.
BRIEF = (
    "IonQ (NYSE: IONQ) is a publicly listed trapped-ion quantum computing company headquartered in "
    "College Park, Maryland, with a manufacturing facility in Bothell, Washington. As of the end of 2024 its "
    "commercial systems include Forte and Forte Enterprise, with the next-generation Tempo system in "
    "development. It reports performance in algorithmic qubits (#AQ), reached #AQ 36 on Forte in 2024, and "
    "is targeting #AQ 64. It is developing photonic interconnects for modular, networked quantum computers and "
    "has announced acquisitions in quantum networking (Entangled Networks, Qubitekk, and an agreement to acquire "
    "ID Quantique). Its systems are offered through AWS Braket, Azure Quantum and Google Cloud and are also sold "
    "on-premise to government and enterprise customers."
)

LAYER_GUIDE = {
    "why": "market drivers, regulation, customer needs, competitive pressure, vision (categories e.g. security/PQC, "
           "export control, enterprise demand, government programs, competitor pressure, benchmark standards)",
    "what": "products, system generations, milestones, service offerings, target specifications "
            "(categories e.g. scale, fidelity, error correction/logical qubits, modularity/interconnect, "
            "networking products, cloud/on-prem offerings, commercialization)",
    "how": "technologies, components, architectures, methods that realize the what layer "
           "(categories e.g. ion species, control technology, trap chips, photonic interconnect, error correction "
           "codes, manufacturing/foundry, software/compilers)",
    "resource": "enablers: funding, facilities, standards, partnerships, regulation approvals, skills",
}

SYSTEM = (
    "You are a technology roadmapping analyst following the Cambridge IfM T-Plan method (why / what / how layers "
    "linked over time). Produce a company technology roadmap as structured JSON only."
)

INSTRUCTIONS = """Build a technology roadmap for {company} for the horizon {h0:.0f}-{h1:.0f}.

Layers and what belongs in each:
- why: {why}
- what: {what}
- how: {how}
- resource: {resource}

Requirements:
1. 24 to 40 nodes in total; every layer must have at least 4 nodes. Each node has a short label (<= 10 words), a
   one-sentence description, a category (the roadmap row it belongs to, 1-3 words), and a time window
   start/end as decimal years within the horizon (e.g. 2026.5 = mid-2026). Use the half-year as resolution.
2. 20 to 60 typed edges among the nodes: "drives" (why -> what), "requires" (what -> how, how -> how),
   "enables" (how -> what, resource -> any), "precedes" (earlier -> later, same layer). No why -> how edges.
3. Where a node depends on evidence you have, cite it in "evidence_ids" using the ids given in the context
   block (if any). Leave the list empty when you have no evidence.
4. Flag a node with "infeasible" in "flags" if its technology (how) arrives later than the product (what) that
   needs it; flag "conflict" if sources disagree about it.
5. Be specific to {company}: use its actual product names, metrics and partners where known; do not invent
   named partners or numbers that are not in the brief or context.
6. Include only items of roadmap significance (drivers, needs, products, milestones, technologies, enabling
   resources). Exclude routine operations (audits, checklists, procedures, staffing minutiae) unless they gate a
   roadmap item.

Company brief (as of 2024-12-31):
{brief}
"""

CONTEXT_HEADER = """
Knowledge base context (structured, derived from documents dated on or before 2024-12-31). Each item carries an
id you may cite in evidence_ids. Prefer this context over your prior knowledge when they disagree.
"""

OUTPUT_SPEC = """
Return JSON: {"nodes": [{"id": "n1", "label": str, "layer": "why|what|how|resource", "category": str,
"description": str, "start": number, "end": number, "evidence_ids": [str], "flags": [str]}],
"edges": [{"src": "n1", "dst": "n2", "type": "drives|requires|enables|precedes"}]}"""


class _NodeOut(BaseModel):
    id: str
    label: str
    layer: Literal["why", "what", "how", "resource"]
    category: str = ""
    description: str = ""
    start: float
    end: float
    evidence_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class _EdgeOut(BaseModel):
    src: str
    dst: str
    type: Literal["drives", "requires", "enables", "precedes"]


class RoadmapOut(BaseModel):
    nodes: list[_NodeOut]
    edges: list[_EdgeOut]


def fixed_prompt(company: str = COMPANY, horizon: tuple[float, float] = HORIZON, brief: str = BRIEF) -> str:
    return INSTRUCTIONS.format(company=company, h0=horizon[0], h1=horizon[1], brief=brief, **LAYER_GUIDE) + OUTPUT_SPEC


def prompt_hash(company: str = COMPANY, horizon: tuple[float, float] = HORIZON, brief: str = BRIEF) -> str:
    return hashlib.sha256((SYSTEM + fixed_prompt(company, horizon, brief)).encode("utf-8")).hexdigest()[:16]


def build_user_prompt(context: str | None, company: str = COMPANY, horizon: tuple[float, float] = HORIZON,
                      brief: str = BRIEF) -> str:
    base = INSTRUCTIONS.format(company=company, h0=horizon[0], h1=horizon[1], brief=brief, **LAYER_GUIDE)
    if context:
        base += CONTEXT_HEADER + "\n" + context.strip() + "\n"
    return base + OUTPUT_SPEC


def to_roadmap(out: RoadmapOut, *, condition: Literal["initial", "advanced"], model: str,
               company: str = COMPANY, horizon: tuple[float, float] = HORIZON,
               ops_by_evidence: dict[str, list[RoadmapOp]] | None = None, cost_usd: float | None = None) -> Roadmap:
    """LLM 출력 → 스키마. initial 은 전부 llm_prior, advanced 는 evidence→연산 매핑으로 produced_by 채움."""
    idmap: dict[str, str] = {}
    nodes: list[RoadmapNode] = []
    for n in out.nodes:
        rn = RoadmapNode(label=n.label, layer=Layer(n.layer), category=n.category or None,
                         start=max(horizon[0], min(n.start, horizon[1])), end=max(horizon[0], min(n.end, horizon[1])),
                         description=n.description, evidence_ids=list(n.evidence_ids), flags=list(n.flags))
        if rn.end < rn.start:
            rn.start, rn.end = rn.end, rn.start
        ops: set[RoadmapOp] = set()
        if ops_by_evidence:
            for ev in n.evidence_ids:
                ops.update(ops_by_evidence.get(ev, []))
        rn.produced_by = sorted(ops, key=lambda o: o.value) if ops else [RoadmapOp.LLM_PRIOR]
        idmap[n.id] = rn.id
        nodes.append(rn)
    edges: list[RoadmapEdge] = []
    seen = set()
    for e in out.edges:
        if e.src in idmap and e.dst in idmap and e.src != e.dst and (e.src, e.dst, e.type) not in seen:
            seen.add((e.src, e.dst, e.type))
            edges.append(RoadmapEdge(src=idmap[e.src], dst=idmap[e.dst], type=RelationType(e.type)))
    return Roadmap(condition=condition, company=company, horizon=horizon, model=model, prompt_hash=prompt_hash(),
                   nodes=nodes, edges=edges, cost_usd=cost_usd)


def generate(llm: LLM, *, condition: Literal["initial", "advanced"], context: str | None = None,
             model: str = DEFAULT_MODEL, temperature: float = 0.2,
             ops_by_evidence: dict[str, list[RoadmapOp]] | None = None) -> Roadmap:
    if condition == "initial":
        assert context is None, "initial condition must not receive KB context"
    before = llm.ledger.total_usd
    out = llm.structured(model, SYSTEM, build_user_prompt(context), RoadmapOut, purpose=f"roadmap_{condition}",
                         temperature=temperature, max_tokens=8000)
    return to_roadmap(out, condition=condition, model=model, ops_by_evidence=ops_by_evidence,
                      cost_usd=llm.ledger.total_usd - before)


def save(rm: Roadmap, run_dir: str | Path) -> Path:
    p = Path(run_dir) / f"roadmap_{rm.condition}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(rm.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")
    return p


def load(run_dir: str | Path, condition: str) -> Roadmap | None:
    p = Path(run_dir) / f"roadmap_{condition}.json"
    return Roadmap.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None


def summary(rm: Roadmap) -> dict:
    by_layer = {l.value: 0 for l in Layer}
    for n in rm.nodes:
        by_layer[n.layer.value] += 1
    return {"condition": rm.condition, "model": rm.model, "prompt_hash": rm.prompt_hash, "nodes": len(rm.nodes),
            "by_layer": by_layer, "edges": len(rm.edges),
            "with_evidence": sum(1 for n in rm.nodes if n.evidence_ids),
            "flagged": sum(1 for n in rm.nodes if n.flags), "cost_usd": rm.cost_usd,
            "generated_at": rm.generated_at.isoformat()}
