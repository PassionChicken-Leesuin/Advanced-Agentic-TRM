"""
trmkb.store — 평문 JSONL 기반 KB 저장소 + append-only 이벤트 기록기.

run_dir/
  kb/
    nodes.jsonl        역량 노드 (upsert: save() 시 전체 재기록)
    claims.jsonl       주장 타임라인 (append-only)
    edges.jsonl        엣지 (upsert)
    evidence.jsonl     근거 청크 (append-only)
    candidates.jsonl   결측 링크 후보 (append-only)
    summaries/<key>.md 행 요약 (덮어쓰되 version 증가)
    time_index.json    연도 → 노드 id
  documents.jsonl      투입 문서 메타
  events.jsonl         이벤트 (append-only, 단일 소스)
  router_log.jsonl     Router 판단 (append-only)

DB 없음. git에 그대로 들어가는 형태를 유지한다 (naite 방식).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from pydantic import BaseModel

from .i18n import t
from .schema import (
    Agent, ClaimBase, Document, Edge, Event, EventType, Evidence, Layer,
    LinkCandidate, NodeBase, NODE_LAYER, NodeType, RelationType, RouterDecision,
    RowSummary, CriticStatus, parse_claim, parse_node,
)


def _dumps(m: BaseModel) -> str:
    return m.model_dump_json(exclude_none=True)


def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _append_jsonl(path: Path, obj: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(_dumps(obj) + "\n")


def _write_jsonl(path: Path, objs: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for o in objs:
            f.write(_dumps(o) + "\n")
    tmp.replace(path)


class EventLog:
    """append-only 이벤트 기록기. seq는 단조 증가."""

    def __init__(self, path: Path):
        self.path = path
        self._seq = 0
        if path.exists():
            for rec in _read_jsonl(path):
                self._seq = max(self._seq, int(rec.get("seq", 0)))

    def emit(self, agent: Agent, type: EventType, message_key: str | None = None,
             *, doc_id: str | None = None, node_id: str | None = None,
             edge_id: str | None = None, claim_id: str | None = None,
             payload: dict[str, Any] | None = None, **fmt) -> Event:
        self._seq += 1
        payload = payload or {}
        msg = t(message_key or f"ev.{type.value}", **{**payload, **fmt})
        ev = Event(seq=self._seq, agent=agent, type=type, doc_id=doc_id, node_id=node_id,
                   edge_id=edge_id, claim_id=claim_id, message=msg, payload=payload)
        _append_jsonl(self.path, ev)
        return ev

    def read(self) -> Iterator[Event]:
        for rec in _read_jsonl(self.path):
            yield Event.model_validate(rec)

    @property
    def seq(self) -> int:
        return self._seq


class KBStore:
    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.kb_dir = self.run_dir / "kb"
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        (self.kb_dir / "summaries").mkdir(exist_ok=True)

        self.nodes: dict[str, NodeBase] = {}
        self.edges: dict[str, Edge] = {}
        self.claims: dict[str, ClaimBase] = {}
        self.evidence: dict[str, Evidence] = {}
        self.documents: dict[str, Document] = {}
        self.candidates: list[LinkCandidate] = []
        self.summaries: dict[str, RowSummary] = {}
        self.time_index: dict[str, list[str]] = defaultdict(list)  # "2027" -> [node ids]

        self._claims_by_node: dict[str, list[str]] = defaultdict(list)
        self._out: dict[str, set[str]] = defaultdict(set)   # node -> edge ids
        self._in: dict[str, set[str]] = defaultdict(set)

        self.events = EventLog(self.run_dir / "events.jsonl")
        self._load()

    # ------------------------------------------------------------------ IO
    def _load(self) -> None:
        for rec in _read_jsonl(self.kb_dir / "nodes.jsonl"):
            n = parse_node(rec); self.nodes[n.id] = n
        for rec in _read_jsonl(self.kb_dir / "edges.jsonl"):
            e = Edge.model_validate(rec); self._index_edge(e)
        for rec in _read_jsonl(self.kb_dir / "claims.jsonl"):
            c = parse_claim(rec); self._index_claim(c)
        for rec in _read_jsonl(self.kb_dir / "evidence.jsonl"):
            ev = Evidence.model_validate(rec); self.evidence[ev.id] = ev
        for rec in _read_jsonl(self.kb_dir / "candidates.jsonl"):
            self.candidates.append(LinkCandidate.model_validate(rec))
        for rec in _read_jsonl(self.run_dir / "documents.jsonl"):
            d = Document.model_validate(rec); self.documents[d.id] = d
        ti = self.kb_dir / "time_index.json"
        if ti.exists():
            self.time_index = defaultdict(list, json.loads(ti.read_text(encoding="utf-8")))
        for p in (self.kb_dir / "summaries").glob("*.json"):
            s = RowSummary.model_validate_json(p.read_text(encoding="utf-8"))
            self.summaries[s.key] = s

    def save(self) -> None:
        """upsert 성격의 파일(nodes, edges, time_index)을 재기록. 나머지는 append 시점에 기록됨."""
        _write_jsonl(self.kb_dir / "nodes.jsonl", self.nodes.values())
        _write_jsonl(self.kb_dir / "edges.jsonl", self.edges.values())
        (self.kb_dir / "time_index.json").write_text(
            json.dumps(dict(self.time_index), ensure_ascii=False, indent=1), encoding="utf-8")

    # --------------------------------------------------------------- 문서
    def add_document(self, doc: Document) -> Document:
        self.documents[doc.id] = doc
        _append_jsonl(self.run_dir / "documents.jsonl", doc)
        return doc

    # --------------------------------------------------------------- 노드
    def upsert_node(self, node: NodeBase) -> NodeBase:
        node.updated_at = datetime.now(node.updated_at.tzinfo)
        self.nodes[node.id] = node
        return node

    def get_node(self, node_id: str) -> NodeBase:
        return self.nodes[node_id]

    def nodes_by_layer(self, layer: Layer) -> list[NodeBase]:
        return [n for n in self.nodes.values() if NODE_LAYER[NodeType(n.type)] == layer]

    def nodes_by_type(self, ntype: NodeType) -> list[NodeBase]:
        return [n for n in self.nodes.values() if n.type == ntype.value]

    def nodes_by_category(self, layer: Layer, category: str) -> list[NodeBase]:
        return [n for n in self.nodes_by_layer(layer) if n.category == category]

    def children(self, node_id: str) -> list[NodeBase]:
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    # --------------------------------------------------------------- 주장
    def _index_claim(self, c: ClaimBase) -> None:
        self.claims[c.id] = c
        self._claims_by_node[c.node_id].append(c.id)

    def add_claim(self, claim: ClaimBase) -> ClaimBase:
        if claim.node_id not in self.nodes:
            raise KeyError(f"claim references unknown node {claim.node_id}")
        self._index_claim(claim)
        _append_jsonl(self.kb_dir / "claims.jsonl", claim)
        return claim

    def claims_for(self, node_id: str) -> list[ClaimBase]:
        """발언 시점(doc_date) 순 타임라인 (원칙 3)."""
        cs = [self.claims[i] for i in self._claims_by_node.get(node_id, [])]
        return sorted(cs, key=lambda c: (c.doc_date, c.created_at))

    def measures_for(self, node_id: str) -> list[tuple[date, str]]:
        """같은 노드에서 측도(measure)가 어떻게 바뀌었는지 → 지표 교체 탐지."""
        out = []
        for c in self.claims_for(node_id):
            m = getattr(c, "measure", None)
            if m:
                out.append((c.doc_date, m))
        return out

    # --------------------------------------------------------------- 근거
    def add_evidence(self, ev: Evidence) -> Evidence:
        self.evidence[ev.id] = ev
        _append_jsonl(self.kb_dir / "evidence.jsonl", ev)
        return ev

    def evidence_for_node(self, node_id: str) -> list[Evidence]:
        return [e for e in self.evidence.values() if node_id in e.node_ids]

    # --------------------------------------------------------------- 엣지
    def _index_edge(self, e: Edge) -> None:
        self.edges[e.id] = e
        self._out[e.src].add(e.id)
        self._in[e.dst].add(e.id)

    def upsert_edge(self, edge: Edge) -> Edge:
        for nid in (edge.src, edge.dst):
            if nid not in self.nodes:
                raise KeyError(f"edge references unknown node {nid}")
        if edge.id in self.edges:
            old = self.edges[edge.id]
            self._out[old.src].discard(edge.id); self._in[old.dst].discard(edge.id)
        self._index_edge(edge)
        return edge

    def find_edge(self, src: str, dst: str, type: RelationType | None = None) -> Edge | None:
        for eid in self._out.get(src, ()):
            e = self.edges[eid]
            if e.dst == dst and (type is None or e.type == type):
                return e
        return None

    def out_edges(self, node_id: str, *, accepted_only: bool = False,
                  type: RelationType | None = None) -> list[Edge]:
        es = [self.edges[i] for i in self._out.get(node_id, ())]
        if accepted_only:
            es = [e for e in es if e.critic_status == CriticStatus.ACCEPTED]
        if type:
            es = [e for e in es if e.type == type]
        return es

    def in_edges(self, node_id: str, *, accepted_only: bool = False,
                 type: RelationType | None = None) -> list[Edge]:
        es = [self.edges[i] for i in self._in.get(node_id, ())]
        if accepted_only:
            es = [e for e in es if e.critic_status == CriticStatus.ACCEPTED]
        if type:
            es = [e for e in es if e.type == type]
        return es

    def neighbors(self, node_id: str, *, accepted_only: bool = True) -> list[NodeBase]:
        ids = {e.dst for e in self.out_edges(node_id, accepted_only=accepted_only)} | \
              {e.src for e in self.in_edges(node_id, accepted_only=accepted_only)}
        return [self.nodes[i] for i in ids if i in self.nodes]

    def degree(self, node_id: str, *, accepted_only: bool = True) -> int:
        return len(self.out_edges(node_id, accepted_only=accepted_only)) + \
               len(self.in_edges(node_id, accepted_only=accepted_only))

    # --------------------------------------------------------------- 후보 · 요약 · 시간
    def add_candidate(self, cand: LinkCandidate) -> LinkCandidate:
        self.candidates.append(cand)
        _append_jsonl(self.kb_dir / "candidates.jsonl", cand)
        return cand

    def set_summary(self, s: RowSummary) -> RowSummary:
        prev = self.summaries.get(s.key)
        if prev:
            s.version = prev.version + 1
        self.summaries[s.key] = s
        safe = s.key.replace(":", "__").replace("/", "_")
        (self.kb_dir / "summaries" / f"{safe}.json").write_text(_dumps(s), encoding="utf-8")
        (self.kb_dir / "summaries" / f"{safe}.md").write_text(
            f"# {s.key} (v{s.version})\n\n{s.text}\n", encoding="utf-8")
        return s

    def index_time(self, node_id: str, year: float) -> None:
        key = str(int(year))
        if node_id not in self.time_index[key]:
            self.time_index[key].append(node_id)

    def log_router(self, rd: RouterDecision) -> RouterDecision:
        _append_jsonl(self.run_dir / "router_log.jsonl", rd)
        return rd

    # --------------------------------------------------------------- 통계
    def stats(self) -> dict[str, Any]:
        by_layer = {l.value: len(self.nodes_by_layer(l)) for l in Layer}
        by_status = defaultdict(int)
        for e in self.edges.values():
            by_status[e.critic_status.value] += 1
        return {
            "documents": len(self.documents),
            "nodes": len(self.nodes),
            "nodes_by_layer": by_layer,
            "claims": len(self.claims),
            "edges": len(self.edges),
            "edges_by_status": dict(by_status),
            "evidence": len(self.evidence),
            "candidates": len(self.candidates),
            "summaries": len(self.summaries),
            "events": self.events.seq,
        }

    def snapshot(self) -> dict[str, Any]:
        """시각화용 경량 그래프 (노드·수락 엣지)."""
        return {
            "nodes": [
                {"id": n.id, "label": n.label, "type": n.type,
                 "layer": NODE_LAYER[NodeType(n.type)].value, "category": n.category,
                 "es": n.es, "ls": n.ls, "priority": n.priority,
                 "n_claims": len(self._claims_by_node.get(n.id, [])),
                 "n_evidence": len(self.evidence_for_node(n.id))}
                for n in self.nodes.values()
            ],
            "edges": [
                {"id": e.id, "src": e.src, "dst": e.dst, "type": e.type.value,
                 "status": e.critic_status.value, "strength": e.strength}
                for e in self.edges.values()
            ],
        }
