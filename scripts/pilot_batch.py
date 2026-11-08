"""묶음 구축 시범: 같은 문서·같은 인용 문장으로 '문서 1건씩'과 '20건 묶음'을 돌려 결과를 비교한다.

python scripts/pilot_batch.py prepare --src runs/struct5 --n 40 --runs runs/bp_seq_a runs/bp_seq_b runs/bp_b20
python scripts/pilot_batch.py build --run runs/bp_b20 --batch 20       (seq 는 --batch 1)
python scripts/pilot_batch.py compare --runs runs/bp_seq_a runs/bp_seq_b runs/bp_b20 --src-log runs/struct5_build.log --out ...md

- prepare: src run 의 문서를 날짜순으로 고르게 n 건 뽑고(180건이면 4~5건마다 1건), 그 문서의 인용 문장을 그대로 복사한다(같은 문장 id,
  Reader 재실행 없음). 그래서 차이는 구축 방식에서만 나온다.
- build: 구축 → 마무리(병합·트리·그리드) → 카드. 시간·비용은 runs/<run>/pilot.json.
- compare: seq_a 대 seq_b 가 '같은 방식을 두 번 돌린 잡음', seq 대 b20 이 '묶음의 효과'. 잡음보다 큰 차이만 묶음 탓으로 본다.
"""
from __future__ import annotations

import argparse
import io
import json
import statistics as S
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.store import Passage, SourceStore


def prepare(src: Path, n: int, runs: list[Path]) -> None:
    s = SourceStore(src)
    docs = sorted(s.docs.values(), key=lambda d: (d["date"], d["id"]))
    docs = [d for d in docs if any(p.doc_id == d["id"] for p in s.passages.values())]
    step = len(docs) / n
    pick = [docs[int(i * step)] for i in range(n)]
    ids = {d["id"] for d in pick}
    for r in runs:
        if r.exists() and any(r.iterdir()):
            raise SystemExit(f"{r} exists; remove it first")
        st = SourceStore(r)
        for d in pick:
            st.docs[d["id"]] = dict(d, read=True)
        for p in s.passages.values():
            if p.doc_id in ids:
                st.passages[p.id] = Passage(id=p.id, doc_id=p.doc_id, doc_date=p.doc_date, source_type=p.source_type,
                                            is_synthetic=p.is_synthetic, text=p.text, claim=p.claim)
        st.save()
    c = Counter("internal" if d["is_synthetic"] else d["source_type"] for d in pick)
    print(f"prepared {len(runs)} runs: {n} docs ({pick[0]['date']}..{pick[-1]['date']}), "
          f"{sum(1 for p in s.passages.values() if p.doc_id in ids)} passages, types {dict(c)}")


