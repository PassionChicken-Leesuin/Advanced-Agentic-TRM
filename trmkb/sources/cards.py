"""
기회 카드 (구조화 JSON) — 사이트·보고서용. worksheets.build_cards 가 생성기용 텍스트를 만든다면, 여기서는 같은 조립 규칙으로
기계가 읽는 카드를 만든다 (why: K3 행 + K2 추세, what: K3 행 + K5 체인, how/resource: K3 행 + K4 관계, 근거: K1 문장).
"""
from __future__ import annotations

from collections import defaultdict

from .store import LAYERS, SourceStore
from .worksheets import MAX_CARDS, _ok, relations_around, themes_for, time_chains


def _row(st, c):
    return {"eid": c["row"], "name": st.entities[c["row"]].name, "relation": c["relation"], "derivation": c["derivation"],
            "strength": c["strength"], "pid": c.get("evidence_pid")}


def build_cards_json(st: SourceStore, *, tree: dict | None = None, grid: dict | None = None, real_only: bool = False,
                     max_cards: int = MAX_CARDS) -> list[dict]:
    grid = grid if grid is not None else st.grid
    tree = tree if tree is not None else st.tree
    if not grid:
        return []
    cells = defaultdict(list)
    for c in grid.get("cells", []):
        cells[c["col"]].append(c)
    out = []
    for col in grid.get("columns", [])[:max_cards]:
        eid = col["eid"]
        ent = st.entities.get(eid)
        if not ent:
            continue
        by_l = defaultdict(list)
        for c in sorted(cells.get(eid, []), key=lambda c: -c["strength"]):
            by_l[c["layer"]].append(c)
        card = {"id": eid, "name": ent.name, "kind": col.get("kind"), "support": col.get("support"), "links": col.get("links"),
                "maturity": col.get("maturity"), "markets": col.get("customers", []), "markets_inferred": col.get("inferred_customers", []),
                "offerings": col.get("offerings", []), "merged": col.get("merged", []),
                **{l: [_row(st, c) for c in by_l.get(l, [])[:8] if c["row"] in st.entities] for l in LAYERS},
                "trend": [], "timing": [], "links_k4": [], "evidence": {}}
        pids = set(ent.passage_ids)
        offerings = {c["row"] for c in by_l.get("what", [])}
        for o in offerings:
            if o in st.entities:
                pids |= set(st.entities[o].passage_ids)
        for t, area in themes_for(st, tree, pids, k=2):
            card["trend"].append({"area": area["name"] if area else None, "area_trend": area.get("trend") if area else None,
                                  "theme": t["name"], "theme_trend": t.get("trend"), "shares": t.get("shares", []),
                                  "summary": t["summary"], "pids": t["pids"][-3:]})
        for subj in [eid] + sorted(offerings):
            if subj not in st.entities:
                continue
            facts = defaultdict(list)
            for f in st.facts.values():
                if f.eid == subj and _ok(st, f.pid, real_only):
                    facts[f.attribute].append(f)
            for a, fs in facts.items():
                fs.sort(key=lambda f: f.stated_on)
                card["timing"].append({"subject": st.entities[subj].name, "attribute": a, "family": fs[-1].family,
                                       "chain": [{"value": f.value, "unit": f.unit, "valid": f.valid_start, "stated": f.stated_on.isoformat(),
                                                  "modality": f.modality, "status": f.status, "fid": f.id, "pid": f.pid} for f in fs]})
        for ln, rp in relations_around(st, {eid} | offerings, real_only, limit=10):
            pass
        for r in st.relations.values():
            if _ok(st, r.pid, real_only) and (r.src in ({eid} | offerings) or r.dst in ({eid} | offerings)) and r.src in st.entities and r.dst in st.entities:
                card["links_k4"].append({"src": st.entities[r.src].name, "rel": r.rel, "dst": st.entities[r.dst].name, "pid": r.pid})
        card["links_k4"] = card["links_k4"][:12]
        cited = {x["pid"] for l in LAYERS for x in card[l] if x["pid"]} | {p for t in card["trend"] for p in t["pids"]} \
            | {s["pid"] for t in card["timing"] for s in t["chain"]} | {x["pid"] for x in card["links_k4"]}
        for pid in cited:
            p = st.passages.get(pid)
            if p:
                card["evidence"][pid] = {"text": p.text, "claim": p.claim, "doc_id": p.doc_id, "date": p.doc_date.isoformat(),
                                         "source_type": p.source_type, "synthetic": p.is_synthetic, "layers": p.layers}
        out.append(card)
    return out
