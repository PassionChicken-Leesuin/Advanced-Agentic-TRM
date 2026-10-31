"""
Reader — 2단 추출.
  1단 triage (저가 모델): 청크가 로드맵 관련 내용을 담는가, 어느 층인가.
  2단 extract (주 모델): 유형별 슬롯이 있는 후보 노드 + 주장 + 근거 인용.

근거 인용(evidence_quote)은 청크의 축약 없는 부분 문자열이어야 하며, 아니면 가장 가까운 문장으로 대체한다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ..llm import LLM
from ..schema import NodeType
from .chunker import Chunk
from .timeparse import parse_time

SEED_CATEGORIES = {
    "why": "security/PQC, export control, government programs, enterprise demand, competitor pressure, benchmark standards, investor expectations, talent market",
    "what": "scale, fidelity, error correction/logical qubits, modularity/interconnect, networking products, cloud offering, on-prem offering, commercialization/bookings, system generation",
    "how": "ion species, control technology, trap chips, photonic interconnect, vacuum/cryo, lasers/optics, error correction codes, decoders, manufacturing/foundry, software/compilers, benchmarks",
    "resource": "funding, facility, partnership, standard, regulation, skills, infrastructure",
}

TRIAGE_SYSTEM = "You screen text chunks from company documents for technology-roadmap content. Answer in JSON."
TRIAGE_USER = """Company: {company}. Document date: {doc_date}. Document type: {source_type}.

Does the chunk below contain roadmap-relevant content about {company} or its environment — i.e. any of:
market drivers / regulation / customer needs (why), products / milestones / targets / specs / market size (what),
technologies / components / capabilities / maturity (how), funding / facilities / partners / standards (resource),
named organizations with a role (actor), risks / barriers / decisions / open questions / assumptions (issue)?
Internal material (meeting minutes, weekly reports, customer or supplier emails, assessments) with requirements, targets, lead times, yields, schedules, decisions, risks or budgets IS relevant. Financial-results press releases with business highlights, bookings, customers or product mentions ARE relevant.
Only pure boilerplate (legal notices, generic forward-looking-statement language, signatures, table-of-contents, reference lists, pure financial tables without narrative) is NOT relevant. When in doubt, answer relevant=true.

Chunk:
\"\"\"{chunk}\"\"\"

Return JSON: {{"relevant": bool, "layers": ["why"|"what"|"how"|"resource"|"actor"|"issue"], "reason": str}}"""


class Triage(BaseModel):
    relevant: bool
    layers: list[str] = Field(default_factory=list)
    reason: str = ""


EXTRACT_SYSTEM = """You are the Reader agent of a technology-roadmap knowledge base for {company}. You extract roadmap knowledge units from one text chunk and return JSON only. Be precise, keep numbers/dates/qualifiers, and never invent facts not in the chunk."""

EXTRACT_USER = """Document: "{title}" dated {doc_date} ({source_type}; author/speaker: {actor}).

Extract every roadmap-relevant unit from the chunk as a proposal. Node types:
- driver (why): external change — STEEP category; need (why): what a stakeholder/customer requires; vision (why)
- opportunity (what): product/application/offering; milestone (what): a dated stage event (demonstrator / first product / shipment / achievement)
- capability (how): a technology or ability; component (how): a part/subsystem of a capability
- enabler (resource): funding, facility, partnership, standard, regulation, skills
- actor: an organization with a role (supplier, customer, funder, regulator, competitor, partner, acquiree)
- issue: risk, barrier, open_question, decision, assumption

For each proposal give:
- label: a canonical NOUN PHRASE naming the thing (2-6 words), the same across documents and documents' wording
  (e.g. "photonic interconnect", "two-qubit gate fidelity", "Tempo system", "export control licensing").
  NO verbs, NO values/dates/targets, NO possessives ("IonQ's ...", "our ..."). Values, dates and targets go into the claim.
  A measurement or a target (e.g. "cavity lock stability 11.4 hours") is a CLAIM about a node ("cavity lock stability"), not a node.
