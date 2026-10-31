"""
trmkb.pipeline — 문서 1건 = 1 에피소드. Reader → Router → (Critic 모순) → Linker → Critic → Timing → Summarizer.
모든 상태 변화는 events.jsonl 에 기록되어 시각화·재생·평가의 단일 소스가 된다.
재개 가능: documents.jsonl 에 이미 있는 문서는 건너뛴다.
"""
from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .agents.chunker import chunk_document
from .agents.critic import Critic
from .agents.embed import Index
from .agents.linker import Linker
from .agents.reader import Reader, locate_quote
from .agents.router import Router, build_claim, row_key
from .agents.summarizer import Summarizer
from .agents import timing as timing_mod
from .corpus.common import CORPUS_ROOT, read_doc
from .llm import LLM
from .schema import Agent, CriticStatus, Document, EventType, Evidence, NODE_LAYER, NodeType, SourceType
from .store import KBStore


@dataclass
class PipelineConfig:
    name: str = "A"
    model_triage: str | None = "openai/gpt-4.1-nano"
    model_reader: str = "openai/gpt-4.1-mini"
    model_router: str = "openai/gpt-4.1-mini"
    model_linker: str = "openai/gpt-4.1-mini"
    model_critic: str = "anthropic/claude-sonnet-4.6"
    model_summarizer: str = "openai/gpt-4.1-mini"
    chunk_chars: int = 2200
    max_chunks_per_doc: int = 14
    max_proposals_per_chunk: int = 10
    summarizer_rows_per_doc: int = 4
    merge_hi: float = 0.80
    merge_lo: float = 0.55
    conflict_check: bool = True
    linker: bool = True

    def dump(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")


@dataclass
class EpisodeStats:
    doc_id: str
    chunks: int = 0
    chunks_relevant: int = 0
    proposals: int = 0
    nodes_created: int = 0
    nodes_merged: int = 0
    claims: int = 0
    edges_proposed: int = 0
    edges_accepted: int = 0
    edges_rejected: int = 0
    conflicts: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None


class Pipeline:
    def __init__(self, run_dir: str | Path, cfg: PipelineConfig, llm: LLM | None = None, corpus_root: Path = CORPUS_ROOT):
        self.run_dir = Path(run_dir)
        self.cfg = cfg
        self.kb = KBStore(self.run_dir)
        self.llm = llm or LLM()
        self.corpus_root = corpus_root
        self.index = Index()
        self.reader = Reader(self.llm, cfg.model_reader, cfg.model_triage)
        self.router = Router(self.llm, cfg.model_router, self.kb, self.index, merge_hi=cfg.merge_hi, merge_lo=cfg.merge_lo)
        self.linker = Linker(self.llm, cfg.model_linker, self.kb, self.index)
        self.critic = Critic(self.llm, cfg.model_critic, self.kb)
        self.summarizer = Summarizer(self.llm, cfg.model_summarizer, self.kb)
        cfg.dump(self.run_dir / "config.json")
        self.stats_path = self.run_dir / "episodes.jsonl"

    # ------------------------------------------------------------------
    def load_corpus_doc(self, rel_path: str) -> tuple[Document, str]:
        fm, body = read_doc(self.corpus_root / rel_path)
        doc = Document(id=fm["id"], title=fm["title"], source_type=SourceType(fm["source_type"]),
                       date=date.fromisoformat(str(fm["date"])), path=rel_path, url=fm.get("url"),
                       is_synthetic=bool(fm.get("is_synthetic")), planted_fact_ids=fm.get("planted_fact_ids") or [],
                       n_chars=len(body))
        return doc, body, fm.get("actor") or "IonQ"

    def run(self, rel_paths: list[str], *, stop_on_error: bool = False) -> list[EpisodeStats]:
        out = []
        for rp in rel_paths:
            doc, body, actor = self.load_corpus_doc(rp)
            if doc.id in self.kb.documents:
                continue
            st = self.episode(doc, body, actor)
            out.append(st)
            with self.stats_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(st), ensure_ascii=False) + "\n")
            if st.error and stop_on_error:
                break
        self.kb.save()
        self.llm.ledger.dump(self.run_dir / "cost.json")
        return out

    # ------------------------------------------------------------------
    def episode(self, doc: Document, body: str, actor: str) -> EpisodeStats:
        cfg, kb, ev = self.cfg, self.kb, self.kb.events
        st = EpisodeStats(doc_id=doc.id)
        t0 = time.time(); cost0 = self.llm.ledger.total_usd
        kb.add_document(doc)
        ev.emit(Agent.SYSTEM, EventType.DOC_STARTED, doc_id=doc.id, title=doc.title, source_type=doc.source_type.value,
                date=doc.date.isoformat(), is_synthetic=doc.is_synthetic)
        touched: dict[str, None] = {}
        excerpts: list[str] = []
        try:
            chunks = chunk_document(body, doc.source_type.value, cfg.chunk_chars, cfg.max_chunks_per_doc)
            st.chunks = len(chunks)
            for ch in chunks:
                tri = self.reader.triage(ch, doc_date=doc.date, source_type=doc.source_type.value)
                if not tri.relevant:
                    continue
                st.chunks_relevant += 1
                props = self.reader.extract(ch, title=doc.title, doc_date=doc.date, source_type=doc.source_type.value, actor=actor)
                props = props[: cfg.max_proposals_per_chunk]
                st.proposals += len(props)
                for p in props:
                    quote, span = locate_quote(ch, p.evidence_quote)
                    ev.emit(Agent.READER, EventType.NODE_PROPOSED, doc_id=doc.id, label=p.label, node_type=p.node_type)
                    rd, node, new = self.router.route(p, doc_id=doc.id, quote=quote)
                    layer = NODE_LAYER[NodeType(node.type)].value
                    if new:
                        st.nodes_created += 1
                        ev.emit(Agent.ROUTER, EventType.NODE_CREATED, doc_id=doc.id, node_id=node.id, label=node.label,
                                node_type=node.type, layer=layer, category=node.category or "")
                    else:
                        st.nodes_merged += 1
                        ev.emit(Agent.ROUTER, EventType.NODE_MERGED, doc_id=doc.id, node_id=node.id, label=p.label, target=node.label)
                    ev.emit(Agent.ROUTER, EventType.ROUTER_DECISION, doc_id=doc.id, node_id=node.id, decision=rd.decision,
                            label=p.label, structures=",".join(s.value for s in rd.structures), reasoning=rd.reasoning[:200])
                    evd = kb.add_evidence(Evidence(doc_id=doc.id, text=quote, span=span, node_ids=[node.id]))
                    ev.emit(Agent.READER, EventType.EVIDENCE_ADDED, doc_id=doc.id, node_id=node.id, n=1, evidence_id=evd.id)
                    excerpts.append(quote)
                    claim = build_claim(p, node.id, doc.id, doc.date, evd.id)
                    if claim:
                        older = kb.claims_for(node.id)
                        kb.add_claim(claim); st.claims += 1
                        evd.claim_ids.append(claim.id)
                        ev.emit(Agent.ROUTER, EventType.CLAIM_ADDED, doc_id=doc.id, node_id=node.id, claim_id=claim.id,
                                text=claim.text[:80], claim_type=claim.type, modality=claim.modality.value,
                                time_raw=claim.time.raw, time_start=claim.time.start)
                        if claim.time.start is not None:
                            kb.index_time(node.id, claim.time.start)
                            ev.emit(Agent.TIMING, EventType.TIME_INDEXED, doc_id=doc.id, node_id=node.id, label=node.label,
                                    year=int(claim.time.start))
                        if cfg.conflict_check and older and not new and re.search(r"\d", claim.text):
                            for cid, reason in self.critic.check_conflict(node, claim, older):
                                claim.conflicts_with.append(cid)
                                if "conflict" not in node.flags:
                                    node.flags.append("conflict"); kb.upsert_node(node)
                                st.conflicts += 1
                                ev.emit(Agent.CRITIC, EventType.CONFLICT_FLAGGED, doc_id=doc.id, node_id=node.id, claim_id=claim.id,
                                        a=claim.text[:60], b=kb.claims[cid].text[:60], reason=reason[:200], other_claim_id=cid)
                    touched[node.id] = None
            # Linker → Critic
            if cfg.linker and touched:
                tnodes = [kb.nodes[i] for i in touched]
                proposals = self.linker.propose(tnodes, doc_id=doc.id, title=doc.title, doc_date=doc.date, excerpts="\n".join(excerpts))
                st.edges_proposed = len(proposals)
                for edge, quote in proposals:
                    kb.upsert_edge(edge)
                    ev.emit(Agent.LINKER, EventType.EDGE_PROPOSED, doc_id=doc.id, edge_id=edge.id, src=kb.nodes[edge.src].label,
                            dst=kb.nodes[edge.dst].label, rel=edge.type.value, scheme=edge.scheme or "")
                judged = self.critic.judge_edges(proposals)
                for edge, reason in judged:
                    if edge.critic_status == CriticStatus.ACCEPTED:
                        st.edges_accepted += 1
                        # 근거 부착
                        evd = kb.add_evidence(Evidence(doc_id=doc.id, text=next((q for e, q in proposals if e.id == edge.id), ""),
                                                       edge_ids=[edge.id], node_ids=[edge.src, edge.dst]))
                        edge.evidence_ids.append(evd.id)
                        ev.emit(Agent.CRITIC, EventType.EDGE_ACCEPTED, doc_id=doc.id, edge_id=edge.id, src=kb.nodes[edge.src].label,
                                dst=kb.nodes[edge.dst].label, reason=reason[:200])
                    elif edge.critic_status == CriticStatus.REJECTED:
                        st.edges_rejected += 1
                        ev.emit(Agent.CRITIC, EventType.EDGE_REJECTED, doc_id=doc.id, edge_id=edge.id, src=kb.nodes[edge.src].label,
                                dst=kb.nodes[edge.dst].label, reason=reason[:200])
                    kb.upsert_edge(edge)
            # Timing
            tr = timing_mod.recompute(kb)
            ev.emit(Agent.TIMING, EventType.TIME_RECOMPUTED, doc_id=doc.id, n=tr["changed"], with_time=tr["with_time"],
                    infeasible=len(tr["infeasible"]))
            # Summarizer (dirty rows only) — 요약 실패는 에피소드를 실패시키지 않는다 (행은 dirty로 남겨 다음 문서에서 재시도)
            dirty = set(self.router.dirty_rows); self.router.dirty_rows.clear()
            try:
                for s, nb, na in self.summarizer.refresh(dirty, doc_id=doc.id, max_rows=cfg.summarizer_rows_per_doc):
                    ev.emit(Agent.SUMMARIZER, EventType.SUMMARY_UPDATED, doc_id=doc.id, layer=s.key, n_before=nb, n_after=na,
                            version=s.version)
            except Exception as e:  # noqa: BLE001
                self.router.dirty_rows |= dirty
                ev.emit(Agent.SUMMARIZER, EventType.ERROR, doc_id=doc.id, msg=f"summarizer: {e}"[:200])
        except Exception as e:  # noqa: BLE001
            st.error = f"{type(e).__name__}: {e}"
            ev.emit(Agent.SYSTEM, EventType.ERROR, doc_id=doc.id, msg=st.error[:300])
            (self.run_dir / "errors.log").open("a", encoding="utf-8").write(f"{doc.id}\n{traceback.format_exc()}\n")
        finally:
            kb.save()
        st.seconds = round(time.time() - t0, 1)
        st.cost_usd = round(self.llm.ledger.total_usd - cost0, 5)
        ev.emit(Agent.SYSTEM, EventType.DOC_FINISHED, doc_id=doc.id, title=doc.title, n_nodes=st.nodes_created,
                n_edges=st.edges_accepted, seconds=st.seconds, cost_usd=st.cost_usd)
        return st
