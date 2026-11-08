"""카드 v2 · 후보 · 선정 · 관점별 로드맵을 사이트 정적 데이터로 내보낸다 (cards_v2.json, candidates.json, selection.json, roadmaps_v2.json).
python scripts/export_site_v2.py --run runs/struct5 --dst "C:/Users/User/dev/agentic-trm-site/public/data/ionq"
구현: trmkb/sources/export.py (업로드 작업과 공유)
"""
import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.export import export_v2
from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--dst", required=True)
    a = ap.parse_args()
    res = export_v2(SourceStore(a.run), Path(a.dst))
    print(f"exported: cards {res['cards']}, stances {res['stances']}, roadmaps {res['roadmaps']}, evidence {res['evidence']}")


if __name__ == "__main__":
    main()
