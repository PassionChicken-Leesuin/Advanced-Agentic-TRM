"""
K2 주제 요약 트리 (RAPTOR 계열) 정리 단계.
  잎   = Router 가 tree 로 보낸 소스 문장 (TreeExtractor 가 주제에 배정)
  주제 = 배정된 문장들의 요약 + 기간(연도)별 요약 줄 + 연도별 문서 수
  영역 = 주제를 묶은 상위 묶음 (LLM 이 6~12개로 묶음) + 영역 요약 + 기간별 줄 + 연도별 문서 수
추세 라벨 없음 (2026-11-03 결정, 2026-11-08 코드 반영): rising/declining 같은 라벨을 LLM 에게 묻지도, 저장하지도 않는다.
  연도별 "그 주제를 다룬 문서 수 / 그해 전체 문서 수" 표만 요약의 근거로 넘기고 그대로 저장한다. 방향 판단은 읽는 쪽(생성기·사람)의 몫.
  전체 = 영역 요약을 다시 요약 + 주요 변화
추세 (2026-11-02 확정): 코드가 연도별 "그 주제를 다룬 문서 수 / 그해 전체 문서 수" 비율과 기울기, 강조 신호(확대·축소) 수를 계산해
  LLM 에 넘기고, LLM 이 그 수치를 보고 추세와 요약을 쓴다. 문서 수가 해마다 느는 편향(2020 10건 → 2024 76건)을 비율로 걷어낸다.
real_only=True 이면 가상(내부) 문서 문장을 빼고 같은 절차로 만든다 (실제 자료 전용 조건용).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from ..llm import LLM
from .store import SOURCE_WEIGHT, SourceStore

MODEL = "openai/gpt-4.1-mini"


class Period(BaseModel):
    year: int
    line: str


class ThemeSum(BaseModel):
    summary: str
    periods: list[Period] = Field(default_factory=list)
    trend: str | None = None          # 더 이상 묻지 않음 (옛 run 읽기 호환용)
    trend_reason: str = ""


class AreaPlan(BaseModel):
    name: str
    theme_ids: list[int] = Field(default_factory=list)


class AreaPlans(BaseModel):
    areas: list[AreaPlan] = Field(default_factory=list)


class RootSum(BaseModel):
    summary: str
    shifts: list[str] = Field(default_factory=list)


def _sys(st=None) -> str:
    co = st.company if st is not None else "IonQ"
    return f"You write the summary tree of a technology-roadmapping knowledge base about {co} (RAPTOR-style). JSON only."

SHARE_NOTE = """The share table gives, per year, how many documents of that year touch this {unit} out of all documents of the year.
Use it as evidence for the yearly lines; do not label the direction (no "rising", "declining" or similar trend words)."""

THEME_USER = """Theme: "{name}". Source passages grouped by the year of the document that states them:
{groups}

Share table (year: documents touching the theme / all documents that year = share):
{shares}

Write: summary (2-3 sentences: what the documents say about this theme, keep key numbers and dates);
periods: one line per year saying what was emphasized or changed that year (under 25 words).
""" + SHARE_NOTE.format(unit="theme") + """

