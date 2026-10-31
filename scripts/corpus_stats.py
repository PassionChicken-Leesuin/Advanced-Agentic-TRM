"""data/corpus/index.jsonl 요약: 출처·연도별 건수, 글자 수, 가상 자료 심은 사실 커버리지."""
import io
import json
import sys
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus import CORPUS_ROOT, rebuild_index
from trmkb.corpus.synth import coverage, load_ledger

rebuild_index()
rows = [json.loads(l) for l in (CORPUS_ROOT / "index.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
by_src = Counter(r["source_type"] for r in rows)
chars = defaultdict(int)
for r in rows:
    chars[r["source_type"]] += r["n_chars"]
by_year = Counter((r["date"][:4], "syn" if r["is_synthetic"] else "pub") for r in rows)

print(f"총 {len(rows)}건 | 공개 {sum(1 for r in rows if not r['is_synthetic'])} | 가상 {sum(1 for r in rows if r['is_synthetic'])}")
print("\n출처별            건수   글자수(천)")
for k, v in by_src.most_common():
    print(f"{k:20s} {v:5d} {chars[k]//1000:8d}")
print("\n연도별 (공개/가상)")
years = sorted({y for y, _ in by_year})
for y in years:
    print(f"{y}: pub {by_year[(y,'pub')]:3d}  syn {by_year[(y,'syn')]:3d}")
print("\n심은 사실 커버리지:", coverage(load_ledger()))
