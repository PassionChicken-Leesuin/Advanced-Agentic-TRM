"""차트 기반 채점: eval_v2 가 남긴 생성 로드맵(runs/<run>/eval/<조건>/rm_<i>.json)을 연도×지표 정답표로 채점.

python scripts/eval_chart.py --run runs/struct5 [--conditions ...] [--no-llm]
산출: runs/<run>/eval/<조건>/chart_<i>.json, eval/chart_summary.{json,md}
"""
import argparse
import io
import json
import statistics as S
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.eval.chart import score_chart
from trmkb.llm import LLM
from trmkb.schema import Roadmap

ORDER = ["Initial", "S0raw", "K1", "ALL", "ALL-K1", "ALL-K2", "ALL-K3", "ALL-K4", "ALL-K5", "ALL-K0", "ALL-real"]
KEYS = ["n_claims", "aq2020_cell_hit", "aq2020_value_recall", "aq2020_year_mae", "aq2025_cell_hit", "aq2025_value_recall",
        "tech_metric_coverage", "tech_cell_hit", "tech_value_recall", "tech_mag_err", "feature_coverage", "feature_year_mae",
        "app_recall", "app_recall_lenient", "app_year_mae", "max_year_claimed"]


def ms(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    return round(S.mean(xs), 3), round(S.pstdev(xs), 3) if len(xs) > 1 else 0.0


def fmt(m, sd, pct=True):
    if m is None:
        return "–"
    if pct:
        return f"{round(m * 100)}%±{round((sd or 0) * 100)}"
    return f"{m:.2f}±{(sd or 0):.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--conditions", nargs="*", default=None)
    ap.add_argument("--no-llm", action="store_true", help="응용 기회 판정(LLM) 생략")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    root = Path(args.run) / "eval"
    conds = args.conditions or [c for c in ORDER if (root / c).exists()]
    llm = None if args.no_llm else LLM()
    per = {}
    for c in conds:
        rows = []
        for rmf in sorted((root / c).glob("rm_*.json")):
            i = rmf.stem.split("_")[1]
            out = root / c / f"chart_{i}.json"
            if out.exists() and not args.force:
                rows.append(json.loads(out.read_text(encoding="utf-8")))
                continue
            rm = Roadmap.model_validate_json(rmf.read_text(encoding="utf-8"))
            r = score_chart(rm, llm)
            out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            rows.append(r)
            print(f"[{c}] rm_{i}: claims={r['n_claims']} aq2020 hit={r['aq2020_cell_hit']} tech cov={r['tech_metric_coverage']} "
                  f"feat={r['feature_coverage']} app={r['app_recall']} ${r['judge_cost_usd']}", flush=True)
        per[c] = rows
    summ = {}
    for c, rows in per.items():
        summ[c] = {"n": len(rows)}
        for k in KEYS:
            summ[c][k] = ms([r.get(k) for r in rows])
        cats = {}
        for r in rows:
            for cat, v in (r.get("app_by_category") or {}).items():
                cats.setdefault(cat, []).append(v)
        summ[c]["app_by_category"] = {cat: ms(v) for cat, v in cats.items()}
        summ[c]["judge_cost_usd"] = round(sum(r.get("judge_cost_usd", 0) for r in rows), 4)
    (root / "chart_summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 차트 기반 채점 (연도×지표 정답표, 생성 n회 평균±표준편차)", "",
          "정답표: data/ground_truth/ionq_roadmap_charts.json. 셀 적중 = 값 일치(#AQ ×1.15, 물리·논리 큐비트 ×1.5, 충실도 불충실도 ×3, 오류율 지수 ±1) ∧ 연도 오차 ≤1. "
          "값 재현 = 값 일치(연도 무관). 자릿수 오차 = 정답 연도 ±1 에 같은 지표 주장이 있을 때 |log10(주장/정답)|. "
          "기능 = 2025년 이후 새로 켜지는 기능 5종의 첫 등장. 응용 = 차트 하단 응용 기회 23건(임베딩 후보 3 + LLM 배치 판정 ∧ 노드 본문에 응용 식별어가 있어야 적중; 'LLM만'은 보조 판정 없이).", "",
          "| 조건 | 수치주장 | #AQ'20 셀적중 | #AQ'20 값재현 | #AQ'20 연도오차 | #AQ'25 셀적중 | 기술지표 언급 | 기술 셀적중 | 기술 값재현 | 기술 자릿수오차 | 기능 등장 | 기능 연도오차 | 응용 recall | 응용 recall(LLM만) | 응용 연도오차 | 최장 연도 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, s in summ.items():
        g = lambda k, pct=True: fmt(*s[k], pct=pct)  # noqa: E731
        md.append(f"| {c} | {g('n_claims', False)} | {g('aq2020_cell_hit')} | {g('aq2020_value_recall')} | {g('aq2020_year_mae', False)} | "
                  f"{g('aq2025_cell_hit')} | {g('tech_metric_coverage')} | {g('tech_cell_hit')} | {g('tech_value_recall')} | {g('tech_mag_err', False)} | "
                  f"{g('feature_coverage')} | {g('feature_year_mae', False)} | {g('app_recall')} | {g('app_recall_lenient')} | {g('app_year_mae', False)} | {g('max_year_claimed', False)} |")
    md += ["", "## 응용 기회 recall, 범주별", "", "| 조건 | " + " | ".join(["AI/ML", "Optimization", "Simulation", "Vision"]) + " |", "|---|---|---|---|---|"]
    for c, s in summ.items():
        md.append(f"| {c} | " + " | ".join(fmt(*s["app_by_category"].get(cat, (None, None))) for cat in ["AI/ML", "Optimization", "Simulation", "Vision"]) + " |")
    (root / "chart_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    if llm:
        print(f"\ncost ${llm.ledger.total_usd:.4f}")


if __name__ == "__main__":
    main()
