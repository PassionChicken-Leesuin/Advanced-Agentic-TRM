"""
구조 전용 추출기 — Router 가 그 구조로 보낸 소스 문장만 받아, 그 구조가 요구하는 형식으로 지식을 뽑는다.
  K2 TreeExtractor  : 주제 배정 (기존 주제 또는 새 주제) + 강조 신호
  K3 GridExtractor  : 응용 기회 기록 (응용처·제공물·고객·가치 신호·동인·요구·성숙도)
  K4 GraphExtractor : (주체, 관계, 대상) 삼중항
  K5 TimeExtractor  : (대상, 속성, 값, 유효 시점, 진술 시점, 양태) 사실 + 기존 사실 대비 상태
각 추출기는 call()(LLM 호출만, 병렬 가능) → apply()(저장소 반영, 순차) 두 단계로 나뉜다.
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md §3
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from ..llm import LLM
from .glossary import attribute_vocab
from .resolve import Resolver, norm
from .store import MATURITY, RELATIONS, Opportunity, Passage, Relation, SourceStore, Theme, TimeFact

MODEL = "openai/gpt-4.1-mini"
GLOSS_NAMES = ("product", "technology", "organization", "application", "program")
ADMIN_FACT_WORDS = ("approval", "approved", "sign-off", "signed-off", "documentation", "questionnaire", "training", "deck",
                    "communications plan", "data summary", "technical report", "memo", "meeting", "review", "checkpoint",
                    "migration assessment", "deliver the report", "report delivery")
VAGUE_MILESTONE = ("plan", "dependency", "improvement", "increase", "decrease", "strategy", "focus", "resolution", "definition and measurement")
# 과거 재무 실적 지표는 로드맵 시점 배치에 쓰지 않음 (전망·가이던스는 planned/forecast 양태로 들어오면 남김)
FINANCIAL_WORDS = ("expense", "cash", "deficit", "net loss", "operating loss", "securities", "liquidity", "lease", "financing", "stock", "share price",
                   "revenue for the year", "cost of revenue", "gross margin")


class Ref(BaseModel):
    eid: str | None = None
    name: str = ""


def _plines(st: SourceStore, ps: list[Passage]) -> str:
    out = []
    for p in ps:
        subs = ", ".join(f"{e} = {st.entities[e].name}" for e in p.entity_ids if e in st.entities) or "-"
        out.append(f"- {p.id} | {p.statement[:300]} | subjects: {subs}")
    return "\n".join(out)


def _hdr(doc: dict) -> str:
    return f'Company: IonQ. Document: "{doc["title"][:120]}" ({doc["date"]}, {doc["source_type"]}{", internal (synthetic)" if doc.get("is_synthetic") else ""}).'


class _Base:
    structure = ""

    def __init__(self, llm: LLM, st: SourceStore, res: Resolver, model: str = MODEL):
        self.llm, self.st, self.res, self.model = llm, st, res, model

    def allowed(self, ps: list[Passage]) -> tuple[set[str], str]:
        ids = self.res.candidates([p.statement[:300] for p in ps], k=3, top=24)
        own = {e for p in ps for e in p.entity_ids}
        return set(ids) | own, self.res.cand_block([e for e in ids if e not in own], n_last=1)

    def gloss(self, types=GLOSS_NAMES, max_chars: int = 1800) -> str:
        return self.st.glossary_block(types, max_chars=max_chars)

    @staticmethod
    def chunked(ps: list[Passage], size: int, fn, workers: int = 6) -> list:
        """긴 문서는 문장을 size 개씩 잘라 병렬로 호출 (한 호출에 수백 문장을 넣으면 출력이 잘리고 느림)."""
        chunks = [ps[i:i + size] for i in range(0, len(ps), size)] or [[]]
        with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as ex:
            return list(ex.map(fn, chunks))

    def term_type(self, name: str | None) -> str | None:
        if not name:
            return None
        n = norm(name)
        for t in self.st.terms.values():
            if t.status != "rejected" and (norm(t.name) == n or any(norm(a) == n for a in t.aliases)):
                return t.type
        return None


# --------------------------------------------------------------------------- K2 주제 요약 트리
class Assign(BaseModel):
    pid: str
    theme_id: str | None = None
    theme_name: str = ""
    emphasis: str = "continuing"


class Assigns(BaseModel):
    assignments: list[Assign] = Field(default_factory=list)


TREE_SYS = "You maintain the theme tree of a roadmapping knowledge base (like RAPTOR leaf clusters). JSON only."
TREE_USER = """{hdr}

