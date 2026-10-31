"""공개 코퍼스 수집 CLI.

python scripts/collect_public.py all            # edgar + arxiv + ionq_web 전량
python scripts/collect_public.py edgar --limit 5
python scripts/collect_public.py index          # frontmatter → data/corpus/index.jsonl 재생성
"""
import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus import rebuild_index
from trmkb.corpus import arxiv, edgar, ionq_web


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=["all", "edgar", "arxiv", "web", "index"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--forms", nargs="*", default=None, help="edgar forms e.g. 10-K 8-K 425")
    args = ap.parse_args()

    n = 0
    if args.source in ("all", "edgar"):
        n += len(edgar.collect(forms=set(args.forms) if args.forms else None, limit=args.limit))
    if args.source in ("all", "arxiv"):
        n += len(arxiv.collect(limit=args.limit))
    if args.source in ("all", "web"):
        n += len(ionq_web.collect(limit=args.limit))
    idx = rebuild_index()
    print(f"collected {n} docs; index → {idx}")


if __name__ == "__main__":
    main()
