"""
K0 용어집 (Glossary) — 다섯 구조가 공유하는 어휘층. 문서마다 Router 앞에서 한 번 돌아 새 용어·별칭·정의를 모은다.
  - 틀은 산업 공통(지표 / 제품 / 기술 / 조직 / 응용 / 수명 단계 / 프로그램 / 약어), 어휘는 산업 고유 → 산업 이식 시 이 파일만 바뀜
  - 제품·기술·조직·응용·프로그램 용어는 공유 대상(Entity)에 연결되고 별칭이 Resolver 에 등록됨 (이름이 갈라지는 것 방지)
  - 지표·수명 단계 용어는 K5 시간 사실의 속성 어휘 (TimeExtractor 는 이 목록에서만 속성을 고름)
  - 모든 항목은 후보(candidate)로 들어오고, 사용자가 표로 확인하면 확정(confirmed)/거절(rejected)
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md §2 (공통 뼈대) K0
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from ..llm import LLM
from .resolve import Resolver, norm
from .store import TERM_SCOPES, TERM_TYPES, Passage, SourceStore, Term

MODEL = "openai/gpt-4.1-mini"
LINKED = ("product", "technology", "organization", "application", "program")
ATTR_TYPES = ("metric", "stage")
# 수명 단계는 산업 공통의 닫힌 어휘(틀)라 문서에서 뽑지 않고 심는다 (문서가 새 단계 이름을 만들어 내는 것을 막음)
STAGES = [("announcement", ["announced"], "The product or capability is publicly announced."),
          ("demonstration", ["demo", "demonstrator", "proof of concept"], "A working demonstration exists, not yet a product."),
          ("early access", ["preview", "private preview", "beta"], "Available to selected customers before general release."),
          ("general availability", ["commercially available", "GA", "commercial launch", "first commercial product"], "Available to customers as a product or service."),
          ("first delivery", ["first shipment", "first installation", "first deployment"], "First unit delivered or installed at a customer site."),
          ("upgrade", ["second commercial product", "next generation"], "A later generation replaces or extends the product."),
          ("end of support", ["end-of-life", "wind-down", "retired", "phased out"], "Support for the product is ended.")]
# 사무 처리·내부 산출물을 가리키는 낱말: 이런 것은 용어도 사실도 아님
ADMIN_WORDS = ("training", "deep-dive", "review", "approval", "questionnaire", "deck", "summary delivery", "documentation", "meeting",
               "checkpoint", "sign-off", "memo", "report delivery", "communications plan", "assessment", "test phase")


def seed_stages(st: SourceStore) -> int:
    names = {norm(t.name) for t in st.terms.values()}
    n = 0
    for name, aliases, definition in STAGES:
        if norm(name) not in names:
            t = Term(name=name, type="stage", aliases=aliases, definition=definition, scope="general", status="confirmed")
            st.terms[t.id] = t; n += 1
    return n

SYSTEM = ("You maintain the glossary of a technology-roadmapping knowledge base: the controlled vocabulary that every other "
          "structure must use for names of metrics, products, technologies, organizations, applications and lifecycle stages. JSON only.")
USER = """Company: {company}{descriptor}. Document: "{title}" ({date}, {stype}{syn}).

Passages from the document:
{passages}

Glossary so far (name (type; aliases) [unit, direction]: definition):
{glossary}

Find terms the glossary should know and that are NOT yet in it under any alias. Types:
- metric: a measured or targeted quantity with a unit (e.g. "#AQ" = algorithmic qubits, "physical qubit count",
  "two-qubit gate fidelity" [%], "quantum volume", "logical qubit count", "gate speed", "system uptime", "bookings" [USD]).
  Give unit and direction (higher_better | lower_better | none).
- product: a named product, system or service generation (e.g. "Harmony", "Aria", "Forte", "Forte Enterprise", "Tempo",
  "IonQ Quantum OS"). Give order = generation number if the text makes the order clear, else null.
- technology: a named technique, component or architecture (e.g. "barium qubits", "photonic interconnect",
  "2D ion trap", "error mitigation", "Evaporated Glass Trap").
- organization: customer, partner, supplier, competitor, agency (e.g. "Hyundai", "AstraZeneca", "AFRL", "AWS Braket", "QuantumBasel").
- application: a market application area where customers get value (e.g. "quantum chemistry simulation", "battery materials",
  "logistics optimization", "quantum machine learning", "drug discovery", "quantum networking"). NOT algorithms, benchmark
  circuits or methods (QFT, phase estimation, Monte Carlo circuits, QAOA are technology), NOT business activities
  (sales, contracts, partnerships), NOT the company itself.
