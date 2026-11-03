"""
trmkb.eval.chart — 공식 로드맵 **차트**(연도×지표 표) 기준 채점.

ionq_roadmap_milestones.json(문장형 19건, LLM 정렬)과 달리, 생성 로드맵에서 **수치·기능·응용 주장을 뽑아**
연도×지표 정답표(data/ground_truth/ionq_roadmap_charts.json)와 결정적으로 비교한다.

  A. 지표 셀   : #AQ(2020판·2025판), 물리 큐비트, 물리 충실도, 논리 큐비트, 논리 오류율
       추출  : 정규식 (노드 라벨+설명). 수치 문장 안에 "by 2028"처럼 연도가 있으면 그 해, 없으면 노드 start–end 구간.
       값 일치: #AQ 는 ×1.15, 물리·논리 큐비트 수는 ×1.5 이내, 충실도는 불충실도(100-값) ×3 이내, 오류율은 지수 ±1
       지표   : cell_hit(값 일치 ∧ 연도 오차 ≤1) / value_recall(값 일치, 연도 무관) / year_mae(값 일치 셀의 연도 오차)
               / mag_err(연도 ±1 안에 같은 지표 주장이 있을 때 그 값과의 자릿수 차 |log10|) / metric_coverage
  B. 기능 등장 : microwave_gate·2d_array·mid_circuit_measurement·parallel_operations·photonic_interconnect 의 첫 등장 연도
       추출  : 키워드. 지표: coverage, year_mae
  C. 응용 기회 : 차트 하단 23건(연도별 막대 시작). 임베딩 상위 3 후보 → LLM 한 번(배치)으로 같은 응용인지 판정 + 결정적 키워드 보조 판정(넓은 범주 노드 배제)
       지표  : recall(strict: LLM ∧ 키워드), recall_lenient(LLM 만), year_mae, 범주별. (이 부분만 LLM 판정)
연도 오차 = 정답 연도와 주장 구간 [start,end]의 거리 (구간 안이면 0).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from ..agents.embed import embed
from ..llm import LLM
from ..schema import Roadmap

CHART_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ground_truth" / "ionq_roadmap_charts.json"

YEAR_RE = re.compile(r"\b(20[2-3]\d)\b")
NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aq", re.compile(r"#\s*AQ\s*(?:of\s*)?" + NUM, re.I)),
    ("aq", re.compile(r"\bAQ\s*" + NUM, re.I)),
    ("aq", re.compile(r">?=?\s*" + NUM + r"\s*\+?\s*algorithmic[- ]qubits?", re.I)),
    ("logical_qubits", re.compile(NUM + r"\s*\+?\s*logical[- ]qubits?", re.I)),
    ("physical_qubits", re.compile(NUM + r"\s*\+?\s*physical[- ]qubits?", re.I)),
    ("physical_qubits", re.compile(NUM + r"\s*\+?\s*-?\s*qubit(?:s)?\b(?!\s*(?:gate|fidelity|depth|circuit))", re.I)),
    ("physical_fidelity", re.compile(r"(9\d(?:\.\d+)?)\s*%", re.I)),
    ("logical_error_rate", re.compile(r"\b1(?:\.0+)?\s*[eE]\s*-\s*(\d+)\b")),
    ("logical_error_rate", re.compile(r"10\s*\^?\s*[-−]\s*(\d+)")),
]
FEATURE_KW = {
    "microwave_gate": ["microwave"],
    "2d_array": ["2d ", "2-d ", "two-dimensional", "2d qubit", "2d array", "2d trap", "2d surface", "2d ion"],
    "mid_circuit_measurement": ["mid-circuit", "mid circuit", "midcircuit"],
    "parallel_operations": ["parallel operation", "parallel gate", "parallel execution", "parallel ops", "parallel circuit"],
    "photonic_interconnect": ["photonic interconnect", "photonic link", "photonic network", "ion-photon", "photonic switch", "photonically"],
}


def load_chart() -> dict:
    return json.loads(CHART_PATH.read_text(encoding="utf-8"))


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _interval_dist(y: int, a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    lo = a if a is not None else b
    hi = b if b is not None else a
    if lo > hi:
        lo, hi = hi, lo
    return max(0.0, lo - y, y - hi)


# ---------------------------------------------------------------- A. 수치 주장 추출
def extract_claims(rm: Roadmap) -> list[dict]:
    """노드 라벨+설명에서 (metric, value, year_start, year_end) 주장을 뽑는다."""
    out = []
    for n in rm.nodes:
        text = f"{n.label}. {n.description}"
        for sent in re.split(r"(?<=[.;])\s+", text):
            seen_spans = []
            for metric, pat in PATTERNS:
                for m in pat.finditer(sent):
                    span = m.span()
                    if any(a <= span[0] < b or a < span[1] <= b for a, b in seen_spans):
                        continue          # 같은 숫자를 더 구체적인 패턴이 먼저 가져감
                    raw = m.group(1)
                    if metric == "logical_error_rate":
                        val = 10.0 ** (-int(raw))
                    else:
                        val = _num(raw)
                    if metric == "physical_fidelity":
                        if val < 99.0 or "fidel" not in sent.lower():
                            continue
                    if metric == "physical_qubits" and ("algorithmic" in sent.lower()[max(0, span[0] - 20):span[1] + 20]):
                        continue
                    ys = YEAR_RE.findall(sent)
                    if ys:
                        y0 = y1 = float(ys[0])
                    else:
                        y0, y1 = n.start, n.end
                    seen_spans.append(span)
                    if any(o["node_id"] == n.id and o["metric"] == metric and o["value"] == val for o in out):
                        continue          # 라벨과 설명에 같은 수치가 반복되면 한 번만
                    out.append({"node_id": n.id, "label": n.label, "metric": metric, "value": val,
                                "start": y0, "end": y1, "text": sent.strip()[:160]})
    return out


def _value_match(metric: str, c: float, g: float) -> bool:
    if metric == "physical_fidelity":
        ic, ig = max(100 - c, 1e-6), max(100 - g, 1e-6)
        return max(ic / ig, ig / ic) <= 3.0
    if metric == "logical_error_rate":
        return abs(math.log10(c) - math.log10(g)) <= 1.0
    if c <= 0 or g <= 0:
        return False
    tol = 1.15 if metric == "aq" else 1.5     # #AQ 는 정답 값이 촘촘(22·25·29·35)해서 좁게
    return max(c / g, g / c) <= tol


def _mag_err(metric: str, c: float, g: float) -> float:
    if metric == "physical_fidelity":
        return abs(math.log10(max(100 - c, 1e-6)) - math.log10(max(100 - g, 1e-6)))
    return abs(math.log10(max(c, 1e-30)) - math.log10(max(g, 1e-30)))


def score_cells(claims: list[dict], metric: str, by_year: dict[str, float]) -> dict:
    cl = [c for c in claims if c["metric"] == metric]
    rows = []
    for ys, g in by_year.items():
        y = int(ys)
        vm = [(c, _interval_dist(y, c["start"], c["end"])) for c in cl if _value_match(metric, c["value"], g)]
        vm = [(c, d) for c, d in vm if d is not None]
        ym = [c for c in cl if (d := _interval_dist(y, c["start"], c["end"])) is not None and d <= 1.0]
        best_v = min(vm, key=lambda t: t[1]) if vm else None
        best_y = min(ym, key=lambda c: _mag_err(metric, c["value"], g)) if ym else None
        rows.append({"year": y, "gold": g,
                     "value_matched": best_v is not None, "year_err": best_v[1] if best_v else None,
                     "value_node": best_v[0]["label"] if best_v else None, "value_claim": best_v[0]["value"] if best_v else None,
                     "year_matched": best_y is not None, "mag_err": _mag_err(metric, best_y["value"], g) if best_y else None,
                     "year_node": best_y["label"] if best_y else None, "year_claim": best_y["value"] if best_y else None,
                     "cell_hit": best_v is not None and best_v[1] <= 1.0})
    n = len(rows)
    ye = [r["year_err"] for r in rows if r["year_err"] is not None]
    me = [r["mag_err"] for r in rows if r["mag_err"] is not None]
    return {"metric": metric, "n_cells": n, "n_claims": len(cl),
            "metric_coverage": bool(cl),
            "cell_hit_rate": round(sum(r["cell_hit"] for r in rows) / n, 3),
            "value_recall": round(sum(r["value_matched"] for r in rows) / n, 3),
            "year_mae": round(float(np.mean(ye)), 2) if ye else None,
            "year_matched_rate": round(sum(r["year_matched"] for r in rows) / n, 3),
            "mag_err": round(float(np.mean(me)), 2) if me else None,
            "max_year_claimed": max((c["end"] or c["start"] or 0) for c in cl) if cl else None,
            "rows": rows}


# ---------------------------------------------------------------- B. 기능 등장
def score_features(rm: Roadmap, feats: list[dict]) -> dict:
    rows = []
    for f in feats:
        if not f.get("scored"):
            continue
        kws = FEATURE_KW[f["id"]]
        hits = []
        for n in rm.nodes:
            t = f"{n.label}. {n.description}".lower()
            if any(k in t for k in kws):
                ys = YEAR_RE.findall(t)
                y = float(min(ys)) if ys else (n.start if n.start is not None else None)
                hits.append((y, n.label))
        hits = [h for h in hits if h[0] is not None]
        first = min(hits) if hits else None
        rows.append({"feature": f["id"], "gold_year": f["first_year"], "found": bool(hits),
                     "claim_year": first[0] if first else None, "node": first[1] if first else None,
                     "year_err": abs(first[0] - f["first_year"]) if first else None})
    ye = [r["year_err"] for r in rows if r["year_err"] is not None]
    return {"n": len(rows), "coverage": round(sum(r["found"] for r in rows) / len(rows), 3) if rows else None,
            "year_mae": round(float(np.mean(ye)), 2) if ye else None, "rows": rows}


# ---------------------------------------------------------------- C. 응용 기회 (임베딩 + LLM 배치 판정)
APP_SYSTEM = "You check whether a generated technology roadmap contains each listed application opportunity. JSON only."
APP_USER = """For each official application item below, decide whether one of its candidate roadmap nodes names the SAME specific application
(same use case / workload; wording and year may differ).
Rules:
- A broad field or category does NOT count: "quantum chemistry applications" is not "protein folding"; "quantum machine learning"
  is not "medical imaging analysis"; "hybrid quantum-classical workflows" is not "LLM fine-tuning"; "optimization services" is not "vehicle routing".
