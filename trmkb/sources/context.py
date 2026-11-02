"""
S5 컨텍스트 (v2 사용 단계): 2단.
  A. 주제 선정 — 계획자(LLM)가 그리드 개요(기회 열, 층별 상위 행, 시점, 지지 문서 수)를 보고 로드맵 주제 대상을 고른다.
     S5np 는 계획자 없이 층별 지지도 순으로 고른다 (계획자 효과 분리용).
  B. 주제별 블록 — 대상마다 여러 문서의 근거 문장(최근·미래 지향 우선, 문서 중복 없이)과 그리드 연결을 묶는다.
     글자 예산을 주제 수로 나눠 배분하므로 절이 통째로 잘리지 않는다.
생성기 프롬프트는 1막·다른 조건과 동일하고, 이 컨텍스트 블록만 다르다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import LLM
from ..roadmap.retrieve import Context
from ..schema import RoadmapOp
from .store import SourceStore

PLANNER_MODEL = "openai/gpt-4.1-mini"
QUOTA = {"why": 7, "what": 11, "how": 10, "resource": 6}
FORWARD = {"planned": 0, "forecast": 0, "required": 1, "vision": 1, "achieved": 2, "current": 3, None: 3}


class Pick(BaseModel):
    eid: str
    layer: str
    why: str = ""


class Picks(BaseModel):
    topics: list[Pick] = Field(default_factory=list)


def _tr(e) -> str:
    if e.time_min is None:
        return "t=?"
    return f"t={e.time_min:.1f}" + (f"–{e.time_max:.1f}" if e.time_max and e.time_max != e.time_min else "")


def overview(st: SourceStore, grid: dict, real_only: bool, per_layer: int = 35) -> str:
    lines = ["## Opportunities (grid columns): eid | name | supporting documents | time | linked rows"]
    for c in grid.get("columns", []):
        e = st.entities[c["eid"]]
        lines.append(f"- {e.id} | {e.name} | {st.support(e.id, real_only=real_only)} docs | {_tr(e)} | {c['links']} links")
    for layer in ("why", "how", "resource"):
        lines.append(f"\n## {layer} rows (grid): eid | name | docs | time | links to opportunities")
        for r in grid.get("rows", {}).get(layer, [])[:per_layer]:
            e = st.entities[r["eid"]]
            lines.append(f"- {e.id} | {e.name} | {r['support']} docs | {_tr(e)} | {r['links']} links")
    # 그리드 밖 what 대상 (마일스톤 등)
    col_ids = {c["eid"] for c in grid.get("columns", [])}
    extra = [e for e in st.entities.values() if e.layer == "what" and e.id not in col_ids and st.support(e.id, real_only=real_only) >= 2]
    extra.sort(key=lambda e: -st.support(e.id, real_only=real_only))
    lines.append("\n## Other what subjects (milestones, targets, offerings): eid | name | docs | time")
    for e in extra[:per_layer]:
        lines.append(f"- {e.id} | {e.name} | {st.support(e.id, real_only=real_only)} docs | {_tr(e)}")
    return "\n".join(lines)


PLAN_SYSTEM = "You plan the rows of a company technology roadmap from a knowledge-base overview. JSON only."
PLAN_USER = """Company: IonQ. Horizon 2025-2030. Knowledge cutoff 2024-12-31.

Knowledge-base overview (subjects with how many independent documents support them, their time range and grid links):
{ov}

Select 26 to 34 subjects to become roadmap items, by eid. Aim for about {q} items per layer (why, what, how, resource).
Prefer subjects that (1) are supported by several independent documents, (2) carry forward-looking statements about
2025-2030 (targets, plans, requirements), (3) are linked to opportunities in the grid, and (4) are specific to IonQ rather
than generic. Avoid legal, financing-transaction and boilerplate subjects.

