"""
K3 기회 연계 그리드 정리 단계 (Cambridge 2014 양자 로드맵 보고서 20~25쪽의 Linkage Grid 를 문서로부터 계산).

  열 = 응용 기회: GridExtractor 가 만든 기회 기록의 기회 대상, 등급(A: 시장 명시 / B: 시장 없음)·지지 문서 수 순.
       같은 기회가 다른 이름으로 갈라진 것은 마무리 정리 단계(consolidate, LLM 판단)에서 이미 합쳐져 들어옴. 출처 가중 없음.
  행 = why(동인·요구) / what(제공물) / how(역량) / resource(인에이블러)
  칸 = 두 갈래로 채운다
       direct  : 기회 기록이 직접 말함 (동인·요구·제공물) 또는 K4 관계 그래프에 기회(또는 그 제공물)와의 관계가 있음
       derived : 같은 문장·같은 문서에 함께 나오는 대상을 LLM 이 확인 (보고서에서 진행자가 상용화 계획으로부터
                 역량·인에이블러 행을 유도한 것에 해당)
  순위 = 열·행마다 연결 수와 강도 합 (보고서처럼 연결 수로 우선순위)
모든 칸은 events.jsonl 에 grid.cell 로 남아 화면에서 그리드가 채워지는 장면을 재생할 수 있다.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from ..llm import LLM
from .store import MATURITY, SOURCE_WEIGHT, SourceStore

MODEL = "openai/gpt-4.1-mini"
REL_OF = {"why": "drives", "what": "serves", "how": "enables", "resource": "enables"}
GRAPH_LAYER_REL = {"requires", "enables", "part_of", "supplies", "funds", "partners_with", "drives", "addresses", "customer_of"}

SYSTEM = "You build a technology-roadmap linkage grid from source passages, like a Cambridge T-Plan workshop. JSON only."
USER = """Roadmap opportunity (column): {col}
Records about it:
{col_st}

Candidate row items that appear together with the opportunity (row eid | layer | name | co-mention passages):
{rows}

For each candidate row decide whether it is linked to the opportunity in the sense of a roadmap linkage grid:
- why rows: does this driver or need motivate or create demand for the opportunity?
- what rows: is this product or service used to deliver the opportunity?
- how rows: is this capability or component needed for or used by the opportunity?
- resource rows: is this enabler (funding, facility, skills, partner, standard, approval) needed to deliver it?
strength: 0 none, 1 weak or indirect, 2 clear, 3 explicitly stated as critical.
evidence_pid: the passage id that best supports it (null if strength 0). reason under 15 words.

