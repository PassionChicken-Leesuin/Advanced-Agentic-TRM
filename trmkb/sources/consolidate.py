"""
마무리 정리 단계 (2026-11-02 확정) — 들어온 순서 때문에 갈라진 것을 전체를 보고 합친다.
  1) 공유 대상 병합: 이름·별칭 임베딩으로 후보 쌍만 추리고(느슨한 문턱), 합칠지는 LLM 이 두 대상의 이름·별칭·층·대표 문장을 보고 판단.
     기회(K3 열)도 대상이므로 여기서 함께 처리됨 (그리드 안의 임베딩 병합은 없음).
  2) 주제 병합: 같은 방식 (이름·요약·대표 문장).
  3) K5 체인 재연결: 병합 뒤 같은 대상·속성의 사실을 진술 날짜 순으로 다시 보고, 코드가 상태(update / duplicate / conflict)를 보정.
     추출기가 호출 때 보지 못한 사실(다른 이름으로 갈라져 있던 것)에 대한 안전망.
임베딩 문턱은 후보를 넓게 잡는 용도라 결과를 정하지 않음. 결정은 LLM 의 판단과 이유로 남는다.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from pydantic import BaseModel, Field

from ..agents.embed import embed
from ..llm import LLM
from .store import SourceStore

MODEL = "openai/gpt-4.1-mini"
PART_WORDS = ("part of", "component", "includes", "broader", "subset", "enables", "generation of", "version of", "used in", "instance of")


class Pair(BaseModel):
    a: str
    b: str
    same: bool
    name: str = ""
    reason: str = ""


class Pairs(BaseModel):
    pairs: list[Pair] = Field(default_factory=list)


ENT_SYS = "You curate the subject index of a technology-roadmapping knowledge base about IonQ. JSON only."
ENT_USER = """Each candidate pair below names two subjects that MAY be the same thing under different names. Decide for each pair
whether they are the SAME subject (same product, technology, organization, application or requirement), so that their
statements should be merged, or DIFFERENT (e.g. a product vs its generation, a system vs a component, a company vs its
service, a broad area vs a specific application or technology inside it). "A is part of B", "A enables B", "A is a
component of B" all mean DIFFERENT. Small differences can matter: keep them apart when the roadmap would place them in
different boxes. SAME only for the same thing under another name or spelling. For SAME pairs give the canonical name to keep.

{pairs}

Return JSON: {{"pairs": [{{"a": id, "b": id, "same": bool, "name": str, "reason": str (under 15 words)}}]}}"""

THEME_SYS = "You curate the theme tree of a technology-roadmapping knowledge base about IonQ. JSON only."
THEME_USER = """Each candidate pair below names two themes that MAY be the same strategic thread. Decide whether they should be ONE
theme (same thread, split only by wording or by the order documents arrived) or stay SEPARATE (different roadmap rows;
e.g. "error correction roadmap" vs "error mitigation software", "networking expansion" vs "modular architecture").
For merged pairs give the theme name to keep.

{pairs}