Return JSON: {{"summary": str, "periods": [{{"year": int, "line": str}}]}}"""

AREA_PLAN_USER = """Themes of the knowledge base (# | name | passages | documents | summary):
{themes}

Group ALL {n} themes into 6 to 12 areas, each area a coherent strand of a technology roadmap (for example market and
demand, products and systems, core hardware technology, error correction, networking, software and access, enablers
such as funding, facilities and partners). Every theme number listed above must appear in exactly one area; do not
stop early and do not leave themes out. Area names: 2-5 words.{existing}

Return JSON: {{"areas": [{{"name": str, "theme_ids": [int]}}]}}"""

AREA_USER = """Area "{name}" of the knowledge base. Its themes with their summaries and yearly lines:
{themes}

Share table for the whole area (year: documents touching any theme of the area / all documents that year):
{shares}

Write the area summary (3-4 sentences, keep key numbers and dates) and one line per year on what changed in this area
(under 30 words).
""" + SHARE_NOTE.format(unit="area") + """

Return JSON: {{"summary": str, "periods": [{{"year": int, "line": str}}]}}"""

ROOT_USER = """Areas of the knowledge base with their summaries, yearly lines and document shares per year:
{areas}

Write the overall summary of where {company} and its market are heading as of the end of {year} (4-6 sentences), and list
3-6 major shifts over time (each under 25 words), preferring shifts that the share tables support.

Return JSON: {{"summary": str, "shifts": [str]}}"""


def _ok(st: SourceStore, pid: str, real_only: bool) -> bool:
    p = st.passages.get(pid)
    return bool(p) and p.status not in ("irrelevant", "duplicate") and not (real_only and p.is_synthetic)


# 추세(연도별 문서 비율·기울기)는 공개 문서만으로 계산한다 (2026-11-02 확정). 가상 내부 문서는 2024년에만 있어
# 시계열 신호가 아니라 분모 왜곡(2024년 비율 급락 → 전부 declining)만 만들기 때문. 요약·기간 서술에는 그대로 쓴다.
# 코퍼스 v2(가상 문서를 연도별로 뿌린 판)에서는 False 로 돌린다.
TREND_PUBLIC_ONLY = True
MIN_YEAR_DOCS = 10


def year_totals(st: SourceStore, real_only: bool) -> dict[int, int]:
    """연도별 전체 문서 수 (저장된 문장이 하나라도 있는 문서)."""
    docs = {}
    for p in st.passages.values():
        if _ok(st, p.id, real_only or TREND_PUBLIC_ONLY) and p.routed:
            docs[p.doc_id] = p.doc_date.year
    return dict(Counter(docs.values()))


def share_stats(st: SourceStore, pids: list[str], totals: dict[int, int]) -> dict:
    """주제(또는 영역)의 연도별 문서 비율, 기울기, 강조 신호, 계산 추세."""
    docs_by_year = defaultdict(set)
    emph = Counter()
    for i in pids:
        p = st.passages[i]
        if not (TREND_PUBLIC_ONLY and p.is_synthetic):
            docs_by_year[p.doc_date.year].add(p.doc_id)
        if p.emphasis in ("expanding", "declining", "new"):
            emph[p.emphasis] += 1
    years = sorted(totals)
    if not years:
        return {"shares": [], "slope": 0.0, "emphasis": dict(emph), "computed": "new"}
    first = min(docs_by_year) if docs_by_year else years[-1]
    rows = [{"year": y, "docs": len(docs_by_year.get(y, ())), "total": totals[y],
             "share": round(len(docs_by_year.get(y, ())) / totals[y], 3) if totals[y] else 0.0} for y in years if y >= first]
    # 그해 전체 문서가 10건 미만인 연도는 비율이 불안정해 기울기 계산에서 뺌 (표에는 남김). 180건 결과에서 2020년(7건)의
    # 비율이 과대해 많은 주제가 declining 으로 기울던 것을 보고 3 → 10 으로 올림 (2026-11-02).
    solid = [r for r in rows if r["total"] >= MIN_YEAR_DOCS] or rows
    xs = [r["year"] for r in solid]; ys = [r["share"] for r in solid]
    slope = 0.0
    if len(xs) >= 2:
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0
    mean = sum(ys) / len(ys) if ys else 0.0
    active = [r for r in rows if r["docs"]]
    if len(active) == 1 and active[0]["year"] == years[-1]:
        comp = "new"
    elif mean > 0 and slope / mean > 0.12:
        comp = "rising"
    elif mean > 0 and slope / mean < -0.12:
        comp = "declining"
    else:
        comp = "stable"
    # 강조 신호(Router 가 문장마다 붙인 new/expanding/declining)로 보정:
    #  - stable 인데 한쪽이 뚜렷하면(차이 3 이상) 그쪽으로.
    #  - 비율 기울기와 강조 신호가 정면으로 어긋나면(declining 인데 확대 문장이 축소의 3배 이상이고 3건 이상, 또는 그 반대) stable 로 내림.
    #    문서 비율은 코퍼스 구성(2021년 공시 밀집)에 끌려가므로 문장 수준 신호와 어긋날 때 단정하지 않는다 (2026-11-02).
    ex, de = emph["expanding"], emph["declining"]
    if comp == "stable":
        if ex >= de + 3:
            comp = "rising"
        elif de >= ex + 3:
            comp = "declining"
    elif comp == "declining" and ex >= 3 and ex >= 3 * de:
        comp = "stable"
    elif comp == "rising" and de >= 3 and de >= 3 * ex:
        comp = "stable"
    return {"shares": rows, "slope": round(slope, 4), "emphasis": dict(emph), "computed": comp}


def share_text(s: dict) -> str:
    return "; ".join(f"{r['year']}: {r['docs']}/{r['total']} = {round(r['share'] * 100)}%" for r in s["shares"]) or "(no data)"


def plan_areas(llm: LLM, out_themes: list[dict], model: str, *, max_rounds: int = 3, sys: str | None = None) -> list[dict]:
    """주제 → 영역 묶기. 번호(1..n)로 묻고, 빠진 주제는 기존 영역 목록을 보여 주며 재시도(2회차부터 상위 모델).
    끝까지 남는 주제만 'Other topics'로 간다."""
    ids = [r["id"] for r in out_themes]
    pos = {tid: k for k, tid in enumerate(ids, 1)}
    areas: list[dict] = []
    assigned: set[str] = set()
    todo = list(ids)
    for rnd in range(max_rounds):
        if not todo:
            break
        todo_set = set(todo)
        lines = [f"- {pos[r['id']]} | {r['name']} | {r['passages']} | {r['support']} | {r['summary'][:140]}"
                 for r in out_themes if r["id"] in todo_set]
        existing = ""
        if areas:
            existing = "\n\nAreas already formed (reuse these names where a theme fits, or add new ones):\n" + "\n".join(f"- {a['name']}" for a in areas)
        use_model = "openai/gpt-4.1"      # 영역 묶기는 한 번뿐이라 상위 모델 사용 (수 센트)
        plan = llm.structured(use_model, sys or _sys(), AREA_PLAN_USER.format(themes="\n".join(lines), n=len(todo), existing=existing),
                              AreaPlans, purpose="tree_areas", max_tokens=6000)
        by_name = {a["name"].strip().lower(): a for a in areas}
        for a in plan.areas:
            got = [ids[k - 1] for k in a.theme_ids if 1 <= k <= len(ids) and ids[k - 1] not in assigned and ids[k - 1] in todo_set]
            if not got:
                continue
            assigned |= set(got)
            key = a.name.strip().lower()
            if key in by_name:
                by_name[key]["theme_ids"].extend(got)
            else:
                rec = {"name": a.name.strip(), "theme_ids": got}
                areas.append(rec); by_name[key] = rec
        todo = [i for i in ids if i not in assigned]
    return [a for a in areas if a["theme_ids"]]


def build_tree(st: SourceStore, llm: LLM, *, real_only: bool = False, model: str = MODEL, min_passages: int = 2,
               emit: bool = True, workers: int = 8) -> dict:
    totals = year_totals(st, real_only)
    themes = {}
    for t in st.themes.values():
        pids = [i for i in t.passage_ids if _ok(st, i, real_only)]
        if pids:
            themes[t.id] = (t, pids)
    if emit:
        st.emit("tree.started", n_themes=len(themes), real_only=real_only, year_totals=totals)
    stats = {tid: share_stats(st, pids, totals) for tid, (t, pids) in themes.items()}

    def theme_job(tid):
        t, pids = themes[tid]
        by_year = defaultdict(list)
        for i in sorted(pids, key=lambda i: st.passages[i].doc_date):
            by_year[st.passages[i].doc_date.year].append(st.passages[i])
        groups = []
        for y in sorted(by_year)[-7:]:
            groups.append(f"[{y}]")
            seen = set()
            for p in by_year[y]:
                if p.doc_id in seen and len(by_year[y]) > 6:
                    continue
                seen.add(p.doc_id)
                groups.append(f"- {p.id} ({p.doc_date}, {p.source_type}{', internal' if p.is_synthetic else ''}"
                              f"{', ' + p.emphasis if p.emphasis in ('expanding', 'declining', 'new') else ''}): {p.statement[:240]}")
                if len(seen) >= 6:
                    break
        return llm.structured(model, _sys(st), THEME_USER.format(name=t.name, groups="\n".join(groups), shares=share_text(stats[tid])), ThemeSum,
                              purpose="tree_theme", max_tokens=1300)

    todo = [tid for tid, (t, pids) in themes.items() if len(pids) >= min_passages]
    sums: dict[str, ThemeSum] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for tid, res in zip(todo, ex.map(theme_job, todo)):
            sums[tid] = res
    out_themes = []
    for tid, (t, pids) in themes.items():
        docs = {}
        for i in pids:
            p = st.passages[i]
            docs[p.doc_id] = max(docs.get(p.doc_id, 0), SOURCE_WEIGHT.get(p.source_type, 1.0))
        s, sh = sums.get(tid), stats[tid]
        rec = {"id": tid, "name": t.name, "passages": len(pids), "support": round(sum(docs.values()), 2),
               "summary": s.summary if s else st.passages[pids[0]].statement[:240],
               "periods": [x.model_dump() for x in s.periods] if s else [],
               "trend": None, "shares": sh["shares"], "emphasis": sh["emphasis"], "pids": pids}
        out_themes.append(rec)
        if not real_only:
            t.summary, t.periods, t.trend, t.dirty, t.version = rec["summary"], rec["periods"], None, False, t.version + 1
        if emit and s:
            st.emit("tree.theme_summarized", tid=tid, name=t.name, passages=len(pids),
                    docs_per_year=[[r["year"], r["docs"], r["total"]] for r in sh["shares"]])
    out_themes.sort(key=lambda r: -r["support"])
    tmap = {r["id"]: r for r in out_themes}
    areas = plan_areas(llm, out_themes, model, sys=_sys(st))
    rest = [i for i in tmap if i not in {t for a in areas for t in a["theme_ids"]}]
    if rest:
        areas.append({"name": "Other topics", "theme_ids": rest})
    for a in areas:
        pids = list(dict.fromkeys(i for t in a["theme_ids"] for i in tmap[t]["pids"]))
        a["share_stats"] = share_stats(st, pids, totals)

    def area_job(a):
        txt = []
        for i in sorted(a["theme_ids"], key=lambda i: -tmap[i]["support"])[:14]:
            r = tmap[i]
            per = "; ".join(f"{x['year']}: {x['line']}" for x in r["periods"][-5:])
            txt.append(f"- {r['name']} ({r['passages']} passages): {r['summary'][:300]} | {per[:400]}")
        return llm.structured(model, _sys(st), AREA_USER.format(name=a["name"], themes="\n".join(txt), shares=share_text(a["share_stats"])), ThemeSum,
                              purpose="tree_area", max_tokens=1300)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for a, s in zip(areas, ex.map(area_job, areas)):
            sh = a.pop("share_stats")
            a["summary"], a["periods"] = s.summary, [x.model_dump() for x in s.periods]
            a["trend"] = None
            a["shares"], a["emphasis"] = sh["shares"], sh["emphasis"]
            a["support"] = round(sum(tmap[i]["support"] for i in a["theme_ids"]), 2)
            a["passages"] = sum(tmap[i]["passages"] for i in a["theme_ids"])
            if not real_only:
                for i in a["theme_ids"]:
                    st.themes[i].area = a["name"]
            if emit:
                st.emit("tree.area_built", name=a["name"], themes=len(a["theme_ids"]),
                        docs_per_year=[[r["year"], r["docs"], r["total"]] for r in sh["shares"]])
    areas.sort(key=lambda a: -a["support"])
    root_txt = "\n".join(f"- {a['name']} ({a['passages']} passages; documents per year "
                         + ", ".join(f"{r['year']} {round(r['share'] * 100)}%" for r in a["shares"]) + f"): {a['summary']} | "
                         + "; ".join(f"{x['year']}: {x['line']}" for x in a["periods"][-5:]) for a in areas)
    root = llm.structured(model, _sys(st), ROOT_USER.format(areas=root_txt, company=st.company, year=str(st.profile["cutoff"])[:4]), RootSum, purpose="tree_root", max_tokens=1500)
    tree = {"root": root.model_dump(), "areas": areas, "themes": out_themes, "real_only": real_only, "year_totals": totals,
            "trend_public_only": TREND_PUBLIC_ONLY}
    if not real_only:
        st.tree = tree
    if emit:
        st.emit("tree.built", areas=len(areas), themes=len(out_themes), real_only=real_only)
    return tree