- category: the roadmap row. Prefer these seeds — why: {cat_why}; what: {cat_what}; how: {cat_how}; resource: {cat_resource}. Create a new short category only if none fits.
- description: one sentence
- evidence_quote: an EXACT verbatim substring of the chunk (<= 300 chars) that supports the proposal
- claim (REQUIRED for every proposal): the specific statement the document makes about this node. Its text must keep
  ALL numbers, dates, names and qualifiers of the source sentence(s) — when the source sentence contains numbers or
  dates, reuse that sentence nearly verbatim (never a generic definition like "the rate of X"); choose claim_type in
  [statement, spec, capability_claim, market_size, maturity, priority, comparison, action],
  modality in [current, planned, achieved, required, forecast, vision], time_raw (as written, e.g. "by Q2 2025"),
  time_start/time_end as decimal years if you can resolve them, speaker (who asserts it),
  and typed slots: measure/value/unit (capability_claim), dims {{size,cost,accuracy,...}} (spec),
  volume/unit_price/total/segment/year (market_size), trl/stage (maturity), vs_label (comparison), responsible_actor/due (action)
- type-specific: steep (driver), stakeholder_type (need), issue_kind (issue), enabler_kind (enabler), actor_roles (actor), milestone_stage (milestone)

Skip generic marketing language, but DO extract from internal material: a customer requirement is a need, a supplier
lead time or a hiring plan or a facility or a license filing is an enabler (resource), a risk-register entry or an
unresolved question or a decision is an issue, an internal target or scheduled shipment is a milestone, a market or
bookings estimate is an opportunity with a market_size claim.
Return the 3-8 most roadmap-relevant proposals per chunk (never more than 8).

Chunk:
\"\"\"{chunk}\"\"\"