Return JSON: {{"topics": [{{"eid": str, "layer": "why"|"what"|"how"|"resource", "why": str (under 12 words)}}]}}"""


def pick_topics(st: SourceStore, grid: dict, llm: LLM | None, real_only: bool) -> list[tuple[str, str]]:
    if llm is None:   # S5np: 층별 지지도 순
        out = []
        for layer, q in QUOTA.items():
            es = [e for e in st.entities.values() if e.layer == layer]
            es.sort(key=lambda e: -st.support(e.id, real_only=real_only))
            out += [(e.id, layer) for e in es[:q] if st.support(e.id, real_only=real_only) > 0]
        return out
    res = llm.structured(PLANNER_MODEL, PLAN_SYSTEM, PLAN_USER.format(ov=overview(st, grid, real_only), q="7-10"),
                         Picks, purpose="planner_v2", max_tokens=2500)
    seen, out = set(), []
    for t in res.topics:
        if t.eid in st.entities and t.eid not in seen:
            seen.add(t.eid); out.append((t.eid, t.layer if t.layer in QUOTA else (st.entities[t.eid].layer or "what")))
    return out


def build_context(st: SourceStore, *, planner: LLM | None = None, real_only: bool = False, grid: dict | None = None,
                  max_chars: int = 70_000, per_topic_passages: int = 6) -> Context:
    grid = grid if grid is not None else st.grid
    topics = pick_topics(st, grid, planner, real_only)
    ctx = Context(text="")
    cells_by = {}
    for c in grid.get("cells", []):
        cells_by.setdefault(c["row"], []).append(c); cells_by.setdefault(c["col"], []).append(c)
    budget = max(800, (max_chars - 600) // max(1, len(topics)))
    blocks = [f"(context condition {'S5' if planner else 'S5np'}{' real-only' if real_only else ''}: roadmap topics, each with "
              "multi-source passages and grid links)", "## Topics"]
    used_p = 0
    for eid, layer in topics:
        e = st.entities[eid]
        tags = ",".join(sorted(e.layer_counts, key=lambda l: -e.layer_counts[l]))
        head = f"\n### {e.id} | {layer} | {e.name} | tags {tags} | {_tr(e)} | {st.support(eid, real_only=real_only)} docs"
        ps = [p for p in st.passages_of(eid, real_only=real_only) if p.status not in ("irrelevant", "duplicate")]
        # 문서당 1개, 미래 지향·최근 우선
        ps.sort(key=lambda p: (FORWARD.get(p.modality, 3), -p.doc_date.toordinal()))
        chosen, docs = [], set()
        for p in ps:
            if p.doc_id in docs:
                continue
            chosen.append(p); docs.add(p.doc_id)
            if len(chosen) >= per_topic_passages:
                break
        chosen.sort(key=lambda p: p.doc_date)
        lines = [head]
        for p in chosen:
            t = f" [refers to {p.time_raw or p.time_start}]" if (p.time_raw or p.time_start) else ""
            flag = f" [{p.status.upper()} of {p.related_pid}]" if p.status in ("update", "conflict") and p.related_pid else ""
            lines.append(f"- {p.id} ({p.doc_date}, {p.source_type}{', internal' if p.is_synthetic else ''}, {p.modality}): {p.statement[:260]}{t}{flag}")
            ctx.tag(p.id, RoadmapOp.GROUNDING); ctx.tag(p.id, RoadmapOp.PRIORITY)
            if p.time_start is not None:
                ctx.tag(p.id, RoadmapOp.TIMING)
            if p.status in ("update", "conflict"):
                ctx.tag(p.id, RoadmapOp.TREND)
        for c in cells_by.get(eid, [])[:6]:
            other = c["col"] if c["row"] == eid else c["row"]
            arrow = f"{st.entities[c['row']].name} --{c['relation']}--> {st.entities[c['col']].name}"
            lines.append(f"  link: {arrow} (strength {c['strength']}, {c['derivation']}, evidence {c['evidence_pid']})")
            if c["evidence_pid"]:
                ctx.tag(c["evidence_pid"], RoadmapOp.LINK)
            for p in chosen:
                ctx.tag(p.id, RoadmapOp.LINK)
        block = "\n".join(lines)
        if len(block) > budget:
            block = block[:budget].rsplit("\n", 1)[0]
        blocks.append(block); used_p += len(chosen)
    ctx.text = "\n".join(blocks)
    ctx.selected_node_ids = [eid for eid, _ in topics]
    ctx.stats = {"condition": "S5" if planner else "S5np", "real_only": real_only, "topics": len(topics), "passages": used_p,
                 "chars": len(ctx.text), "by_layer": {l: sum(1 for _, x in topics if x == l) for l in QUOTA}}
    return ctx
