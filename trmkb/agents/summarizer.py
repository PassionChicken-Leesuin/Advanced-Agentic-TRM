"""
Summarizer — 역량 행(layer:category) 단위 계층 요약을 바뀐 행만 증분 갱신 (연산 ②).
입력: 행의 노드들과 각 노드의 주장 타임라인(발언 시점 순). 출력: ≤150단어의 현재 상태·궤적·지표 변화·상충 서술.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..llm import LLM
from ..schema import Layer, RowSummary
from ..store import KBStore
from .router import row_key

SUM_SYSTEM = "You write concise, factual roadmap-row summaries for a technology-roadmap knowledge base. JSON only."
SUM_USER = """Row: {key}
Rows group knowledge-base nodes that share a layer and category. Summarize this row in <= 150 words for a roadmap analyst:
current state, trajectory over time (what was said when), any metric changes (e.g. a measure replaced by another),
and conflicts between sources. Cite nodes by label and dates by year. Do not add outside knowledge.

Nodes and their claim timelines (date: [modality] text):
{body}

Previous summary (may be outdated): {prev}

Return JSON: {{"text": str}}"""


class SumOut(BaseModel):
    text: str


class Summarizer:
    def __init__(self, llm: LLM, model: str, kb: KBStore):
        self.llm, self.model, self.kb = llm, model, kb

    def refresh(self, keys: set[str], *, doc_id: str, max_rows: int = 4) -> list[tuple[RowSummary, int, int]]:
        done = []
        for key in sorted(keys)[:max_rows]:
            layer_s, cat = key.split(":", 1)
            layer = Layer(layer_s)
            nodes = [n for n in self.kb.nodes_by_layer(layer) if row_key(n) == key]
            if not nodes:
                continue
            body = []
            for n in nodes[:12]:
                cl = self.kb.claims_for(n.id)
                lines = "\n".join(f"    {c.doc_date}: [{c.modality.value}] {c.text[:220]}" for c in cl[-8:])
                body.append(f"- {n.label} ({n.type}{', ES ' + str(round(n.es, 1)) if n.es else ''}):\n{lines or '    (no claims)'}")
            prev = self.kb.summaries.get(key)
            out = self.llm.structured(self.model, SUM_SYSTEM,
                                      SUM_USER.format(key=key, body="\n".join(body), prev=prev.text if prev else "(none)"),
                                      SumOut, purpose="summarizer", max_tokens=1200)
            n_before = len(prev.node_ids) if prev else 0
            s = self.kb.set_summary(RowSummary(key=key, layer=layer, text=out.text, node_ids=[n.id for n in nodes],
                                               claim_count=sum(len(self.kb.claims_for(n.id)) for n in nodes), updated_by_doc=doc_id))
            done.append((s, n_before, len(nodes)))
        return done