These passages were routed to the theme tree because they show strategic direction or trends:
{passages}

Existing themes (tid | name | passages so far | latest years):
{themes}

Glossary names to use in theme names (K0):
{glossary}

Assign every passage to ONE theme. Reuse an existing tid whenever the passage fits it. Create a new theme only when
none fits. A theme is a strategic thread that can collect passages from many documents over several years, at the
level of a roadmap row, broader than a single feature or issue. The whole knowledge base should end up with roughly
30-60 themes, so prefer broadening an existing theme over creating a narrow new one
(e.g. "error correction roadmap", "enterprise on-premise sales", "quantum networking expansion", "export control
regime", "manufacturing scale-up"). New theme names: 2-5 words, no numbers or dates.
emphasis: new (topic appears for the first time) | continuing | expanding (more scope, money or priority than before)
| declining (scaled back, delayed, de-emphasized).

Return JSON: {{"assignments": [{{"pid": str, "theme_id": str|null, "theme_name": str, "emphasis": str}}]}}"""


class TreeExtractor(_Base):
    structure = "tree"

    def _themes(self) -> str:
        ts = sorted(self.st.themes.values(), key=lambda t: -len(t.passage_ids))[:150]
        lines = []
        for t in ts:
            yrs = sorted({self.st.passages[i].doc_date.year for i in t.passage_ids if i in self.st.passages})[-3:]
            lines.append(f"- {t.id} | {t.name} | {len(t.passage_ids)} | {','.join(map(str, yrs))}")
        return "\n".join(lines) or "(none yet)"

    def call(self, doc: dict, ps: list[Passage]) -> Assigns:
        themes, gl = self._themes(), self.gloss(("application", "technology", "product"), 1200)
        outs = self.chunked(ps, 40, lambda c: self.llm.structured(
            self.model, TREE_SYS, TREE_USER.format(hdr=_hdr(doc), passages=_plines(self.st, c), themes=themes, glossary=gl),
            Assigns, purpose="extract_tree", max_tokens=3000))
        return Assigns(assignments=[a for o in outs for a in o.assignments])

    def apply(self, doc: dict, ps: list[Passage], res: Assigns) -> int:
        st, n = self.st, 0
        byp = {p.id: p for p in ps}
        by_name = {norm(t.name): t for t in st.themes.values()}
        for a in res.assignments:
            p = byp.get(a.pid)
            if not p:
                continue
            t = st.themes.get(a.theme_id) if a.theme_id else None
            if t is None:
                nm = (a.theme_name or "").strip()
                if not nm:
                    continue
                t = by_name.get(norm(nm))
                if t is None:
                    t = Theme(name=nm)
                    st.themes[t.id] = t; by_name[norm(nm)] = t
                    st.emit("tree.theme_created", doc_id=p.doc_id, tid=t.id, name=nm)
            if p.id not in t.passage_ids:
                t.passage_ids.append(p.id)
            t.dirty = True
            p.theme_id = t.id
            p.emphasis = a.emphasis if a.emphasis in ("new", "continuing", "expanding", "declining") else "continuing"
            st.emit("tree.assigned", doc_id=p.doc_id, pid=p.id, tid=t.id, theme=t.name, emphasis=p.emphasis)
            n += 1
        return n


# --------------------------------------------------------------------------- K3 기회 연계 그리드
class OppOut(BaseModel):
    pid: str
    opportunity: Ref
    kind: str = "application"
    offering: Ref | None = None
    customer: str | None = None
    value: str | None = None
    drivers: list[Ref] = Field(default_factory=list)
    needs: list[Ref] = Field(default_factory=list)
    maturity: str = "exploring"


class OppsOut(BaseModel):
    records: list[OppOut] = Field(default_factory=list)


GRID_SYS = ("You fill the opportunity linkage grid of a roadmapping knowledge base, like the Cambridge 2014 quantum "
            "technology roadmap (columns = application opportunities; rows = drivers and needs, capabilities, enablers). JSON only.")
GRID_USER = """{hdr}

These passages were routed to the opportunity grid because they speak about applications, demand or business:
{passages}

Existing opportunities (eid | name | records so far):
{opps}

Other subjects that may match (eid | name | layer | latest statement):
{cands}

Glossary (K0): application areas, products and organizations to name things by:
{glossary}

An opportunity here is what the Cambridge 2014 quantum roadmap called an opportunity cluster: ONE application area
(e.g. "quantum chemistry simulation", "battery materials research", "logistics optimization", "quantum machine learning",
"quantum networking") or ONE product type (e.g. "on-premise quantum computers", "cloud quantum computing service",
"networked multi-QPU systems"), ideally with the market it serves. It is NOT a concrete product (Forte, Tempo), not a
company goal ("quantum advantage"), not the company or an organization, not a technology or algorithm, not a business activity
("sales", "contracts", "partnerships"), and not a value statement ("maximum value for customers", "enterprise-grade value").
For each passage that names or implies such an opportunity, write one record:
- opportunity: application area or product type (reuse an existing eid when it is the same one). kind: application | product_type
- offering: the concrete IonQ product or service used for it (eid or name, e.g. "Forte Enterprise"), null if none
- customer: the target market, customer, partner or segment as written (e.g. "Hyundai", "pharmaceutical companies",
  "US government agencies"), null if the passage names none. Never the generic word "customers".
- value: the value signal copied from the passage (market size, contract amount, demand statement), null if none
- drivers: external why-layer forces that create the opportunity and are specific enough to be a roadmap row
  (e.g. "EV battery R&D demand", "post-quantum cryptography migration", "US government quantum programs",
  "pharmaceutical R&D cost pressure"). Empty list if the passage names none. Never repeat the opportunity itself and
  never use generic phrases such as "quantum computing era" or "quantum computing commercialization".
- needs: what customers require from the solution (e.g. "higher two-qubit fidelity", "on-premise deployment",
  "more qubits"), eid or short name. Empty list if none is stated.
- maturity: exploring | pilot | contracted | revenue
Skip passages that do not concern an opportunity, and passages that only praise value without naming an application or
product type.

Return JSON: {{"records": [{{"pid": str, "opportunity": {{"eid": str|null, "name": str}}, "kind": str, "offering": {{"eid": str|null, "name": str}}|null,
"customer": str|null, "value": str|null, "drivers": [{{"eid": str|null, "name": str}}], "needs": [{{"eid": str|null, "name": str}}], "maturity": str}}]}}"""


class GridExtractor(_Base):
    structure = "grid"

    def _opps(self) -> tuple[str, set[str]]:
        cnt: dict[str, int] = {}
        for o in self.st.opps.values():
            cnt[o.eid] = cnt.get(o.eid, 0) + 1
        top = sorted(cnt, key=lambda e: -cnt[e])[:80]
        return ("\n".join(f"- {e} | {self.st.entities[e].name} | {cnt[e]}" for e in top if e in self.st.entities) or "(none yet)"), set(top)

    def call(self, doc: dict, ps: list[Passage]):
        allowed, cands = self.allowed(ps)
        opps, oids = self._opps()
        gl = self.gloss(("application", "product", "organization"), 1600)
        outs = self.chunked(ps, 30, lambda c: self.llm.structured(
            self.model, GRID_SYS, GRID_USER.format(hdr=_hdr(doc), passages=_plines(self.st, c), opps=opps, cands=cands, glossary=gl),
            OppsOut, purpose="extract_grid", max_tokens=4000))
        return OppsOut(records=[r for o in outs for r in o.records]), allowed | oids

    def apply(self, doc: dict, ps: list[Passage], res) -> int:
        out, allowed = res
        st, n = self.st, 0
        byp = {p.id: p for p in ps}
        for r in out.records:
            p = byp.get(r.pid)
            if not p:
                continue
            bad = {"quantum computing era", "quantum computing commercialization", "quantum computing", "quantum advantage",
                   "broad quantum advantage", "enterprise quantum application value", "customer value", "maximum value", "ionq",
                   "quantum algorithms", "customer contracts and partnerships", "international sales"}
            on = norm(r.opportunity.name)
            if on in bad or any(w in on for w in ("value", "advantage era", "sales", "contracts", "partnerships")):
                continue
            # 회사·조직·기술·지표 용어는 기회가 아님 (제품 유형은 제품 용어여도 됨)
            tt = self.term_type(r.opportunity.name) or (self.term_type(st.entities[r.opportunity.eid].name) if r.opportunity.eid in st.entities else None)
            if tt in ("organization", "technology", "metric") or (tt == "product" and r.kind != "product_type"):
                continue
            opp = self.res.resolve(r.opportunity.eid, r.opportunity.name, p, allowed=allowed)
            if not opp:
                continue
            off = self.res.resolve(r.offering.eid, r.offering.name, p, allowed=allowed) if r.offering and (r.offering.eid or r.offering.name) else None
            drv = [e.id for x in r.drivers[:3] if norm(x.name) not in bad and (e := self.res.resolve(x.eid, x.name, p, allowed=allowed)) and e.id != opp.id]
            nds = [e.id for x in r.needs[:3] if (e := self.res.resolve(x.eid, x.name, p, allowed=allowed)) and e.id != opp.id]
            cust = (r.customer or "").strip()
            if norm(cust) in ("customers", "customer", "clients", "users", "enterprises", "partners"):
                cust = ""
            o = Opportunity(eid=opp.id, kind=r.kind if r.kind in ("application", "product_type") else "application",
                            offering=off.id if off else None, customer=cust[:80] or None,
                            value=(r.value or None) and r.value[:200], drivers=drv, needs=nds,
                            maturity=r.maturity if r.maturity in MATURITY else "exploring", pid=p.id, doc_date=p.doc_date)
            st.opps[o.id] = o
            st.emit("grid.opportunity", doc_id=p.doc_id, pid=p.id, oid=o.id, eid=opp.id, name=opp.name, kind=o.kind,
                    offering=off.name if off else None, customer=o.customer, maturity=o.maturity,
                    drivers=[st.entities[d].name for d in drv], needs=[st.entities[d].name for d in nds])
            n += 1
        return n


# --------------------------------------------------------------------------- K4 의존 관계 그래프
class TripleOut(BaseModel):
    pid: str
    src: Ref
    rel: str
    dst: Ref
    reason: str = ""


class TriplesOut(BaseModel):
    triples: list[TripleOut] = Field(default_factory=list)


GRAPH_SYS = "You extract the dependency graph of a roadmapping knowledge base (GraphRAG-style typed relations). JSON only."
GRAPH_USER = """{hdr}

These passages were routed to the dependency graph because they state relations between subjects:
{passages}

Other subjects that may match (eid | name | layer | latest statement):
{cands}

Glossary (K0) canonical names for products, technologies, organizations, applications:
{glossary}

Extract every relation that a passage states DIRECTLY (do not infer), as (src, rel, dst). rel is one of:
requires (src needs dst), enables (src makes dst possible), drives (src creates demand or motivation for dst),
part_of (src is a component of dst), supplies (src provides dst or provides to dst), partners_with, customer_of
(src buys from dst), competes_with, funds (src pays for dst), threatens (src is a risk to dst), addresses (src solves
dst), precedes (src comes before dst in a plan).
A relation may sit inside one sentence ("X improves Y", "X is needed for Y", "X uses Y", "X reduces the overhead of Y").
src and dst must both be SUBJECTS: a technology, component, product, system, organization, application, requirement
or resource, written as a noun phrase. Never a verb phrase, task or outcome description ("simplify this task",
"accelerate innovation"); skip the relation if one end is not a subject. Use the passage subjects' eids or other
listed eids when they match; otherwise a short canonical name (2-6 words, no numbers or dates). reason: under 12 words.

Return JSON: {{"triples": [{{"pid": str, "src": {{"eid": str|null, "name": str}}, "rel": str, "dst": {{"eid": str|null, "name": str}}, "reason": str}}]}}"""


VERBS = {"simplify", "increase", "accelerate", "improve", "enable", "enables", "reduce", "provide", "routing", "grow",
         "achieve", "make", "allow", "help", "support", "deliver", "advance", "drive", "create", "bring", "boost", "lower",
         "speed", "new", "advantages", "innovation", "access"}


def subject_like(ref: "Ref", st: SourceStore) -> bool:
    if ref.eid and ref.eid in st.entities:
        return True
    w = (ref.name or "").strip().split()
    return 0 < len(w) <= 6 and w[0].lower() not in VERBS


class GraphExtractor(_Base):
    structure = "graph"

    def call(self, doc: dict, ps: list[Passage]):
        allowed, cands = self.allowed(ps)
        gl = self.gloss(max_chars=1600)
        outs = self.chunked(ps, 30, lambda c: self.llm.structured(
            self.model, GRAPH_SYS, GRAPH_USER.format(hdr=_hdr(doc), passages=_plines(self.st, c), cands=cands, glossary=gl),
            TriplesOut, purpose="extract_graph", max_tokens=4000))
        return TriplesOut(triples=[t for o in outs for t in o.triples]), allowed

    def apply(self, doc: dict, ps: list[Passage], res) -> int:
        out, allowed = res
        st, n = self.st, 0
        byp = {p.id: p for p in ps}
        seen = {(r.src, r.rel, r.dst, r.pid) for r in st.relations.values()}
        for t in out.triples:
            p = byp.get(t.pid)
            if not p or t.rel not in RELATIONS or not subject_like(t.src, st) or not subject_like(t.dst, st):
                continue
            a = self.res.resolve(t.src.eid, t.src.name, p, allowed=allowed)
            b = self.res.resolve(t.dst.eid, t.dst.name, p, allowed=allowed)
            if not a or not b or a.id == b.id or (a.id, t.rel, b.id, p.id) in seen:
                continue
            r = Relation(src=a.id, rel=t.rel, dst=b.id, pid=p.id, doc_date=p.doc_date, reason=t.reason[:100])
            st.relations[r.id] = r; seen.add((a.id, t.rel, b.id, p.id))
            st.emit("graph.relation", doc_id=p.doc_id, pid=p.id, rid=r.id, src=a.id, src_name=a.name, rel=t.rel, dst=b.id, dst_name=b.name)
            n += 1
        return n


# --------------------------------------------------------------------------- K5 시간 지식그래프
class FactOut(BaseModel):
    passage_id: str = ""         # 소스 문장 id (ps_...). 'pid' 라고 부르면 모델이 사실 id(tf_...) 와 혼동해 틀리게 채움
    subject: Ref
    family: str = "metric"
    attribute: str
    value: str
    number: float | None = None
    unit: str | None = None
    valid_start: float | None = None
    valid_end: float | None = None
    modality: str = "planned"
    status: str = "new"
    related_fact: str | None = None


class FactsOut(BaseModel):
    facts: list[FactOut] = Field(default_factory=list)


TIME_SYS = ("You maintain the temporal knowledge graph of a roadmapping knowledge base (Zep / temporal-KG style: facts are "
            "never overwritten; a newer statement about the same subject and attribute is linked as an update or conflict). JSON only.")
TIME_USER = """{hdr} Statements in this document are made on {date}.

These passages were routed to the temporal knowledge graph because they carry dates, targets or schedule changes:
{passages}

Facts already stored for these subjects (fact id | subject | family | attribute | value | valid time | stated on | modality):
{facts}

Subjects you may use (eid | name) — the subject of a fact MUST be one of these; do not invent new subjects:
{subjects}

Attribute vocabulary (K0 glossary; metric attributes and lifecycle stages):
{vocab}

Write one fact per roadmap-relevant time-bearing statement. A fact is (subject, attribute, value, valid time) stated
on {date}. Three families:
- metric: a measured or targeted quantity. attribute = the metric name from the vocabulary (e.g. "#AQ", "two-qubit gate
  fidelity", "physical qubit count"); value = the number as written ("64", "99.9%"); number = numeric value; unit.
  Example: "Forte passed #AQ 35 in Jan 2024" -> subject Forte, family metric, attribute "#AQ", value "35", number 35,
  valid 2024.0, modality achieved.
- lifecycle: a product or capability reaching a stage. attribute = "lifecycle stage"; value = the stage word from the
  vocabulary (e.g. "general availability", "demonstration", "first delivery", "end of support").
  Example: "Forte became commercially available in 2023" -> subject Forte, family lifecycle, attribute "lifecycle stage",
  value "general availability", valid 2023.0, achieved.
- milestone: a company- or program-level goal or event with a time. subject = the company, program or technology it is
  about; attribute = short goal name ("broad quantum advantage", "networked QPU demonstration", "facility opening",
  "contract award", "revenue guidance"); value = what is to happen as written.
  Example: "by 2025 we expect broad quantum advantage" -> subject IonQ, family milestone, attribute "broad quantum
  advantage", value "achieve broad quantum advantage", valid 2025.0, planned.
Rules:
- The subject is the thing the time belongs to (product, system, technology, organization, program), chosen from the
  list above. Prefer the most specific thing the passage names: the product or system (Forte, Aria, Tempo) over the
  company; use the company only for company-level goals. NEVER a target, milestone or event phrase as subject ("2024
  technical target", "#AQ 64 target", "Forte general availability"): the target goes into attribute/value, the thing
  into subject.
- One passage can yield several facts (e.g. "#AQ 35 was the 2024 target and was achieved in January 2024" -> a planned
  fact valid 2024 and an achieved fact valid 2024.0, the second as UPDATE of the first if the first is stored).
- valid_start, valid_end: decimal years the value holds for or is targeted at (Q2 2025 = 2025.25-2025.5; "by 2025" = 2025.0).
  Put the time ONLY here, never in value. If the statement has no time and no number, skip it.
- modality: achieved | planned | forecast | required | current
- status against stored facts of the SAME subject and attribute: new | duplicate (same value and time) | update (a newer
  value or date for the same target; give related_fact) | conflict (both cannot be true; give related_fact)
- A milestone must be a concrete dated event or goal about a product, technology, market, facility or program ("deploy
  networked systems in 2023", "open manufacturing facility in 2024"). Not restated strategy ("improve gate quality",
  "scale qubit counts", "revenue depends on..."), not internal work items.
- Skip: administrative and internal items (meetings, reviews, approvals, document or report deliveries, questionnaires,
  trainings, communications plans, test checkpoints), historical financial results (net loss, past revenue, accumulated
  deficit), stock and financing events, generic claims without a value or time.

Return JSON: {{"facts": [{{"passage_id": "the ps_... id of the source passage", "subject": {{"eid": str, "name": str}}, "family": str,
"attribute": str, "value": str, "number": number|null, "unit": str|null, "valid_start": number|null, "valid_end": number|null,
"modality": str, "status": str, "related_fact": "tf_... id or null"}}]}}"""


class TimeExtractor(_Base):
    structure = "time"
    # 시점 사실은 문장 수가 적고(전체의 ~7%) 빠뜨림·가족 오분류 비용이 커서 상위 모델을 씀
    def __init__(self, llm: LLM, st: SourceStore, res: Resolver, model: str = "openai/gpt-4.1"):
        super().__init__(llm, st, res, model)

    def _facts(self, eids: list[str]) -> str:
        lines = []
        for e in eids:
            fs = self.st.facts_of(e)[-8:]
            for f in fs:
                vt = "" if f.valid_start is None else f"{f.valid_start:.2f}" + (f"-{f.valid_end:.2f}" if f.valid_end not in (None, f.valid_start) else "")
                lines.append(f"- {f.id} | {e} = {self.st.entities[e].name} | {f.family} | {f.attribute} | {f.value} | {vt} | {f.stated_on} | {f.modality}")
        return "\n".join(lines[:80]) or "(none yet)"

    def _subjects(self, ps: list[Passage], allowed: set[str]) -> tuple[list[str], str]:
        """대상 후보: 문장의 대상 + 유사 대상 + 회사·제품·기술·프로그램 용어에 연결된 대상 (사건형 새 대상 생성은 막음)."""
        st = self.st
        eids = list(dict.fromkeys([e for p in ps for e in p.entity_ids] + [e for e in allowed if e in st.entities]))
        for t in st.terms_by_type("product", "technology", "program", "organization"):
            if t.eid and t.eid in st.entities and t.eid not in eids and len(eids) < 60:
                eids.append(t.eid)
        return eids, "\n".join(f"- {e} | {st.entities[e].name}" for e in eids) or "(none)"

    def call(self, doc: dict, ps: list[Passage]):
        allowed, _ = self.allowed(ps)
        eids, subj = self._subjects(ps, allowed)
        facts, vocab = self._facts(eids), attribute_vocab(self.st)
        outs = self.chunked(ps, 25, lambda c: self.llm.structured(
            self.model, TIME_SYS, TIME_USER.format(hdr=_hdr(doc), date=doc["date"], passages=_plines(self.st, c), facts=facts, subjects=subj, vocab=vocab),
            FactsOut, purpose="extract_time", max_tokens=5000))
        return FactsOut(facts=[f for o in outs for f in o.facts]), set(eids)

    def apply(self, doc: dict, ps: list[Passage], res) -> int:
        out, allowed = res
        st, n = self.st, 0
        byp = {p.id: p for p in ps}
        metric_names = {norm(t.name): t for t in st.terms_by_type("metric")}
        for t in st.terms_by_type("metric"):
            for a_ in t.aliases:
                metric_names.setdefault(norm(a_), t)
        for f in out.facts:
            p = byp.get(f.passage_id)
            if p is None:                                  # id 를 잘못 채운 경우: 값(숫자)과 대상 이름이 든 문장으로 되찾음
                num = re.search(r"\d+(?:\.\d+)?", f.value or "")
                hits = [q for q in ps if (not num or num.group() in q.text) and norm(f.subject.name)[:12] in norm(q.statement)]
                p = hits[0] if len(hits) >= 1 else (ps[0] if len(ps) == 1 else None)
            if not p or not f.attribute.strip() or not (f.value or "").strip():
                continue
            fam = f.family if f.family in ("metric", "lifecycle", "milestone") else "metric"
            attr0 = f.attribute.strip()
            low = (attr0 + " " + f.value).lower()
            if any(w in low for w in ADMIN_FACT_WORDS):
                continue                                   # 사무 처리·내부 산출물은 K5 에 두지 않음
            if fam == "milestone" and any(attr0.lower().endswith(w) for w in VAGUE_MILESTONE):
                continue                                   # 전략 재진술 ("quality improvement plan") 은 사실이 아님
            if any(w in attr0.lower() for w in FINANCIAL_WORDS) and f.modality in (None, "achieved", "current"):
                continue                                   # 과거 재무 실적
            if fam == "metric" and re.fullmatch(r"(19|20)\d\d", f.value.strip()):
                continue                                   # 값 자리에 연도만 들어온 지표 ("#AQ = 2022") 는 추출 오류
            # 속성이 지표 용어와 맞으면 가족을 지표로 고정하고 값에서 숫자를 뽑음 ("#AQ25 achievement" → #AQ = 25)
            mt = metric_names.get(norm(attr0)) or next((t for k, t in metric_names.items()
                                                        if len(k) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z])", norm(f.value))), None)
            if mt and fam == "milestone":
                m = re.search(r"\d+(?:\.\d+)?", f.value)
                if m:
                    fam, attr0, f.number, f.value = "metric", mt.name, float(m.group()), m.group()
            if fam == "metric" and f.number is None:
                m = re.search(r"\d+(?:\.\d+)?", f.value)
                if not m:
                    continue                               # 지표 사실인데 숫자가 없음 → 버림
                f.number = float(m.group())
            f.attribute = attr0
            if f.valid_start is None and f.valid_end is None and fam != "metric":
                continue                                   # 시점도 숫자도 없는 사실은 K5 에 둘 것이 아님
            ent = self.res.resolve(f.subject.eid, f.subject.name, p, allowed=allowed, create=False)
            if not ent:
                continue                                   # 목록에 없는 대상(사건형 이름 등)은 만들지 않음
            attr = f.attribute.strip()
            if fam == "metric":
                t = metric_names.get(norm(attr))
                if t:
                    attr = t.name
                    f.unit = f.unit or t.unit
            elif fam == "lifecycle":
                attr = "lifecycle stage"
                # 값은 K0 의 닫힌 단계 어휘여야 함 ("nine generations developed" 같은 서술은 단계가 아님 → 버림)
                stage = next((t for t in st.terms_by_type("stage")
                              if norm(t.name) in norm(f.value) or any(norm(x) in norm(f.value) for x in t.aliases)), None)
                if stage is None:
                    continue
                f.value = stage.name
            a, b = f.valid_start, f.valid_end
            if a is not None and not (1990 <= a <= 2060):
                a = None
            if b is not None and not (1990 <= b <= 2060):
                b = None
            if a is not None and b is not None and b < a:
                a, b = b, a
            if a is None and b is not None:
                a = b
            rel = f.related_fact if f.related_fact in st.facts else None
            status = f.status if f.status in ("new", "duplicate", "update", "conflict") else "new"
            key = (ent.id, attr.lower(), (f.value or "").strip().lower(), a, f.modality)
            if any((x.eid, x.attribute.lower(), x.value.lower(), x.valid_start, x.modality) == key for x in st.facts.values()):
                continue                                   # 같은 호출·같은 문서 안의 중복 (모델이 둘로 쓴 같은 사실)
            if status in ("update", "conflict") and rel is None:
                status = "new"
            tf = TimeFact(eid=ent.id, family=fam, attribute=attr[:60], value=f.value.strip()[:80], number=f.number, unit=f.unit,
                          valid_start=a, valid_end=b if b is not None else a, stated_on=p.doc_date, modality=f.modality, pid=p.id,
                          status=status, related_fact=rel)
            st.facts[tf.id] = tf
            if p.time_start is None and a is not None:
                p.time_start, p.time_end = a, tf.valid_end
            p.time_raw = p.time_raw or f.value[:40]
            for t in (a, tf.valid_end):
                if t is not None:
                    ent.time_min = t if ent.time_min is None else min(ent.time_min, t)
                    ent.time_max = t if ent.time_max is None else max(ent.time_max, t)
            st.emit("time.fact", doc_id=p.doc_id, pid=p.id, fid=tf.id, eid=ent.id, name=ent.name, family=fam, attribute=tf.attribute,
                    value=tf.value, valid=a, modality=tf.modality, status=status, related=rel)
            n += 1
        return n


EXTRACTORS = {"tree": TreeExtractor, "grid": GridExtractor, "graph": GraphExtractor, "time": TimeExtractor}
