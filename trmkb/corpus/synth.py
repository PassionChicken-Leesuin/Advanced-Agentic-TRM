"""
trmkb.corpus.synth — 가상 내부자료 생성기 (심은 사실 원장 기반).

절차:
  1. data/facts_ledger.json 의 사실 N개를 문서 M개에 배정 (결정적, seed 고정).
     - 사실마다 2~3개 문서에 분산, 모순 쌍(contradicts)은 서로 다른 문서·다른 날짜에.
     - 문서 유형별 친화도: 고객 니즈→고객 메일·회의록, 공급사→공급사 메일·회의록,
       결정·열린질문→기술평가서·회의록, 역량·구성요소→R&D 주간보고·기술평가서.
  2. 문서마다 LLM이 유형에 맞는 영어 문서를 작성. 심은 사실은 의미를 보존해 자연스럽게 녹이고,
     주변은 그럴듯한 일상 내용으로 채운다. 출력 JSON: {title, body, facts_included:[{id, sentence}]}.
  3. data/corpus/synthetic_data/text/<id>.md 저장 (frontmatter에 planted_fact_ids), 원장에 planted_in_doc_ids 역기록.

모델 선택은 CLI 인자. 기본 anthropic/claude-sonnet-4.6 (OpenRouter 가격 기준 50건 ≈ $1).
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from ..llm import LLM
from ..schema import SourceType
from .common import CORPUS_ROOT, CorpusDoc, log, save_json

LEDGER_PATH = CORPUS_ROOT.parent / "facts_ledger.json"

DOC_TYPES: dict[str, dict] = {
    "syn_meeting": {
        "label": "internal meeting minutes",
        "count": 14,
        "affinity": {"need", "milestone", "issue", "enabler", "actor", "opportunity", "driver"},
        "style": "Minutes of an internal IonQ leadership or program meeting: attendees by role (no real names), agenda, discussion bullets, decisions, action items with owners and dates. 500-800 words.",
    },
    "syn_rd_report": {
        "label": "R&D weekly report",
        "count": 14,
        "affinity": {"capability", "component", "milestone", "issue"},
        "style": "Weekly engineering status report from a hardware or software team lead: progress, measurements with numbers and units, blockers, next week plan, risks. 500-800 words. Technical tone.",
    },
    "syn_customer_email": {
        "label": "customer email thread",
        "count": 8,
        "affinity": {"need", "opportunity", "driver"},
        "style": "An email thread (2-4 messages) between an IonQ account lead and a customer technical contact. Customer states requirements and timelines; IonQ responds. Include subject line and signatures by role only. 400-700 words.",
    },
    "syn_supplier_email": {
        "label": "supplier email thread",
        "count": 7,
        "affinity": {"enabler", "component", "milestone", "actor", "issue"},
        "style": "An email thread (2-4 messages) between IonQ procurement/engineering and a component supplier about lead times, yields, delivery slips, quotes. 400-700 words.",
    },
    "syn_tech_assessment": {
        "label": "internal technology assessment memo",
        "count": 7,
        "affinity": {"issue", "capability", "component", "driver", "actor", "enabler"},
        "style": "An internal technology/strategy assessment memo: background, options considered with pros/cons, estimates with numbers, open questions, recommendation, risks. 700-1000 words.",
    },
}

FILLER_TOPICS = [
    "cloud job scheduler maintenance window", "calibration cadence for Aria-class systems", "intern program onboarding",
    "ISO 27001 audit preparation", "conference travel budget", "laser alignment procedure revision", "data retention policy",
    "customer success quarterly review", "SDK release notes", "facilities HVAC upgrade", "patent disclosure backlog",
    "benchmark reproducibility checklist", "vendor security questionnaire", "hiring pipeline for software engineers",
    "quarterly OKR review", "lab safety training", "documentation portal migration", "cryostat spare parts inventory",
    "noise characterization study", "compiler optimization pass", "partner webinar planning", "Q-CTRL integration test",
]


class _GenOut(BaseModel):
    title: str
    body: str
    facts_included: list[dict[str, str]] = Field(default_factory=list)  # {id, sentence}


@dataclass
class SynthSpec:
    doc_id: str
    doc_type: str
    date: date
    fact_ids: list[str]
    fillers: list[str] = field(default_factory=list)


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def plan(ledger: dict, *, seed: int = 7, start: date = date(2024, 1, 8), end: date = date(2024, 12, 20),
         facts_per_doc: tuple[int, int] = (1, 4), appearances: tuple[int, int] = (2, 3),
         late_docs: int = 8, late_window_days: int = 45) -> list[SynthSpec]:
    rng = random.Random(seed)
    facts = {f["id"]: f for f in ledger["facts"]}
    # 문서 슬롯 생성 (유형별 count, 날짜 균등 산포)
    specs: list[SynthSpec] = []
    span = (end - start).days
    # 유형 라벨을 섞어 날짜 슬롯에 배정 → 유형이 기간 전체에 고루 퍼짐
    labels = [dt for dt, cfg in DOC_TYPES.items() for _ in range(cfg["count"])]
    rng.shuffle(labels)
    # 사실 대부분이 2024 하반기에 생기므로 마지막 late_window_days 안에 late_docs 건을 보장
    early = rng.sample(range(span - late_window_days), len(labels) - late_docs)
    late = rng.sample(range(span - late_window_days, span + 1), late_docs)
    slots = sorted(early + late)
    counters: dict[str, int] = {dt: 0 for dt in DOC_TYPES}
    for day, dt in zip(slots, labels):
        d = start + timedelta(days=day)
        counters[dt] += 1
        specs.append(SynthSpec(doc_id=f"syn_{dt[4:]}_{d.isoformat()}_{counters[dt]:02d}", doc_type=dt, date=d,
                               fact_ids=[], fillers=rng.sample(FILLER_TOPICS, 2)))
    specs.sort(key=lambda s: s.date)

    def window_ok(f: dict, s: SynthSpec) -> bool:
        nb = f.get("not_before"); na = f.get("not_after")
        if nb and s.date < date.fromisoformat(nb):
            return False
        if na and s.date > date.fromisoformat(na):
            return False
        return True

    def eligible(f: dict, s: SynthSpec) -> bool:
        if f["expected_node_type"] not in DOC_TYPES[s.doc_type]["affinity"]:
            return False
        if len(s.fact_ids) >= facts_per_doc[1]:
            return False
        if not window_ok(f, s):
            return False
        # 모순 쌍은 같은 문서에 두지 않는다 (양방향 검사)
        c = f.get("contradicts")
        if c and c in s.fact_ids:
            return False
        if any(facts[x].get("contradicts") == f["id"] for x in s.fact_ids):
            return False
        return True

    # 사실 배정: 날짜 창이 좁은 사실부터 (배정 실패 방지), 덜 찬 문서·다른 유형 우선
    def width(f: dict) -> int:
        nb = date.fromisoformat(f.get("not_before", start.isoformat()))
        na = date.fromisoformat(f.get("not_after", end.isoformat()))
        return (na - nb).days
    for f in sorted(facts.values(), key=width):
        fid = f["id"]
        n = rng.randint(*appearances)
        pool = [s for s in specs if eligible(f, s)]
        rng.shuffle(pool)
        chosen: list[SynthSpec] = []
        used_types: set[str] = set()
        for s in sorted(pool, key=lambda s: (s.doc_type in used_types, len(s.fact_ids))):
            if len(chosen) >= n:
                break
            chosen.append(s); used_types.add(s.doc_type)
        for s in chosen:
            s.fact_ids.append(fid)
        if not chosen:
            log(f"[synth] WARNING: no eligible doc for {fid}")
    # 최소 개수 보장
    for s in specs:
        tries = 0
        while len(s.fact_ids) < facts_per_doc[0] and tries < 20:
            tries += 1
            cands = [f for f in facts.values() if eligible(f, s) and f["id"] not in s.fact_ids]
            if not cands:
                break
            s.fact_ids.append(rng.choice(cands)["id"])
    return specs


SYSTEM = """You write realistic internal business documents for IonQ, a trapped-ion quantum computing company, as they would have existed on the given date. The documents are fictional but must read as authentic internal material. Use roles instead of real personal names (e.g., "VP Hardware", "Account Lead", "Procurement Manager"). Fictional partner/supplier names given in the facts may be used as-is. Do not mention that anything is fictional. Do not include knowledge of events after the document date."""

USER_TMPL = """Document type: {label}
Date: {date}
Style: {style}