def build(run: Path, batch: int) -> None:
    from trmkb.llm import LLM
    from trmkb.sources.build import build_docs, finish
    from trmkb.sources.cards_v2 import build_cards, dump
    st = SourceStore(run)
    llm = LLM()
    order = sorted(st.docs.values(), key=lambda d: (d["date"], d["id"]))
    t0 = time.time()
    per_doc = []
    build_docs(st, llm, order, batch=batch, on_doc=lambda d, r, secs: per_doc.append(secs))
    t1 = time.time(); c1 = llm.ledger.total_usd
    finish(st, llm, real_only_too=False)
    t2 = time.time()
    cards = build_cards(st, min_docs=1)
    dump(cards, run / "cards_v2")
    llm.ledger.dump(run / "cost_pilot.json")
    rec = {"batch": batch, "build_seconds": round(t1 - t0, 1), "finish_seconds": round(t2 - t1, 1),
           "build_usd": round(c1, 3), "total_usd": round(llm.ledger.total_usd, 3), "docs": len(order),
           "per_doc_seconds": per_doc}
    (run / "pilot.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rec.items() if k != "per_doc_seconds"}))


# ------------------------------------------------------------------ 비교
def _profile(run: Path) -> dict:
    from trmkb.sources.resolve import norm
    st = SourceStore(run)
    ps = list(st.passages.values())
    evs = [json.loads(l) for l in (run / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pilot = json.loads((run / "pilot.json").read_text(encoding="utf-8")) if (run / "pilot.json").exists() else {}
    cards = json.loads((run / "cards_v2" / "cards.json").read_text(encoding="utf-8")) if (run / "cards_v2" / "cards.json").exists() else []
    created = sum(1 for e in evs if e["type"] == "entity.created")
    merged = sum(1 for e in evs if e["type"] == "entity.merged")
    names = Counter(norm(e.name) for e in st.entities.values())
    return {
        "st": st, "pilot": pilot,
        "row": {
            "build_seconds": pilot.get("build_seconds"), "finish_seconds": pilot.get("finish_seconds"), "total_usd": pilot.get("total_usd"),
            "passages": len(ps),
            "new": sum(p.status == "new" for p in ps), "duplicate": sum(p.status == "duplicate" for p in ps),
            "irrelevant": sum(p.status == "irrelevant" for p in ps),
            "entities_created": created, "entity_merges": merged, "entities_final": len(st.entities),
            "same_name_entities": sum(c - 1 for c in names.values() if c > 1),
            "glossary_terms": len(st.terms), "glossary_confirmed": sum(t.status == "confirmed" for t in st.terms.values()),
            "relations": len(st.relations), "time_facts": len(st.facts),
            "time_update": sum(f.status == "update" for f in st.facts.values()), "time_conflict": sum(f.status == "conflict" for f in st.facts.values()),
            "time_duplicate": sum(f.status == "duplicate" for f in st.facts.values()),
            "themes": len(st.themes), "areas": len(st.tree.get("areas", [])) if st.tree else 0,
            "opp_records": len(st.opps), "cards": len(cards),
            "errors": sum(1 for e in evs if e["type"] == "error"),
        },
        "cards": {c["name"].lower() for c in cards},
    }


def _agree(a: SourceStore, b: SourceStore) -> dict:
    """같은 문장 id 에 대한 Router 판정 일치율."""
    ids = set(a.passages) & set(b.passages)
    st_same = sum(a.passages[i].status == b.passages[i].status for i in ids)
    sys_same = sum(set(a.passages[i].systems) == set(b.passages[i].systems) for i in ids)
    lay_same = sum(set(a.passages[i].layers) == set(b.passages[i].layers) for i in ids)
    # 시스템별 일치 (각 구조로 보냈는가)
    per = {}
    for s in ("tree", "grid", "graph", "time"):
        per[s] = round(sum((s in a.passages[i].systems) == (s in b.passages[i].systems) for i in ids) / max(1, len(ids)), 3)
    return {"n": len(ids), "status": round(st_same / max(1, len(ids)), 3), "systems_exact": round(sys_same / max(1, len(ids)), 3),
            "layers_exact": round(lay_same / max(1, len(ids)), 3), "per_structure": per}


def _jacc(x: set, y: set) -> float:
    return round(len(x & y) / max(1, len(x | y)), 2)


def compare(runs: list[Path], src_log: Path | None, out: Path | None) -> None:
    import re
    prof = {r.name: _profile(r) for r in runs}
    names = list(prof)
    keys = list(prof[names[0]]["row"])
    L = ["# 묶음 구축 시범 비교", "", "| 항목 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in keys:
        L.append(f"| {k} | " + " | ".join(str(prof[n]["row"][k]) for n in names) + " |")
    if src_log and src_log.exists():
        ids = set(prof[names[0]]["st"].docs)
        secs = []
        for l in src_log.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.search(r"^\[\d+\] \S+ (\S+)\s.*?\s(\d+)s \$", l)
            if m and any(i.startswith(m.group(1)) or m.group(1).startswith(i[:44]) for i in ids):
                secs.append(int(m.group(2)))
        if secs:
            L += ["", f"참고: 180건 본 구축 로그에서 같은 문서 {len(secs)}건의 문서 1건씩 처리 시간 합계 {sum(secs)}초 (평균 {S.mean(secs):.0f}초). "
                  "seq 시범은 둘을 동시에 돌려 키를 나눠 썼으므로 이 값을 순차 기준 시간으로 씀."]
    L += ["", "## Router 판정 일치율 (같은 문장 id)", "", "| 비교 | 문장 | 상태 | 구조 집합 | 층 집합 | tree | grid | graph | time |", "|---|---|---|---|---|---|---|---|---|"]
    pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]
    for x, y in pairs:
        a = _agree(prof[x]["st"], prof[y]["st"])
        L.append(f"| {x} vs {y} | {a['n']} | {a['status']:.0%} | {a['systems_exact']:.0%} | {a['layers_exact']:.0%} | "
                 + " | ".join(f"{a['per_structure'][s]:.0%}" for s in ("tree", "grid", "graph", "time")) + " |")
    L += ["", "## 카드 이름 겹침 (Jaccard)", ""]
    for x, y in pairs:
        L.append(f"- {x} vs {y}: {_jacc(prof[x]['cards'], prof[y]['cards'])} ({len(prof[x]['cards'])} / {len(prof[y]['cards'])}장)")
    txt = "\n".join(L)
    if out:
        out.write_text(txt, encoding="utf-8"); print("wrote", out)
    print(txt)
    (runs[-1].parent / "bp_compare.json").write_text(json.dumps({n: prof[n]["row"] for n in names}, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare"); a.add_argument("--src", default="runs/struct5"); a.add_argument("--n", type=int, default=40); a.add_argument("--runs", nargs="+", required=True)
    b = sub.add_parser("build"); b.add_argument("--run", required=True); b.add_argument("--batch", type=int, default=1)
    c = sub.add_parser("compare"); c.add_argument("--runs", nargs="+", required=True); c.add_argument("--src-log", default=None); c.add_argument("--out", default=None)
    x = ap.parse_args()
    if x.cmd == "prepare":
        prepare(Path(x.src), x.n, [Path(r) for r in x.runs])
    elif x.cmd == "build":
        build(Path(x.run), x.batch)
    else:
        compare([Path(r) for r in x.runs], Path(x.src_log) if x.src_log else None, Path(x.out) if x.out else None)


if __name__ == "__main__":
    main()
