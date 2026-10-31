"""
trmkb.eval.contrast — 대조 과업 3종 (연구구상 §5.5 상호작용 효과).
같은 KB 에서 S0(평면 RAG) vs S4(제안 구조) 컨텍스트로 세 과업을 풀고, 과업별 이득(S4−S0)을 로드맵 과업의 이득과 비교한다.

  T1 사실 QA        : 가상 사실 42건 → 질문/정답. 조건별 검색 컨텍스트로 답하고 LLM 판정(correct/partial/wrong). 지표: 정답률
  T2 트렌드 요약     : 역량 행 8개에 대해 "2020→2024 궤적" 요약. 판정: 행의 주장 타임라인 대비 포괄성·연대순 정확성 1~5
  T3 기회 목록       : 로드맵 기회 10개 제안. 판정: 근거성(컨텍스트 id 인용) · 구체성 · 공식 2025판 마일스톤과의 일치 수

컨텍스트: S0 = 질문별 근거 청크 top-k, S4 = 질문별 노드 검색 → 노드·주장·근거·링크·시간.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from ..agents.embed import embed
from ..corpus.synth import load_ledger
from ..llm import LLM
from ..schema import CriticStatus, NODE_LAYER, NodeType
from ..store import KBStore
from .alignment import load_gt

ANSWER_MODEL = "openai/gpt-4.1"
JUDGE_MODEL = "openai/gpt-4.1-mini"


# ---------------------------------------------------------------- 조건별 질문 컨텍스트
class _Idx:
    def __init__(self, kb: KBStore):
        self.kb = kb
        self.evs = [e for e in kb.evidence.values() if e.text]
        self.ev_vecs = embed([e.text[:600] for e in self.evs]) if self.evs else np.zeros((0, 384))
        self.nodes = list(kb.nodes.values())
        self.node_vecs = embed([f"{n.label}. {n.description or ''}" for n in self.nodes]) if self.nodes else np.zeros((0, 384))

    def s0(self, query: str, k: int = 12) -> str:
        q = embed([query])[0]
        order = np.argsort(-(self.ev_vecs @ q))[:k]
        return "\n".join(f"- {self.evs[int(i)].id}: \"{self.evs[int(i)].text[:400]}\"" for i in order)

    def s4(self, query: str, k: int = 8) -> str:
        kb = self.kb
        q = embed([query])[0]
        order = np.argsort(-(self.node_vecs @ q))[:k]
        parts = []
        for i in order:
            n = self.nodes[int(i)]
            layer = NODE_LAYER[NodeType(n.type)].value
            tm = f" t={n.es:.1f}" if n.es is not None else ""
            parts.append(f"- {n.id} | {layer}/{n.type} | {n.label}{tm} | row={n.category or '-'}")
            for c in kb.claims_for(n.id)[-4:]:
                parts.append(f"    claim {c.id} ({c.doc_date.year}/{c.modality.value}): {c.text[:220]}" + (" [CONFLICT]" if c.conflicts_with else ""))
            for ev in kb.evidence_for_node(n.id)[:1]:
                parts.append(f"    evidence {ev.id}: \"{ev.text[:200]}\"")
            for e in kb.out_edges(n.id, accepted_only=True)[:4]:
                parts.append(f"    link {e.id}: {n.label} --{e.type.value}--> {kb.nodes[e.dst].label}")
            for e in kb.in_edges(n.id, accepted_only=True)[:3]:
                parts.append(f"    link {e.id}: {kb.nodes[e.src].label} --{e.type.value}--> {n.label}")
            key = f"{layer}:{n.category or 'uncategorized'}"
            s = kb.summaries.get(key)
            if s:
                parts.append(f"    row summary ({key}): {s.text[:300]}")
        return "\n".join(parts)


# ---------------------------------------------------------------- T1
class QA(BaseModel):
    question: str
    answer: str


class QJudge(BaseModel):
    verdict: str  # correct / partial / wrong
    reason: str = ""


def t1_fact_qa(kb: KBStore, idx: _Idx, llm: LLM, processed: set[str]) -> dict:
    facts = [f for f in load_ledger()["facts"] if any(d in processed for d in f.get("planted_in_doc_ids", []))]
    results = []
    for f in facts:
        qa = llm.structured(JUDGE_MODEL, "Write one specific factual question whose answer is the given fact. JSON only.",
                            f"Fact: {f['text']}\nReturn JSON: {{\"question\": str, \"answer\": str}}", QA, purpose="t1_q", max_tokens=200)
        row = {"fact_id": f["id"], "question": qa.question, "gold": f["text"]}
        for cond in ("S0", "S4"):
            ctx = idx.s0(qa.question) if cond == "S0" else idx.s4(qa.question)
            ans = llm.complete(ANSWER_MODEL, "Answer the question using ONLY the context. If the context does not contain the answer, say 'not in context'. Be specific with numbers and dates.",
                               f"Context:\n{ctx}\n\nQuestion: {qa.question}", purpose=f"t1_answer_{cond}", max_tokens=300)
            j = llm.structured(JUDGE_MODEL, "Grade an answer against the gold fact. JSON only.",
                               f"Gold fact: {f['text']}\nAnswer: {ans}\ncorrect = states the same fact with the key numbers/dates; partial = right entity but a key number/date missing or wrong; wrong = otherwise or 'not in context'.\nReturn JSON: {{\"verdict\": \"correct\"|\"partial\"|\"wrong\", \"reason\": str}}",
                               QJudge, purpose="t1_judge", max_tokens=150)
            row[cond] = {"answer": ans[:300], "verdict": j.verdict}
        results.append(row)
    def score(cond, lenient=False):
        ok = sum(1 for r in results if r[cond]["verdict"] == "correct" or (lenient and r[cond]["verdict"] == "partial"))
        return round(ok / max(1, len(results)), 3)
    return {"n": len(results), "S0": score("S0"), "S4": score("S4"), "S0_lenient": score("S0", True), "S4_lenient": score("S4", True),
            "gain": round(score("S4") - score("S0"), 3), "results": results}


# ---------------------------------------------------------------- T2
class TJudge(BaseModel):
    coverage: int = Field(ge=1, le=5)
    chronology: int = Field(ge=1, le=5)
    grounded: int = Field(ge=1, le=5)
    reason: str = ""


def t2_trend_summary(kb: KBStore, idx: _Idx, llm: LLM, n_rows: int = 8) -> dict:
    rows = sorted(kb.summaries.values(), key=lambda s: -s.claim_count)[:n_rows]
    results = []
    for s in rows:
        node_ids = [i for i in s.node_ids if i in kb.nodes]
        timeline = "\n".join(f"- {c.doc_date}: {c.text[:200]}" for i in node_ids for c in kb.claims_for(i))[:6000]
        query = f"trend of {s.key.split(':', 1)[1]} for IonQ over time"
        row = {"row": s.key, "n_claims": s.claim_count}
        for cond in ("S0", "S4"):
            ctx = idx.s0(query, k=15) if cond == "S0" else idx.s4(query, k=10)
            out = llm.complete(ANSWER_MODEL, "You summarize how a technology-roadmap row evolved over time, using only the context. Cite years.",
                               f"Context:\n{ctx}\n\nTask: In <=150 words, describe how '{s.key}' evolved from the earliest to the latest statement: what was claimed when, what changed (targets, metrics, dates), and any contradictions.",
                               purpose=f"t2_{cond}", max_tokens=400)
            j = llm.structured(JUDGE_MODEL, "Grade a trend summary against the reference claim timeline. JSON only.",
                               f"Reference timeline (date: claim):\n{timeline}\n\nSummary:\n{out}\n\nScore 1-5: coverage (how many reference claims are reflected), chronology (order and dates correct), grounded (no statements absent from the reference).\nReturn JSON: {{\"coverage\": int, \"chronology\": int, \"grounded\": int, \"reason\": str}}",
                               TJudge, purpose="t2_judge", max_tokens=200)
            row[cond] = {"summary": out[:400], "coverage": j.coverage, "chronology": j.chronology, "grounded": j.grounded,
                         "score": round((j.coverage + j.chronology + j.grounded) / 3, 2)}
        results.append(row)
    def mean(cond):
        return round(float(np.mean([r[cond]["score"] for r in results])), 3) if results else None
    return {"n": len(results), "S0": mean("S0"), "S4": mean("S4"), "gain": round((mean("S4") or 0) - (mean("S0") or 0), 3), "results": results}


# ---------------------------------------------------------------- T3
class Opp(BaseModel):
    title: str
    why: str = ""
    refs: list[str] = Field(default_factory=list)


class OppList(BaseModel):
    opportunities: list[Opp] = Field(default_factory=list)


class OJudge(BaseModel):
    specific: int = Field(ge=1, le=5)
    grounded: int = Field(ge=1, le=5)
    gt_matches: int = 0
    reason: str = ""


def t3_opportunities(kb: KBStore, idx: _Idx, llm: LLM) -> dict:
    gt = [g for g in load_gt() if g["version"] == "2025"]
    gt_txt = "\n".join(f"- {g['label']}: {g['description'][:120]}" for g in gt)
    query = "IonQ unaddressed market drivers, customer needs without products, products without enabling technology, open questions"
    results = {}
    for cond in ("S0", "S4"):
        ctx = idx.s0(query, k=40) if cond == "S0" else idx.s4(query, k=20)
        if cond == "S4":
            from ..roadmap.retrieve import structural_gaps
            gaps = structural_gaps(kb)[:25]
            ctx += "\n## Structural gaps\n" + "\n".join(f"- gap/{k}: {n.id} \"{n.label}\" — {note[:120]}" for k, n, note in gaps)
        out = llm.structured(ANSWER_MODEL, "You propose roadmap opportunities for a company from a knowledge context. JSON only.",
                             f"Context:\n{ctx}\n\nPropose 10 concrete roadmap opportunities for IonQ 2025-2030 (new products, capabilities, partnerships, or responses to drivers) that the context supports. Each: title, why (one sentence), refs (ids from the context).\nReturn JSON: {{\"opportunities\": [{{\"title\": str, \"why\": str, \"refs\": [str]}}]}}",
                             OppList, purpose=f"t3_{cond}", max_tokens=1500)
        valid_ids = set(kb.nodes) | set(kb.claims) | set(kb.evidence) | set(kb.edges)
        grounded_rate = round(sum(1 for o in out.opportunities if any(r in valid_ids for r in o.refs)) / max(1, len(out.opportunities)), 3)
        j = llm.structured(JUDGE_MODEL, "Grade a list of roadmap opportunities. JSON only.",
                           f"Opportunities:\n" + "\n".join(f"- {o.title}: {o.why}" for o in out.opportunities) +
                           f"\n\nOfficial 2025 roadmap milestones (published after the knowledge cutoff):\n{gt_txt}\n\nScore 1-5 specific (concrete, actionable, IonQ-specific), grounded (follows from stated drivers/needs rather than generic), and count gt_matches = how many opportunities correspond to an official milestone.\nReturn JSON: {{\"specific\": int, \"grounded\": int, \"gt_matches\": int, \"reason\": str}}",
                           OJudge, purpose="t3_judge", max_tokens=250)
        results[cond] = {"n": len(out.opportunities), "ref_grounded_rate": grounded_rate, "specific": j.specific, "grounded": j.grounded,
                         "gt_matches": j.gt_matches, "score": round((j.specific + j.grounded) / 2 + grounded_rate * 2 + j.gt_matches * 0.5, 2),
                         "items": [o.model_dump() for o in out.opportunities]}
    return {"S0": results["S0"]["score"], "S4": results["S4"]["score"], "gain": round(results["S4"]["score"] - results["S0"]["score"], 3), "detail": results}


def evaluate(run_dir: str | Path, llm: LLM) -> dict:
    kb = KBStore(run_dir)
    idx = _Idx(kb)
    processed = set(kb.documents)
    cost0 = llm.ledger.total_usd
    out = {"T1_fact_qa": t1_fact_qa(kb, idx, llm, processed), "T2_trend_summary": t2_trend_summary(kb, idx, llm),
           "T3_opportunities": t3_opportunities(kb, idx, llm)}
    out["cost_usd"] = round(llm.ledger.total_usd - cost0, 4)
    Path(run_dir, "eval_contrast.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
