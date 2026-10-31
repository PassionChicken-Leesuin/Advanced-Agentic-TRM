import json
from datetime import date
from pathlib import Path

import pytest

from trmkb.schema import (
    ActorNode, ActorRole, Agent, CapabilityClaim, CapabilityNode, CriticStatus, DriverNode,
    Edge, EventType, Evidence, Document, IssueKind, IssueNode, Layer, MilestoneNode, Modality,
    NodeType, PlantedFact, RelationType, RowSummary, SourceType, SpecClaim, Stage,
    SteepCategory, TimeExpr, TimeExprKind, parse_claim, parse_node,
)
from trmkb.store import KBStore
from trmkb.replay import replay
from trmkb.i18n import t
from trmkb.llm import _extract_json, load_keys


# ---------------------------------------------------------------- schema
def test_node_union_roundtrip():
    d = DriverNode(label="GPS vulnerabilities", steep=SteepCategory.TECHNOLOGICAL, category="technological")
    data = json.loads(d.model_dump_json())
    back = parse_node(data)
    assert isinstance(back, DriverNode) and back.layer == Layer.WHY
    cap = CapabilityNode(label="Photonic interconnect", area="Integration")
    assert cap.layer == Layer.HOW


def test_claim_union_roundtrip():
    c = CapabilityClaim(node_id="n_x", text="#AQ 64 by 2025", measure="#AQ", value="64",
                        value_num=64, time=TimeExpr.year(2025), doc_id="d1", doc_date=date(2020, 12, 9))
    back = parse_claim(json.loads(c.model_dump_json()))
    assert isinstance(back, CapabilityClaim) and back.measure == "#AQ"
    s = SpecClaim(node_id="n_x", text="shoebox", dims={"size": "shoebox", "cost": "£1-10k"},
                  doc_id="d1", doc_date=date(2014, 8, 7))
    assert parse_claim(json.loads(s.model_dump_json())).dims["cost"] == "£1-10k"


def test_time_expr():
    assert TimeExpr.year(2027).midpoint == 2027
    rel = TimeExpr(raw="within 2 years from demo", kind=TimeExprKind.RELATIVE, anchor_id="n_demo", lag_years=2)
    assert rel.midpoint is None
    with pytest.raises(ValueError):
        TimeExpr(raw="bad", kind=TimeExprKind.ABSOLUTE, start=2030, end=2020)


def test_edge_validation():
    with pytest.raises(ValueError):
        Edge(src="a", dst="a", type=RelationType.REQUIRES)


def test_planted_fact_layer_default():
    pf = PlantedFact(text="x", expected_node_type=NodeType.MILESTONE)
    assert pf.expected_layer == Layer.WHAT


# ---------------------------------------------------------------- store
def _build(tmp_path: Path) -> KBStore:
    kb = KBStore(tmp_path / "run")
    doc = kb.add_document(Document(id="doc_2020", title="IonQ roadmap 2020", source_type=SourceType.PRESS_RELEASE,
                                   date=date(2020, 12, 9), path="public/ionq_2020.md"))
    kb.events.emit(Agent.SYSTEM, EventType.DOC_STARTED, doc_id=doc.id, title=doc.title)

    scale = kb.upsert_node(CapabilityNode(id="n_scale", label="Qubit scale", category="scale", area="Quantum Devices"))
    ionq = kb.upsert_node(ActorNode(id="n_ionq", label="IonQ", roles=[ActorRole.SELF]))
    ms = kb.upsert_node(MilestoneNode(id="n_ms", label="#AQ 64", milestone_stage=Stage.FIRST_PRODUCT,
                                      date=TimeExpr.year(2025)))
    issue = kb.upsert_node(IssueNode(id="n_dec", label="Laser vs electronic control", kind=IssueKind.DECISION))
    kb.events.emit(Agent.ROUTER, EventType.NODE_CREATED, node_id=scale.id, label=scale.label)

    ev = kb.add_evidence(Evidence(id="ev1", doc_id=doc.id, text="IonQ targets #AQ 64 by 2025", node_ids=[scale.id]))
    kb.add_claim(CapabilityClaim(node_id=scale.id, text="#AQ 64 by 2025", measure="#AQ", value="64",
                                 time=TimeExpr.year(2025), doc_id=doc.id, doc_date=date(2020, 12, 9),
                                 evidence_id=ev.id, speaker=ionq.id))
    kb.add_claim(CapabilityClaim(node_id=scale.id, text="10,000 physical qubits by 2027", measure="physical qubits",
                                 value="10,000", value_num=10000, time=TimeExpr.year(2027), doc_id=doc.id,
                                 doc_date=date(2025, 6, 10), speaker=ionq.id))
    e = kb.upsert_edge(Edge(id="e1", src=ms.id, dst=scale.id, type=RelationType.REQUIRES, evidence_ids=[ev.id],
                            critic_status=CriticStatus.ACCEPTED))
    kb.upsert_edge(Edge(id="e2", src=issue.id, dst=scale.id, type=RelationType.THREATENS))
    kb.events.emit(Agent.CRITIC, EventType.EDGE_ACCEPTED, edge_id=e.id, src=ms.label, dst=scale.label)
    kb.index_time(ms.id, 2025)
    kb.set_summary(RowSummary(key="how:scale", layer=Layer.HOW, text="scale row summary", node_ids=[scale.id]))
    kb.set_summary(RowSummary(key="how:scale", layer=Layer.HOW, text="scale row summary v2", node_ids=[scale.id]))
    kb.save()
    return kb


