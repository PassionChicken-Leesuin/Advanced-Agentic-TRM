"""P4 이전 시각화 검증용 데모 run 생성 (LLM 없음, 결정적).

심은 사실 원장에서 노드·주장·엣지·이벤트를 흉내 내어 runs/demo/ 에 쓴다.
Reader→Router→Linker→Critic→Timing 이 실제로 하는 것과 같은 이벤트 순서를 낸다.

python scripts/demo_run.py [--run runs/demo] [--docs 24]
"""
import argparse
import io
import random
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus.synth import load_ledger
from trmkb.schema import (
    Agent, CapabilityClaim, CapabilityNode, ComponentNode, CriticStatus, Derivation, Document, DriverNode,
    Edge, EnablerNode, EventType, Evidence, IssueKind, IssueNode, MilestoneNode, NeedNode, OpportunityNode,
    RelationType, RouterDecision, RowSummary, SourceType, StructureTarget, TimeExpr, NODE_LAYER, NodeType, Layer,
)
from trmkb.store import KBStore

NODE_CLS = {"driver": DriverNode, "need": NeedNode, "opportunity": OpportunityNode, "milestone": MilestoneNode,
            "capability": CapabilityNode, "component": ComponentNode, "enabler": EnablerNode, "issue": IssueNode}
