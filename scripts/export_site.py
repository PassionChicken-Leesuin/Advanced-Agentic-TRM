"""사이트(agentic-trm-site) 정적 데이터 내보내기 (meta.json, events.jsonl, cards.json, roadmaps.json).
python scripts/export_site.py --run runs/struct5 --dst C:/Users/User/dev/agentic-trm-site/public/data/ionq
구현: trmkb/sources/export.py (업로드 작업과 공유)
"""
import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.export import export_cards_v1, export_meta, export_roadmaps
from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--dst", required=True)
    a = ap.parse_args()
    st = SourceStore(a.run)
    dst = Path(a.dst)
    meta = export_meta(st, dst)
    n = export_cards_v1(st, dst)
    rms = export_roadmaps(st, dst)
    print(f"exported → {dst}: docs {len(meta['documents'])}, cards {n}, roadmaps {rms}")


if __name__ == "__main__":
    main()
