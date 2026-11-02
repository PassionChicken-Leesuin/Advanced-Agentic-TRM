"""
작업지 (worksheet) — 생성기는 지식베이스를 텍스트 한 덩어리로 받지 않고, 코드가 구조에서 기계적으로 뽑은 요약표를 받는다.

2026-11-02 확정: 작업지의 앞부분은 **기회 카드**다. Cambridge 2014 보고서(26~27쪽)가 기회마다 토픽 로드맵(시장 행·제품 행·기술 행)을
그렸듯, 기회(K3 열) 하나마다 다섯 구조에서 그 기회에 관한 것을 모아 한 장으로 조립한다:
  시장·동인(why)  ← K3 why 행 + K2 (그 기회의 문장이 속한 주제·영역의 추세)
  제공물(what)    ← K3 what 행 (구체 제품)  + K5 (제공물·기회의 시점 체인)
  역량·자원(how/resource) ← K3 how·resource 행 + K4 (제공물·기회에서 1단계 관계)
  근거            ← K1 (위에 나온 문장 id)
구조 간 연결이 생성기의 해석이 아니라 코드에 고정되고, 어느 구조가 카드의 어느 줄을 댔는지가 그대로 추적된다.
카드 뒤에는 구조별 나머지 (K2 전체·영역 요약, 카드에 안 든 K4 관계·K5 체인, K1 근거 문장) 가 온다.
구조를 빼면 카드에서 그 구조의 줄이 빠지고 그 구조의 구조별 절도 빠진다. 글자 예산은 K1 근거 문장에 넘어간다.
K3 를 빼면 카드의 기준(열)이 없으므로 지지 문서 수 상위 대상을 카드 기준으로 쓴다.
K0 용어 범례는 공통 골격이라 모든 조건에 붙는다 (별도 예산).
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md §5
"""
from __future__ import annotations

from collections import defaultdict

from ..roadmap.retrieve import Context
from ..schema import RoadmapOp
from .store import LAYERS, SourceStore

STRUCTS = ("grid", "tree", "graph", "time", "evidence")
BUDGET = {"grid": 14000, "tree": 11000, "graph": 11000, "time": 16000, "evidence": 18000}
GLOSSARY_BUDGET = 1800
OP = {"evidence": RoadmapOp.GROUNDING, "tree": RoadmapOp.TREND, "grid": RoadmapOp.OPPORTUNITY,
      "graph": RoadmapOp.LINK, "time": RoadmapOp.TIMING}
NAME = {"grid": "K3 opportunity linkage grid", "tree": "K2 theme summary tree", "graph": "K4 dependency graph",
        "time": "K5 temporal knowledge graph", "evidence": "K1 evidence store"}
FORWARD = {"planned", "forecast", "required", "vision"}
MAX_CARDS = 10


def budgets(structures: set[str]) -> dict[str, int]:
    b = {s: BUDGET[s] for s in STRUCTS if s in structures}
    spare = sum(BUDGET[s] for s in STRUCTS if s not in structures)
    if "evidence" in b:
        b["evidence"] += spare
    elif b:
        tot = sum(b.values())
        for s in b:
            b[s] += int(spare * b[s] / tot)
    return b


class _W:
    """구조 하나의 글자 예산. 줄을 쌓고(add) 또는 다른 곳(카드)에 쓴 줄의 글자만 셈하며(charge), 줄에 나온 문장 id 를 구조 연산으로 태그한다."""

    def __init__(self, ctx: Context, struct: str, budget: int, header: str):
        self.ctx, self.s, self.budget = ctx, struct, budget
        self.lines = [f"## {NAME[struct]}", header]
        self.used = len(header) + 40
        self.pids: list[str] = []
        self.card_chars = 0

    def charge(self, line: str, pids=()) -> bool:
        if self.used + len(line) + 1 > self.budget:
            return False
        self.used += len(line) + 1
        self.card_chars += len(line) + 1
        for p in pids:
            if p:
                self.ctx.tag(p, OP[self.s])
                if self.s == "grid":
                    self.ctx.tag(p, RoadmapOp.PRIORITY)
                if p not in self.pids:
                    self.pids.append(p)
        return True

    def add(self, line: str, pids=()) -> bool:
        if not self.charge(line, pids):
            return False
        self.card_chars -= len(line) + 1
        self.lines.append(line)
        return True

    @property
    def text(self) -> str:
        return "\n".join(self.lines) if len(self.lines) > 2 else ""