Return JSON: {{"proposals": [ ... ]}}"""


CLAIM_TYPES = {"statement", "spec", "capability_claim", "market_size", "maturity", "priority", "comparison", "action"}
MODALITIES = {"current", "planned", "achieved", "required", "forecast", "vision"}
NODE_TYPES = {"driver", "need", "vision", "opportunity", "milestone", "capability", "component", "enabler", "actor", "issue"}


class ClaimOut(BaseModel):
    claim_type: str = "statement"
    text: str = ""
    modality: str = "planned"
    time_raw: str | None = None
    time_start: float | None = None
    time_end: float | None = None
    speaker: str | None = None
    measure: str | None = None
    value: str | None = None
    unit: str | None = None
    dims: dict[str, str] | None = None
    volume: str | None = None
    unit_price: str | None = None
    total: str | None = None
    segment: str | None = None
    year: float | None = None
    trl: int | None = None
    stage: str | None = None
    vs_label: str | None = None
    responsible_actor: str | None = None
    due: str | None = None


class Proposal(BaseModel):
    node_type: str = Field(description="one of: driver, need, vision, opportunity, milestone, capability, component, enabler, actor, issue",
                           json_schema_extra={"enum": sorted(NODE_TYPES)})
    label: str = ""
    category: str | None = None
    description: str = ""
    evidence_quote: str = ""
    claim: ClaimOut | None = None
    steep: str | None = None
    stakeholder_type: str | None = None
    issue_kind: str | None = None
    enabler_kind: str | None = None
    actor_roles: list[str] | None = None
    milestone_stage: str | None = None


class ReaderOut(BaseModel):
    proposals: list[Proposal] = Field(default_factory=list)


def _infer_type(p: "Proposal") -> str:
    """node_type이 비정상일 때 유형별 슬롯·범주 시드로 추정."""
    if p.issue_kind:
        return "issue"
    if p.enabler_kind:
        return "enabler"
    if p.actor_roles:
        return "actor"
    if p.milestone_stage:
        return "milestone"
    if p.stakeholder_type:
        return "need"
    if p.steep:
        return "driver"
    cat = (p.category or "").lower()
    for layer, default in (("resource", "enabler"), ("why", "driver"), ("what", "opportunity"), ("how", "capability")):
        if cat and any(cat in s or s in cat for s in SEED_CATEGORIES[layer].split(", ")):
            return default
    return "capability"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def locate_quote(chunk: Chunk, quote: str) -> tuple[str, tuple[int, int]]:
    """인용을 청크에서 찾는다. 없으면 가장 많이 겹치는 문장으로 대체."""
    q = quote.strip()
    if q and q in chunk.text:
        s = chunk.text.index(q)
        return q, (chunk.start + s, chunk.start + s + len(q))
    nq = _norm(q)
    nt = _norm(chunk.text)
    if nq and nq in nt:
        # 정규화 매치: 원문 위치는 근사
        s = nt.index(nq)
        return chunk.text[s: s + len(q)], (chunk.start + s, chunk.start + s + len(q))
    best, best_score = None, 0.0
    qtok = set(nq.split())
    for m in re.finditer(r"[^.!?\n]+[.!?]?", chunk.text):
        st = set(_norm(m.group(0)).split())
        if not st:
            continue
        score = len(qtok & st) / max(1, len(qtok))
        if score > best_score:
            best, best_score = m, score
    if best and best_score >= 0.4:
        return best.group(0).strip(), (chunk.start + best.start(), chunk.start + best.end())
    return q[:300], (chunk.start, chunk.start)


class Reader:
    def __init__(self, llm: LLM, model_extract: str, model_triage: str | None, company: str = "IonQ"):
        self.llm = llm
        self.model_extract = model_extract
        self.model_triage = model_triage
        self.company = company

    def triage(self, chunk: Chunk, *, doc_date: date, source_type: str) -> Triage:
        if not self.model_triage:
            return Triage(relevant=True)
        return self.llm.structured(self.model_triage, TRIAGE_SYSTEM,
                                   TRIAGE_USER.format(company=self.company, doc_date=doc_date, source_type=source_type,
                                                      chunk=chunk.text[:4000]),
                                   Triage, purpose="reader_triage", max_tokens=300)

    def extract(self, chunk: Chunk, *, title: str, doc_date: date, source_type: str, actor: str) -> list[Proposal]:
        out = self.llm.structured(
            self.model_extract, EXTRACT_SYSTEM.format(company=self.company),
            EXTRACT_USER.format(title=title, doc_date=doc_date, source_type=source_type, actor=actor, chunk=chunk.text,
                                cat_why=SEED_CATEGORIES["why"], cat_what=SEED_CATEGORIES["what"],
                                cat_how=SEED_CATEGORIES["how"], cat_resource=SEED_CATEGORIES["resource"]),
            ReaderOut, purpose="reader_extract", max_tokens=9000)
        props = []
        for p in out.proposals:
            p.node_type = (p.node_type or "").strip().lower().replace(" ", "_")
            p.label = (p.label or "").strip().strip(".")
            if p.node_type not in NODE_TYPES:
                p.node_type = _infer_type(p)   # 잘못된 유형은 범주·슬롯으로 추정 (버리지 않는다)
            if not p.label or not p.evidence_quote:
                continue
            if p.claim is None or not p.claim.text:
                # 주장 누락 시 설명+근거로 statement 주장을 합성 (타임라인·평가의 단위는 주장이므로 비워두지 않는다)
                p.claim = ClaimOut(claim_type="statement", text=(p.description or p.evidence_quote)[:400],
                                   modality="current", speaker=actor)
            p.claim.claim_type = p.claim.claim_type if p.claim.claim_type in CLAIM_TYPES else "statement"
            p.claim.modality = p.claim.modality if p.claim.modality in MODALITIES else "planned"
            # 주장이 수치를 잃었는데 근거에는 수치가 있으면 근거 문장을 주장으로 (회수율의 단위는 주장)
            if not re.search(r"\d", p.claim.text) and re.search(r"\d", p.evidence_quote):
                p.claim.text = p.evidence_quote.strip()[:300]
            props.append(p)
        return props


def claim_time(c: ClaimOut, doc_date: date):
    if c.time_start is not None or c.time_end is not None:
        from ..schema import TimeExpr, TimeExprKind
        s, e = c.time_start, c.time_end
        if s is not None and e is not None and e < s:
            s, e = e, s
        return TimeExpr(raw=c.time_raw or "", kind=TimeExprKind.ABSOLUTE, start=s, end=e)
    return parse_time(c.time_raw, doc_date)
