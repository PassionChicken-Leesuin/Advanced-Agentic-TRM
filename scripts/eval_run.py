"""run 평가·비교 CLI.

python scripts/eval_run.py recovery --run runs/pilotA            # 심은 사실 회수율 + 모순 탐지율 (LLM 판정자)
python scripts/eval_run.py compare runs/pilotA runs/pilotB       # 통계·비용·회수율 나란히
python scripts/eval_run.py inspect --run runs/pilotA [--layer how]
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.store import KBStore


def cmd_recovery(args):
    from trmkb.eval.recovery import evaluate
    from trmkb.llm import LLM
    llm = LLM()
    s = evaluate(args.run, llm, model=args.judge)
    print(json.dumps({k: v for k, v in s.items() if k != "results"}, ensure_ascii=False, indent=1))
    print("\nabsent/partial facts:")
    for r in s["results"]:
        if r["verdict"] != "present":
            print(f"  {r['fact_id']} [{r['verdict']}] ({r['expected_node_type']}) best={r['best_node']} sim={r['top_sim']:.2f} :: {r['reason'][:100]}")
    print(f"\njudge cost ${llm.ledger.total_usd:.4f}")


def _run_summary(run: str) -> dict:
    p = Path(run)
    kb = KBStore(p)
    st = kb.stats()
    cost = json.loads((p / "cost.json").read_text(encoding="utf-8")) if (p / "cost.json").exists() else {}
    eps = [json.loads(l) for l in (p / "episodes.jsonl").read_text(encoding="utf-8").splitlines()] if (p / "episodes.jsonl").exists() else []
    rec = json.loads((p / "eval_recovery.json").read_text(encoding="utf-8")) if (p / "eval_recovery.json").exists() else {}
    cfg = json.loads((p / "config.json").read_text(encoding="utf-8")) if (p / "config.json").exists() else {}
    n_claims_num = sum(1 for c in kb.claims.values() if getattr(c, "value_num", None) is not None)
    return {
        "run": p.name, "config": cfg.get("name"), "reader": cfg.get("model_reader"), "critic": cfg.get("model_critic"),
        "docs": st["documents"], "errors": sum(1 for e in eps if e.get("error")),
        "nodes": st["nodes"], "by_layer": st["nodes_by_layer"], "claims": st["claims"], "numeric_claims": n_claims_num,
        "edges_acc": st["edges_by_status"].get("accepted", 0), "edges_rej": st["edges_by_status"].get("rejected", 0),
        "edges_hold": st["edges_by_status"].get("hold", 0),
        "with_time": sum(1 for n in kb.nodes.values() if n.es is not None),
        "conflicts": sum(1 for n in kb.nodes.values() if "conflict" in n.flags),
        "merge_rate": round(sum(e["nodes_merged"] for e in eps) / max(1, sum(e["nodes_merged"] + e["nodes_created"] for e in eps)), 2) if eps else None,
        "cost_total": round(cost.get("total_usd", 0), 3), "cost_per_doc": round(cost.get("total_usd", 0) / max(1, st["documents"]), 4),
        "sec_per_doc": round(sum(e["seconds"] for e in eps) / max(1, len(eps)), 0) if eps else None,
        "recovery": rec.get("recovery_rate"), "recovery_lenient": rec.get("recovery_rate_lenient"),
        "conflict_detection": rec.get("conflict_detection"),
        "cost_by_purpose": {k: round(v["cost_usd"], 3) for k, v in cost.get("by_purpose", {}).items()},
    }


def cmd_compare(args):
    rows = [_run_summary(r) for r in args.runs]
    keys = ["config", "reader", "critic", "docs", "errors", "nodes", "claims", "numeric_claims", "edges_acc", "edges_rej",
            "edges_hold", "with_time", "conflicts", "merge_rate", "cost_total", "cost_per_doc", "sec_per_doc",
            "recovery", "recovery_lenient", "conflict_detection"]
    w = max(len(k) for k in keys) + 2
    print(" " * w + "".join(f"{r['run']:>22s}" for r in rows))
    for k in keys:
        print(f"{k:{w}s}" + "".join(f"{str(r.get(k)):>22s}" for r in rows))
    for r in rows:
        print(f"\n{r['run']} by_layer={r['by_layer']}\n  cost_by_purpose={r['cost_by_purpose']}")


def cmd_inspect(args):
    kb = KBStore(args.run)
    for n in sorted(kb.nodes.values(), key=lambda n: (n.layer.value, n.category or "", n.label)):
        if args.layer and n.layer.value != args.layer:
            continue
        cl = kb.claims_for(n.id)
        print(f"[{n.layer.value:8s}/{n.type:11s}] {n.label:44s} cat={n.category} es={n.es} ls={n.ls} flags={n.flags} "
              f"claims={len(cl)} deg={kb.degree(n.id)} aliases={n.aliases[:2]}")
        if args.claims:
            for c in cl:
                print(f"      {c.doc_date} [{c.type[:10]}/{c.modality.value[:7]}] {c.text[:110]} | t={c.time.raw}->{c.time.start}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("recovery"); a.add_argument("--run", required=True); a.add_argument("--judge", default="openai/gpt-4.1-mini")
    b = sub.add_parser("compare"); b.add_argument("runs", nargs="+")
    c = sub.add_parser("inspect"); c.add_argument("--run", required=True); c.add_argument("--layer"); c.add_argument("--claims", action="store_true")
    args = ap.parse_args()
    {"recovery": cmd_recovery, "compare": cmd_compare, "inspect": cmd_inspect}[args.cmd](args)


if __name__ == "__main__":
    main()
