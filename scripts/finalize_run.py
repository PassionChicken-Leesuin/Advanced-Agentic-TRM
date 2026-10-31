"""run 마무리: Advanced Roadmap → diff → 심은 사실 회수율 → 공식 로드맵 정렬 → 요약(JSON + markdown).

python scripts/finalize_run.py --run runs/full [--initial-from data/roadmaps/roadmap_initial_gpt-4.1_v2_2026-10-31.json]
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.eval.alignment import evaluate_run as align_run
from trmkb.eval.recovery import evaluate as recovery
from trmkb.llm import LLM
from trmkb.roadmap import diff as D
from trmkb.roadmap import generate as G
from trmkb.roadmap import retrieve as R
from trmkb.store import KBStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--initial-from", default=None)
    ap.add_argument("--model", default=G.DEFAULT_MODEL)
    ap.add_argument("--skip-advanced", action="store_true")
    args = ap.parse_args()
    run = Path(args.run)
    llm = LLM()
    kb = KBStore(run)
    print("KB:", kb.stats())

    if args.initial_from and not G.load(run, "initial"):
        import shutil
        shutil.copy(args.initial_from, run / "roadmap_initial.json")
    ini = G.load(run, "initial")
    assert ini, "roadmap_initial.json missing (use --initial-from or gen_roadmap.py initial)"

    if not args.skip_advanced or not G.load(run, "advanced"):
        ctx = R.build_context(kb)
        print("context:", ctx.stats)
        (run / "context_advanced.txt").write_text(ctx.text, encoding="utf-8")
        adv = G.generate(llm, condition="advanced", context=ctx.text, model=args.model, ops_by_evidence=ctx.ops_by_ref)
        G.save(adv, run)
    adv = G.load(run, "advanced")
    assert ini.prompt_hash == adv.prompt_hash, f"prompt hash mismatch {ini.prompt_hash} vs {adv.prompt_hash}"

    d = D.compute_diff(ini, adv, llm); D.save(d, run)
    rec = recovery(run, llm)
    al = align_run(run, llm)

    summ = {
        "run": run.name, "kb": kb.stats(),
        "initial": G.summary(ini), "advanced": G.summary(adv),
        "diff": {k: v for k, v in d.items() if k != "pairs"},
        "recovery": {k: v for k, v in rec.items() if k not in ("results", "conflicts")},
        "conflict_pairs": rec.get("conflicts"),
        "alignment": {c: {k: v for k, v in s.items() if k != "results"} for c, s in al.items()},
        "finalize_cost_usd": round(llm.ledger.total_usd, 4),
    }
    (run / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")

    a_i, a_a = al.get("initial", {}), al.get("advanced", {})
    md = [f"# Run {run.name} — 결과 요약", "",
          f"KB: 문서 {kb.stats()['documents']} · 노드 {kb.stats()['nodes']} {kb.stats()['nodes_by_layer']} · 주장 {kb.stats()['claims']} · 수락 링크 {kb.stats()['edges_by_status'].get('accepted',0)} · 근거 {kb.stats()['evidence']}", "",
          "| 지표 | Initial (KB 없음) | Advanced (KB 사용) |", "|---|---|---|",
          f"| 노드 수 | {len(ini.nodes)} | {len(adv.nodes)} |",
          f"| 근거 있는 노드 | {sum(1 for n in ini.nodes if n.evidence_ids)} | {sum(1 for n in adv.nodes if n.evidence_ids)} |",
          f"| 공식 로드맵 recall 엄격/관대 | {a_i.get('recall_strict')} / {a_i.get('recall_lenient')} | {a_a.get('recall_strict')} / {a_a.get('recall_lenient')} |",
          f"| 2020판 recall (관대) | {a_i.get('recall_2020_lenient')} | {a_a.get('recall_2020_lenient')} |",
          f"| 2025판 recall (관대, 선견) | {a_i.get('recall_2025_lenient')} | {a_a.get('recall_2025_lenient')} |",
          f"| 연도 MAE | {a_i.get('year_mae')} | {a_a.get('year_mae')} |",
          "", f"Diff: {d['counts']} · 근거 있는 신규 {d['new_with_evidence']}/{d['counts'].get('new',0)}",
          f"심은 사실 회수율: 엄격 {rec.get('recovery_rate')} · 관대 {rec.get('recovery_rate_lenient')} · 모순 탐지 {rec.get('conflict_detection')}",
          f"회수율(노드 유형별): {rec.get('by_node_type')}",
          f"마무리 비용 ${llm.ledger.total_usd:.3f}"]
    (run / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