def _ok(st: SourceStore, pid: str | None, real_only: bool) -> bool:
    p = st.passages.get(pid) if pid else None
    return bool(p) and p.status not in ("irrelevant", "duplicate") and not (real_only and p.is_synthetic)


def focus_subjects(st: SourceStore, grid: dict | None, real_only: bool, use_grid: bool, n: int = 45) -> list[str]:
    out: list[str] = []
    if use_grid and grid:
        out += [c["eid"] for c in grid.get("columns", [])]
        rows = [r for l in ("what", "why", "how", "resource") for r in grid.get("rows", {}).get(l, [])]
        rows.sort(key=lambda r: (-r["links"], -r["strength_sum"]))
        out += [r["eid"] for r in rows[:30]]
    per = defaultdict(list)
    for e in st.entities.values():
        if e.layer:
            per[e.layer].append((st.support(e.id, real_only=real_only), e.id))
    for l in per:
        per[l].sort(reverse=True)
    i = 0
    while len(dict.fromkeys(out)) < n and any(i < len(v) for v in per.values()):
        for l in LAYERS:
            if i < len(per.get(l, [])) and per[l][i][0] > 0:
                out.append(per[l][i][1])
        i += 1
    return list(dict.fromkeys(out))[:n]


# ----------------------------------------------------------------------------- 공통 조각
def time_chains(st, eid, real_only, max_attrs=6):
    """대상 하나의 속성별 체인 문자열 [(line, pids)]. 마지막 항목이 최신."""
    facts = defaultdict(list)
    for f in st.facts.values():
        if f.eid == eid and _ok(st, f.pid, real_only):
            facts[f.attribute].append(f)
    out = []
    for a in sorted(facts, key=lambda a: -max(f.stated_on.toordinal() for f in facts[a]))[:max_attrs]:
        fs = sorted(facts[a], key=lambda f: f.stated_on)
        dup = sum(1 for f in fs if f.status == "duplicate")
        fs = [f for f in fs if f.status != "duplicate"][-4:] or fs[-1:]
        chain = " -> ".join(
            f"\"{f.value}\"" + (f" {f.unit}" if f.unit and f.unit not in f.value else "")
            + f" @{'' if f.valid_start is None else round(f.valid_start, 2)} ({f.stated_on}, {f.modality}"
            + (f", {f.status.upper()} of {f.related_fact}" if f.status in ("update", "conflict") else "") + f") [{f.id}, {f.pid}]"
            for f in fs)
        fam = fs[-1].family
        out.append((f"{a} ({fam}): {chain}" + (f" (+{dup} repeats)" if dup else ""), [f.pid for f in fs]))
    return out


def relations_around(st, anchors: set[str], real_only, limit=10):
    trip = defaultdict(list)
    for r in st.relations.values():
        if _ok(st, r.pid, real_only) and (r.src in anchors or r.dst in anchors):
            trip[(r.src, r.rel, r.dst)].append(r.pid)
    order = sorted(trip, key=lambda t: -len(trip[t]))[:limit]
    return [(f"{st.entities[s].name} --{rel}--> {st.entities[d].name} [{', '.join(trip[(s, rel, d)][:2])}]", trip[(s, rel, d)][:2])
            for (s, rel, d) in order if s in st.entities and d in st.entities]


def themes_for(st, tree, pids: set[str], k=2):
    """문장 집합과 가장 많이 겹치는 주제 k개와 그 영역."""
    if not tree:
        return []
    amap = {t: a for a in tree.get("areas", []) for t in a["theme_ids"]}
    scored = []
    for t in tree.get("themes", []):
        ov = len(pids & set(t["pids"]))
        if ov:
            scored.append((ov, t))
    scored.sort(key=lambda x: -x[0])
    return [(t, amap.get(t["id"])) for _, t in scored[:k]]


