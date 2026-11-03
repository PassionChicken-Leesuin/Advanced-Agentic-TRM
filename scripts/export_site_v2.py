"""카드 v2 · 선정 · 관점별 로드맵을 사이트 정적 데이터로 내보낸다.

python scripts/export_site_v2.py --run runs/struct5 --dst "C:/Users/User/dev/agentic-trm-site/public/data/ionq"
산출: cards_v2.json, selection.json, roadmaps_v2.json (관점별 rm + evidence)
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.cards_v2 import Card
from trmkb.sources.select import STANCES
from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--dst", required=True)
    a = ap.parse_args()
    run, dst = Path(a.run), Path(a.dst)
    st = SourceStore(run)
    cdir = run / "cards_v2"
    raw = json.loads((cdir / "cards.json").read_text(encoding="utf-8"))
    cards = []
    for d in raw:
        c = Card(**{k: (set(v) if k in ("pids", "elements") else v) for k, v in d.items()})
        cards.append({"eid": c.eid, "name": c.name, "kind": c.kind, "customers": c.customers[:4], "maturity": c.maturity,
                      "docs_public": c.docs_public, "docs_internal": c.docs_internal, "first_date": c.first_date, "last_date": c.last_date,
                      "lines": {k: getattr(c, k) for k in ("state", "why", "trend", "what", "when", "how", "resource", "actors", "issue")},
                      "digest": c.digest()})
    (dst / "cards_v2.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    stances = {}
    for key, meta in STANCES.items():
        pf = cdir / "selection" / ("profiles.json" if key == "balanced" else f"profiles_{key}.json")
        if not pf.exists():
            continue
        recs = json.loads(pf.read_text(encoding="utf-8"))
        recs.sort(key=lambda r: r["profile"]["rank"])
        stances[key] = {"label": meta["label"], "desc": meta["desc"],
                        "order": [r["eid"] for r in recs],
                        "selected": [r["eid"] for r in recs if r["profile"]["selected"]],
                        "profiles": {r["eid"]: {"q1": r["profile"]["q1"], "q2": r["profile"]["q2"], "q3": r["profile"]["q3"], "rank": r["profile"]["rank"],
                                                "sd": [r["profile"]["q1_sd_final"], r["profile"]["q2_sd_final"], r["profile"]["q3_sd_final"]],
                                                "reasons": {m: v["final"]["reasons"] for m, v in r["models"].items()},
                                                "replies": {m: v["final"].get("replies", [])[:2] for m, v in r["models"].items()}}
                                     for r in recs}}
    (dst / "selection.json").write_text(json.dumps({"questions": {
        "q1": "Why should the company go for it? Who demands it, for what, under what conditions and by when; has the company stated this direction itself?",
        "q2": "Where is the company now? Offerings and their lifecycle stage, latest capability metrics, secured customers, partners and resources.",
        "q3": "Can the company get there? Is the gap between the requirement and current capability documented, with a dated plan to close it?"},
        "stances": stances}, ensure_ascii=False), encoding="utf-8")
    rms = {}
    for key in STANCES:
        p = cdir / "roadmaps" / f"rm_{key}.json"
        if p.exists():
            rms[key] = json.loads(p.read_text(encoding="utf-8"))
    ev = {}
    for pid in {e for rm in rms.values() for n in rm.get("nodes", []) for e in n.get("evidence_ids", [])}:
        p = st.passages.get(pid)
        if p:
            ev[pid] = {"text": p.text, "doc_id": p.doc_id, "date": p.doc_date.isoformat(), "source_type": p.source_type, "synthetic": p.is_synthetic}
        else:
            f = st.facts.get(pid)
            if f and f.pid in st.passages:
                q = st.passages[f.pid]
                ev[pid] = {"text": f"[{f.attribute}: {f.value}] " + q.text, "doc_id": q.doc_id, "date": q.doc_date.isoformat(), "source_type": q.source_type, "synthetic": q.is_synthetic}
    (dst / "roadmaps_v2.json").write_text(json.dumps({**rms, "evidence": ev}, ensure_ascii=False), encoding="utf-8")
    print(f"exported: cards {len(cards)}, stances {list(stances)}, roadmaps {list(rms)}, evidence {len(ev)}")


if __name__ == "__main__":
    main()