You MUST weave in every one of the following facts so that each is clearly stated (paraphrase allowed, but keep every number, name, date and qualifier intact). They should appear as natural parts of the document, not as a list:
{facts}

Also include ordinary, unrelated operational content on these topics to make the document realistic: {fillers}.

Return JSON: {{"title": str, "body": str (markdown or plain text, no frontmatter), "facts_included": [{{"id": fact id, "sentence": the exact sentence in the body that conveys it}}]}}"""


def generate(specs: list[SynthSpec], ledger: dict, llm: LLM, model: str, *, root: Path = CORPUS_ROOT,
             overwrite: bool = False) -> list[CorpusDoc]:
    facts = {f["id"]: f for f in ledger["facts"]}
    docs: list[CorpusDoc] = []
    manifest = []
    for s in specs:
        out_path = root / "synthetic_data" / "text" / f"{s.doc_id}.md"
        if out_path.exists() and not overwrite:
            log(f"[synth] skip existing {s.doc_id}"); continue
        cfg = DOC_TYPES[s.doc_type]
        facts_txt = "\n".join(f"- [{fid}] {facts[fid]['text']}" for fid in s.fact_ids)
        user = USER_TMPL.format(label=cfg["label"], date=s.date.isoformat(), style=cfg["style"],
                                facts=facts_txt, fillers=", ".join(s.fillers))
        out = llm.structured(model, SYSTEM, user, _GenOut, purpose="synth", temperature=0.7, max_tokens=3000)
        included = {d.get("id") for d in out.facts_included}
        missing = [fid for fid in s.fact_ids if fid not in included]
        doc = CorpusDoc(
            id=s.doc_id, title=out.title, source_type=SourceType(s.doc_type), date=s.date, url=None,
            body=out.body, actor="IonQ (internal)", is_synthetic=True, planted_fact_ids=list(s.fact_ids),
            extra={"doc_type": s.doc_type, "facts_included": out.facts_included, "facts_missing_by_self_report": missing},
        )
        doc.write(root)
        docs.append(doc)
        for fid in s.fact_ids:
            facts[fid].setdefault("planted_in_doc_ids", [])
            if s.doc_id not in facts[fid]["planted_in_doc_ids"]:
                facts[fid]["planted_in_doc_ids"].append(s.doc_id)
        manifest.append({"id": s.doc_id, "date": s.date.isoformat(), "type": s.doc_type, "facts": s.fact_ids,
                         "missing_self_report": missing, "chars": len(out.body)})
        log(f"[synth] {s.doc_id} facts={s.fact_ids} missing={missing} ({len(out.body):,} chars)")
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    save_json(root / "synthetic_data" / "_manifest_synth.json", manifest)
    return docs


def coverage(ledger: dict) -> dict:
    facts = ledger["facts"]
    n_docs = {f["id"]: len(f.get("planted_in_doc_ids", [])) for f in facts}
    return {"facts": len(facts), "min_docs": min(n_docs.values()), "max_docs": max(n_docs.values()),
            "unplanted": [k for k, v in n_docs.items() if v == 0]}