# ----------------------------------------------------------------------------- 기회 카드
def build_cards(st, ctx, structures, tree, grid, focus, real_only, W: dict) -> tuple[list[str], set[str], set[str], set[str]]:
    """카드 텍스트, 카드 기준 eid, 카드에 쓴 열 eid, 카드에 쓴 (대상) eid 집합을 돌려준다. 글자는 각 구조의 예산에서 찬다."""
    lines: list[str] = []
    use_grid = "grid" in structures and bool(grid)
    if use_grid:
        anchors = [c for c in grid.get("columns", [])][:MAX_CARDS]
        anchor_ids = [c["eid"] for c in anchors]
    else:
        anchor_ids = [e for e in focus if e in st.entities][:8]
        anchors = [{"eid": e, "name": st.entities[e].name, "support": st.support(e, real_only=real_only)} for e in anchor_ids]
    cells = defaultdict(list)
    if use_grid:
        for c in grid.get("cells", []):
            cells[c["col"]].append(c)
    used_subjects: set[str] = set()
    hdr = ("## Opportunity cards (one per opportunity, assembled from the structures present: market & drivers (why) <- K3 rows + "
           "K2 trend; offerings (what) <- K3 rows + K5 timing chains; capabilities & enablers (how/resource) <- K3 rows + K4 relations; "
           "evidence <- K1 ids. Each card is a candidate vertical slice of the roadmap.)")
    lines.append(hdr)
    for k, a in enumerate(anchors, 1):
        eid = a["eid"]
        ent = st.entities.get(eid)
        if not ent:
            continue
        head = f"\n### Card {k}: {ent.name} ({eid})"
        if use_grid:
            head += (f" | {a.get('kind', '')} | {a.get('support')} docs | maturity {a.get('maturity')} | links {a.get('links')}")
            if a.get("customers"):
                head += " | markets: " + ", ".join(a["customers"][:4])
            elif a.get("inferred_customers"):
                head += " | markets (inferred from same documents): " + ", ".join(a["inferred_customers"][:3])
            else:
                head += " | markets: unspecified"
            w = W["grid"]
        else:
            head += f" | {a.get('support')} docs (anchor by document support; no opportunity grid in this condition)"
            w = W["evidence"] if "evidence" in W else next(iter(W.values()))
        if not w.charge(head):
            break
        lines.append(head)
        used_subjects.add(eid)
        offerings: set[str] = set()
        by_l = defaultdict(list)
        for c in sorted(cells.get(eid, []), key=lambda c: -c["strength"]):
            by_l[c["layer"]].append(c)
        # why: K3 행 + K2 추세
        if use_grid and by_l.get("why"):
            items = by_l["why"][:6]
            ln = "  why (K3): " + "; ".join(f"{st.entities[c['row']].name} [{c['relation']}, {c['derivation']}, {c['strength']}, {c['evidence_pid'] or '-'}]" for c in items)
            if W["grid"].charge(ln, [c["evidence_pid"] for c in items]):
                lines.append(ln)
            used_subjects |= {c["row"] for c in items}
        if "tree" in W and tree:
            pids = set(ent.passage_ids)
            for c in by_l.get("what", []):
                if c["row"] in st.entities:
                    pids |= set(st.entities[c["row"]].passage_ids)
            for t, area in themes_for(st, tree, pids):
                sh = ", ".join(f"{r['year']} {round(r['share'] * 100)}%" for r in t.get("shares", [])[-4:])
                ex = t["pids"][-2:]
                ln = (f"  trend (K2): area \"{area['name'] if area else '-'}\" ({area.get('trend') if area else '-'}); theme \"{t['name']}\" "
                      f"({t['trend']}, doc share {sh}): {t['summary'][:200]} [{', '.join(ex)}]")
                if W["tree"].charge(ln, ex):
                    lines.append(ln)
        # what: K3 제공물 행 + K5 체인
        if use_grid and by_l.get("what"):
            items = by_l["what"][:5]
            offerings |= {c["row"] for c in items}
            ln = "  what (K3): " + "; ".join(f"{st.entities[c['row']].name} [{c['relation']}, {c['derivation']}, {c['strength']}, {c['evidence_pid'] or '-'}]" for c in items)
            if W["grid"].charge(ln, [c["evidence_pid"] for c in items]):
                lines.append(ln)
        if "time" in W:
            n = 0
            for subj in [eid] + sorted(offerings):
                for ln0, pids in time_chains(st, subj, real_only, max_attrs=4):
                    ln = f"  timing (K5) {st.entities[subj].name}: {ln0}"
                    if W["time"].charge(ln, pids):
                        lines.append(ln); n += 1
                    if n >= 6:
                        break
                if n >= 6:
                    break
        # how / resource: K3 행 + K4 관계
        for l in ("how", "resource"):
            if use_grid and by_l.get(l):
                items = by_l[l][:6]
                ln = f"  {l} (K3): " + "; ".join(f"{st.entities[c['row']].name} [{c['relation']}, {c['derivation']}, {c['strength']}, {c['evidence_pid'] or '-'}]" for c in items)
                if W["grid"].charge(ln, [c["evidence_pid"] for c in items]):
                    lines.append(ln)
                used_subjects |= {c["row"] for c in items}
        if "graph" in W:
            for ln0, pids in relations_around(st, {eid} | offerings, real_only, limit=8):
                ln = f"  link (K4): {ln0}"
                if W["graph"].charge(ln, pids):
                    lines.append(ln)
        used_subjects |= offerings
    return lines, set(anchor_ids), used_subjects


