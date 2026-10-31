"""
trmkb.schema — KB 공통 뼈대의 pydantic 정의.

근거 문서:
  - 연구계획/2026-10-21_연구구상 §4.2 공통 뼈대 (노드: 층타입·ES/LS·신뢰도, 엣지: enables/requires/precedes·근거ID)
  - 연구계획/2026-10-31_구현계획 §2.1-b 5원칙, §2.2 저장 스키마, §2.3-b 사용 설계
  - 연구계획/2026-10-31_분석_Cambridge양자로드맵 §5 (노드 10종, 주장 7종, 관계 11종)

설계 원칙:
  1. 지식 단위 = 노드(역량 행 등) + 그 노드에 쌓이는 주장(claim) 타임라인. 주장은 덮어쓰지 않는다.
  2. 노드·주장은 type 필드로 구분되는 discriminated union. 공통 봉투 + 유형별 슬롯.
  3. 모든 시간은 TimeExpr로 받는다 (원문 보존 + 정규화 + 유형).
  4. 엣지는 근거·Critic 판정·도출 방식을 반드시 가진다.
  5. events.jsonl 한 줄 = Event 하나. 시각화·재생·평가의 단일 소스.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# 공통 열거형
# ---------------------------------------------------------------------------

class Layer(StrEnum):
    WHY = "why"            # 트렌드·드라이버, 이해관계자 니즈, 비전
    WHAT = "what"          # 응용 기회·제품, 마일스톤
    HOW = "how"            # 역량·기술, 구성요소
    RESOURCE = "resource"  # 인에이블러 (자금·인력·표준·시설·규제·파트너십)
    CROSS = "cross"        # 행위자, 이슈 (층을 가로지름)


class NodeType(StrEnum):
    DRIVER = "driver"
    NEED = "need"
    VISION = "vision"
    OPPORTUNITY = "opportunity"
    MILESTONE = "milestone"
    CAPABILITY = "capability"
    COMPONENT = "component"
    ENABLER = "enabler"
    ACTOR = "actor"
    ISSUE = "issue"


NODE_LAYER: dict[NodeType, Layer] = {
    NodeType.DRIVER: Layer.WHY,
    NodeType.NEED: Layer.WHY,
    NodeType.VISION: Layer.WHY,
    NodeType.OPPORTUNITY: Layer.WHAT,
    NodeType.MILESTONE: Layer.WHAT,
    NodeType.CAPABILITY: Layer.HOW,
    NodeType.COMPONENT: Layer.HOW,
    NodeType.ENABLER: Layer.RESOURCE,
    NodeType.ACTOR: Layer.CROSS,
    NodeType.ISSUE: Layer.CROSS,
}


class ClaimType(StrEnum):
    SPEC = "spec"                        # 다차원 목표 사양 벡터
    CAPABILITY_CLAIM = "capability_claim"  # 단일 측도·값 (예: #AQ 64 by 2025)
    MARKET_SIZE = "market_size"
    MATURITY = "maturity"                # TRL / 상용화 단계
    PRIORITY = "priority"
    COMPARISON = "comparison"            # 경쟁 대안과의 사양 비교
    ACTION = "action"                    # 책임 행위자가 있는 조치


class RelationType(StrEnum):
    DRIVES = "drives"              # why → what
    REQUIRES = "requires"          # what → how, how → how
    ENABLES = "enables"            # how → what, resource → any
    PRECEDES = "precedes"          # 시간 순서 (+lag)
    PART_OF = "part_of"            # 계층
    COMPETES_WITH = "competes_with"
    THREATENS = "threatens"        # issue(risk/barrier) → node
    ADDRESSED_BY = "addressed_by"  # issue(barrier) → action claim 보유 노드
    PROVIDES = "provides"          # actor → capability/enabler/opportunity
    ENDORSED_BY = "endorsed_by"    # vision/opportunity → actor
    DECIDED_OVER = "decided_over"  # issue(decision) → chosen/rejected


class Modality(StrEnum):
    CURRENT = "current"      # as-is 현재 상태
    PLANNED = "planned"      # 계획·목표
    ACHIEVED = "achieved"    # 달성 보고
    REQUIRED = "required"    # 고객·규제의 요구
    FORECAST = "forecast"    # 제3자 전망
    VISION = "vision"        # 장기 목표 상태


class TimeExprKind(StrEnum):
    ABSOLUTE = "absolute"    # "2018", "Q2 2027"
    RELATIVE = "relative"    # "within 2 years from demo"
    BAND = "band"            # short/medium/long
    UNKNOWN = "unknown"      # "When?" 공란


class Stage(StrEnum):
    RESEARCH = "research"
    DEMONSTRATOR = "demonstrator"
    FIRST_PRODUCT = "first_product"
    SECOND_PRODUCT = "second_product"
    VOLUME = "volume"


class CriticStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    HOLD = "hold"


class Derivation(StrEnum):
    DIRECT = "direct"    # 문서에 명시된 연결
    DERIVED = "derived"  # Linker가 추론한 연결


class SteepCategory(StrEnum):
    SOCIAL = "social"
    TECHNOLOGICAL = "technological"
    ECONOMIC = "economic"
    ENVIRONMENTAL = "environmental"
    POLITICAL = "political"  # political / legal / regulatory


class StakeholderType(StrEnum):
    GOVERNMENT = "government"
    CUSTOMER = "customer"
    LARGE_INDUSTRY = "large_industry"
    SME = "sme"
    RESEARCH = "research"
    INVESTOR = "investor"
    REGULATOR = "regulator"
    OTHER = "other"


class EnablerKind(StrEnum):
    FUNDING = "funding"
    SKILLS = "skills"
    STANDARD = "standard"
    FACILITY = "facility"
    PARTNERSHIP = "partnership"
    REGULATION = "regulation"
    INFRASTRUCTURE = "infrastructure"


class ActorRole(StrEnum):
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    FUNDER = "funder"
    REGULATOR = "regulator"
    COMPETITOR = "competitor"
    PARTNER = "partner"
    ACQUIREE = "acquiree"
    INTEGRATOR = "integrator"
    SELF = "self"  # KB의 주체 기업


class IssueKind(StrEnum):
    RISK = "risk"
    BARRIER = "barrier"
    OPEN_QUESTION = "open_question"
    DECISION = "decision"
    ASSUMPTION = "assumption"


class IssueType(StrEnum):
    TECHNICAL = "technical"
    MARKET = "market"
    POLITICAL = "political"
    COMPETITIVE = "competitive"
    FINANCIAL = "financial"
    REGULATORY = "regulatory"


class IssueStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    STALE = "stale"


class Agent(StrEnum):
    READER = "reader"
    ROUTER = "router"
    LINKER = "linker"
    CRITIC = "critic"
    TIMING = "timing"
    SUMMARIZER = "summarizer"
    GENERATOR = "generator"
    SYSTEM = "system"


class EventType(StrEnum):
    DOC_STARTED = "doc.started"
    DOC_FINISHED = "doc.finished"
    NODE_PROPOSED = "node.proposed"
    NODE_CREATED = "node.created"
    NODE_MERGED = "node.merged"
    NODE_UPDATED = "node.updated"
    CLAIM_ADDED = "claim.added"
    EVIDENCE_ADDED = "evidence.added"
    EDGE_PROPOSED = "edge.proposed"
    EDGE_ACCEPTED = "edge.accepted"
    EDGE_REJECTED = "edge.rejected"
    CONFLICT_FLAGGED = "conflict.flagged"
    SUMMARY_UPDATED = "summary.updated"
    TIME_INDEXED = "time.indexed"
    TIME_RECOMPUTED = "time.recomputed"
    ROUTER_DECISION = "router.decision"
    CANDIDATE_ADDED = "candidate.added"
    ERROR = "error"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 시간 표현
# ---------------------------------------------------------------------------

class TimeExpr(BaseModel):
    """시간 표현. 원문을 보존하고 연도 실수로 정규화한다 (2027.5 = 2027년 중반)."""
    raw: str = ""
    kind: TimeExprKind = TimeExprKind.UNKNOWN
    start: float | None = None   # 정규화된 시작 연도 (ES 후보)
    end: float | None = None     # 정규화된 종료 연도 (LS 후보)
    anchor_id: str | None = None  # relative일 때 기준 노드/마일스톤 id
    lag_years: float | None = None  # relative일 때 기준으로부터의 지연

    @model_validator(mode="after")
    def _check(self) -> "TimeExpr":
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"TimeExpr end < start: {self.raw!r}")
        return self

    @classmethod
    def year(cls, y: float, raw: str | None = None) -> "TimeExpr":
        return cls(raw=raw or str(y), kind=TimeExprKind.ABSOLUTE, start=float(y), end=float(y))

    @classmethod
    def unknown(cls, raw: str = "") -> "TimeExpr":
        return cls(raw=raw, kind=TimeExprKind.UNKNOWN)

    @property
    def midpoint(self) -> float | None:
        if self.start is None and self.end is None:
            return None
        if self.start is None:
            return self.end
        if self.end is None:
            return self.start
        return (self.start + self.end) / 2


# ---------------------------------------------------------------------------
# 문서 · 근거
# ---------------------------------------------------------------------------

class SourceType(StrEnum):
    SEC_FILING = "sec_filing"
    PRESS_RELEASE = "press_release"
    INVESTOR_DECK = "investor_deck"
    BLOG = "blog"
    ARXIV = "arxiv"
    PATENT = "patent"
    NEWS = "news"
    INDUSTRY_REPORT = "industry_report"
    # 가상 내부자료
    SYN_MEETING = "syn_meeting"
    SYN_RD_REPORT = "syn_rd_report"
    SYN_CUSTOMER_EMAIL = "syn_customer_email"
    SYN_SUPPLIER_EMAIL = "syn_supplier_email"
    SYN_TECH_ASSESSMENT = "syn_tech_assessment"


class Document(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    title: str
    source_type: SourceType
    date: date
    path: str                      # md 파일 경로 (Code/data/corpus/ 기준 상대)
    url: str | None = None
    actor_id: str | None = None    # 발행 주체 (actor 노드)
    is_synthetic: bool = False
    planted_fact_ids: list[str] = Field(default_factory=list)
    n_chars: int = 0


class Evidence(BaseModel):
    """근거 청크. 노드·주장·엣지에 부착된다 (연산 ① grounding)."""
    id: str = Field(default_factory=lambda: new_id("ev"))
    doc_id: str
    text: str
    span: tuple[int, int] | None = None   # 문서 내 문자 오프셋
    node_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 노드 (10종)
# ---------------------------------------------------------------------------

class NodeBase(BaseModel):
    id: str = Field(default_factory=lambda: new_id("n"))
    label: str
    description: str = ""
    category: str | None = None        # 역량 영역 / 응용 범주 / STEEP 등 행 범주
    parent_id: str | None = None       # part_of 상위 노드
    aliases: list[str] = Field(default_factory=list)
    # 시간 속성 (Timing 에이전트가 갱신)
    es: float | None = None            # earliest start (연도)
    ls: float | None = None            # latest start
    time_band: str | None = None       # short / medium / long
    maturity_trl: int | None = Field(default=None, ge=1, le=9)
    stage: Stage | None = None
    # 계산 속성
    priority: float | None = None      # Router/Critic가 재계산
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    scope: str | None = None           # geography / ownership 한정어
    created_by_doc: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def layer(self) -> Layer:
        return NODE_LAYER[NodeType(self.type)]  # type: ignore[attr-defined]


class DriverNode(NodeBase):
    type: Literal["driver"] = "driver"
    steep: SteepCategory | None = None
    direction: str | None = None  # 증가/감소/전환 등 한 구절


class NeedNode(NodeBase):
    type: Literal["need"] = "need"
    stakeholder_type: StakeholderType | None = None
    segment: str | None = None
    requirement_text: str | None = None


class VisionNode(NodeBase):
    type: Literal["vision"] = "vision"
    horizon: TimeExpr | None = None
    target_state: str | None = None


class OpportunityNode(NodeBase):
    type: Literal["opportunity"] = "opportunity"
    segments: list[str] = Field(default_factory=list)
    time_window: TimeExpr | None = None


class MilestoneNode(NodeBase):
    type: Literal["milestone"] = "milestone"
    milestone_stage: Stage | None = None
    date: TimeExpr | None = None
    opportunity_id: str | None = None


class CapabilityNode(NodeBase):
    type: Literal["capability"] = "capability"
    area: str | None = None  # Components / Quantum Devices / Integration / ...


class ComponentNode(NodeBase):
    type: Literal["component"] = "component"
    capability_id: str | None = None


class EnablerNode(NodeBase):
    type: Literal["enabler"] = "enabler"
    kind: EnablerKind | None = None
    amount: float | None = None
    currency: str | None = None
    source: str | None = None       # 자금 출처·표준 기관 등
    gatekeeper: str | None = None   # 규제·승인 기관 (actor id 또는 이름)


class ActorNode(NodeBase):
    type: Literal["actor"] = "actor"
    org_type: str | None = None
    roles: list[ActorRole] = Field(default_factory=list)


class IssueNode(NodeBase):
    type: Literal["issue"] = "issue"
    kind: IssueKind = IssueKind.RISK
    issue_type: IssueType | None = None
    status: IssueStatus = IssueStatus.OPEN
    alternatives: list[str] = Field(default_factory=list)  # decision일 때 선택지 노드 id


Node = Annotated[
    Union[
        DriverNode, NeedNode, VisionNode, OpportunityNode, MilestoneNode,
        CapabilityNode, ComponentNode, EnablerNode, ActorNode, IssueNode,
    ],
    Field(discriminator="type"),
]

NODE_CLASSES: dict[str, type[NodeBase]] = {
    "driver": DriverNode, "need": NeedNode, "vision": VisionNode,
    "opportunity": OpportunityNode, "milestone": MilestoneNode,
    "capability": CapabilityNode, "component": ComponentNode,
    "enabler": EnablerNode, "actor": ActorNode, "issue": IssueNode,
}


def parse_node(data: dict[str, Any]) -> NodeBase:
    cls = NODE_CLASSES[data["type"]]
    return cls.model_validate(data)


# ---------------------------------------------------------------------------
# 주장 (7종) — 노드에 쌓이는 타임라인 항목. 덮어쓰지 않는다.
# ---------------------------------------------------------------------------

class ClaimBase(BaseModel):
    id: str = Field(default_factory=lambda: new_id("c"))
    node_id: str
    text: str                                  # 주장 한 문장 (정규화 전 요지)
    speaker: str | None = None                 # 발화 주체 (actor id 또는 이름)
    modality: Modality = Modality.PLANNED
    time: TimeExpr = Field(default_factory=TimeExpr.unknown)  # 주장이 가리키는 시점
    scope: str | None = None
    doc_id: str
    doc_date: date                             # 발언 시점 → 타임라인 정렬 키
    evidence_id: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    conflicts_with: list[str] = Field(default_factory=list)  # Critic가 플래그한 상충 주장 id
    created_at: datetime = Field(default_factory=utcnow)


class SpecClaim(ClaimBase):
    type: Literal["spec"] = "spec"
    dims: dict[str, str] = Field(default_factory=dict)  # {"size": "shoebox", "cost": "£1-10k", ...}
    segment: str | None = None
    stage: Stage | None = None


class CapabilityClaim(ClaimBase):
    type: Literal["capability_claim"] = "capability_claim"
    measure: str                     # "#AQ", "two-qubit fidelity", "physical qubits"
    value: str                       # "64", "99.99%", "10,000" (문자열 보존)
    value_num: float | None = None
    unit: str | None = None


class MarketSizeClaim(ClaimBase):
    type: Literal["market_size"] = "market_size"
    volume: str | None = None
    unit_price: str | None = None
    total: str | None = None
    currency: str | None = None
    segment: str | None = None
    year: float | None = None


class MaturityClaim(ClaimBase):
    type: Literal["maturity"] = "maturity"
    trl: int | None = Field(default=None, ge=1, le=9)
    stage: Stage | None = None


class PriorityClaim(ClaimBase):
    type: Literal["priority"] = "priority"
    score: float
    method: str  # vote / mention / capital / degree / management_emphasis


class ComparisonClaim(ClaimBase):
    type: Literal["comparison"] = "comparison"
    vs_node_id: str | None = None
    vs_label: str | None = None
    dims: dict[str, str] = Field(default_factory=dict)
    verdict: str | None = None  # better / worse / mixed


class ActionClaim(ClaimBase):
    type: Literal["action"] = "action"
    responsible_actor: str | None = None
    due: TimeExpr | None = None
    addresses_issue_id: str | None = None


Claim = Annotated[
    Union[SpecClaim, CapabilityClaim, MarketSizeClaim, MaturityClaim,
          PriorityClaim, ComparisonClaim, ActionClaim],
    Field(discriminator="type"),
]

CLAIM_CLASSES: dict[str, type[ClaimBase]] = {
    "spec": SpecClaim, "capability_claim": CapabilityClaim, "market_size": MarketSizeClaim,
    "maturity": MaturityClaim, "priority": PriorityClaim, "comparison": ComparisonClaim,
    "action": ActionClaim,
}


def parse_claim(data: dict[str, Any]) -> ClaimBase:
    return CLAIM_CLASSES[data["type"]].model_validate(data)


# ---------------------------------------------------------------------------
# 엣지 (11종)
# ---------------------------------------------------------------------------

class Edge(BaseModel):
    id: str = Field(default_factory=lambda: new_id("e"))
    src: str
    dst: str
    type: RelationType
    strength: int = Field(default=1, ge=1, le=3)   # 연계 그리드 강도
    derivation: Derivation = Derivation.DERIVED
    condition: str | None = None                   # "if price is right"
    lag_years: float | None = None                 # precedes일 때
    scheme: str | None = None                      # Walton 논증 스킴 태그
    evidence_ids: list[str] = Field(default_factory=list)
    critic_status: CriticStatus = CriticStatus.PENDING
    critic_reason: str | None = None
    proposed_by: Agent = Agent.LINKER
    created_by_doc: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _check(self) -> "Edge":
        if self.src == self.dst:
            raise ValueError("self-loop edge")
        return self


# ---------------------------------------------------------------------------
# Router 판단 로그 · 결측 링크 후보 · 요약
# ---------------------------------------------------------------------------

class StructureTarget(StrEnum):
    EVIDENCE = "evidence"     # ① 근거 청크
    SUMMARY = "summary"       # ② 행 요약 갱신
    GRAPH = "graph"           # ③④ 노드·엣지
    TIME_INDEX = "time_index"  # ⑤ 시간 인덱스


class RouterDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rd"))
    doc_id: str
    proposal_label: str                 # Reader가 낸 후보 라벨
    proposal_type: NodeType
    decision: Literal["merge", "create", "hold"]
    target_node_id: str | None = None   # merge면 기존 노드, create면 새 노드
    candidates: list[tuple[str, float]] = Field(default_factory=list)  # (node_id, similarity)
    structures: list[StructureTarget] = Field(default_factory=list)
    reasoning: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class LinkCandidate(BaseModel):
    """③ 기회 생성용 결측 링크 후보."""
    id: str = Field(default_factory=lambda: new_id("lc"))
    src: str
    dst: str
    type: RelationType
    score: float
    rationale: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class RowSummary(BaseModel):
    """② 역량 행(범주) 단위 계층 요약. 행이 바뀔 때만 증분 갱신."""
    key: str                      # layer:category 또는 node id
    layer: Layer
    text: str
    node_ids: list[str] = Field(default_factory=list)
    claim_count: int = 0
    version: int = 1
    updated_at: datetime = Field(default_factory=utcnow)
    updated_by_doc: str | None = None


# ---------------------------------------------------------------------------
# 이벤트 (append-only, 시각화·재생의 단일 소스)
# ---------------------------------------------------------------------------

class Event(BaseModel):
    seq: int = 0
    ts: datetime = Field(default_factory=utcnow)
    agent: Agent
    type: EventType
    doc_id: str | None = None
    node_id: str | None = None
    edge_id: str | None = None
    claim_id: str | None = None
    message: str = ""                 # UI 한 줄 (i18n 키 + 인자로 재구성 가능)
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 로드맵 (1·3막 출력, KB 스키마의 부분집합)
# ---------------------------------------------------------------------------

class RoadmapOp(StrEnum):
    GROUNDING = "op1_grounding"
    TREND = "op2_trend"
    OPPORTUNITY = "op3_opportunity"
    LINK = "op4_link"
    TIMING = "op5_timing"
    ISSUE = "op6_issue"
    PRIORITY = "op7_priority"
    LLM_PRIOR = "llm_prior"   # KB 없이 모델 사전지식에서 나온 항목


class RoadmapNode(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rn"))
    label: str
    layer: Layer
    category: str | None = None
    start: float | None = None
    end: float | None = None
    description: str = ""
    kb_node_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    produced_by: list[RoadmapOp] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)   # "infeasible", "conflict" 등


class RoadmapEdge(BaseModel):
    src: str
    dst: str
    type: RelationType
    evidence_ids: list[str] = Field(default_factory=list)


class Roadmap(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rm"))
    condition: Literal["initial", "advanced"]
    company: str
    horizon: tuple[float, float]
    model: str
    prompt_hash: str
    nodes: list[RoadmapNode] = Field(default_factory=list)
    edges: list[RoadmapEdge] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    cost_usd: float | None = None


# ---------------------------------------------------------------------------
# 가상 자료의 심은 사실 원장 (평가용)
# ---------------------------------------------------------------------------

class PlantedFact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pf"))
    text: str
    expected_node_type: NodeType
    expected_claim_type: ClaimType | None = None
    expected_layer: Layer | None = None
    planted_in_doc_ids: list[str] = Field(default_factory=list)
    contradicts: str | None = None   # 모순 쌍일 때 상대 사실 id
    notes: str = ""

    @model_validator(mode="after")
    def _layer(self) -> "PlantedFact":
        if self.expected_layer is None:
            self.expected_layer = NODE_LAYER[self.expected_node_type]
        return self
