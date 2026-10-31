import json
from pathlib import Path

from fastapi.testclient import TestClient

from trmkb.roadmap import generate as G
from trmkb.schema import Layer, RoadmapOp


def _out():
    return G.RoadmapOut.model_validate({
        "nodes": [
            {"id": "a", "label": "PQC demand", "layer": "why", "category": "security", "start": 2025, "end": 2028},
            {"id": "b", "label": "Tempo", "layer": "what", "category": "scale", "start": 2026.5, "end": 2025.5,
             "evidence_ids": ["ev1"], "flags": ["infeasible"]},
            {"id": "c", "label": "Photonic interconnect", "layer": "how", "category": "interconnect", "start": 2024, "end": 2031},
        ],
        "edges": [{"src": "a", "dst": "b", "type": "drives"}, {"src": "b", "dst": "c", "type": "requires"},
                  {"src": "b", "dst": "c", "type": "requires"}, {"src": "c", "dst": "c", "type": "precedes"}],
    })


def test_prompt_is_fixed_and_context_only_varies():
    h1, h2 = G.prompt_hash(), G.prompt_hash()
    assert h1 == h2 and len(h1) == 16
    p0 = G.build_user_prompt(None)
    p1 = G.build_user_prompt("[ev1] IonQ targets #AQ 64 by 2025")
    assert p0 != p1 and p1.startswith(p0.split(G.OUTPUT_SPEC)[0]) and "ev1" in p1
    assert "evidence_ids" in p0 and "2025-2030" in p0


def test_to_roadmap_clamps_dedupes_and_tags_ops():
    rm = G.to_roadmap(_out(), condition="advanced", model="m",
                      ops_by_evidence={"ev1": [RoadmapOp.GROUNDING, RoadmapOp.TIMING]})
    assert len(rm.nodes) == 3 and len(rm.edges) == 2          # 중복 엣지·자기 루프 제거
    c = next(n for n in rm.nodes if n.label.startswith("Photonic"))
    assert (c.start, c.end) == (2025.0, 2030.0)               # 지평으로 클램프
    b = next(n for n in rm.nodes if n.label == "Tempo")
    assert b.start <= b.end and b.produced_by == [RoadmapOp.GROUNDING, RoadmapOp.TIMING] and "infeasible" in b.flags
    a = next(n for n in rm.nodes if n.layer == Layer.WHY)
    assert a.produced_by == [RoadmapOp.LLM_PRIOR]
    s = G.summary(rm)
    assert s["by_layer"] == {"why": 1, "what": 1, "how": 1, "resource": 0, "cross": 0} and s["with_evidence"] == 1


def test_roadmap_save_load(tmp_path: Path):
    rm = G.to_roadmap(_out(), condition="initial", model="m")
    p = G.save(rm, tmp_path)
    assert p.name == "roadmap_initial.json" and G.load(tmp_path, "initial").id == rm.id
    assert G.load(tmp_path, "advanced") is None


def test_server_endpoints(tmp_path: Path, monkeypatch):
    import viz.server as S
    from trmkb.schema import Agent, CapabilityNode, Document, EventType, SourceType
    from trmkb.store import KBStore
    from datetime import date
    monkeypatch.setattr(S, "RUNS", tmp_path)
    kb = KBStore(tmp_path / "r1")
    kb.add_document(Document(id="d", title="Doc", source_type=SourceType.BLOG, date=date(2024, 1, 1), path="x.md"))
    n = kb.upsert_node(CapabilityNode(id="n1", label="Interconnect"))
    kb.events.emit(Agent.SYSTEM, EventType.DOC_STARTED, doc_id="d", title="Doc")
    kb.events.emit(Agent.ROUTER, EventType.NODE_CREATED, node_id=n.id, label=n.label)
    kb.save()
    G.save(G.to_roadmap(_out(), condition="initial", model="m"), tmp_path / "r1")
    c = TestClient(S.app)
    assert c.get("/").status_code == 200
    runs = c.get("/api/runs").json()
    assert runs[0]["run"] == "r1" and runs[0]["events"] == 2 and runs[0]["roadmaps"] == ["initial"]
    snap = c.get("/api/runs/r1/snapshot").json()
    assert snap["nodes"][0]["layer"] == "how" and snap["documents"][0]["id"] == "d"
    evs = c.get("/api/runs/r1/events?since=1").json()
    assert len(evs) == 1 and evs[0]["payload"]["label"] == "Interconnect" and evs[0]["message"] == "노드 생성: Interconnect"
    body = c.get("/api/runs/r1/stream?speed=0").text
    assert "event: hello" in body and body.count("event: kb") == 2 and "event: done" in body
    rms = c.get("/api/runs/r1/roadmaps").json()
    assert rms["initial"]["summary"]["nodes"] == 3
    assert c.get("/api/runs/nope/snapshot").status_code == 404
    assert c.get("/api/i18n?lang=en").json()["layer.why"].startswith("Why (market")