# ----------------------------------------------------------------------------- 구조별 나머지 절
def ws_grid(st, ctx, grid, w, skip_cols: set[str]):
    w.lines[1] = "(remaining columns not shown as cards; each row link: layer: item [relation, direct|derived, strength, evidence id])"
    cells = defaultdict(list)
    for c in grid.get("cells", []):
        cells[c["col"]].append(c)
    k = 0
    for col in grid.get("columns", []):
        if col["eid"] in skip_cols:
            continue
        k += 1
        meta = f"C{k} {col['name']} ({col['eid']}) | {col['support']} docs | maturity {col.get('maturity')} | links {col['links']}"
        if col.get("customers"):
            meta += " | markets: " + ", ".join(col["customers"][:4])
        if col.get("offerings"):
            meta += " | offerings: " + ", ".join(col["offerings"][:4])
        if not w.add(meta):
            break
        cs = sorted(cells[col["eid"]], key=lambda c: (LAYERS.index(c["layer"]) if c["layer"] in LAYERS else 9, -c["strength"]))
        by_l = defaultdict(list)
        for c in cs:
            by_l[c["layer"]].append(c)
        for l in LAYERS:
            items = by_l.get(l, [])[:6]
            if items:
                txt = "; ".join(f"{st.entities[c['row']].name} [{c['relation']}, {c['derivation']}, {c['strength']}, {c['evidence_pid'] or '-'}]" for c in items)
                w.add(f"  {l}: {txt}", [c["evidence_pid"] for c in items])
    return w


def ws_tree(st, ctx, tree, w):
    w.lines[1] = ("(root summary, then areas with document-share by year, yearly lines and their themes; trend = rising|stable|declining|new, "
                  "computed from the share of documents per year that touch the area, then checked by the summarizer)")
    root = tree.get("root", {})
    w.add("Root: " + root.get("summary", ""))
    for s in root.get("shifts", []):
        w.add(f"- shift: {s}")
    tmap = {t["id"]: t for t in tree.get("themes", [])}
    for a in tree.get("areas", []):
        sh = ", ".join(f"{r['year']} {round(r['share'] * 100)}%" for r in a.get("shares", []))
        if not w.add(f"\n### Area: {a['name']} ({a.get('passages', 0)} passages, {a.get('support', 0)} docs, trend {a.get('trend')}; doc share {sh})"):
            break
        w.add(a.get("summary", ""))
        per = "; ".join(f"{x['year']}: {x['line']}" for x in a.get("periods", [])[-5:])
        if per:
            w.add("yearly: " + per)
        ths = sorted((tmap[i] for i in a["theme_ids"] if i in tmap), key=lambda t: -t["support"])[:6]
        for t in ths:
            ex = [p for p in t["pids"][-2:]]
            w.add(f"- theme {t['name']} ({t['passages']} passages, {t['trend']}): {t['summary'][:220]} [{', '.join(ex)}]", ex)
    return w


def ws_graph(st, ctx, focus, real_only, w, skip: set[str]):
    w.lines[1] = "(relations stated in documents between subjects not covered by the cards: src --relation--> dst [evidence ids])"
    rank = {e: i for i, e in enumerate(focus)}
    trip = defaultdict(list)
    for r in st.relations.values():
        if _ok(st, r.pid, real_only) and (r.src in rank or r.dst in rank) and not (r.src in skip or r.dst in skip):
            trip[(r.src, r.rel, r.dst)].append(r.pid)
    order = sorted(trip, key=lambda t: (min(rank.get(t[0], 999), rank.get(t[2], 999)), -len(trip[t])))
    by_anchor = defaultdict(list)
    for t in order:
        a = t[0] if rank.get(t[0], 999) <= rank.get(t[2], 999) else t[2]
        by_anchor[a].append(t)
    for a in sorted(by_anchor, key=lambda e: rank.get(e, 999)):
        if not w.add(f"{st.entities[a].name} ({a}):"):
            break
        for (s, rel, d) in by_anchor[a][:8]:
            pids = trip[(s, rel, d)][:2]
            if not w.add(f"  - {st.entities[s].name} --{rel}--> {st.entities[d].name} [{', '.join(pids)}]", pids):
                break
    return w


def ws_time(st, ctx, focus, real_only, w, skip: set[str]):
    w.lines[1] = ("(subjects not covered by the cards; per subject and attribute, statements in the order they were made: \"value\" @valid-time "
                  "(stated date, modality[, UPDATE/CONFLICT of fact]) [fact id, evidence id]; the last one is the latest)")
    subjects = {f.eid for f in st.facts.values() if _ok(st, f.pid, real_only)} - skip
    rank = {e: i for i, e in enumerate(focus)}

    def fwd(e):
        return sum(1 for f in st.facts.values() if f.eid == e and (f.modality in FORWARD or (f.valid_end or 0) >= 2024.5))
    for e in sorted(subjects, key=lambda e: (0 if e in rank and fwd(e) else 1 if fwd(e) else 2, rank.get(e, 999), -fwd(e))):
        if e not in st.entities or not w.add(f"{st.entities[e].name} ({e}):"):
            break
        for ln, pids in time_chains(st, e, real_only):
            if not w.add(f"  - {ln}", pids):
                break
    return w


def ws_evidence(st, ctx, focus, real_only, w, cited: list[str]):
    chosen: list[str] = [p for p in dict.fromkeys(cited) if _ok(st, p, real_only)]
    for e in focus:
        if e not in st.entities:
            continue
        ps = [p for p in st.passages_of(e, real_only=real_only) if p.status not in ("irrelevant", "duplicate")]
        ps.sort(key=lambda p: (0 if p.modality in FORWARD else 1, -p.doc_date.toordinal()))
        docs = set()
        for p in ps:
            if p.doc_id in docs:
                continue
            docs.add(p.doc_id); chosen.append(p.id)
            if len(docs) >= 4:
                break
    rest = sorted((p for p in st.passages.values() if _ok(st, p.id, real_only) and p.routed),
                  key=lambda p: (0 if p.modality in FORWARD else 1, -len(p.entity_ids), -p.doc_date.toordinal()))
    chosen += [p.id for p in rest[:600]]
    chosen = list(dict.fromkeys(chosen))
    by_l = defaultdict(list)
    for pid in chosen:
        p = st.passages[pid]
        by_l[p.layers[0] if p.layers else "what"].append(p)

    def line(p):
        subs = ", ".join(st.entities[e].name for e in p.entity_ids[:3] if e in st.entities)
        return f"- {p.id} ({p.doc_date}, {p.source_type}{', internal' if p.is_synthetic else ''}) {{{subs}}}: {p.statement[:230]}"
    # 층마다 돌아가며 채움 (먼저 고른 것 = 카드·다른 작업지가 인용한 것 우선)
    idx = {l: 0 for l in LAYERS}
    blocks = {l: [] for l in LAYERS}
    full = False
    base = w.used
    while not full and any(idx[l] < len(by_l[l]) for l in LAYERS):
        for l in LAYERS:
            if idx[l] < len(by_l[l]):
                p = by_l[l][idx[l]]; idx[l] += 1
                ln = line(p)
                if w.used + len(ln) + 20 > w.budget:
                    full = True
                    break
                blocks[l].append((ln, p.id)); w.used += len(ln) + 1
    w.used = base
    for l in LAYERS:
        if blocks[l]:
            w.add(f"### {l}")
            for ln, pid in blocks[l]:
                w.add(ln, [pid])
    return w


