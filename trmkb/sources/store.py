"""v2 저장소: 소스 문장(Passage)이 기본 단위(K1), 층은 태그, 공유 대상(Entity)은 구조 사이를 잇는 색인.
K2 주제 요약 트리(Theme, tree), K3 기회 연계 그리드(Opportunity, grid), K4 의존 관계 그래프(Relation), K5 시간 지식그래프(TimeFact).
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from pydantic import BaseModel, Field

LAYERS = ("why", "what", "how", "resource")
KINDS = ("driver", "need", "vision", "opportunity", "milestone", "capability", "component", "enabler", "actor", "issue")
STATUSES = ("new", "duplicate", "update", "conflict", "irrelevant")
SOURCE_WEIGHT: dict[str, float] = {}   # 2026-11-02 확정: 출처 가중 없음 (모든 문서 1.0). 이전 값 {"investor_deck": 0.5, "sec_filing": 0.8} 은 근거 없는 임의값이라 폐기


def new_eid() -> str:
    return f"e_{uuid4().hex[:10]}"


class Passage(BaseModel):
    id: str                       # 원 근거 id (ev_...) 를 그대로 사용 → 로드맵 인용과 호환
    doc_id: str
    doc_date: date
    source_type: str
    is_synthetic: bool = False
    text: str                     # 원문 인용 (문서에서 그대로)
    claim: str | None = None      # Reader 가 수치·날짜를 살려 다시 쓴 진술
    reader_hints: list[dict] = Field(default_factory=list)   # [{label, kind}]
    # ---- Router v2 판단 결과 (태그)
    layers: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    time_start: float | None = None
    time_end: float | None = None
    time_raw: str | None = None
    modality: str | None = None
    status: str | None = None
    related_pid: str | None = None
    reason: str = ""
    routed: bool = False
    systems: list[str] = Field(default_factory=list)      # Router 가 보낸 구조 (tree/grid/graph/time). K1 은 저장 판정이면 항상
    route_reasons: dict[str, str] = Field(default_factory=dict)   # 구조별 "이 문장이 그 구조에서 어떤 TRM 기능에 기여하는가"
    theme_id: str | None = None
    emphasis: str | None = None                           # K2 강조 신호: new | continuing | expanding | declining

    @property
    def functions(self) -> list[str]:
        return (["grounding"] if self.routed and self.status not in ("irrelevant", "duplicate") else []) + [FUNCTION_OF[s] for s in self.systems if s in FUNCTION_OF]

    @property
    def statement(self) -> str:
        return self.claim or self.text


class Entity(BaseModel):
    id: str = Field(default_factory=new_eid)
    name: str
    aliases: list[str] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)
    layer_counts: dict[str, int] = Field(default_factory=dict)
    kind_counts: dict[str, int] = Field(default_factory=dict)
    first_date: date | None = None
    last_date: date | None = None
    time_min: float | None = None
    time_max: float | None = None
    created_by_doc: str | None = None

    @property
    def layer(self) -> str | None:
        return max(self.layer_counts, key=self.layer_counts.get) if self.layer_counts else None

    @property
    def kind(self) -> str | None:
        return max(self.kind_counts, key=self.kind_counts.get) if self.kind_counts else None


TERM_TYPES = ("metric", "product", "technology", "organization", "application", "stage", "program", "acronym")
TERM_SCOPES = ("company", "industry", "general")


class Term(BaseModel):
    """K0 용어집 항목 — 다섯 구조가 공유하는 어휘층. 문서를 읽으며 자라고(후보), 사용자가 확인하면 확정된다.
    지표(metric)와 수명 단계(stage)는 K5 속성 어휘, 나머지는 공유 대상(Entity)에 연결되는 이름 사전."""
    id: str = Field(default_factory=lambda: f"g_{uuid4().hex[:8]}")
    name: str
    type: str
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    unit: str | None = None              # metric: 단위 (#AQ, qubits, %, ms, USD ...)
    direction: str | None = None         # metric: higher_better | lower_better | none
    order: int | None = None             # product: 세대 순서 (Harmony 1, Aria 2, Forte 3, Tempo 4 ...)
    scope: str = "industry"              # company | industry | general
    status: str = "candidate"            # candidate | confirmed | rejected
    eid: str | None = None               # 대상 색인(Entity) 연결 (product/technology/organization/application/program)
    first_doc: str | None = None
    first_date: date | None = None
    passage_ids: list[str] = Field(default_factory=list)
    count: int = 0                       # 언급 문서 수


SYSTEMS = ("tree", "grid", "graph", "time")   # K2~K5. K1 근거 저장소는 기본층 (Router 는 무관·중복만 거른다)
FUNCTION_OF = {"tree": "trend", "grid": "opportunity", "graph": "link", "time": "timing"}   # TRM 기능 ②~⑤ (①은 K1)
MATURITY = ("exploring", "pilot", "contracted", "revenue")
RELATIONS = ("requires", "enables", "drives", "part_of", "supplies", "partners_with", "customer_of", "competes_with",
             "funds", "threatens", "addresses", "precedes")


class Relation(BaseModel):
    """개체·관계 그래프 (GraphRAG 계열): 문장이 직접 말하는 (주체, 관계, 대상)."""
    id: str = Field(default_factory=lambda: f"r_{uuid4().hex[:10]}")
    src: str
    rel: str
    dst: str
    pid: str
    doc_date: date
    reason: str = ""


class TimeFact(BaseModel):
    """시간 지식그래프 (Temporal KG 계열): (대상, 속성, 값, 유효 시점) + 진술 시점. 덮어쓰지 않고 갱신·충돌로 잇는다."""
    id: str = Field(default_factory=lambda: f"tf_{uuid4().hex[:10]}")
    eid: str
    family: str = "metric"       # metric(지표 값) | lifecycle(수명 단계) | milestone(전략 마일스톤·사건)
    attribute: str               # 지표·단계 이름: K0 용어집의 metric/stage 용어 (예: "#AQ", "two-qubit gate fidelity", "lifecycle stage")
    value: str                   # 값 (예: "64", "99.9%", "general availability", "broad quantum advantage")
    number: float | None = None  # metric: 숫자 값
    unit: str | None = None
    valid_start: float | None = None
    valid_end: float | None = None
    stated_on: date
    modality: str | None = None
    pid: str
    status: str = "new"          # new | update | conflict | duplicate
    related_fact: str | None = None


class Opportunity(BaseModel):
    """기회 연계 그리드 (Cambridge linkage grid 계열)의 기록: 응용처·제공물·고객·가치 신호·동인·요구·성숙도."""
    id: str = Field(default_factory=lambda: f"o_{uuid4().hex[:10]}")
    eid: str                     # 기회 대상: 응용 분야 또는 제품 유형 (Cambridge 2014 보고서 19쪽의 기회 군집과 같은 수준)
    kind: str = "application"    # application(응용 분야) | product_type(제품 유형)
    offering: str | None = None  # IonQ 제공물 대상 eid (구체 제품: Forte, Tempo ...) → 기회 아래 what 행
    customer: str | None = None  # 대상 시장·고객·부문 (이름 그대로). 있으면 그 기회는 A급
    value: str | None = None     # 가치 신호 원문 (시장 규모, 계약 금액, 수요 진술)
    drivers: list[str] = Field(default_factory=list)   # why 대상 eid (동인)
    needs: list[str] = Field(default_factory=list)     # why 대상 eid (고객 요구)
    maturity: str = "exploring"
    pid: str
    doc_date: date


class Theme(BaseModel):
    """계층 요약 트리 (RAPTOR 계열)의 잎: Router 가 배정한 주제와 그 요약."""
    id: str = Field(default_factory=lambda: f"t_{uuid4().hex[:10]}")
    name: str
    passage_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    periods: list[dict] = Field(default_factory=list)   # [{"year": int, "line": str}] 기간별 요약
    trend: str | None = None                             # rising | stable | declining | new
    version: int = 0
    dirty: bool = True
    area: str | None = None


def _w(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(r.model_dump_json(exclude_none=True) + "\n")
    tmp.replace(path)


def _r(path: Path) -> Iterator[dict]:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


class SourceStore:
    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir); self.dir.mkdir(parents=True, exist_ok=True)
        self.passages: dict[str, Passage] = {p["id"]: Passage.model_validate(p) for p in _r(self.dir / "passages.jsonl")}
        self.entities: dict[str, Entity] = {e["id"]: Entity.model_validate(e) for e in _r(self.dir / "entities.jsonl")}
        self.docs: dict[str, dict] = {d["id"]: d for d in _r(self.dir / "documents.jsonl")}
        self.grid: dict = json.loads((self.dir / "grid.json").read_text(encoding="utf-8")) if (self.dir / "grid.json").exists() else {}
        self.relations: dict[str, Relation] = {r["id"]: Relation.model_validate(r) for r in _r(self.dir / "graph.jsonl")}
        self.facts: dict[str, TimeFact] = {f["id"]: TimeFact.model_validate(f) for f in _r(self.dir / "time_kg.jsonl")}
        self.themes: dict[str, Theme] = {t["id"]: Theme.model_validate(t) for t in _r(self.dir / "tree_themes.jsonl")}
        self.opps: dict[str, Opportunity] = {o["id"]: Opportunity.model_validate(o) for o in _r(self.dir / "grid_opportunities.jsonl")}
        self.tree: dict = json.loads((self.dir / "tree.json").read_text(encoding="utf-8")) if (self.dir / "tree.json").exists() else {}
        self.terms: dict[str, Term] = {t["id"]: Term.model_validate(t) for t in _r(self.dir / "glossary.jsonl")}
        self._seq = sum(1 for _ in _r(self.dir / "events.jsonl"))
        from . import profile as _prof
        self.profile: dict = _prof.load(self.dir)      # 회사·기준일·기간 (업로드 run 은 profile.json, 기본값은 IonQ 데모)

    @property
    def company(self) -> str:
        return self.profile["company"]

    # ------------------------------------------------------------ K0 용어집
    def terms_by_type(self, *types: str, active_only: bool = True, confirmed_only: bool = False) -> list["Term"]:
        """confirmed_only: 확정 용어만 (문서 2건 이상 또는 심은 어휘). 확정 용어가 5개 미만인 초기에는 전체를 돌려줌 (빈 어휘 방지)."""
        ts = [t for t in self.terms.values() if (not types or t.type in types) and (not active_only or t.status != "rejected")]
        if confirmed_only:
            conf = [t for t in ts if t.status == "confirmed"]
            if len(conf) >= 5:
                ts = conf
        return sorted(ts, key=lambda t: (-t.count, t.name))

    def glossary_block(self, types: tuple[str, ...] = (), max_chars: int = 3500, confirmed_only: bool = False) -> str:
        """프롬프트용 용어 범례: name (type; aliases) [unit] — definition. 언급 많은 순."""
        lines, used = [], 0
        for t in self.terms_by_type(*types, confirmed_only=confirmed_only):
            s = f"- {t.name} ({t.type}" + (f"; aka {', '.join(t.aliases[:4])}" if t.aliases else "") + ")"
            if t.unit:
                s += f" [{t.unit}" + (f", {t.direction}" if t.direction and t.direction != "none" else "") + "]"
            if t.definition:
                s += f": {t.definition[:110]}"
            if used + len(s) > max_chars:
                break
            lines.append(s); used += len(s) + 1
        return "\n".join(lines) or "(none yet)"

    # ------------------------------------------------------------ events (시각화·재생의 단일 소스)
    def emit(self, type: str, **payload) -> None:
        self._seq += 1
        rec = {"seq": self._seq, "ts": datetime.now(timezone.utc).isoformat(), "type": type, **payload}
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def log_router(self, rec: dict) -> None:
        with (self.dir / "router_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def save(self) -> None:
        _w(self.dir / "passages.jsonl", self.passages.values())
        _w(self.dir / "entities.jsonl", self.entities.values())
        with (self.dir / "documents.jsonl").open("w", encoding="utf-8") as f:
            for d in self.docs.values():
                f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
        if self.grid:
            (self.dir / "grid.json").write_text(json.dumps(self.grid, ensure_ascii=False, indent=1), encoding="utf-8")
        _w(self.dir / "graph.jsonl", self.relations.values())
        _w(self.dir / "time_kg.jsonl", self.facts.values())
        _w(self.dir / "tree_themes.jsonl", self.themes.values())
        _w(self.dir / "grid_opportunities.jsonl", self.opps.values())
        _w(self.dir / "glossary.jsonl", self.terms.values())
        if self.tree:
            (self.dir / "tree.json").write_text(json.dumps(self.tree, ensure_ascii=False, indent=1), encoding="utf-8")

    def facts_of(self, eid: str, *, real_only: bool = False) -> list["TimeFact"]:
        fs = [f for f in self.facts.values() if f.eid == eid]
        if real_only:
            fs = [f for f in fs if f.pid in self.passages and not self.passages[f.pid].is_synthetic]
        return sorted(fs, key=lambda f: (f.attribute, f.stated_on))

    def relations_of(self, eid: str, *, real_only: bool = False) -> list["Relation"]:
        rs = [r for r in self.relations.values() if eid in (r.src, r.dst)]
        if real_only:
            rs = [r for r in rs if r.pid in self.passages and not self.passages[r.pid].is_synthetic]
        return rs

    # ------------------------------------------------------------ entity bookkeeping
    def attach(self, ent: Entity, p: Passage) -> None:
        if p.id not in ent.passage_ids:
            ent.passage_ids.append(p.id)
        if p.doc_id not in ent.doc_ids:
            ent.doc_ids.append(p.doc_id)
        for l in p.layers:
            ent.layer_counts[l] = ent.layer_counts.get(l, 0) + 1
        for k in p.kinds:
            ent.kind_counts[k] = ent.kind_counts.get(k, 0) + 1
        ent.first_date = min(filter(None, [ent.first_date, p.doc_date]))
        ent.last_date = max(filter(None, [ent.last_date, p.doc_date]))
        for t in (p.time_start, p.time_end):
            if t is not None:
                ent.time_min = t if ent.time_min is None else min(ent.time_min, t)
                ent.time_max = t if ent.time_max is None else max(ent.time_max, t)

    def passages_of(self, eid: str, *, real_only: bool = False) -> list[Passage]:
        ps = [self.passages[i] for i in self.entities[eid].passage_ids if i in self.passages]
        if real_only:
            ps = [p for p in ps if not p.is_synthetic]
        return sorted(ps, key=lambda p: p.doc_date)

    def support(self, eid: str, *, real_only: bool = False) -> float:
        """지지 문서 수 = 그 대상을 말한 서로 다른 문서 수. 2026-11-02 확정: duplicate 판정 문장도 셈 (같은 사실의 반복은 중요도 신호),
        무관 판정만 제외. 구조 추출과 작업지에서는 duplicate 를 쓰지 않음 (같은 사실을 여러 번 저장·읽지 않음). 출처 가중 없음."""
        docs = {}
        for p in self.passages_of(eid, real_only=real_only):
            if p.status == "irrelevant":
                continue
            docs[p.doc_id] = max(docs.get(p.doc_id, 0), SOURCE_WEIGHT.get(p.source_type, 1.0))
        return round(sum(docs.values()), 2)

    def stats(self) -> dict[str, Any]:
        st = Counter(p.status for p in self.passages.values())
        lay = Counter(l for p in self.passages.values() for l in p.layers)
        multi = sum(1 for p in self.passages.values() if len(p.layers) > 1)
        elay = Counter(e.layer for e in self.entities.values())
        sysc = Counter(s for p in self.passages.values() for s in p.systems)
        sysc["evidence"] = sum(1 for p in self.passages.values() if p.routed and p.status not in ("irrelevant", "duplicate"))
        func = Counter(f for p in self.passages.values() for f in p.functions)
        # 문서 유형별 배정 비율 (Router 의 분배가 문서 성격에 따라 어떻게 달라지는가)
        by_type: dict[str, dict] = {}
        for p in self.passages.values():
            if not p.routed:
                continue
            d = by_type.setdefault(p.source_type, {"passages": 0, **{s: 0 for s in SYSTEMS}})
            d["passages"] += 1
            for s in p.systems:
                d[s] += 1
        route_share = {k: {s: round(v[s] / v["passages"], 2) for s in SYSTEMS} | {"passages": v["passages"]} for k, v in by_type.items() if v["passages"]}
        return {"documents": len(self.docs), "passages": len(self.passages), "routed": sum(p.routed for p in self.passages.values()),
                "status": dict(st), "layer_tags": dict(lay), "multi_layer_passages": multi,
                "routed_to_system": dict(sysc), "functions": dict(func), "route_share_by_source_type": route_share,
                "entities": len(self.entities), "entities_by_dominant_layer": dict(elay),
                "glossary_terms": len(self.terms), "glossary_by_type": dict(Counter(t.type for t in self.terms.values())),
                "graph_relations": len(self.relations), "time_facts": len(self.facts),
                "time_fact_family": dict(Counter(f.family for f in self.facts.values())),
                "time_fact_status": dict(Counter(f.status for f in self.facts.values())),
                "grid_opportunities": len(self.opps), "tree_themes": len(self.themes), "tree_areas": len(self.tree.get("areas", [])) if self.tree else 0,
                "grid_cells": len(self.grid.get("cells", [])) if self.grid else 0, "events": self._seq}
