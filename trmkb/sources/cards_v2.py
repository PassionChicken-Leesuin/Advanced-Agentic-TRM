"""기회 카드 v2 — 토픽 로드맵 한 장을 네 구조(K1·K2·K4·K5)에서 조립한다. 순위는 매기지 않는다 (선택은 생성기의 몫).

설계 (2026-11-03, 사용자와 확정):
  Landscaping(K0 위에 K1·K2·K4·K5 축적) → 기회 카드 추출(what 층 기회 후보 전부, 이 모듈) → 생성기가 카드를 보고 상위 N 선정 → 요소 추출·조립.
  카드 한 장 = Trueman(2014) 토픽 로드맵 서식: 시장(why)·제품(what)·기술(how)·인에이블러(resource) 행 × 현재→목표 열 + 마일스톤 띠 + Actions/Risks/Barriers.
줄 구성 (각 항목 끝에 K1 문장 id, 내부 자료는 'internal' 표시):
  0 머리줄   기회 이름·종류, 대상 시장·고객(기회 기록 + K4 customer_of), 현재 상태(K5 lifecycle 최신), 지지 문서 수(공개/내부)
  1 why      이 기회에 붙은 K1 요구·동인·비전 문장 그대로 (수치 있는 문장 우선, 최신 우선)
  2 trend    이 기회의 문장이 속한 K2 주제의 연도별 문서 수/전체 (라벨 없음, 숫자만)
  3 what     제공물·하위 제품(K4 part_of/addresses + 기회 기록 offering)과 각각의 K5 최신 사실 (현재 열)
  4 when     카드 대상들의 K5 체인 전체, 시점순, UPDATE/CONFLICT 표시 (단기→장기 열 + 마일스톤 띠)
  5 how      K4 requires/enables/part_of 로 연결된 how 층 대상 + 그 대상의 K5 최신 지표
  6 resource K4 supplies/funds/partners_with/enables 로 연결된 resource 층 대상
  7 actors   K4 customer_of/partners_with/competes_with 의 조직
  8 issue    kind=issue 인 K1 문장과 threatens 관계 (Actions/Risks/Barriers 행)
카드 안 줄의 정렬: Trueman p.10 규칙대로 '몇 장의 카드와 연결되는가'(다른 카드에도 나오는 요소 우선), 그 다음 최신순.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from .grid import bad_column
from .store import MATURITY, SourceStore

NUM_RE = re.compile(r"\d")
FORWARD = ("planned", "forecast", "required", "vision")
HOW_RELS = ("requires", "enables", "part_of")
RES_RELS = ("supplies", "funds", "partners_with", "enables")
ACTOR_RELS = ("customer_of", "partners_with", "competes_with", "supplies", "funds")


@dataclass
class Card:
    eid: str
    name: str
    kind: str
    customers: list[str]
    value: str | None
    maturity: str
    docs_public: int
    docs_internal: int
    first_date: str | None
    last_date: str | None
    subjects: list[str]                      # 카드가 다루는 대상 eid (기회 + 제공물 + 하위 what)
    state: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)
    trend: list[str] = field(default_factory=list)
    what: list[str] = field(default_factory=list)
    when: list[str] = field(default_factory=list)
    how: list[str] = field(default_factory=list)
    resource: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    issue: list[str] = field(default_factory=list)
    pids: set[str] = field(default_factory=set)
    elements: set[str] = field(default_factory=set)   # 카드에 나온 다른 대상 eid (줄 정렬용)

    def text(self) -> str:
        head = (f"### {self.name} ({self.eid}) | {self.kind} | docs {self.docs_public} public + {self.docs_internal} internal"
                f" | {self.first_date}..{self.last_date} | maturity {self.maturity}")
        if self.customers:
            head += " | markets: " + "; ".join(self.customers[:5])
        if self.value:
            head += f" | value signal: {self.value[:140]}"
        parts = [head]
        for label, lines in (("state", self.state), ("why", self.why), ("trend", self.trend), ("what", self.what), ("when", self.when),
                             ("how", self.how), ("resource", self.resource), ("actors", self.actors), ("issue", self.issue)):
            if lines:
                parts.append(f"  {label}:")
                parts += [f"    - {ln}" for ln in lines]
        return "\n".join(parts)

    def digest(self) -> str:
        d = f"- {self.name} ({self.eid}) | {self.kind} | docs {self.docs_public}+{self.docs_internal}i | maturity {self.maturity}"
        if self.customers:
            d += " | markets: " + "; ".join(self.customers[:3])
        if self.why:
            d += "\n    why: " + self.why[0][:200]
        fw = [w for w in self.when if "planned" in w or "forecast" in w]
        if fw:
            d += "\n    target: " + fw[0][:200]
        return d

    def to_dict(self) -> dict:
        d = {k: (sorted(v) if isinstance(v, set) else v) for k, v in self.__dict__.items()}
        return d


def _ok(st: SourceStore, pid: str | None, real_only: bool) -> bool:
    p = st.passages.get(pid) if pid else None
    return bool(p) and p.status not in ("irrelevant", "duplicate") and not (real_only and p.is_synthetic)


def _tag(p) -> str:
    return "internal" if p.is_synthetic else p.source_type


def _fact_line(f) -> str:
    v = f"\"{f.value}\"" + (f" {f.unit}" if f.unit and f.unit not in f.value else "")
    return (v + f" @{'' if f.valid_start is None else round(f.valid_start, 2)} ({f.stated_on}, {f.modality}"
            + (f", {f.status.upper()} of {f.related_fact}" if f.status in ("update", "conflict") else "") + f") [{f.id}, {f.pid}]")


def chains(st: SourceStore, eid: str, real_only: bool, max_attrs: int = 8) -> list[tuple[str, list[str], bool]]:
    """대상의 속성별 체인 [(line, pids, forward?)]. 최신 진술 순. 전체 체인(최대 6개 사실)을 보여 준다."""
    facts = defaultdict(list)
    for f in st.facts.values():
        if f.eid == eid and _ok(st, f.pid, real_only):
            facts[f.attribute].append(f)
    out = []
    for a in sorted(facts, key=lambda a: -max(f.stated_on.toordinal() for f in facts[a]))[:max_attrs]:
        fs = sorted(facts[a], key=lambda f: f.stated_on)
        dup = sum(1 for f in fs if f.status == "duplicate")
        fs = [f for f in fs if f.status != "duplicate"][-6:] or fs[-1:]
        fwd = any(f.modality in FORWARD or (f.valid_start or 0) >= 2025 for f in fs)
        line = f"{st.entities[eid].name}: {a} ({fs[-1].family}): " + " -> ".join(_fact_line(f) for f in fs) + (f" (+{dup} repeats)" if dup else "")
        out.append((line, [f.pid for f in fs], fwd))
    return out


def latest_fact(st: SourceStore, eid: str, real_only: bool, families=("lifecycle", "metric")) -> str | None:
    fs = [f for f in st.facts.values() if f.eid == eid and f.family in families and f.status != "duplicate" and _ok(st, f.pid, real_only)]
    if not fs:
        return None
    f = max(fs, key=lambda f: f.stated_on)
    return f"{f.attribute} {_fact_line(f)}"


def build_cards(st: SourceStore, *, real_only: bool = False, min_docs: int = 1, max_per_line: dict | None = None) -> list[Card]:
    L = {"why": 6, "trend": 2, "what": 6, "when": 10, "how": 8, "resource": 5, "actors": 5, "issue": 4}
    if max_per_line:
        L.update(max_per_line)
    tree = st.tree or {}
    theme_by_id = {t["id"]: t for t in tree.get("themes", [])}
    area_of = {tid: a["name"] for a in tree.get("areas", []) for tid in a.get("theme_ids", [])}

    # ---- 후보: 기회 기록이 있는 대상 (일반어·조직·기술 이름은 제외), 문서 수 하한
    recs = defaultdict(list)
    for o in st.opps.values():
        if _ok(st, o.pid, real_only) and o.eid in st.entities and not bad_column(st, o.eid):
            recs[o.eid].append(o)
    # 허브 제공물: 여러 기회에 공통으로 붙는 플랫폼 대상(예: "IonQ quantum computers")은 카드에 이름과 최신 사실만 싣고
    # 그 대상의 문장·체인·관계는 펼치지 않는다 (카드마다 같은 내용이 쏟아져 들어오는 것을 막음)
    off_freq = Counter(o.offering for os in recs.values() for o in {o.offering: o for o in os if o.offering}.values())
    hub_names = {"ionq quantum computers", "quantum computers", "ionq", "ionq system", "ionq systems", "quantum computing systems", "ionq hardware"}
    def is_hub(x: str) -> bool:
        e = st.entities.get(x)
        return bool(e) and (e.name.lower().strip() in hub_names or off_freq.get(x, 0) >= max(4, round(0.15 * len(recs))))
    totals_pub = Counter(); totals_int = Counter(); seen_docs = set()
    for p in st.passages.values():
        if p.routed and p.status not in ("irrelevant", "duplicate") and p.doc_id not in seen_docs:
            seen_docs.add(p.doc_id); (totals_int if p.is_synthetic else totals_pub)[p.doc_date.year] += 1
    theme_docs = defaultdict(lambda: defaultdict(set))
    for p in st.passages.values():
        if p.theme_id and p.status not in ("irrelevant", "duplicate"):
            theme_docs[p.theme_id][(p.doc_date.year, p.is_synthetic)].add(p.doc_id)
    cards: list[Card] = []
    for eid, os in recs.items():
        pids_rec = [o.pid for o in os]
        docs = {st.passages[p].doc_id: st.passages[p].is_synthetic for p in pids_rec}
        if len(docs) < min_docs:
            continue
        ent = st.entities[eid]
        offerings = [o.offering for o in os if o.offering and o.offering in st.entities]
        subjects = [eid] + [x for x in dict.fromkeys(offerings) if x != eid]
        # 하위 what 대상 (part_of / addresses / precedes 로 이 기회에 붙은 what 층 대상)
        for r in st.relations.values():
            if not _ok(st, r.pid, real_only):
                continue
            other = r.dst if r.src == eid else r.src if r.dst == eid else None
            if other and other in st.entities and st.entities[other].layer == "what" and r.rel in ("part_of", "addresses", "precedes") and other not in subjects:
                subjects.append(other)
        subjects = subjects[:6]
        hubs = {x for x in subjects if x != eid and is_hub(x)}
        core = [x for x in subjects if x not in hubs]          # 문장·체인·관계를 펼치는 대상
        customers = list(dict.fromkeys(o.customer.strip() for o in os if o.customer))
        for r in st.relations.values():
            if _ok(st, r.pid, real_only) and r.rel == "customer_of" and r.dst in subjects and r.src in st.entities:
                customers.append(st.entities[r.src].name)
        customers = list(dict.fromkeys(customers))
        mat = max((o.maturity for o in os), key=lambda m: MATURITY.index(m) if m in MATURITY else -1)
        c = Card(eid=eid, name=ent.name, kind=os[0].kind, customers=customers, value=next((o.value for o in os if o.value), None),
                 maturity=mat, docs_public=sum(1 for s in docs.values() if not s), docs_internal=sum(1 for s in docs.values() if s),
                 first_date=str(ent.first_date) if ent.first_date else None, last_date=str(ent.last_date) if ent.last_date else None,
                 subjects=subjects)
        c.pids |= set(pids_rec)
        S = set(core)

        # 0 state: 대상별 수명단계 최신
        for s in core:
            lf = latest_fact(st, s, real_only, families=("lifecycle",))
            if lf:
                c.state.append(f"{st.entities[s].name}: {lf}")
        # 1 why: 이 기회(또는 그 동인·요구 대상)에 붙은 why 문장
        # 제공물·허브의 문장은 넣지 않는다. 우선순위: 기회 자체에 붙은 문장(기회 기록의 문장, 또는 대상에 기회 id) > 요구 대상의 문장 > 동인 대상의 문장
        need_eids = {n for o in os for n in o.needs}; drv_eids = {d for o in os for d in o.drivers}
        cand = []
        for p in st.passages.values():
            if not _ok(st, p.id, real_only) or "why" not in p.layers:
                continue
            ents = set(p.entity_ids)
            tier = 0 if (p.id in c.pids or eid in ents) else 1 if ents & need_eids else 2 if ents & drv_eids else None
            if tier is None:
                continue
            kinds = [k for k in p.kinds if k in ("need", "driver", "vision", "issue")]
            if not kinds:
                continue
            k = "need" if "need" in kinds else "driver" if "driver" in kinds else kinds[0]
            if k == "issue":
                continue
            score = (tier, 0 if k == "need" else 1, 0 if NUM_RE.search(p.statement) else 1, -p.doc_date.toordinal())
            cand.append((score, k, p))
        seen = set()
        for _, k, p in sorted(cand, key=lambda x: x[0]):
            key = p.statement[:60].lower()
            if key in seen:
                continue
            seen.add(key)
            c.why.append(f"[{k}, {p.modality or '-'}, {p.doc_date}, {_tag(p)}] {p.statement[:260]} [{p.id}]")
            c.pids.add(p.id)
            if len(c.why) >= L["why"]:
                break
        # 2 trend: 카드 문장이 속한 주제의 연도별 수치 (라벨 없음)
        tcount = Counter(st.passages[p].theme_id for p in c.pids if st.passages[p].theme_id in theme_by_id)
        for tid, n in tcount.most_common(L["trend"]):
            t = theme_by_id[tid]
            years = sorted(set(totals_pub) | set(totals_int))
            cells = []
            for y in years:
                pub = len(theme_docs[tid].get((y, False), ())); it = len(theme_docs[tid].get((y, True), ()))
                if pub or it or totals_pub.get(y):
                    cells.append(f"{y}: {pub}/{totals_pub.get(y, 0)}" + (f" (+{it}/{totals_int.get(y, 0)} internal)" if totals_int.get(y) else ""))
            c.trend.append(f"theme \"{t['name']}\" (area {area_of.get(tid, '?')}; documents touching it per year, public: {', '.join(cells)})")
        # 3 what: 제공물과 하위 what + 최신 사실
        for s in subjects[1:]:
            lf = latest_fact(st, s, real_only)
            c.what.append(f"{st.entities[s].name} ({s})" + (" [platform]" if s in hubs else "") + (f": {lf}" if lf else ""))
            c.elements.add(s)
        # 4 when: 기회 자신은 체인 전체, 제공물은 미래 지향 체인만 (허브 제외)
        allc = chains(st, eid, real_only)
        for s in core[1:]:
            allc += [x for x in chains(st, s, real_only) if x[2]]
        allc.sort(key=lambda x: (0 if x[2] else 1))
        for line, pids, _ in allc[:L["when"]]:
            c.when.append(line)
            c.pids |= set(pids)
        # 5~7 how / resource / actors via K4
        rel_lines = defaultdict(list)
        for r in st.relations.values():
            if not _ok(st, r.pid, real_only):
                continue
            if r.src in S and r.dst in st.entities and r.dst not in S:
                other, direction = r.dst, "->"
            elif r.dst in S and r.src in st.entities and r.src not in S:
                other, direction = r.src, "<-"
            else:
                continue
            oe = st.entities[other]
            if r.rel == "threatens":
                bucket = "issue"
            elif oe.kind == "actor" or r.rel in ("customer_of", "partners_with", "competes_with"):
                bucket = "actors"
            elif oe.layer == "how":
                bucket = "how"
            elif oe.layer == "resource":
                bucket = "resource"
            else:
                continue
            me = st.entities[r.src if direction == "->" else r.dst].name
            txt = f"{me} --{r.rel}--> {oe.name}" if direction == "->" else f"{oe.name} --{r.rel}--> {me}"
            rel_lines[bucket].append((other, txt, r.pid, r.doc_date))
        for bucket in ("how", "resource", "actors", "issue"):
            seen_other = {}
            for other, txt, pid, d in sorted(rel_lines[bucket], key=lambda x: -x[3].toordinal()):
                if other in seen_other:
                    continue
                seen_other[other] = (txt, pid)
            lines = []
            for other, (txt, pid) in seen_other.items():
                extra = latest_fact(st, other, real_only, families=("metric",)) if bucket == "how" else None
                lines.append((other, f"{txt} [{pid}]" + (f" | latest: {extra}" if extra else "")))
                c.pids.add(pid)
                c.elements.add(other)
            getattr(c, bucket).extend(ln for _, ln in lines)   # 정렬은 아래 2차 패스
            c.__dict__[f"_{bucket}_eids"] = [o for o, _ in lines]
        # 8 issue: kind=issue 문장
        iss = []
        for p in st.passages.values():
            if _ok(st, p.id, real_only) and "issue" in p.kinds and set(p.entity_ids) & S:
                iss.append(p)
        for p in sorted(iss, key=lambda p: -p.doc_date.toordinal())[:L["issue"]]:
            c.issue.append(f"[issue, {p.doc_date}, {_tag(p)}] {p.statement[:220]} [{p.id}]")
            c.pids.add(p.id)
        cards.append(c)

    # ---- 2차 패스: 줄 정렬 = 다른 카드에도 나오는 요소 우선 (Trueman p.10: 우선 기회와의 연결 수), 상한 적용
    freq = Counter(e for c in cards for e in c.elements)
    for c in cards:
        for bucket in ("how", "resource", "actors", "issue"):
            eids = c.__dict__.pop(f"_{bucket}_eids", [])
            lines = getattr(c, bucket)
            if bucket == "issue":
                rel_part, txt_part = lines[:len(eids)], lines[len(eids):]
                order = sorted(zip(eids, rel_part), key=lambda x: -freq[x[0]])
                setattr(c, bucket, ([f"{ln} (in {freq[e]} cards)" for e, ln in order] + txt_part)[:L["issue"] + 2])
            else:
                order = sorted(zip(eids, lines), key=lambda x: -freq[x[0]])
                setattr(c, bucket, [f"{ln} (in {freq[e]} cards)" for e, ln in order][:L[bucket]])
    cards.sort(key=lambda c: c.eid)   # 순위가 아님: 안정적이되 의미 없는 순서 (선택은 생성기의 몫)
    return cards


def dump(cards: list[Card], out_dir) -> dict:
    from pathlib import Path
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "cards.json").write_text(json.dumps([c.to_dict() for c in cards], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "cards.md").write_text("\n\n".join(c.text() for c in cards) + "\n", encoding="utf-8")
    (out / "digest.md").write_text("\n".join(c.digest() for c in cards) + "\n", encoding="utf-8")
    lens = [len(c.text()) for c in cards]
    stats = {"cards": len(cards), "chars_total": sum(lens), "chars_mean": round(sum(lens) / max(len(lens), 1)),
             "chars_max": max(lens) if lens else 0, "digest_chars": sum(len(c.digest()) + 1 for c in cards),
             "with_why": sum(1 for c in cards if c.why), "with_when": sum(1 for c in cards if c.when),
             "with_how": sum(1 for c in cards if c.how), "with_issue": sum(1 for c in cards if c.issue),
             "tier_A": sum(1 for c in cards if c.customers), "lines_mean": {k: round(sum(len(getattr(c, k)) for c in cards) / max(len(cards), 1), 1)
                                                                            for k in ("why", "trend", "what", "when", "how", "resource", "actors", "issue")}}
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats
