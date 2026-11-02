"""
Router (분배 에이전트) — 문서 하나의 소스 문장들을 받아 문장마다 판단한다.
  1) 저장 여부: new(저장) | duplicate(같은 사실이 이미 있음) | irrelevant(상투 문구)
  2) 공통 태그: 층 태그(why/what/how/resource, 복수), 종류, 양태, 공유 대상(기존 eid 또는 새 이름)
  3) 보낼 구조: tree(K2 주제 요약 트리) / grid(K3 기회 연계 그리드) / graph(K4 의존 관계 그래프) / time(K5 시간 지식그래프)
     중 0개 이상. 구조마다 "이 문장이 그 구조에서 TRM 의 어떤 기능에 기여하는가"를 이유로 적는다.
     K1 근거 저장소에는 저장 판정이면 항상 들어간다.
구조가 정해진 뒤의 추출은 extract.py 의 구조 전용 추출기가 맡는다.
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md §4
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from ..llm import LLM
from .resolve import Resolver
from .store import KINDS, LAYERS, SYSTEMS, Passage, SourceStore

SYSTEM = ("You are the Router agent of a knowledge base built so that an AI can write a company technology roadmap. "
          "Every stored item is a source passage quoted from a document. You decide, passage by passage, which "
          "knowledge structures the passage must be stored in to serve which roadmapping function. JSON only.")

USER = """Company: IonQ. Document: "{title}" ({date}, {stype}{syn}).

Passages (pid | quote | restated claim | reader hint):
{passages}

Existing subjects in the knowledge base that may match (eid | name | dominant layer | latest statements):
{cands}

Glossary (K0, controlled vocabulary; use these canonical names for subjects and resolve aliases to them):
{glossary}

The knowledge base has five structures. K1 (evidence store) receives every stored passage automatically. You decide
which of the other four each passage must ALSO go to. First apply the significance test: a passage feeds K2-K5 only if
it bears on the roadmap (markets, needs, products, milestones, technologies, enabling resources, strategy). Internal
administration (meeting dates, review deadlines, memo logistics, document handling, approval chains, staffing tasks)
stays in K1 only, with no routes. Then judge each of the four structures INDEPENDENTLY; many passages belong to two or
three of them.
- "tree" = theme summary tree, serves TREND synthesis: the passage tells where the company, the market or the
  competition is heading, or what is being prioritized, expanded or scaled back (strategy statements, investment focus,
  market and competitive movements, repeated emphasis). NOT for descriptions of how a technology works, product
  specifications, single results, definitions, or individual issues, options and tasks: those stay in K1 (and may go to
  graph/time/grid). Expect roughly a quarter of a strategic document's passages to qualify, far fewer in a technical one.
- "grid" = opportunity linkage grid, serves OPPORTUNITIES and their priority: application areas, customer demand,
  market size, business opportunities, customer cases, pilots and contracts, government program demand.