def glossary_legend(st, max_chars=GLOSSARY_BUDGET) -> str:
    if not st.terms:
        return ""
    parts = ["## K0 glossary (canonical names used throughout; metric [unit, direction]; product generations in order)"]
    for typ in ("metric", "product", "stage", "application", "technology", "organization", "program"):
        ts = st.terms_by_type(typ, confirmed_only=True)      # 범례에는 확정 용어만
        if not ts:
            continue
        if typ == "product":
            ts = sorted(ts, key=lambda t: (t.order is None, t.order or 0, -t.count))
        items = []
        for t in ts[:14]:
            s = t.name + (f" (aka {', '.join(t.aliases[:2])})" if t.aliases else "")
            if typ == "metric" and t.unit:
                s += f" [{t.unit}{', ' + t.direction if t.direction and t.direction != 'none' else ''}]"
            if typ == "product" and t.order is not None:
                s += f" (gen {t.order})"
            items.append(s)
        parts.append(f"- {typ}: " + "; ".join(items))
    txt = "\n".join(parts)
    return txt[:max_chars]


def build_worksheets(st: SourceStore, structures: set[str], *, tree: dict | None = None, grid: dict | None = None,
                     real_only: bool = False, label: str = "") -> Context:
    ctx = Context(text="")
    b = budgets(structures)
    grid = grid if grid is not None else st.grid
    tree = tree if tree is not None else st.tree
    focus = focus_subjects(st, grid, real_only, use_grid="grid" in structures)
    W = {}
    if "grid" in structures and grid:
        W["grid"] = _W(ctx, "grid", b["grid"], "")
    if "tree" in structures and tree:
        W["tree"] = _W(ctx, "tree", b["tree"], "")
    if "graph" in structures:
        W["graph"] = _W(ctx, "graph", b["graph"], "")
    if "time" in structures:
        W["time"] = _W(ctx, "time", b["time"], "")
    if "evidence" in structures:
        W["evidence"] = _W(ctx, "evidence", b["evidence"], "(source passages quoted from documents, grouped by layer tag; cite them by id; "
                                                           "'internal' marks internal company documents)")
    card_lines, anchors, used = build_cards(st, ctx, structures, tree, grid, focus, real_only, W)
    if "grid" in W:
        ws_grid(st, ctx, grid, W["grid"], anchors)
    if "tree" in W:
        ws_tree(st, ctx, tree, W["tree"])
    if "graph" in W:
        ws_graph(st, ctx, focus, real_only, W["graph"], used)
    if "time" in W:
        ws_time(st, ctx, focus, real_only, W["time"], used)
    if "evidence" in W:
        cited = [p for k in ("grid", "time", "graph", "tree") if k in W for p in W[k].pids]
        ws_evidence(st, ctx, focus, real_only, W["evidence"], cited)
    order = [s for s in STRUCTS if s in W]
    head = (f"(context condition {label or '+'.join(order)}{' real-only' if real_only else ''}: knowledge structures "
            f"{', '.join(NAME[s] for s in order)}; {len(anchors)} opportunity cards)")
    legend = glossary_legend(st)
    parts = [head] + ([legend] if legend else []) + (["\n".join(card_lines)] if len(card_lines) > 1 else []) + [W[s].text for s in order if W[s].text]
    ctx.text = "\n\n".join(parts)
    ctx.selected_node_ids = focus
    ctx.stats = {"condition": label, "structures": order, "real_only": real_only, "chars": len(ctx.text), "cards": len(anchors),
                 "chars_cards": sum(len(x) + 1 for x in card_lines), "chars_glossary": len(legend),
                 "chars_by_structure": {s: W[s].used for s in order}, "card_chars_by_structure": {s: W[s].card_chars for s in order},
                 "pids_by_structure": {s: len(W[s].pids) for s in order}, "budgets": b, "focus_subjects": len(focus)}
    return ctx
