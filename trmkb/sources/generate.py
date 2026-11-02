"""
구조 해석 생성기 — 작업지(구조별 요약표)와, 들어온 구조에 해당하는 읽기 규칙만 받아 로드맵을 만든다.
기업 소개문·지시문·출력 형식·모델·온도는 roadmap.generate 와 같다 (Initial 과 같은 고정 부분).
구조를 빼면 작업지와 그 읽기 규칙이 함께 빠진다.
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md §3 각 구조의 '생성기 읽기 절차', §5
"""
from __future__ import annotations

import hashlib

from ..llm import LLM
from ..roadmap import generate as G
from ..roadmap.retrieve import Context
from ..schema import Roadmap

CARDS = ("Opportunity cards: the context starts with one card per opportunity, assembled by code from the structures present "
         "(why rows and trend, what rows and timing chains, how/resource rows and relations, evidence ids). Treat each card as a "
         "candidate vertical slice of the roadmap: its why items drive its what items, which require its how/resource items; "
         "take dates from its timing chains and cite the ids on the card. Keep cards with strong support (a stated market, many links, many "
         "documents) and merge or drop weak ones; areas not covered by any card come from the sections after the cards.")
GLOSSARY = ("K0 glossary: use its canonical names for products, metrics, technologies and organizations in node labels; product "
            "generations are ordered; metric units and directions tell you how to read numbers.")
READING = {
    "grid": ("K3 opportunity linkage grid: build the what layer around the top-ranked opportunity columns (more linked rows "
             "and more supporting documents = higher priority). For each opportunity you keep, take its linked rows as "
             "candidates for why nodes (drivers, needs), what nodes (offerings), how nodes (capabilities) and resource nodes "
             "(enablers). 'direct' links are stated in documents; 'derived' links are inferred from the same plan."),
    "tree": ("K2 theme summary tree: use the root and area summaries to decide which areas the roadmap must cover; every area "
             "with substantial support should appear in at least one node. Use the yearly lines and trends to choose and "
             "describe why-layer drivers and to judge what is rising or declining."),
    "graph": ("K4 dependency graph: draw edges between roadmap nodes from the stated relations between subjects: drives -> "
              "drives; requires and part_of -> requires; enables, supplies and funds -> enables; precedes -> precedes. "
              "Prefer edges the graph supports, and cite the relation's evidence id on the nodes it connects."),
    "time": ("K5 temporal knowledge graph: set each node's start/end from the most recent statement about its target (the "
             "last item of a chain). If a target was revised (UPDATE), use the latest value and add the flag \"revised\"; if "
             "statements conflict, add \"conflict\". Things already achieved before 2025 are not future nodes unless they "
             "continue into the horizon."),
    "evidence": ("K1 evidence store: cite the passage ids that support each node in evidence_ids. Prefer public sources over "
                 "internal documents when both exist; a node supported only by internal documents should still cite them."),
}


def reading_rules(structures: list[str], *, cards: bool = True, glossary: bool = True) -> str:
    rules = ([f"- {GLOSSARY}"] if glossary else []) + ([f"- {CARDS}"] if cards else []) \
        + [f"- {READING[s]}" for s in ("grid", "tree", "graph", "time", "evidence") if s in structures]
    return "How to read the knowledge structures in this context:\n" + "\n".join(rules) + "\n"


def build_prompt(ctx: Context) -> str:
    base = G.INSTRUCTIONS.format(company=G.COMPANY, h0=G.HORIZON[0], h1=G.HORIZON[1], brief=G.BRIEF, **G.LAYER_GUIDE)
    return base + G.CONTEXT_HEADER + "\n" + reading_rules(ctx.stats.get("structures", []), cards=bool(ctx.stats.get("cards")),
                                                           glossary=bool(ctx.stats.get("chars_glossary"))) + "\n" + ctx.text.strip() + "\n" + G.OUTPUT_SPEC


def generate(llm: LLM, ctx: Context, *, model: str = G.DEFAULT_MODEL, temperature: float = 0.2) -> Roadmap:
    before = llm.ledger.total_usd
    user = build_prompt(ctx)
    out = llm.structured(model, G.SYSTEM, user, G.RoadmapOut, purpose="roadmap_structured", temperature=temperature, max_tokens=8000)
    rm = G.to_roadmap(out, condition="advanced", model=model, ops_by_evidence=ctx.ops_by_ref, cost_usd=llm.ledger.total_usd - before)
    rm.prompt_hash = hashlib.sha256((G.SYSTEM + user.replace(ctx.text.strip(), "")).encode("utf-8")).hexdigest()[:16]
    return rm
