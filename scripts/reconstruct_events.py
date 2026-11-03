"""구축 사건 기록(events.jsonl)에서 빠진 문서의 사건을 지식베이스 상태로부터 복원한다.

구축이 중단·재개되는 사이에 14건의 문서가 처리되었지만 사건이 기록되지 않았다(지식베이스에는 들어 있음). 이 스크립트는 그 문서들의
doc.started / entity.created / entity.linked / passage.routed / graph.relation / grid.opportunity / time.fact / tree.assigned / doc.finished 를
저장소 상태에서 만들어 날짜 순서상 제자리에 끼워 넣고, 전체 seq 를 다시 매긴다. 복원된 사건에는 reconstructed: true 를 붙인다.

python scripts/reconstruct_events.py --run runs/struct5 [--dry]
원본은 runs/<run>/events.before_reconstruct.jsonl 로 보관.
"""
import argparse
import io
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.store import SourceStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    run = Path(a.run)
    st = SourceStore(run)
    ev = [json.loads(l) for l in (run / "events.jsonl").open(encoding="utf-8")]
    read = [e for e in ev if e["type"] == "doc.read"]
    finished = {e["doc_id"] for e in ev if e["type"] == "doc.finished"}
    order = [e["doc_id"] for e in read]                       # 읽기 순서 = 처리 순서 (날짜 순)
    missing = [d for d in order if d not in finished]
    print(f"documents read {len(order)}, finished {len(finished)}, missing {len(missing)}")
    by_doc = defaultdict(list)
    for p in st.passages.values():
        by_doc[p.doc_id].append(p)
    rel_by_pid = defaultdict(list)
    for r in st.relations.values():
        rel_by_pid[r.pid].append(r)
    fact_by_pid = defaultdict(list)
    for f in st.facts.values():
        fact_by_pid[f.pid].append(f)
    opp_by_pid = defaultdict(list)
    for o in st.opps.values():
        opp_by_pid[o.pid].append(o)
    themes = {t.id: t for t in st.themes.values()} if hasattr(st, "themes") else {}
    created_by = defaultdict(list)
    for e in st.entities.values():
        if e.created_by_doc:
            created_by[e.created_by_doc].append(e)
    meta = {e["doc_id"]: e for e in read}

    def synth(doc_id: str) -> list[dict]:
        ps = sorted(by_doc.get(doc_id, []), key=lambda p: p.id)
        m = meta[doc_id]
        d = st.docs.get(doc_id, {})
        out = [{"type": "doc.started", "doc_id": doc_id, "title": m.get("title"), "date": m.get("date"), "source_type": d.get("source_type"),
                "synthetic": d.get("is_synthetic", False), "n": len(ps)}]
        for e in created_by.get(doc_id, []):
            out.append({"type": "entity.created", "doc_id": doc_id, "pid": e.passage_ids[0] if e.passage_ids else None, "eid": e.id, "name": e.name,
                        "layers": sorted(e.layer_counts)})
        routes = Counter(); status = Counter(); extracted = Counter(); kept = 0
        for p in ps:
            status[p.status or "new"] += 1
            if not p.routed or p.status in ("irrelevant", "duplicate"):
                continue
            for eid in p.entity_ids:
                en = st.entities.get(eid)
                if en:
                    out.append({"type": "entity.linked", "doc_id": doc_id, "pid": p.id, "eid": eid, "name": en.name, "layers": p.layers})
            out.append({"type": "passage.routed", "doc_id": doc_id, "pid": p.id, "status": p.status, "layers": p.layers, "kinds": p.kinds,
                        "entities": p.entity_ids, "systems": p.systems, "reasons": p.route_reasons, "synthetic": p.is_synthetic, "text": p.statement[:160]})
            kept += 1
            for s in p.systems:
                routes[s] += 1
            for r in rel_by_pid.get(p.id, []):
                if r.src in st.entities and r.dst in st.entities:
                    out.append({"type": "graph.relation", "doc_id": doc_id, "pid": p.id, "rid": r.id, "src": r.src, "src_name": st.entities[r.src].name,
                                "rel": r.rel, "dst": r.dst, "dst_name": st.entities[r.dst].name}); extracted["graph"] += 1
            for o in opp_by_pid.get(p.id, []):
                if o.eid in st.entities:
                    out.append({"type": "grid.opportunity", "doc_id": doc_id, "pid": p.id, "oid": o.id, "eid": o.eid, "name": st.entities[o.eid].name,
                                "kind": o.kind, "offering": o.offering, "customer": o.customer, "maturity": o.maturity, "drivers": o.drivers, "needs": o.needs})
                    extracted["grid"] += 1
            for f in fact_by_pid.get(p.id, []):
                if f.eid in st.entities:
                    out.append({"type": "time.fact", "doc_id": doc_id, "pid": p.id, "fid": f.id, "eid": f.eid, "name": st.entities[f.eid].name, "family": f.family,
                                "attribute": f.attribute, "value": f.value, "valid": f.valid_start, "modality": f.modality, "status": f.status, "related": f.related_fact})
                    extracted["time"] += 1
            if p.theme_id and p.theme_id in themes:
                out.append({"type": "tree.assigned", "doc_id": doc_id, "pid": p.id, "tid": p.theme_id, "theme": themes[p.theme_id].name, "emphasis": p.emphasis})
                extracted["tree"] += 1
        out.append({"type": "doc.finished", "doc_id": doc_id, "title": m.get("title"), "passages": len(ps), "kept": kept, "routes": dict(routes),
                    "status": dict(status), "glossary": {"new_terms": 0, "new_aliases": 0}, "extracted": dict(extracted)})
        for x in out:
            x["reconstructed"] = True
        return out

    # 삽입 위치: 처리 순서상 바로 앞 문서의 doc.finished 뒤 (앞 문서가 없거나 그것도 빠졌으면 더 앞으로)
    fin_idx = {e["doc_id"]: i for i, e in enumerate(ev) if e["type"] == "doc.finished"}
    last_read_idx = max(i for i, e in enumerate(ev) if e["type"] == "doc.read")
    inserts = defaultdict(list)   # index after which to insert → list of events
    for d in missing:
        k = order.index(d)
        pos = last_read_idx
        for j in range(k - 1, -1, -1):
            if order[j] in fin_idx:
                pos = fin_idx[order[j]]; break
        inserts[pos].extend(synth(d))
    new = []
    for i, e in enumerate(ev):
        new.append(e)
        if i in inserts:
            new.extend(inserts[i])
    # seq 재부여, ts 는 앞 사건에서 1ms 씩
    prev_ts = None
    for i, e in enumerate(new, 1):
        e["seq"] = i
        if e.get("reconstructed"):
            prev_ts = (prev_ts or datetime.now(timezone.utc)) + timedelta(milliseconds=1)
            e["ts"] = prev_ts.isoformat()
        else:
            prev_ts = datetime.fromisoformat(e["ts"])
    added = sum(len(v) for v in inserts.values())
    print(f"inserted {added} reconstructed events for {len(missing)} documents; total {len(ev)} → {len(new)}")
    if a.dry:
        return
    shutil.copyfile(run / "events.jsonl", run / "events.before_reconstruct.jsonl")
    with (run / "events.jsonl").open("w", encoding="utf-8") as f:
        for e in new:
            f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
    print("written", run / "events.jsonl")


if __name__ == "__main__":
    main()