def test_store_roundtrip_and_timeline(tmp_path):
    kb = _build(tmp_path)
    # 타임라인은 doc_date 순, 측도 변화(지표 교체)가 보여야 함
    tl = kb.claims_for("n_scale")
    assert [c.doc_date.year for c in tl] == [2020, 2025]
    assert [m for _, m in kb.measures_for("n_scale")] == ["#AQ", "physical qubits"]
    # 재로드
    kb2 = KBStore(tmp_path / "run")
    assert set(kb2.nodes) == {"n_scale", "n_ionq", "n_ms", "n_dec"}
    assert kb2.edges["e1"].critic_status == CriticStatus.ACCEPTED
    assert kb2.find_edge("n_ms", "n_scale", RelationType.REQUIRES) is not None
    assert [n.id for n in kb2.neighbors("n_scale")] == ["n_ms"]          # accepted만
    assert kb2.degree("n_scale", accepted_only=False) == 2
    assert kb2.time_index["2025"] == ["n_ms"]
    assert kb2.summaries["how:scale"].version == 2
    assert kb2.evidence_for_node("n_scale")[0].id == "ev1"
    assert len(kb2.claims_for("n_scale")) == 2
    st = kb2.stats()
    assert st["nodes_by_layer"]["how"] == 1 and st["edges_by_status"] == {"accepted": 1, "pending": 1}
    snap = kb2.snapshot()
    assert any(n["layer"] == "cross" for n in snap["nodes"])


def test_store_rejects_dangling(tmp_path):
    kb = KBStore(tmp_path / "run")
    with pytest.raises(KeyError):
        kb.upsert_edge(Edge(src="nope", dst="nope2", type=RelationType.ENABLES))
    with pytest.raises(KeyError):
        kb.add_claim(SpecClaim(node_id="nope", text="x", doc_id="d", doc_date=date(2024, 1, 1)))


def test_events_seq_and_replay(tmp_path):
    kb = _build(tmp_path)
    evs = list(replay(tmp_path / "run", speed=None))
    assert [e.seq for e in evs] == [1, 2, 3]
    assert evs[0].message.startswith("문서 처리 시작")
    assert evs[2].message == "링크 수락: #AQ 64 → Qubit scale"
    # 재오픈해도 seq 이어짐
    kb2 = KBStore(tmp_path / "run")
    ev = kb2.events.emit(Agent.SYSTEM, EventType.ERROR, msg="boom")
    assert ev.seq == 4 and ev.message == "오류: boom"


def test_i18n_fallback():
    assert t("layer.why") == "Why (시장·동인)"
    assert t("layer.why", lang="en") == "Why (market & drivers)"
    assert t("agent.reader", lang="en") == "Reader"   # en 미정의 키 → ko 폴백
    assert t("node.actor", lang="en") == "Actor"
    assert t("no.such.key") == "no.such.key"


# ---------------------------------------------------------------- llm helpers (no network)
def test_extract_json():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('text before {"a": [1,2]} after') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        _extract_json("nothing here")
    # 잘린 출력 복구: 마지막 완결 원소까지
    truncated = '{"proposals": [{"label": "a", "n": 1}, {"label": "b", "n": 2}, {"label": "c", "n'
    assert _extract_json(truncated) == {"proposals": [{"label": "a", "n": 1}, {"label": "b", "n": 2}]}


def test_load_keys_order(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("Open_Router_key10=k10\nOpen_Router_key2=k2\nOpen_Router_key1=k1\nOTHER=x\n", encoding="utf-8")
    assert load_keys(env) == ["k1", "k2", "k10"]
