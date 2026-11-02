"""K5 시간 사실만 다시 뽑기 (Router 결과는 그대로, time 으로 보낸 문장을 문서 날짜 순으로 다시 추출).
python scripts/redo_time.py --run runs/pilot3
"""
import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.llm import LLM
from trmkb.sources.extract import TimeExtractor
from trmkb.sources.resolve import Resolver
from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/pilot3")
    a = ap.parse_args()
    st = SourceStore(a.run)
    llm = LLM()
    st.facts.clear()
    for p in st.passages.values():
        p.time_start = p.time_end = p.time_raw = None
    ex = TimeExtractor(llm, st, Resolver(st))
    docs = sorted((d for d in st.docs.values() if any(p.doc_id == d["id"] and "time" in p.systems for p in st.passages.values())),
                  key=lambda d: (d["date"], d["id"]))
    for d in docs:
        ps = [p for p in st.passages.values() if p.doc_id == d["id"] and "time" in p.systems]
        n = ex.apply(d, ps, ex.call(d, ps))
        print(f"{d['date']} {d['id'][:50]:50s} time passages {len(ps):3d} -> facts {n}")
    st.save()
    print("facts", len(st.facts), "| cost", round(llm.ledger.total_usd, 3))


if __name__ == "__main__":
    main()
