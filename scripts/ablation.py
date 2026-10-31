"""S0~S4(+ablation) 비교: 같은 KB에서 컨텍스트 빌더만 바꿔 Advanced 를 만들고 같은 평가를 돌린다.

python scripts/ablation.py --run runs/full [--conditions S0 S1 S2 S3 S4 S4a S4b S4c S4d] [--model openai/gpt-4.1]
산출: runs/<run>/ablation/<cond>/{context.txt, roadmap_advanced.json, roadmap_diff.json, eval_alignment.json}
      runs/<run>/ablation/summary.json, summary.md  (조건 × 지표 표)
"""
import argparse
import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.eval.alignment import align
from trmkb.llm import LLM
from trmkb.roadmap import diff as D
from trmkb.roadmap import generate as G
from trmkb.roadmap import retrieve as R
from trmkb.schema import RoadmapOp
from trmkb.store import KBStore


def pct(x):
    return "—" if x is None else f"{round(x * 100)}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--conditions", nargs="*", default=list(R.CONDITIONS))
    ap.add_argument("--model", default=G.DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    run = Path(args.run)
    kb = KBStore(run)
    ini = G.load(run, "initial")
    assert ini, "roadmap_initial.json required in run"
    llm = LLM()
    out_root = run / "ablation"
    rows = []
    for cond in args.conditions:
        d = out_root / cond; d.mkdir(parents=True, exist_ok=True)
        shutil.copy(run / "roadmap_initial.json", d / "roadmap_initial.json")
        if (d / "roadmap_advanced.json").exists() and not args.force:
            adv = G.load(d, "advanced")
            print(f"[{cond}] reuse existing advanced")
        else:
            ctx = R.build_context(kb, condition=cond)
            (d / "context.txt").write_text(ctx.text, encoding="utf-8")
            (d / "context_stats.json").write_text(json.dumps(ctx.stats, ensure_ascii=False), encoding="utf-8")
            adv = G.generate(llm, condition="advanced", context=ctx.text, model=args.model, ops_by_evidence=ctx.ops_by_ref)
            G.save(adv, d)
            print(f"[{cond}] context {ctx.stats} → advanced {len(adv.nodes)} nodes, evidence {sum(1 for n in adv.nodes if n.evidence_ids)}")
        df = D.compute_diff(ini, adv, llm); D.save(df, d)
        al = align(adv, llm)
        (d / "eval_alignment.json").write_text(json.dumps(al, ensure_ascii=False, indent=1), encoding="utf-8")
        ops = {}
        for n in adv.nodes:
            for o in n.produced_by:
                ops[o.value] = ops.get(o.value, 0) + 1
        rows.append({
            "condition": cond, "nodes": len(adv.nodes), "with_evidence": sum(1 for n in adv.nodes if n.evidence_ids),
            "evidence_rate": round(sum(1 for n in adv.nodes if n.evidence_ids) / max(1, len(adv.nodes)), 3),
            "by_layer": G.summary(adv)["by_layer"], "edges": len(adv.edges),
            "flag_infeasible": sum(1 for n in adv.nodes if "infeasible" in n.flags),
            "ops": ops,
            "diff_new": df["counts"].get("new", 0), "diff_new_evidenced": df["new_with_evidence"],
            "diff_refined": df["counts"].get("refined", 0), "diff_dropped": df["counts"].get("dropped", 0),
            "recall_strict": al["recall_strict"], "recall_lenient": al["recall_lenient"],
            "recall_2020_lenient": al["recall_2020_lenient"], "recall_2025_lenient": al["recall_2025_lenient"],
            "year_mae": al["year_mae"], "matched_with_evidence": al["matched_with_evidence"],
            "context_chars": json.loads((d / "context_stats.json").read_text(encoding="utf-8")).get("chars") if (d / "context_stats.json").exists() else None,
        })
    # Initial 기준선 행
    al0 = align(ini, llm)
    rows.insert(0, {"condition": "Initial(no KB)", "nodes": len(ini.nodes), "with_evidence": 0, "evidence_rate": 0.0,
                    "by_layer": G.summary(ini)["by_layer"], "edges": len(ini.edges), "flag_infeasible": 0, "ops": {"llm_prior": len(ini.nodes)},
                    "diff_new": None, "diff_new_evidenced": None, "diff_refined": None, "diff_dropped": None,
                    "recall_strict": al0["recall_strict"], "recall_lenient": al0["recall_lenient"],
                    "recall_2020_lenient": al0["recall_2020_lenient"], "recall_2025_lenient": al0["recall_2025_lenient"],
                    "year_mae": al0["year_mae"], "matched_with_evidence": 0, "context_chars": 0})
    summ = {"run": run.name, "model": args.model, "rows": rows, "cost_usd": round(llm.ledger.total_usd, 4)}
    (out_root / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    hdr = "| 조건 | 항목 | 근거 부착률 | 링크 | infeasible | 신규(근거) | 세분화 | 탈락 | recall 엄격/관대 | 2020판 | 2025판(사전예측) | 연도 MAE |"
    md = [f"# Ablation — {run.name} ({args.model})", "", hdr, "|" + "---|" * 12]
    for r in rows:
        md.append(f"| {r['condition']} | {r['nodes']} | {pct(r['evidence_rate'])} | {r['edges']} | {r['flag_infeasible']} | "
                  f"{r['diff_new'] if r['diff_new'] is not None else '—'}({r['diff_new_evidenced'] if r['diff_new_evidenced'] is not None else '—'}) | "
                  f"{r['diff_refined'] if r['diff_refined'] is not None else '—'} | {r['diff_dropped'] if r['diff_dropped'] is not None else '—'} | "
                  f"{pct(r['recall_strict'])} / {pct(r['recall_lenient'])} | {pct(r['recall_2020_lenient'])} | {pct(r['recall_2025_lenient'])} | {r['year_mae']} |")
    md.append(f"\n판정·생성 비용 ${llm.ledger.total_usd:.3f}")
    (out_root / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