- Count a match only if the node text itself names the use case (e.g. the node mentions drug discovery, battery chemistry, portfolio, routing, protein, imaging...).
- The item "Broad Quantum Advantage" matches only a node about reaching quantum advantage.
Return JSON: {{"items": [{{"id": str, "match": int|null, "quote": str}}]}} where match is the candidate index (or null) and quote is the
phrase (<=12 words) in that candidate that names the use case.

{items}"""

APP_GENERIC = {"quantum", "model", "models", "modeling", "analysis", "discovery", "design", "prediction", "learning", "optimization",
               "simulation", "advanced", "training", "data", "generation", "equipment", "materials", "with", "more", "solvent",
               "team", "picking", "assignment", "action", "planning", "detection", "change", "screening", "redesign", "rebalancing",
               "commitment", "fine-tuning", "fine", "tuning", "higher", "larger", "complex"}
APP_SYNONYMS = {"pharma": ["pharma", "drug", "molecul"], "llm": ["llm", "language model"],
                "cae": ["cae", "engineering", "structural"], "grids": ["grid", "utility", "power"], "robotic": ["robot"],
                "medical": ["medical", "health", "clinical"], "chemical": ["chemi"], "catalyst": ["catalys"], "catalysts": ["catalys"],
                "battery": ["batter"], "protein": ["protein", "peptide"], "fluid": ["fluid", "cfd"], "polymorph": ["polymorph", "crystal"],
                "carbon": ["carbon", "co2"], "portfolio": ["portfolio", "asset"], "vehicle": ["vehicle", "routing", "logistic", "fleet"],
                "routing": ["routing", "logistic"], "imaging": ["imag"], "federated": ["federated"], "agent": ["agent"],
                "synthetic": ["synthetic data"], "drug-target": ["drug", "affinity", "binding"], "affinity": ["affinity", "binding"],
                "advantage": ["advantage"], "sports": ["sport"], "fantasy": ["fantasy"], "unit": ["unit commitment", "dispatch"],
                "electric": ["electric", "grid", "power"], "image": ["imag"], "laminar": ["fluid", "flow"], "dynamics": ["fluid", "flow"],
                "institutional": ["portfolio", "asset", "financ"], "reaction": ["reaction"], "folding": ["protein", "fold"]}


def _app_keyword_ok(label: str, node_text: str) -> bool:
    """결정적 보조 판정: 응용 항목 라벨의 식별 단어(또는 동의어)가 노드 본문에 있어야 '구체적' 일치로 본다."""
    t = node_text.lower()
    for w in re.findall(r"[a-z0-9/-]+", label.lower()):
        if w in APP_GENERIC or len(w) < 4:
            continue
        for k in APP_SYNONYMS.get(w, [w[:5]]):
            if k in t:
                return True
    return False


class AppPick(BaseModel):
    id: str
    match: int | None = None
    quote: str = ""


class AppOut(BaseModel):
    items: list[AppPick]


def score_apps(rm: Roadmap, apps: list[dict], llm: LLM | None, *, model: str = "openai/gpt-4.1", k: int = 3) -> dict:
    nodes = rm.nodes
    if not nodes:
        return {"n": len(apps), "recall": 0.0, "year_mae": None, "rows": []}
    vecs = embed([f"{n.label}. {n.description}" for n in nodes])
    qs = embed([f"{a['label']} ({a['category']}; {a['scaling']})" for a in apps])
    cand = {}
    blocks = []
    for a, q in zip(apps, qs):
        sims = vecs @ q
        order = [int(i) for i in np.argsort(-sims)[:k]]
        cand[a["id"]] = order
        lines = "\n".join(f"  [{i}] \"{nodes[j].label}\" — {nodes[j].description[:160]} ({nodes[j].start}–{nodes[j].end})" for i, j in enumerate(order))
        blocks.append(f"{a['id']}: \"{a['label']}\" [{a['category']}] (official year {a['year']})\n{lines}")
    picks: dict[str, tuple[int | None, str]] = {}
    cost0 = llm.ledger.total_usd if llm else 0.0
    if llm is not None:
        out = llm.structured(model, APP_SYSTEM, APP_USER.format(items="\n\n".join(blocks)), AppOut, purpose="eval_chart_apps", max_tokens=2000)
        picks = {p.id: (p.match, p.quote) for p in out.items}
    rows = []
    for a in apps:
        m, quote = picks.get(a["id"], (None, ""))
        node = nodes[cand[a["id"]][m]] if m is not None and 0 <= m < len(cand[a["id"]]) else None
        # LLM 이 고른 뒤 결정적 보조 판정: 노드 본문에 응용을 식별하는 단어가 있어야 strict 적중 (넓은 범주 노드가 여러 항목을 먹는 것을 막음)
        specific = bool(node) and _app_keyword_ok(a["label"], f"{node.label}. {node.description}")
        rows.append({"id": a["id"], "label": a["label"], "category": a["category"], "gold_year": a["year"],
                     "hit": specific, "hit_lenient": node is not None, "node": node.label if node else None, "quote": quote,
                     "year_err": _interval_dist(a["year"], node.start, node.end) if specific else None})
    ye = [r["year_err"] for r in rows if r["year_err"] is not None]
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["hit"])
    return {"n": len(rows), "recall": round(sum(r["hit"] for r in rows) / len(rows), 3),
            "recall_lenient": round(sum(r["hit_lenient"] for r in rows) / len(rows), 3),
            "year_mae": round(float(np.mean(ye)), 2) if ye else None,
            "by_category": {c: round(sum(v) / len(v), 3) for c, v in by_cat.items()},
            "judge_cost_usd": round((llm.ledger.total_usd - cost0), 4) if llm else 0.0, "rows": rows}


# ---------------------------------------------------------------- 전체
def score_chart(rm: Roadmap, llm: LLM | None = None, *, chart: dict | None = None) -> dict:
    ch = chart or load_chart()
    claims = extract_claims(rm)
    tables = {
        "aq_2020": score_cells(claims, "aq", ch["aq_2020"]["by_year"]),
        "aq_2025": score_cells(claims, "aq", ch["aq_2025"]["by_year"]),
    }
    for metric, by_year in ch["tech_2025"]["metrics"].items():
        tables[f"tech_{metric}"] = score_cells(claims, metric, by_year)
    tech = [t for k, t in tables.items() if k.startswith("tech_")]
    feats = score_features(rm, ch["features_2025"]["items"])
    apps = score_apps(rm, ch["applications_2025"]["items"], llm)
    summary = {
        "condition": rm.condition, "model": rm.model, "n_claims": len(claims),
        "claims_by_metric": {m: sum(1 for c in claims if c["metric"] == m) for m in sorted({c["metric"] for c in claims})},
        "aq2020_cell_hit": tables["aq_2020"]["cell_hit_rate"], "aq2020_value_recall": tables["aq_2020"]["value_recall"],
        "aq2020_year_mae": tables["aq_2020"]["year_mae"],
        "aq2025_cell_hit": tables["aq_2025"]["cell_hit_rate"], "aq2025_value_recall": tables["aq_2025"]["value_recall"],
        "aq2025_year_mae": tables["aq_2025"]["year_mae"],
        "tech_metric_coverage": round(sum(t["metric_coverage"] for t in tech) / len(tech), 3),
        "tech_cell_hit": round(sum(t["cell_hit_rate"] * t["n_cells"] for t in tech) / sum(t["n_cells"] for t in tech), 3),
        "tech_value_recall": round(sum(t["value_recall"] * t["n_cells"] for t in tech) / sum(t["n_cells"] for t in tech), 3),
        "tech_mag_err": (round(float(np.mean([t["mag_err"] for t in tech if t["mag_err"] is not None])), 2)
                         if any(t["mag_err"] is not None for t in tech) else None),
        "feature_coverage": feats["coverage"], "feature_year_mae": feats["year_mae"],
        "app_recall": apps["recall"], "app_recall_lenient": apps.get("recall_lenient"), "app_year_mae": apps["year_mae"], "app_by_category": apps["by_category"],
        "max_year_claimed": max([t["max_year_claimed"] for t in tables.values() if t["max_year_claimed"]] or [None]),
        "judge_cost_usd": apps.get("judge_cost_usd", 0.0),
        "tables": tables, "features": feats, "applications": apps, "claims": claims,
    }
    return summary
