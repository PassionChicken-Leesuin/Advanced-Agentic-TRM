"""TRM-making 단계 — 선정된 기회 카드(v2) 전문 + 랜드스케이프 요약을 읽고 로드맵을 만든다.

파이프라인 (2026-11-03 확정): Landscaping(K1·K2·K4·K5) → 카드 추출(cards_v2) → 선정(select: 세 질문 토론) → 제작(이 모듈).
컨텍스트 = K0 범례 + K2 랜드스케이프 요약(라벨 없이 연도별 문서 수) + 선정 카드 전문(선정 이유 포함) [+ 선정 밖 카드 요약본].
기업 소개·지시문·출력 형식·모델·온도는 roadmap.generate 와 같다.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..llm import LLM
from ..roadmap import generate as G
from ..roadmap.retrieve import Context
from ..schema import Roadmap, RoadmapOp
from .cards_v2 import Card
from .store import SourceStore
from .worksheets import glossary_legend

ID_RE = re.compile(r"\b(?:ps|tf)_[0-9a-f]+\b")

RULES = """How to read this context:
- K0 glossary: use its canonical names for products, metrics, technologies and organizations; product generations are ordered.
- Landscape: the company's document base summarised by area, with the number of documents per year that touch each area
  (public n/total, internal n/total). No trend labels are given: judge direction yourself from the numbers and the yearly lines.
- Opportunity cards: one card per opportunity the company's documents describe, assembled by code. Lines: state (current lifecycle
  stage), why (the company's own need/driver/vision sentences), trend (documents per year for the card's themes), what (offerings and
  their latest facts), when (dated statements per subject and attribute in the order made; UPDATE/CONFLICT mark revisions), how
  (capabilities/components linked by stated relations, with latest metrics), resource (enablers), actors, issue (risks, barriers,
  open questions, actions). Every item carries evidence ids (ps_ = passage, tf_ = time fact); 'internal' marks internal documents.
- Selection: the cards shown were chosen by a panel debate on three questions (why go / where are we / can we get there); each card's
  profile and the panel's reasons are given. Build the roadmap from these cards: a card's why lines become why nodes, its offerings
  and dated targets become what nodes with start/end taken from the when lines (latest statement wins; add "revised" when a target
  was UPDATEd, "conflict" when statements conflict), its how/resource lines become how/resource nodes, and the stated relations become
  edges. Cards marked 'path needed' have demand but no documented path: include the need and mark the missing capability as a how
  node with flag "infeasible" if no timeline exists. Cite the ids from the cards in evidence_ids.
