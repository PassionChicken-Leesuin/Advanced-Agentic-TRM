"""사이트(agentic-trm-site) 정적 데이터 내보내기.
python scripts/export_site.py --run runs/struct5 --dst C:/Users/User/dev/agentic-trm-site/public/data/ionq
  meta.json      문서 목록·계획 수·대상 이름·트리 영역·용어집·통계
  events.jsonl   사건 기록 (그대로 복사; 사이트가 재생)
  cards.json     기회 카드 (구조화)
  roadmaps.json  eval/<cond>/rm_1.json 이 있으면 Initial / ALL 로드맵
"""
import argparse
import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.cards import build_cards_json
from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--dst", required=True)
    a = ap.parse_args()
    run, dst = Path(a.run), Path(a.dst)
    dst.mkdir(parents=True, exist_ok=True)
    st = SourceStore(run)
    read_ids = {p.doc_id for p in st.passages.values()}
    docs = [{"id": d["id"], "title": d["title"], "date": d["date"], "source_type": d["source_type"], "is_synthetic": d["is_synthetic"]}
            for d in sorted(st.docs.values(), key=lambda d: (d["date"], d["id"])) if d["id"] in read_ids]
    plan = run / "plan.json"
    meta = {"run": run.name, "documents": docs,
            "planned_total": json.loads(plan.read_text(encoding="utf-8")).get("total") if plan.exists() else len(docs),
            "entities": {e.id: {"name": e.name, "layer": e.layer} for e in st.entities.values()},
            "tree": {"areas": [{"name": x["name"], "theme_ids": x["theme_ids"], "trend": x.get("trend"), "shares": x.get("shares", [])} for x in st.tree["areas"]],
                     "root": st.tree.get("root")} if st.tree else None,
            "glossary": [{"name": t.name, "type": t.type, "aliases": t.aliases, "unit": t.unit, "definition": t.definition, "status": t.status, "count": t.count}
                         for t in st.terms_by_type()],
            "stats": st.stats()}
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(run / "events.jsonl", dst / "events.jsonl")
    cards = build_cards_json(st)
    (dst / "cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    rms = {}
    for cond, key in (("Initial", "initial"), ("ALL", "kb")):
        p = run / "eval" / cond / "rm_1.json"
        if p.exists():
            rms[key] = json.loads(p.read_text(encoding="utf-8"))
    ev = {}
    for pid in {e for rm in rms.values() for n in rm.get("nodes", []) for e in n.get("evidence_ids", [])}:
        p = st.passages.get(pid)
        if p:
            ev[pid] = {"text": p.text, "doc_id": p.doc_id, "date": p.doc_date.isoformat(), "source_type": p.source_type, "synthetic": p.is_synthetic}
    (dst / "roadmaps.json").write_text(json.dumps({**rms, "evidence": ev}, ensure_ascii=False), encoding="utf-8")
    print(f"exported → {dst}: docs {len(docs)}, events {sum(1 for _ in (run / 'events.jsonl').open(encoding='utf-8'))}, cards {len(cards)}, roadmaps {list(rms)}")


if __name__ == "__main__":
    main()
