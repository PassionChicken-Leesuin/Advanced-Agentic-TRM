"""가상 내부자료 생성 CLI.

python scripts/gen_synthetic.py plan                       # 배정 계획만 출력 (LLM 호출 없음)
python scripts/gen_synthetic.py gen --limit 2              # 파일럿 2건
python scripts/gen_synthetic.py gen --model anthropic/claude-sonnet-4.6
"""
import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus import rebuild_index
from trmkb.corpus.synth import coverage, generate, load_ledger, plan
from trmkb.llm import LLM


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "gen"])
    ap.add_argument("--model", default="anthropic/claude-sonnet-4.6")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    ledger = load_ledger()
    specs = plan(ledger)
    if args.limit:
        specs = specs[: args.limit]
    if args.cmd == "plan":
        for s in specs:
            print(f"{s.date} {s.doc_type:22s} {s.doc_id:40s} {s.fact_ids}")
        from collections import Counter
        c = Counter(fid for s in specs for fid in s.fact_ids)
        print(f"\n{len(specs)} docs; facts covered {len(c)}/{len(ledger['facts'])}; "
              f"appearances min={min(c.values())} max={max(c.values())}")
        return
    llm = LLM()
    docs = generate(specs, ledger, llm, args.model, overwrite=args.overwrite)
    rebuild_index()
    llm.ledger.dump("data/corpus/synthetic_data/_cost_synth.json")
    print(f"\ngenerated {len(docs)} docs | cost ${llm.ledger.total_usd:.4f} | coverage {coverage(load_ledger())}")


if __name__ == "__main__":
    main()
