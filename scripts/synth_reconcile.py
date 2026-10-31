"""생성된 가상 문서의 frontmatter(실제 심은 사실)와 현재 plan()의 배정을 대조하고,
다른 문서만 다시 생성한다. 원장의 planted_in_doc_ids 도 frontmatter 기준으로 재구축한다.

python scripts/synth_reconcile.py check
python scripts/synth_reconcile.py regen [--model ...]
"""
import argparse
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus import CORPUS_ROOT, iter_docs, rebuild_index
from trmkb.corpus.synth import LEDGER_PATH, coverage, generate, load_ledger, plan
from trmkb.llm import LLM


def diff():
    ledger = load_ledger()
    planned = {s.doc_id: s for s in plan(ledger)}
    actual = {fm["id"]: fm.get("planted_fact_ids") or [] for _, fm, _ in iter_docs(CORPUS_ROOT, "synthetic") if fm}
    missing = [d for d in planned if d not in actual]
    changed = [d for d in planned if d in actual and sorted(actual[d]) != sorted(planned[d].fact_ids)]
    return ledger, planned, actual, missing, changed


def rebuild_ledger_links(ledger: dict, actual: dict[str, list[str]]) -> None:
    for f in ledger["facts"]:
        f["planted_in_doc_ids"] = sorted(d for d, fids in actual.items() if f["id"] in fids)
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "regen"])
    ap.add_argument("--model", default="anthropic/claude-sonnet-4.6")
    args = ap.parse_args()
    ledger, planned, actual, missing, changed = diff()
    print(f"planned {len(planned)} | generated {len(actual)} | missing {len(missing)} | changed {len(changed)}")
    for d in changed:
        print(f"  changed {d}: {actual[d]} -> {planned[d].fact_ids}")
    if args.cmd == "check":
        return
    todo = [planned[d] for d in missing + changed]
    if todo:
        llm = LLM()
        generate(todo, ledger, llm, args.model, overwrite=True)
        print(f"regenerated {len(todo)} | cost ${llm.ledger.total_usd:.4f}")
    ledger, planned, actual, missing, changed = diff()
    rebuild_ledger_links(ledger, actual)
    rebuild_index()
    print("coverage:", coverage(load_ledger()), "| remaining diffs:", len(missing) + len(changed))


if __name__ == "__main__":
    main()