- "graph" = dependency graph, serves LINKS between roadmap items: the passage directly states a relation between two
  or more subjects (requires, enables, drives demand for, is part of, supplies, partners with, is a customer of,
  competes with, funds, threatens, addresses, precedes), including inside one sentence ("X improves Y", "X is needed
  for Y", "X uses Y", "X reduces the overhead of Y"). Never for a passage about a single subject.
- "time" = temporal knowledge graph, serves TIMING: a roadmap-relevant date or target time, a numeric target, an
  achieved result with its time, a delay or schedule change of a product, technology, market or financial plan.
  Not administrative dates and not internal work items (report or document deliveries, approvals, reviews, trainings,
  questionnaires, test checkpoints), even when they carry a date. Not historical financial statements (net loss, cash,
  R&D expense, lease obligations, financing) and not generic "we expect losses until..." language: those stay in K1.
Examples:
- "Tempo, our next system targeting #AQ 64 in 2025, will use barium qubits" -> time (Tempo #AQ 64 target 2025),
  graph (Tempo requires barium qubits), tree (shift to barium-based next generation)
- "Hyundai is using Forte to simulate battery chemistry" -> grid (battery chemistry opportunity, customer Hyundai),
  graph (Hyundai customer_of IonQ)
- "Please send comments by July 16" -> no routes (administrative)
A passage may go to none of them (evidence only) or to several.

For EVERY passage return:
- status: new | duplicate (the same fact is already stored for that subject; give related_pid) | irrelevant
  (boilerplate: legal disclaimers, generic risk language, signatures, table of contents)
- layers: roadmap layers the passage informs, one or more of
    why = external drivers, market and regulation, customer or stakeholder needs, competition, vision
    what = products, offerings, applications, milestones, targets, specifications, market size, commercial results
    how = technologies, components, architectures, methods, technical performance
    resource = funding, facilities, people and skills, partners and suppliers, standards, licenses and approvals
- kinds: any of {kinds}
- modality: current | planned | achieved | required | forecast | vision
- subjects: 1-3 things the passage is about. Reuse an existing eid when it is the SAME subject (same technology,
  product, organization, application or requirement, possibly named differently). Otherwise give a new canonical
  name: a noun phrase of 2-6 words, no numbers, dates or verbs (e.g. "photonic interconnect", "Tempo system").
  Subjects are products, technologies, components, organizations, applications, requirements or resources, never
  targets or events ("2024 technical target") and never generic phrases ("quantum computing era").
- routes: [{{"structure": "tree"|"grid"|"graph"|"time", "reason": what it contributes to that function, under 14 words}}]

Return JSON: {{"decisions": [{{"pid": str, "status": str, "related_pid": str|null, "layers": [str], "kinds": [str],
"modality": str, "subjects": [{{"eid": str|null, "name": str}}], "routes": [{{"structure": str, "reason": str}}]}}]}}"""


class Subj(BaseModel):
    eid: str | None = None
    name: str = ""


class Route(BaseModel):
    structure: str
    reason: str = ""


class Decision(BaseModel):
    pid: str
    status: str = "new"
    related_pid: str | None = None
    layers: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    modality: str | None = None
    subjects: list[Subj] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)


class Decisions(BaseModel):
    decisions: list[Decision] = Field(default_factory=list)


class Router:
    def __init__(self, llm: LLM, store: SourceStore, resolver: Resolver, model: str = "openai/gpt-4.1-mini", batch: int = 14,
                 workers: int = 6):
        self.llm, self.store, self.res, self.model, self.batch, self.workers = llm, store, resolver, model, batch, workers

    def _call(self, doc: dict, chunk: list[Passage]):
        """문장 묶음 하나의 LLM 판단 (읽기만 하므로 병렬 가능). 반영은 route_doc 에서 순서대로."""
        st = self.store
        cand_ids = self.res.candidates([" ".join(h.get("label", "") for h in p.reader_hints) + ". " + p.statement[:300] for p in chunk])
        pl = "\n".join(f"- {p.id} | \"{p.text[:280]}\" | {p.claim[:220] if p.claim else '-'} | "
                       + ", ".join(f"{h.get('label')} ({h.get('kind')})" for h in p.reader_hints[:2]) for p in chunk)
        res = self.llm.structured(self.model, SYSTEM, USER.format(
            title=doc["title"][:120], date=doc["date"], stype=doc["source_type"],
            syn=", internal (synthetic)" if doc.get("is_synthetic") else "", passages=pl,
            cands=self.res.cand_block(cand_ids), kinds=", ".join(KINDS),
            glossary=st.glossary_block(("product", "technology", "organization", "application", "program"), max_chars=2500)),
            Decisions, purpose="router", max_tokens=7000)
        return cand_ids, res

    def route_doc(self, doc: dict, ps: list[Passage]) -> dict:
        st = self.store
        out = {"passages": 0, "kept": 0, "routes": {s: 0 for s in SYSTEMS}, "status": {}}
        chunks = [ps[i:i + self.batch] for i in range(0, len(ps), self.batch)]
        # LLM 호출은 묶음별로 병렬 (키 20개 라운드로빈을 실제로 쓰기 위해), 저장소 반영은 문서 안 순서대로
        with ThreadPoolExecutor(max_workers=min(self.workers, max(1, len(chunks)))) as ex:
            results = list(ex.map(lambda c: self._call(doc, c), chunks))
        for chunk, (cand_ids, res) in zip(chunks, results):
            byid = {d.pid: d for d in res.decisions}
            allowed = set(cand_ids)
            for p in chunk:
                d = byid.get(p.id) or Decision(pid=p.id, status="irrelevant")
                p.layers = [l for l in dict.fromkeys(d.layers) if l in LAYERS]
                p.kinds = [k for k in dict.fromkeys(d.kinds) if k in KINDS]
                p.status = d.status if d.status in ("new", "duplicate", "irrelevant") else "new"
                if not p.layers:
                    p.status = "irrelevant"
                p.related_pid = d.related_pid if d.related_pid in st.passages else None
                p.modality, p.routed = d.modality, True
                p.entity_ids, p.systems, p.route_reasons = [], [], {}
                if p.status != "irrelevant":
                    for sj in d.subjects[:3]:
                        self.res.resolve(sj.eid, sj.name, p, allowed=allowed)
                if p.status == "new":
                    for r in d.routes:
                        if r.structure in SYSTEMS and r.structure not in p.systems:
                            p.systems.append(r.structure)
                            p.route_reasons[r.structure] = r.reason[:140]
                            out["routes"][r.structure] += 1
                    out["kept"] += 1
                p.reason = "; ".join(f"{k}: {v}" for k, v in p.route_reasons.items())[:300]
                st.emit("passage.routed", doc_id=p.doc_id, pid=p.id, status=p.status, layers=p.layers, kinds=p.kinds,
                        entities=p.entity_ids, systems=p.systems, reasons=p.route_reasons, synthetic=p.is_synthetic,
                        text=p.statement[:160])
                st.log_router({"doc_id": p.doc_id, "pid": p.id, "status": p.status, "related_pid": p.related_pid,
                               "layers": p.layers, "kinds": p.kinds, "modality": p.modality, "entities": p.entity_ids,
                               "systems": p.systems, "reasons": p.route_reasons})
                out["status"][p.status] = out["status"].get(p.status, 0) + 1
                out["passages"] += 1
        return out