Return JSON: {{"links": [{{"row": eid, "strength": int, "evidence_pid": str|null, "reason": str}}]}}"""


class Link(BaseModel):
    row: str
    strength: int = 0
    evidence_pid: str | None = None
    reason: str = ""


class Links(BaseModel):
    links: list[Link] = Field(default_factory=list)


# 열이 될 수 없는 대상: 포괄어("quantum computing applications", "industry transformation" 등)와 K0 종류가
# 조직·기술·지표인 대상. 추출기에도 같은 필터가 있지만, 병합으로 이름이 바뀌거나 용어가 뒤늦게 확정된 경우를 여기서 다시 거른다.
GENERIC_COL_WORDS = ("applications", "application development", "transformation", "adoption", "demand", "business",
                     "challenges", "industry impact", "benchmark", "ecosystem", "use cases", "breakthrough", "landscape",
                     "market", "strategy", "roadmap", "opportunit", "innovation", "leadership", "growth", "readiness")
GENERIC_COL_EXACT = {"quantum computing", "quantum computers", "quantum computer", "ionq", "quantum technology", "quantum"}


def bad_column(st: SourceStore, eid: str) -> bool:
    e = st.entities.get(eid)
    if e and e.name.lower().strip() == st.company.lower():
        return True
    if not e:
        return True
    n = e.name.lower().strip()
    if n in GENERIC_COL_EXACT or any(w in n for w in GENERIC_COL_WORDS):
        return True
    for t in st.terms.values():
        if t.status == "confirmed" and t.type in ("organization", "technology", "metric", "stage", "program")                 and (t.eid == eid or t.name.lower() == n):
            return True
    return False


def build_grid(st: SourceStore, llm: LLM, *, n_cols: int = 15, real_only: bool = False, model: str = MODEL,
               cands_per_col: int = 18, emit: bool = True) -> dict:
    def ok(pid):
        p = st.passages.get(pid)
        return bool(p) and p.status not in ("irrelevant", "duplicate") and not (real_only and p.is_synthetic)

    opps = [o for o in st.opps.values() if ok(o.pid) and o.eid in st.entities and not bad_column(st, o.eid)]
    docs_of = defaultdict(dict)
    for o in opps:
        p = st.passages[o.pid]
        docs_of[o.eid][p.doc_id] = max(docs_of[o.eid].get(p.doc_id, 0), SOURCE_WEIGHT.get(p.source_type, 1.0))
    sup = {e: round(sum(d.values()), 2) for e, d in docs_of.items()}
    # 등급: A = 대상 시장·고객이 문서에 명시된 기회, B = 응용·제품 유형만 있고 시장이 없는 기회 (열 후보로 두되 뒤로)
    tier = {e: ("A" if any(o.customer for o in opps if o.eid == e) else "B") for e in sup}
    ranked = sorted(sup, key=lambda e: (tier[e], -sup[e]))
    # 기회 병합은 마무리 정리 단계(consolidate.merge_entities, LLM 판단)에서 이미 끝남. 여기서는 상위 n_cols 만 고름.
    rep: dict[str, str] = {}
    cols: list[str] = []
    for e in ranked:
        if len(cols) < n_cols:
            cols.append(e); rep[e] = e
    group = defaultdict(set)
    for e, r in rep.items():
        group[r].add(e)
    col_sup = {c: round(sum(sup[e] for e in group[c]), 2) for c in cols}
    col_tier = {c: ("A" if any(tier[e] == "A" for e in group[c]) else "B") for c in cols}
    cols.sort(key=lambda c: (col_tier[c], -col_sup[c]))
    # B급 기회의 시장 유추: 같은 문서에서 A급 기회에 붙은 고객·시장 이름 (유추 표시)
    cust_by_doc = defaultdict(set)
    for o in opps:
        if o.customer:
            cust_by_doc[st.passages[o.pid].doc_id].add(o.customer)

    cells: dict[tuple, dict] = {}

    def add(row, col, layer, strength, derivation, pid, reason, rel=None):
        if row in group[col] or row not in st.entities:
            return
        key = (row, col)
        c = cells.get(key)
        if c is None:
            cells[key] = {"row": row, "col": col, "layer": layer, "relation": rel or REL_OF[layer], "strength": strength,
                          "derivation": derivation, "evidence_pid": pid, "reason": reason[:120], "n": 1}
        else:
            c["n"] += 1
            if derivation == "direct" and c["derivation"] != "direct":
                c["derivation"], c["evidence_pid"] = "direct", pid
            c["strength"] = min(3, max(c["strength"], strength) + (1 if c["n"] == 2 else 0))

    if emit:
        st.emit("grid.started", real_only=real_only, columns=[{"eid": c, "name": st.entities[c].name, "support": col_sup[c], "tier": col_tier[c]} for c in cols])
    col_meta = {}
    for c in cols:
        recs = [o for o in opps if rep.get(o.eid) == c]
        offerings = set()
        for o in recs:
            for d in o.drivers:
                add(d, c, "why", 2, "direct", o.pid, "stated driver")
            for d in o.needs:
                add(d, c, "why", 2, "direct", o.pid, "stated customer need", rel="needs")
            if o.offering:
                offerings.add(o.offering)
                add(o.offering, c, "what", 2, "direct", o.pid, "offering for this opportunity")
        # K4 관계: 기회(또는 제공물)와 직접 이어진 대상
        anchors = group[c] | offerings
        for r in st.relations.values():
            if not ok(r.pid) or r.rel not in GRAPH_LAYER_REL:
                continue
            other = r.dst if r.src in anchors else r.src if r.dst in anchors else None
            if other and other not in anchors and other in st.entities:
                lay = st.entities[other].layer or "how"
                add(other, c, lay, 2, "direct", r.pid, f"graph: {r.rel}")
        mats = [o.maturity for o in recs]
        kinds = [o.kind for o in recs]
        inferred = sorted({x for o in recs for x in cust_by_doc.get(st.passages[o.pid].doc_id, ())})[:4] if col_tier[c] == "B" else []
        col_meta[c] = {"tier": col_tier[c], "kind": max(set(kinds), key=kinds.count) if kinds else "application",
                       "maturity": max(mats, key=MATURITY.index) if mats else "exploring",
                       "customers": sorted({o.customer for o in recs if o.customer})[:6], "inferred_customers": inferred,
                       "values": [o.value for o in recs if o.value][:3], "records": len(recs),
                       "offerings": [st.entities[o].name for o in offerings if o in st.entities][:5]}
        # 공출현 후보 → LLM 확인 (derived)
        score, snippets = defaultdict(float), defaultdict(list)
        col_pids = {o.pid for o in recs}
        for pid in col_pids:
            p = st.passages[pid]
            for e in p.entity_ids:
                if e not in group[c]:
                    score[e] += 2; snippets[e].append(pid)
        col_docs = {st.passages[pid].doc_id for pid in col_pids}
        for p in st.passages.values():
            if p.doc_id in col_docs and ok(p.id) and p.id not in col_pids:
                for e in p.entity_ids:
                    if e not in group[c]:
                        score[e] += 0.5
                        if len(snippets[e]) < 2:
                            snippets[e].append(p.id)
        cand = [e for e, _ in sorted(score.items(), key=lambda x: -x[1]) if (e, c) not in cells and e not in anchors][:cands_per_col]
        if cand:
            col_st = "\n".join(f"- {o.pid}: offering={st.entities[o.offering].name if o.offering in st.entities else '-'}, "
                               f"customer={o.customer or '-'}, value={o.value or '-'}, maturity={o.maturity} | {st.passages[o.pid].statement[:160]}"
                               for o in recs[:6])
            lines = []
            for e in cand:
                txt = " || ".join(f"{pid}: {st.passages[pid].statement[:150]}" for pid in snippets[e][:2] if pid in st.passages)
                lines.append(f"- {e} | {st.entities[e].layer} | {st.entities[e].name} | {txt}")
            out = llm.structured(model, SYSTEM, USER.format(col=st.entities[c].name, col_st=col_st, rows="\n".join(lines)),
                                 Links, purpose="grid_verify", max_tokens=2500)
            for lk in out.links:
                if lk.row in cand and lk.strength > 0:
                    lay = st.entities[lk.row].layer or "how"
                    add(lk.row, c, lay, max(1, min(3, lk.strength)), "derived",
                        lk.evidence_pid if lk.evidence_pid in st.passages else None, lk.reason)
        if emit:
            for cell in [x for x in cells.values() if x["col"] == c]:
                st.emit("grid.cell", **{k: v for k, v in cell.items() if k != "n"}, row_name=st.entities[cell["row"]].name,
                        col_name=st.entities[c].name)
    cl = list(cells.values())

    def rank(ids, key):
        agg = defaultdict(lambda: [0, 0])
        for x in cl:
            agg[x[key]][0] += 1; agg[x[key]][1] += x["strength"]
        return sorted(({"eid": i, "name": st.entities[i].name, "links": agg[i][0], "strength_sum": agg[i][1],
                        "support": st.support(i, real_only=real_only)} for i in ids), key=lambda x: (-x["links"], -x["strength_sum"]))

    rows = defaultdict(set)
    for x in cl:
        rows[x["layer"]].add(x["row"])
    columns = rank(cols, "col")
    for col in columns:
        col["support"] = col_sup[col["eid"]]
        col.update(col_meta[col["eid"]])
        col["merged"] = [st.entities[e].name for e in group[col["eid"]] if e != col["eid"]]
    columns.sort(key=lambda x: (x["tier"], -x["links"], -x["strength_sum"]))     # A급 먼저, 그 안에서 연결 수
    n_a, n_b = sum(1 for e in sup if tier[e] == "A"), sum(1 for e in sup if tier[e] == "B")
    g = {"columns": columns, "rows": {l: rank(ids, "row") for l, ids in rows.items()}, "cells": cl,
         "meta": {"real_only": real_only, "n_cols": len(cols), "model": model, "candidates": {"A": n_a, "B": n_b},
                  "columns_by_tier": {"A": sum(1 for x in columns if x["tier"] == "A"), "B": sum(1 for x in columns if x["tier"] == "B")}}}
    if not real_only:
        st.grid = g
    if emit:
        st.emit("grid.built", n_cells=len(cl), real_only=real_only)
    return g