"""


def _card_from_dict(d: dict) -> Card:
    return Card(**{k: (set(v) if k in ("pids", "elements") else v) for k, v in d.items()})


def landscape_text(st: SourceStore, max_chars: int = 9000) -> str:
    """K2 랜드스케이프: 라벨 없이 연도별 문서 수. 루트 요약 + 영역별 요약·연도 줄."""
    tree = st.tree or {}
    totals_pub, totals_int, seen = {}, {}, set()
    for p in st.passages.values():
        if p.routed and p.status not in ("irrelevant", "duplicate") and p.doc_id not in seen:
            seen.add(p.doc_id)
            d = totals_int if p.is_synthetic else totals_pub
            d[p.doc_date.year] = d.get(p.doc_date.year, 0) + 1
    tmap = {t["id"]: t for t in tree.get("themes", [])}
    area_docs = {}
    for a in tree.get("areas", []):
        yd = {}
        for tid in a.get("theme_ids", []):
            for pid in tmap.get(tid, {}).get("pids", []):
                p = st.passages.get(pid)
                if p and p.status not in ("irrelevant", "duplicate"):
                    yd.setdefault((p.doc_date.year, p.is_synthetic), set()).add(p.doc_id)
        area_docs[a["name"]] = yd
    lines = ["## Landscape (K2 theme summary tree; documents per year that touch each area, public n/total, internal n/total)"]
    root = tree.get("root", {})
    if root.get("summary"):
        lines.append("Root: " + root["summary"])
    years = sorted(set(totals_pub) | set(totals_int))
    for a in tree.get("areas", []):
        yd = area_docs[a["name"]]
        cells = []
        for y in years:
            pub = len(yd.get((y, False), ())); it = len(yd.get((y, True), ()))
            cells.append(f"{y}: {pub}/{totals_pub.get(y, 0)}" + (f" (+{it}/{totals_int.get(y, 0)} internal)" if totals_int.get(y) else ""))
        lines.append(f"\n### Area: {a['name']} ({a.get('passages', 0)} passages; documents per year: {', '.join(cells)})")
        lines.append(re.sub(r"\b(rising|declining|stable)\b trend|trend (rising|declining|stable)", "", a.get("summary", "")).strip())
        per = "; ".join(f"{x['year']}: {x['line']}" for x in a.get("periods", [])[-5:])
        if per:
            lines.append("yearly: " + per)
    txt = "\n".join(lines)
    return txt[:max_chars]


def build_context(st: SourceStore, cards_dir: Path, *, selection: str = "debate", top: int = 10, include_digest: bool = False,
                  label: str = "", stance: str = "balanced") -> Context:
    """selection: 'debate' (토론 프로파일 순위; stance = balanced|q1|q2|q3 → profiles[_stance].json) | 'support' (문서 수 순) | 'all' (전부, 선정 없음)."""
    cards = [_card_from_dict(d) for d in json.loads((cards_dir / "cards.json").read_text(encoding="utf-8"))]
    by = {c.eid: c for c in cards}
    profiles = {}
    pf = cards_dir / "selection" / ("profiles.json" if stance == "balanced" else f"profiles_{stance}.json")
    if pf.exists():
        profiles = {r["eid"]: r for r in json.loads(pf.read_text(encoding="utf-8"))}
    if selection == "debate":
        order = [r["eid"] for r in sorted(profiles.values(), key=lambda r: r["profile"]["rank"]) if r["eid"] in by and r["profile"].get("selected", True)][:top]
    elif selection == "support":
        order = [c.eid for c in sorted(cards, key=lambda c: -(c.docs_public + c.docs_internal))][:top]
    else:
        order = [c.eid for c in cards]
    ctx = Context(text="")
    parts = [f"(context condition {label or 'cards_v2-' + selection}: landscape + {len(order)} opportunity cards" + (" + digest of the rest" if include_digest else "") + ")",
             glossary_legend(st), landscape_text(st)]
    from .select import STANCES
    hdr = f"## Opportunity cards ({len(order)} of {len(cards)}; " + (f"selected by panel debate on three questions; stance: {STANCES[stance]['label']} ({STANCES[stance]['desc']})" if selection == "debate"
          else "selected by document support" if selection == "support" else "all, no selection") + ")"
    parts.append(hdr)
    for k, eid in enumerate(order, 1):
        c = by[eid]
        head = f"--- card {k} ---"
        if eid in profiles and selection == "debate":
            p = profiles[eid]["profile"]
            reasons = []
            for m, v in profiles[eid]["models"].items():
                r = v["final"]["reasons"]
                reasons.append(f"{m}: why {r.get('q1', '')[:140]} | now {r.get('q2', '')[:140]} | path {r.get('q3', '')[:140]}")
            head += (f"\nselection profile: why-go {p['q1']}/10, where-now {p['q2']}/10, can-get-there {p['q3']}/10"
                     + (" | PATH NEEDED (demand without documented path)" if p.get("path_needed") else "") + "\npanel reasons: " + " || ".join(reasons))
        parts.append(head + "\n" + c.text())
        # 출처 → 연산 태그 (produced_by)
        for ln in c.why:
            for i in ID_RE.findall(ln):
                ctx.tag(i, RoadmapOp.GROUNDING); ctx.tag(i, RoadmapOp.OPPORTUNITY)
        for ln in c.trend:
            pass
        for ln in c.state + c.what + c.when:
            for i in ID_RE.findall(ln):
                ctx.tag(i, RoadmapOp.GROUNDING); ctx.tag(i, RoadmapOp.TIMING)
        for ln in c.how + c.resource + c.actors + c.issue:
            for i in ID_RE.findall(ln):
                ctx.tag(i, RoadmapOp.GROUNDING); ctx.tag(i, RoadmapOp.LINK)
        for i in c.pids:
            ctx.tag(i, RoadmapOp.OPPORTUNITY)
    if include_digest:
        rest = [by[e] for e in by if e not in set(order)]
        parts.append(f"## Other opportunities in the documents (not selected; digest only, {len(rest)})")
        parts += [c.digest() for c in rest]
    ctx.text = "\n\n".join(parts)
    ctx.selected_node_ids = order
    ctx.stats = {"condition": label or f"cards_v2-{selection}", "structures": ["evidence", "tree", "graph", "time"], "cards": len(order), "stance": stance,
                 "chars": len(ctx.text), "selection": selection, "top": top, "include_digest": include_digest,
                 "chars_cards": sum(len(by[e].text()) for e in order), "chars_landscape": len(parts[2]), "chars_glossary": len(parts[1])}
    return ctx


def build_prompt(ctx: Context) -> str:
    base = G.INSTRUCTIONS.format(company=G.COMPANY, h0=G.HORIZON[0], h1=G.HORIZON[1], brief=G.BRIEF, **G.LAYER_GUIDE)
    return base + G.CONTEXT_HEADER + "\n" + RULES + "\n" + ctx.text.strip() + "\n" + G.OUTPUT_SPEC


def generate(llm: LLM, ctx: Context, *, model: str = G.DEFAULT_MODEL, temperature: float = 0.2) -> Roadmap:
    before = llm.ledger.total_usd
    user = build_prompt(ctx)
    out = llm.structured(model, G.SYSTEM, user, G.RoadmapOut, purpose="roadmap_cards_v2", temperature=temperature, max_tokens=8000)
    rm = G.to_roadmap(out, condition="advanced", model=model, ops_by_evidence=ctx.ops_by_ref, cost_usd=llm.ledger.total_usd - before)
    rm.prompt_hash = hashlib.sha256((G.SYSTEM + user.replace(ctx.text.strip(), "")).encode("utf-8")).hexdigest()[:16]
    return rm