Return JSON: {{"pairs": [{{"a": id, "b": id, "same": bool, "name": str, "reason": str (under 15 words)}}]}}"""


def _candidates(ids: list[str], texts: list[str], sim: float, per: int = 3) -> list[tuple[str, str, float]]:
    if len(ids) < 2:
        return []
    v = embed(texts)
    s = v @ v.T
    np.fill_diagonal(s, -1)
    out, seen = [], set()
    for i, a in enumerate(ids):
        for j in np.argsort(-s[i])[:per]:
            if s[i, j] >= sim:
                key = tuple(sorted((a, ids[j])))
                if key not in seen:
                    seen.add(key); out.append((key[0], key[1], float(s[i, j])))
    return sorted(out, key=lambda x: -x[2])


def _ask(llm: LLM, model: str, system: str, template: str, blocks: list[tuple[str, str, str]], batch: int = 16,
         workers: int = 6) -> dict[tuple, Pair]:
    """쌍 판정을 16쌍씩 묶어 병렬 호출 (묶음 사이에 의존이 없음). 결과는 묶음 순서대로 합침."""
    chunks = [blocks[i:i + batch] for i in range(0, len(blocks), batch)]

    def job(chunk):
        txt = "\n\n".join(f"PAIR {k + 1}\n  a = {a}\n  b = {b}" for k, (a, b, _) in enumerate(chunk))
        return llm.structured(model, system, template.format(pairs=txt), Pairs, purpose="consolidate", max_tokens=3000)
    out = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks)))) as ex:
        for chunk, res in zip(chunks, ex.map(job, chunks)):
            ids = {(blk[2][0], blk[2][1]) for blk in chunk}
            for p in res.pairs:
                if (p.a, p.b) in ids:
                    out[(p.a, p.b)] = p
                elif (p.b, p.a) in ids:
                    out[(p.b, p.a)] = Pair(a=p.b, b=p.a, same=p.same, name=p.name, reason=p.reason)
    return out


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# --------------------------------------------------------------------------- 1) 공유 대상 병합
def merge_entities(st: SourceStore, llm: LLM, *, sim: float = 0.72, model: str = MODEL, emit: bool = True, max_group: int = 6) -> dict:
    ents = [e for e in st.entities.values() if e.passage_ids]
    ids = [e.id for e in ents]
    texts = [" / ".join([e.name] + e.aliases[:3]) for e in ents]
    cands = _candidates(ids, texts, sim)

    def desc(eid):
        e = st.entities[eid]
        last = [st.passages[i] for i in e.passage_ids[-2:] if i in st.passages]
        stm = " || ".join(f"({p.doc_date}) {p.statement[:120]}" for p in last)
        return f"{eid} | {e.name}" + (f" (aka {', '.join(e.aliases[:3])})" if e.aliases else "") + f" | layer {e.layer} | {len(e.passage_ids)} passages | {stm}"
    # K0 종류가 다른 대상(예: 응용 "Quantum Networking" 과 기술 "Photonic Interconnect")은 후보에서 제외
    ttype = {}
    for t in st.terms.values():
        if t.eid and t.status != "rejected":
            ttype[t.eid] = t.type
    cands = [(a, b, s) for a, b, s in cands if not (ttype.get(a) and ttype.get(b) and ttype[a] != ttype[b])]
    blocks = [(desc(a), desc(b), (a, b)) for a, b, _ in cands]
    decisions = _ask(llm, model, ENT_SYS, ENT_USER, blocks) if blocks else {}
    uf = _UF()
    names = {}
    # 가드 1) K0 확정 용어가 다른 두 대상은 다른 것 (예: IonQ Aria 와 IonQ Forte 는 둘 다 제품 용어) — 그룹 단위로 검사해
    #         A~B, B~C 식의 연쇄로 두 용어가 한 그룹에 들어오는 것도 막는다.
    # 가드 2) 허브 상한: 한 그룹이 max_group 을 넘으면 더 합치지 않는다 (포괄 대상에 여러 구체 대상이 연쇄로 빨려 들어가는 것 방지).
    term_of = {}
    by_name = {}
    for t in st.terms.values():
        if t.status == "confirmed":
            by_name[t.name.lower()] = t.name
            if t.eid:
                term_of[t.eid] = t.name
    for e in ents:
        if e.id not in term_of and e.name.lower() in by_name:
            term_of[e.id] = by_name[e.name.lower()]
    gterms: dict[str, set] = defaultdict(set)
    gsize: dict[str, int] = {}
    blocked = {"k0": 0, "hub": 0}
    ordered = sorted(decisions.items(), key=lambda kv: -next((s for a, b, s in cands if (a, b) == kv[0]), 0.0))
    for (a, b), d in ordered:
        # 이유가 포함·부분 관계를 말하면 '같은 것'이 아님 (모델이 same 이라 해도 뒤집음)
        if d.same and any(w in d.reason.lower() for w in PART_WORDS):
            d.same = False; d.reason = "kept apart: " + d.reason
        if not d.same:
            continue
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        ta = gterms[ra] | ({term_of[a]} if a in term_of else set())
        tb = gterms[rb] | ({term_of[b]} if b in term_of else set())
        if len(ta | tb) > 1:
            d.same = False; d.reason = "kept apart (K0 terms differ): " + d.reason; blocked["k0"] += 1
            continue
        if gsize.get(ra, 1) + gsize.get(rb, 1) > max_group:
            d.same = False; d.reason = "kept apart (group cap): " + d.reason; blocked["hub"] += 1
            continue
        uf.union(a, b)
        r = uf.find(a)
        gterms[r] = ta | tb
        gsize[r] = gsize.get(ra, 1) + gsize.get(rb, 1)
        names[r] = d.name or names.get(r, "")
    groups = defaultdict(list)
    for e in ids:
        if e in uf.p:
            groups[uf.find(e)].append(e)
    remap: dict[str, str] = {}
    merged = 0
    for root, members in groups.items():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda e: len(st.entities[e].passage_ids))
        k = st.entities[keep]
        for m in members:
            if m == keep:
                continue
            o = st.entities[m]
            for n in [o.name] + o.aliases:
                if n not in k.aliases and n != k.name and len(k.aliases) < 24:
                    k.aliases.append(n)
            for pid in o.passage_ids:
                if pid not in k.passage_ids:
                    k.passage_ids.append(pid)
            for d in o.doc_ids:
                if d not in k.doc_ids:
                    k.doc_ids.append(d)
            for l, c in o.layer_counts.items():
                k.layer_counts[l] = k.layer_counts.get(l, 0) + c
            for l, c in o.kind_counts.items():
                k.kind_counts[l] = k.kind_counts.get(l, 0) + c
            k.first_date = min(filter(None, [k.first_date, o.first_date]), default=k.first_date)
            k.last_date = max(filter(None, [k.last_date, o.last_date]), default=k.last_date)
            remap[m] = keep
            merged += 1
        nm = names.get(root)
        if nm and nm.strip() and nm.strip() != k.name:
            if k.name not in k.aliases:
                k.aliases.append(k.name)
            k.name = nm.strip()
        if emit:
            d0 = next((d for (a, b), d in decisions.items() if uf.find(a) == root and d.same), None)
            st.emit("entity.merged", keep=keep, name=k.name, merged=[st.entities[m].name for m in members if m != keep],
                    reason=d0.reason if d0 else "")
    if remap:
        for p in st.passages.values():
            p.entity_ids = list(dict.fromkeys(remap.get(e, e) for e in p.entity_ids))
        for r in st.relations.values():
            r.src, r.dst = remap.get(r.src, r.src), remap.get(r.dst, r.dst)
        for f in st.facts.values():
            f.eid = remap.get(f.eid, f.eid)
        for o in st.opps.values():
            o.eid = remap.get(o.eid, o.eid)
            o.offering = remap.get(o.offering, o.offering) if o.offering else None
            o.drivers = list(dict.fromkeys(remap.get(e, e) for e in o.drivers if remap.get(e, e) != o.eid))
            o.needs = list(dict.fromkeys(remap.get(e, e) for e in o.needs if remap.get(e, e) != o.eid))
        for t in st.terms.values():
            if t.eid:
                t.eid = remap.get(t.eid, t.eid)
        for m in remap:
            st.entities.pop(m, None)
        # 자기 자신을 가리키게 된 관계 제거
        for rid in [r.id for r in st.relations.values() if r.src == r.dst]:
            st.relations.pop(rid)
    return {"candidate_pairs": len(cands), "same": sum(1 for d in decisions.values() if d.same), "merged_entities": merged, "blocked": blocked}


# --------------------------------------------------------------------------- 2) 주제 병합
def merge_themes(st: SourceStore, llm: LLM, *, sim: float = 0.70, model: str = MODEL, emit: bool = True) -> dict:
    ths = [t for t in st.themes.values() if t.passage_ids]
    ids = [t.id for t in ths]

    def sample(t, n=2):
        ps = [st.passages[i] for i in t.passage_ids if i in st.passages]
        return " || ".join(p.statement[:110] for p in ps[:n])
    texts = [f"{t.name}. {t.summary[:200] if t.summary else sample(t)}" for t in ths]
    cands = _candidates(ids, texts, sim)
    blocks = [(f"{a} | {st.themes[a].name} | {len(st.themes[a].passage_ids)} passages | {sample(st.themes[a])}",
               f"{b} | {st.themes[b].name} | {len(st.themes[b].passage_ids)} passages | {sample(st.themes[b])}", (a, b)) for a, b, _ in cands]
    decisions = _ask(llm, model, THEME_SYS, THEME_USER, blocks) if blocks else {}
    uf, names = _UF(), {}
    for (a, b), d in decisions.items():
        if d.same:
            uf.union(a, b); names[uf.find(a)] = d.name or names.get(uf.find(a), "")
    groups = defaultdict(list)
    for t in ids:
        if t in uf.p:
            groups[uf.find(t)].append(t)
    merged = 0
    for root, members in groups.items():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda t: len(st.themes[t].passage_ids))
        k = st.themes[keep]
        for m in members:
            if m == keep:
                continue
            o = st.themes[m]
            for pid in o.passage_ids:
                if pid not in k.passage_ids:
                    k.passage_ids.append(pid)
                if pid in st.passages:
                    st.passages[pid].theme_id = keep
            st.themes.pop(m); merged += 1
        k.dirty = True
        nm = names.get(root)
        if nm and nm.strip():
            k.name = nm.strip()
        if emit:
            d0 = next((d for (a, b), d in decisions.items() if uf.find(a) == root and d.same), None)
            st.emit("tree.theme_merged", keep=keep, name=k.name, merged=len(members) - 1, reason=d0.reason if d0 else "")
    return {"candidate_pairs": len(cands), "same": sum(1 for d in decisions.values() if d.same), "merged_themes": merged}


# --------------------------------------------------------------------------- 3) K5 체인 재연결
def relink_facts(st: SourceStore, *, emit: bool = True) -> dict:
    groups = defaultdict(list)
    for f in st.facts.values():
        groups[(f.eid, f.attribute.lower())].append(f)
    changed = {"update": 0, "duplicate": 0, "conflict": 0}
    for key, fs in groups.items():
        fs.sort(key=lambda f: (f.stated_on, f.id))
        prev = None
        for f in fs:
            if prev is not None and f.status == "new":
                same_val = f.value.strip().lower() == prev.value.strip().lower() and (f.number == prev.number)
                same_time = (f.valid_start == prev.valid_start)
                if same_val and same_time and f.modality == prev.modality:
                    f.status, f.related_fact = "duplicate", prev.id; changed["duplicate"] += 1
                elif same_val and same_time:               # 같은 값·시점이지만 양태가 바뀜 (planned → achieved): 목표 달성의 확인 = update
                    f.status, f.related_fact = "update", prev.id; changed["update"] += 1
                elif (f.modality == "achieved" and prev.modality == "achieved" and same_time and f.number is not None
                      and prev.number is not None and f.number != prev.number):
                    f.status, f.related_fact = "conflict", prev.id; changed["conflict"] += 1
                elif not same_val or not same_time:
                    f.status, f.related_fact = "update", prev.id; changed["update"] += 1
            if f.status != "duplicate":
                prev = f
    if emit:
        st.emit("time.relinked", **changed)
    return changed


def consolidate(st: SourceStore, llm: LLM, *, emit: bool = True) -> dict:
    out = {"entities": merge_entities(st, llm, emit=emit), "themes": merge_themes(st, llm, emit=emit)}
    out["facts"] = relink_facts(st, emit=emit)
    return out
