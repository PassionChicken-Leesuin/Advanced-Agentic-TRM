# -*- coding: utf-8 -*-
"""마무리 정리(consolidate) 결과를 이벤트 로그로 되돌리고, 가드가 추가된 병합을 다시 수행한다.
복원 근거: entity.created / entity.linked (대상 ↔ 문장), graph.relation (관계 양끝), time.fact (사실 → 대상),
grid.opportunity (기회 → 대상·드라이버·요구·제공물). 주제 병합(K2)은 대상과 무관하므로 유지한다.
python scripts/unmerge.py --run runs/struct5
"""
import argparse, io, json, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trmkb.llm import LLM
from trmkb.sources.store import SourceStore, Entity, Relation
from trmkb.sources.consolidate import merge_entities, relink_facts
from trmkb.sources.grid import build_grid

ap = argparse.ArgumentParser(); ap.add_argument("--run", required=True); ap.add_argument("--dry", action="store_true")
a = ap.parse_args()
run = Path(a.run)
st = SourceStore(str(run))
ev = [json.loads(l) for l in (run / "events.jsonl").open(encoding="utf-8")]

# 1) 대상 복원 ---------------------------------------------------------------
old_entities = st.entities
ents: dict[str, Entity] = {}
links: dict[str, list[dict]] = defaultdict(list)
for e in ev:
    if e["type"] in ("entity.created", "entity.linked"):
        links[e["eid"]].append(e)
for eid, L in links.items():
    created = next((x for x in L if x["type"] == "entity.created"), L[0])
    ent = Entity(id=eid, name=created["name"], created_by_doc=created.get("doc_id"))
    for x in L:
        if x["pid"] in st.passages and x["pid"] not in ent.passage_ids:
            ent.passage_ids.append(x["pid"])
        if x["doc_id"] not in ent.doc_ids:
            ent.doc_ids.append(x["doc_id"])
        for l in x.get("layers", []):
            ent.layer_counts[l] = ent.layer_counts.get(l, 0) + 1
        if x["name"] != ent.name and x["name"] not in ent.aliases and len(ent.aliases) < 24:
            ent.aliases.append(x["name"])
    dates = [st.passages[p].doc_date for p in ent.passage_ids if p in st.passages]
    if dates:
        ent.first_date, ent.last_date = min(dates), max(dates)
    ents[eid] = ent
# 이벤트에 없는 대상(문장 링크가 없어 병합 대상이 아니었던 것)은 그대로 둠
kept_plain = 0
for eid, e in old_entities.items():
    if eid not in ents:
        ents[eid] = e; kept_plain += 1
st.entities = ents
# 문장 ↔ 대상: 이벤트 링크 + (이벤트 없이 만들어진 대상에 대한) 기존 링크를 합침
pe = defaultdict(list)
for eid, L in links.items():
    for x in L:
        pe[x["pid"]].append(eid)
kept_links = 0
for pid, p in st.passages.items():
    old_ids = [e for e in p.entity_ids if e not in links and e in ents]
    kept_links += len(old_ids)
    p.entity_ids = list(dict.fromkeys(pe.get(pid, []) + old_ids))
print(f"passage links: event-based {sum(len(v) for v in pe.values())}, kept for non-event entities {kept_links}")
# 2) 관계 복원 (자기참조로 삭제된 것도 되살림) -------------------------------------
rel_ev = {e["rid"]: e for e in ev if e["type"] == "graph.relation"}
restored = 0
for rid, e in rel_ev.items():
    if rid in st.relations:
        st.relations[rid].src, st.relations[rid].dst = e["src"], e["dst"]
    elif e["pid"] in st.passages and e["src"] in ents and e["dst"] in ents:
        p = st.passages[e["pid"]]
        st.relations[rid] = Relation(id=rid, src=e["src"], rel=e["rel"], dst=e["dst"], pid=e["pid"], doc_date=p.doc_date, reason="")
        restored += 1