YEAR_HINT = {"pf01": 2025.9, "pf02": 2024.5, "pf06": 2024.2, "pf07": 2025.4, "pf08": 2025.9, "pf09": 2024.4,
             "pf10": 2025.5, "pf11": 2025.6, "pf14": 2026.0, "pf20": 2025.1, "pf21": 2025.4, "pf22": 2026.0,
             "pf23": 2028.0, "pf26": 2025.6, "pf28": 2024.7, "pf32": 2027.0, "pf40": 2025.3}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/demo")
    ap.add_argument("--docs", type=int, default=24)
    args = ap.parse_args()
    run = Path(args.run)
    if run.exists():
        shutil.rmtree(run)
    kb = KBStore(run)
    rng = random.Random(3)
    ledger = load_ledger()
    facts = [f for f in ledger["facts"] if f["expected_node_type"] in NODE_CLS]
    node_by_hint: dict[str, str] = {}
    t = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)

    def tick(sec: float = 0.4) -> None:
        nonlocal t
        t += timedelta(seconds=sec)

    docs = [Document(id=f"demo_doc_{i:02d}", title=f"Internal document {i:02d}",
                     source_type=rng.choice(list(SourceType)), date=date(2024, 1, 1) + timedelta(days=rng.randint(0, 350)),
                     path=f"synthetic/demo_{i:02d}.md", is_synthetic=True) for i in range(1, args.docs + 1)]
    chunks = [facts[i::args.docs] for i in range(args.docs)]
    for doc, fs in zip(docs, chunks):
        kb.add_document(doc)
        ev = kb.events.emit(Agent.SYSTEM, EventType.DOC_STARTED, doc_id=doc.id, title=doc.title); ev.ts = t; tick()
        n_nodes = n_edges = 0
        for f in fs:
            hint = f["node_hint"]
            # Reader → Router
            kb.events.emit(Agent.READER, EventType.NODE_PROPOSED, doc_id=doc.id, label=hint); tick(0.3)
            if hint in node_by_hint:
                nid = node_by_hint[hint]
                kb.log_router(RouterDecision(doc_id=doc.id, proposal_label=hint, proposal_type=NodeType(f["expected_node_type"]),
                                             decision="merge", target_node_id=nid, structures=[StructureTarget.EVIDENCE, StructureTarget.SUMMARY],
                                             reasoning="same capability row"))
                kb.events.emit(Agent.ROUTER, EventType.NODE_MERGED, doc_id=doc.id, node_id=nid, label=hint, target=kb.nodes[nid].label)
            else:
                cls = NODE_CLS[f["expected_node_type"]]
                kwargs = dict(label=hint, category=hint.split(" ")[-1], created_by_doc=doc.id)
                if cls is IssueNode:
                    kwargs["kind"] = IssueKind(f.get("issue_kind", "risk"))
                node = cls(**kwargs)
                y = YEAR_HINT.get(f["id"])
                if y:
                    node.es = y; node.ls = y + 0.5
                kb.upsert_node(node); nid = node.id; node_by_hint[hint] = nid; n_nodes += 1
                kb.log_router(RouterDecision(doc_id=doc.id, proposal_label=hint, proposal_type=NodeType(f["expected_node_type"]),
                                             decision="create", target_node_id=nid, structures=[StructureTarget.GRAPH, StructureTarget.EVIDENCE],
                                             reasoning="no existing row"))
                kb.events.emit(Agent.ROUTER, EventType.NODE_CREATED, doc_id=doc.id, node_id=nid, label=hint)
            tick(0.3)
            ev = kb.add_evidence(Evidence(doc_id=doc.id, text=f["text"], node_ids=[nid]))
            kb.events.emit(Agent.READER, EventType.EVIDENCE_ADDED, doc_id=doc.id, node_id=nid, n=1); tick(0.2)
            c = kb.add_claim(CapabilityClaim(node_id=nid, text=f["text"], measure=f.get("expected_claim_type") or "statement",
                                             value="-", doc_id=doc.id, doc_date=doc.date, evidence_id=ev.id,
                                             time=TimeExpr.year(YEAR_HINT[f["id"]]) if f["id"] in YEAR_HINT else TimeExpr.unknown()))
            kb.events.emit(Agent.ROUTER, EventType.CLAIM_ADDED, doc_id=doc.id, node_id=nid, claim_id=c.id, text=f["text"][:60]); tick(0.2)
            if f["id"] in YEAR_HINT:
                kb.index_time(nid, YEAR_HINT[f["id"]])
                kb.events.emit(Agent.TIMING, EventType.TIME_INDEXED, node_id=nid, label=hint, year=int(YEAR_HINT[f["id"]])); tick(0.2)
            # Linker → Critic
            others = [x for x in kb.nodes.values() if x.id != nid]
            if others and rng.random() < 0.8:
                tgt = rng.choice(others)
                la, lb = NODE_LAYER[NodeType(kb.nodes[nid].type)], NODE_LAYER[NodeType(tgt.type)]
                rel = RelationType.DRIVES if la == Layer.WHY else RelationType.REQUIRES if la == Layer.WHAT else RelationType.ENABLES
                if kb.find_edge(nid, tgt.id) is None:
                    e = kb.upsert_edge(Edge(src=nid, dst=tgt.id, type=rel, evidence_ids=[ev.id], derivation=Derivation.DERIVED,
                                            created_by_doc=doc.id))
                    kb.events.emit(Agent.LINKER, EventType.EDGE_PROPOSED, doc_id=doc.id, edge_id=e.id, src=hint, dst=tgt.label, rel=rel.value); tick(0.4)
                    layer_violation = la == Layer.WHY and lb == Layer.HOW
                    if layer_violation or rng.random() < 0.25:
                        e.critic_status = CriticStatus.REJECTED
                        e.critic_reason = "why→how 층 위반" if layer_violation else "근거 불충분"
                        kb.events.emit(Agent.CRITIC, EventType.EDGE_REJECTED, edge_id=e.id, src=hint, dst=tgt.label, reason=e.critic_reason)
                    else:
                        e.critic_status = CriticStatus.ACCEPTED; n_edges += 1
                        kb.events.emit(Agent.CRITIC, EventType.EDGE_ACCEPTED, edge_id=e.id, src=hint, dst=tgt.label)
                    tick(0.3)
            if f.get("contradicts") and f["contradicts"] in {x["id"] for x in facts}:
                other = next((x for x in facts if x["id"] == f["contradicts"]), None)
                if other and other["node_hint"] in node_by_hint:
                    kb.events.emit(Agent.CRITIC, EventType.CONFLICT_FLAGGED, node_id=nid, a=f["text"][:40], b=other["text"][:40]); tick(0.3)
        # Summarizer · Timing
        layer = rng.choice(list(Layer))
        n_layer = len(kb.nodes_by_layer(layer))
        kb.set_summary(RowSummary(key=f"{layer.value}:all", layer=layer, text=f"{n_layer} nodes", node_ids=[n.id for n in kb.nodes_by_layer(layer)]))
        kb.events.emit(Agent.SUMMARIZER, EventType.SUMMARY_UPDATED, layer=layer.value, n_before=max(0, n_layer - n_nodes), n_after=n_layer); tick(0.3)
        kb.events.emit(Agent.TIMING, EventType.TIME_RECOMPUTED, n=len(kb.nodes)); tick(0.2)
        kb.events.emit(Agent.SYSTEM, EventType.DOC_FINISHED, doc_id=doc.id, title=doc.title, n_nodes=n_nodes, n_edges=n_edges); tick(0.5)
    kb.save()
    # 이벤트 ts 를 가상 시계로 재기록 (재생 간격용)
    _rewrite_ts(run / "events.jsonl")
    print("demo run:", kb.stats())


def _rewrite_ts(path: Path) -> None:
    import json
    lines = path.read_text(encoding="utf-8").splitlines()
    t0 = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
    out = []
    for i, line in enumerate(lines):
        rec = json.loads(line)
        rec["ts"] = (t0 + timedelta(seconds=0.35 * i)).isoformat()
        out.append(json.dumps(rec, ensure_ascii=False))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