- program: a named funding or research program or contract vehicle (e.g. "DARPA QBI", "AFRL contract", "QuantumBasel deployment").
- acronym: an abbreviation the documents define (e.g. "QCaaS", "NISQ", "QPU") when it does not fit the types above.
(Lifecycle stages are a fixed vocabulary already in the glossary; do not add stage terms.)
Rules: a metric name never contains a value ("#AQ", not "#AQ 35"); canonical name as the company writes it (2-5 words, no
dates); aliases = other spellings in the text; skip internal administrative items (trainings, reviews, questionnaires,
meeting names, document deliverables);
definition = one sentence in plain words, from the text when the text defines it; scope = company ({company}-specific term),
industry (industry term), general. Also list aliases for EXISTING glossary terms that appear here under a new
spelling ("existing_aliases"). Skip people, places, legal and accounting terms, and generic words.

Return JSON: {{"terms": [{{"name": str, "type": str, "aliases": [str], "definition": str, "unit": str|null, "direction": str|null,
"order": int|null, "scope": str, "pids": [str]}}], "existing_aliases": [{{"name": str, "alias": str}}]}}"""


class TermOut(BaseModel):
    name: str
    type: str
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    unit: str | None = None
    direction: str | None = None
    order: int | None = None
    scope: str = "industry"
    pids: list[str] = Field(default_factory=list)


class AliasOut(BaseModel):
    name: str
    alias: str


class GlossaryOut(BaseModel):
    terms: list[TermOut] = Field(default_factory=list)
    existing_aliases: list[AliasOut] = Field(default_factory=list)


class GlossaryExtractor:
    def __init__(self, llm: LLM, st: SourceStore, res: Resolver, model: str = MODEL):
        self.llm, self.st, self.res, self.model = llm, st, res, model
        seed_stages(st)
        self.by_name: dict[str, str] = {}
        for t in st.terms.values():
            for n in [t.name] + t.aliases:
                self.by_name.setdefault(norm(n), t.id)

    def lookup(self, name: str) -> Term | None:
        tid = self.by_name.get(norm(name))
        return self.st.terms.get(tid) if tid else None

    def call(self, doc: dict, ps: list[Passage]) -> GlossaryOut:
        if not ps:
            return GlossaryOut()
        gl = self.st.glossary_block(max_chars=5000)
        chunks = [ps[i:i + 120] for i in range(0, len(ps), 120)]      # 긴 문서는 120문장씩 병렬 (전에는 앞 160문장만 봤음)

        def one(c):
            lines = "\n".join(f"- {p.id} | {p.text[:260]}" for p in c)
            return self.llm.structured(self.model, SYSTEM, USER.format(
                company=self.st.company, descriptor=(" (" + self.st.profile["descriptor"] + ")") if self.st.profile.get("descriptor") else "",
                title=doc["title"][:120], date=doc["date"], stype=doc["source_type"],
                syn=", internal (synthetic)" if doc.get("is_synthetic") else "", passages=lines, glossary=gl),
                GlossaryOut, purpose="glossary", max_tokens=4000)
        with ThreadPoolExecutor(max_workers=min(6, len(chunks))) as ex:
            outs = list(ex.map(one, chunks))
        return GlossaryOut(terms=[t for o in outs for t in o.terms], existing_aliases=[a for o in outs for a in o.existing_aliases])

    def apply(self, doc: dict, ps: list[Passage], out: GlossaryOut) -> dict:
        st, byp = self.st, {p.id: p for p in ps}
        n_new = n_alias = 0
        d = date.fromisoformat(doc["date"])
        for a in out.existing_aliases:
            t = self.lookup(a.name)
            if t and a.alias and not self.lookup(a.alias) and len(t.aliases) < 16:
                t.aliases.append(a.alias.strip()); self.by_name[norm(a.alias)] = t.id; n_alias += 1
                if t.eid:
                    self.res.register_alias(t.eid, a.alias.strip())
        for to in out.terms:
            nm = (to.name or "").strip().strip(".")
            if not nm or len(nm) > 60 or to.type not in TERM_TYPES or to.type == "stage":
                continue
            low = nm.lower()
            if any(w in low for w in ADMIN_WORDS):
                continue
            if to.type == "metric" and any(ch.isdigit() for ch in nm):
                continue                                    # "#AQ 35" 는 지표가 아니라 값
            if to.type == "application" and any(w in low for w in ("circuit", "algorithm", "program", "transform", "estimation",
                                                                      "sales", "contract", "partnership", "ionq")):
                if any(w in low for w in ("sales", "contract", "partnership", "ionq", self.st.company.lower())):
                    continue
                to.type = "technology"
            t = self.lookup(nm)
            if t is None:
                t = Term(name=nm, type=to.type, aliases=[x.strip() for x in to.aliases if x.strip() and norm(x) != norm(nm)][:8],
                         definition=(to.definition or "")[:240], unit=to.unit, direction=to.direction if to.direction in ("higher_better", "lower_better", "none") else None,
                         order=to.order, scope=to.scope if to.scope in TERM_SCOPES else "industry", first_doc=doc["id"], first_date=d)
                st.terms[t.id] = t
                for n in [t.name] + t.aliases:
                    self.by_name.setdefault(norm(n), t.id)
                n_new += 1
                st.emit("glossary.term", doc_id=doc["id"], tid=t.id, name=t.name, term_type=t.type, aliases=t.aliases, unit=t.unit, scope=t.scope)
            else:
                for x in to.aliases:
                    if x.strip() and not self.lookup(x) and len(t.aliases) < 16:
                        t.aliases.append(x.strip()); self.by_name[norm(x)] = t.id; n_alias += 1
                if not t.definition and to.definition:
                    t.definition = to.definition[:240]
            pids = [i for i in to.pids if i in byp]
            if doc["id"] not in {st.passages[i].doc_id for i in t.passage_ids if i in st.passages}:
                t.count += 1
            if t.count >= 2 and t.status == "candidate":      # 자동 확정 규칙 (2026-11-02): 문서 2건 이상
                t.status = "confirmed"
                st.emit("glossary.confirmed", doc_id=doc["id"], tid=t.id, name=t.name, term_type=t.type)
            for i in pids[:6]:
                if i not in t.passage_ids:
                    t.passage_ids.append(i)
            # 이름 사전 → 대상 색인 연결 (제품·기술·조직·응용·프로그램)
            if t.type in LINKED:
                p0 = byp.get(pids[0]) if pids else (ps[0] if ps else None)
                if p0 is not None and t.eid is None:
                    ent = self.res.resolve(None, t.name, p0, emit=False)
                    if ent:
                        t.eid = ent.id
                if t.eid:
                    for x in t.aliases:
                        self.res.register_alias(t.eid, x)
        return {"new_terms": n_new, "new_aliases": n_alias}


def attribute_vocab(st: SourceStore) -> str:
    """K5 추출기용 속성 어휘: 지표와 수명 단계 용어."""
    ms = [f"{t.name}" + (f" [{t.unit}]" if t.unit else "") + (f" (aka {', '.join(t.aliases[:3])})" if t.aliases else "")
          for t in st.terms_by_type("metric", confirmed_only=True)]
    ss = [t.name for t in st.terms_by_type("stage")]
    return ("metrics: " + ("; ".join(ms[:60]) or "(none yet)") + "\nstages: " + ("; ".join(ss[:30]) or "(none yet)"))


def export_review(st: SourceStore, path: Path) -> Path:
    """사용자 확인용 표 (md). 확정/거절은 이 표를 보고 받은 답으로 apply_review 가 반영."""
    rows = ["# K0 용어집 후보 확인표", "", f"항목 {len(st.terms)}개. 상태를 바꿀 것만 알려 주세요 (확정이 기본값, 거절·병합·이름 수정).", "",
            "| id | 이름 | 종류 | 별칭 | 단위·방향 | 범위 | 문서 수 | 정의 | 상태 |", "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(st.terms.values(), key=lambda t: (TERM_TYPES.index(t.type) if t.type in TERM_TYPES else 9, -t.count)):
        ud = (t.unit or "") + (f", {t.direction}" if t.direction and t.direction != "none" else "")
        rows.append(f"| {t.id} | {t.name} | {t.type} | {', '.join(t.aliases[:5])} | {ud} | {t.scope} | {t.count} | {t.definition[:120].replace('|', '/')} | {t.status} |")
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def apply_review(st: SourceStore, decisions: dict[str, str]) -> int:
    """{term_id: 'confirmed'|'rejected'|'merge:<other_id>'|'rename:<name>'}"""
    n = 0
    for tid, dec in decisions.items():
        t = st.terms.get(tid)
        if not t:
            continue
        if dec in ("confirmed", "rejected"):
            t.status = dec; n += 1
        elif dec.startswith("rename:"):
            t.name = dec[7:].strip(); t.status = "confirmed"; n += 1
        elif dec.startswith("merge:"):
            o = st.terms.get(dec[6:].strip())
            if o and o.id != t.id:
                o.aliases = list(dict.fromkeys(o.aliases + [t.name] + t.aliases))[:16]
                o.count += t.count; o.passage_ids = list(dict.fromkeys(o.passage_ids + t.passage_ids))
                t.status = "rejected"; n += 1
    return n
