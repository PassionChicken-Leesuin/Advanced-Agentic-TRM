"""공개 자료 259건 원본 파일 확보.

python scripts/fetch_originals.py             # 전체 (재실행 시 받은 것은 건너뜀)
python scripts/fetch_originals.py --limit 3   # 시험
python scripts/fetch_originals.py --report    # 매니페스트 요약
"""
import argparse
import io
import json
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus.originals import MANIFEST, collect


def report() -> None:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by = Counter((r.get("source", "?"), r["status"] == "ok") for r in man.values())
    size = sum(f["bytes"] for r in man.values() for f in r["files"])
    files = sum(len(r["files"]) for r in man.values())
    print(f"docs {len(man)} | files {files} | {size/1e6:.1f} MB")
    for (src, ok), n in sorted(by.items()):
        print(f"  {src:10s} {'ok' if ok else 'FAIL':4s} {n}")
    for r in man.values():
        if r["status"] != "ok" or r.get("warnings"):
            print("  !", r["doc_id"][:60], r["status"][:60], (r.get("warnings") or [])[:2])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if not args.report:
        collect(limit=args.limit)
    report()


if __name__ == "__main__":
    main()
