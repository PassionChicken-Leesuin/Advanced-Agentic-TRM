"""기회 카드 v2 를 구축된 run 위에서 만든다 (지식베이스 재구축 없음).

python scripts/make_cards_v2.py --run runs/struct5 [--min-docs 1] [--show "air-gapped" "Drug Discovery" "Quantum Machine Learning"]
산출: runs/<run>/cards_v2/{cards.json, cards.md, digest.md, stats.json}
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.cards_v2 import build_cards, dump
from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--min-docs", type=int, default=1)
    ap.add_argument("--real-only", action="store_true")
    ap.add_argument("--show", nargs="*", default=["air-gapped", "Drug Discovery", "Quantum Machine Learning"])
    a = ap.parse_args()
    st = SourceStore(a.run)
    cards = build_cards(st, real_only=a.real_only, min_docs=a.min_docs)
    stats = dump(cards, Path(a.run) / "cards_v2")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    for key in a.show:
        for c in cards:
            if key.lower() in c.name.lower():
                print("\n" + "=" * 100 + "\n" + c.text())
                break


if __name__ == "__main__":
    main()