# 3) 사실·기회 복원 ----------------------------------------------------------------
fe = {e["fid"]: e for e in ev if e["type"] == "time.fact"}
for fid, f in st.facts.items():
    if fid in fe:
        f.eid = fe[fid]["eid"]
    f.status, f.related_fact = "new", None
oe = {e["oid"]: e for e in ev if e["type"] == "grid.opportunity"}
name2id = {}
for e in ents.values():
    name2id.setdefault(e.name.lower(), e.id)
    for al in e.aliases:
        name2id.setdefault(al.lower(), e.id)

def to_id(x):
    if not x:
        return None
    if x in ents:
        return x
    return name2id.get(str(x).lower())
miss = 0
for oid, o in st.opps.items():
    if oid in oe:
        x = oe[oid]
        o.eid = x["eid"] if x["eid"] in ents else o.eid
        off = to_id(x.get("offering")) or (o.offering if o.offering in ents else None)
        o.offering = off
        drv = [to_id(d) for d in (x.get("drivers") or [])]
        nds = [to_id(d) for d in (x.get("needs") or [])]
        miss += sum(1 for d in drv + nds if d is None)
        o.drivers = [d for d in dict.fromkeys(drv) if d and d != o.eid] or [d for d in o.drivers if d in ents]
        o.needs = [d for d in dict.fromkeys(nds) if d and d != o.eid] or [d for d in o.needs if d in ents]
print(f"opportunity drivers/needs unresolved names: {miss}")
# 4) 용어 → 대상 링크 재해석 (같은 이름의 대상이 있으면 그것으로)
by_name = {e.name.lower(): e.id for e in ents.values()}
for t in st.terms.values():
    if t.eid and t.eid not in ents:
        t.eid = by_name.get(t.name.lower())
    elif t.eid is None and t.name.lower() in by_name:
        t.eid = by_name[t.name.lower()]
# 5) 연도만 값으로 잡힌 지표 사실 제거 (예: value="2022")
import re
drop = [fid for fid, f in st.facts.items() if f.family == "metric" and re.fullmatch(r"(19|20)\d\d", (f.value or "").strip())]
for fid in drop:
    st.facts.pop(fid)
dang = {"facts": sum(1 for f in st.facts.values() if f.eid not in ents), "opps": sum(1 for o in st.opps.values() if o.eid not in ents),
        "relations": sum(1 for r in st.relations.values() if r.src not in ents or r.dst not in ents)}
print(f"restored: entities {len(old_entities)} → {len(ents)} (unlinked kept {kept_plain}), relations +{restored}, dropped year-valued metric facts {len(drop)}, dangling {dang}")
for fid in [fid for fid, f in st.facts.items() if f.eid not in ents]:
    st.facts.pop(fid)
for rid in [rid for rid, r in st.relations.items() if r.src not in ents or r.dst not in ents]:
    st.relations.pop(rid)
if a.dry:
    sys.exit(0)
# 6) 가드가 들어간 병합 다시 수행 ------------------------------------------------------
llm = LLM()
c = {"entities": merge_entities(st, llm)}
c["facts"] = relink_facts(st)
print("consolidate2:", c)
st.save()
(run / "consolidated2.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
g = build_grid(st, llm); st.save()
print("grid:", {"columns": len(g["columns"]), "cells": len(g["cells"]), "meta": g["meta"]})
gr = build_grid(st, llm, real_only=True, emit=False)
(run / "grid_real.json").write_text(json.dumps(gr, ensure_ascii=False, indent=1), encoding="utf-8")
print("grid_real:", {"columns": len(gr["columns"]), "cells": len(gr["cells"])})
llm.ledger.dump(run / "cost_unmerge.json"); print(f"cost ${llm.ledger.total_usd:.3f}")
print("stats:", json.dumps(st.stats(), ensure_ascii=False)[:400])
