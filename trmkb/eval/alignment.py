"""
trmkb.eval.alignment — 생성 로드맵 ↔ IonQ 공식 로드맵 마일스톤 정렬 (연구계획 §1.3·§4 정렬 절차).

정답 마일스톤마다: 로드맵 노드 임베딩 상위 k 후보 → LLM 판정
  match      : 같은 마일스톤/역량을 말함 (수치·연도는 달라도 됨)
  refined    : 로드맵이 더 구체적
  generalized: 로드맵이 더 포괄적 (범주 수준)
  missed     : 없음
지표: recall(match+refined[+generalized]) 전체/판별(2020·2025)/범주별, 시점 MAE(연, match·refined),
      foresight = 2025판 전용 마일스톤 recall (cutoff 이전 KB가 변화를 앞서 봤는가).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from ..agents.embed import embed
from ..llm import LLM
from ..schema import Roadmap

GT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ground_truth" / "ionq_roadmap_milestones.json"

JUDGE_SYSTEM = "You align a generated technology roadmap against a company's official roadmap milestones. JSON only."
JUDGE_USER = """Official milestone: "{label}" — {desc} (year {year}, row {cat})

Generated roadmap candidates:
{cands}

Does any candidate refer to the same milestone or capability (numbers and years may differ)? Classify:
- match: same milestone/capability at similar specificity
- refined: candidate is more specific than the official milestone
- generalized: candidate covers it only at a broad category level (e.g. "error correction" for "logical error rate < 1e-12")
- missed: none

Return JSON: {{"match": int|null, "category": "match"|"refined"|"generalized"|"missed", "reason": str (<=20 words)}}"""


class Judge(BaseModel):
    match: int | None = None
    category: str = "missed"
    reason: str = ""


def load_gt() -> list[dict]:
    return json.loads(GT_PATH.read_text(encoding="utf-8"))["milestones"]


def align(rm: Roadmap, llm: LLM, *, model: str = "openai/gpt-4.1-mini", k: int = 5, min_sim: float = 0.3,
          include_reported: bool = True) -> dict:
    gt = [g for g in load_gt() if include_reported or g["confidence"] == "primary"]
    nodes = rm.nodes
    vecs = embed([f"{n.label}. {n.description}" for n in nodes])
    results = []
    cost0 = llm.ledger.total_usd
    for g in gt:
        q = embed([f"{g['label']}. {g['description']}"])[0]
        sims = vecs @ q
        order = [int(i) for i in np.argsort(-sims)[:k] if sims[i] >= min_sim]
        if not order:
            results.append({"gt_id": g["id"], "version": g["version"], "category_row": g["category"], "verdict": "missed",
                            "node_id": None, "top_sim": float(sims.max()) if len(sims) else 0.0})
            continue
        cands = "\n".join(f"[{i}] \"{nodes[j].label}\" — {nodes[j].description} ({nodes[j].start}–{nodes[j].end}, row {nodes[j].category}, "
                          f"evidence {len(nodes[j].evidence_ids)}) sim={sims[j]:.2f}" for i, j in enumerate(order))
        out = llm.structured(model, JUDGE_SYSTEM, JUDGE_USER.format(label=g["label"], desc=g["description"], year=g["year"],
                                                                     cat=g["category"], cands=cands), Judge, purpose="eval_alignment", max_tokens=200)
        node = nodes[order[out.match]] if out.category != "missed" and out.match is not None and 0 <= out.match < len(order) else None
        rec = {"gt_id": g["id"], "version": g["version"], "category_row": g["category"], "gt_year": g["year"],
               "verdict": out.category if node else "missed", "node_id": node.id if node else None,
               "node_label": node.label if node else None, "node_start": node.start if node else None,
               "year_error": (abs((node.start or 0) - g["year"]) if node else None), "node_evidence": len(node.evidence_ids) if node else 0,
               "top_sim": float(sims[order[0]]), "reason": out.reason}
        results.append(rec)
    hit = lambda r, lenient=False: r["verdict"] in (("match", "refined", "generalized") if lenient else ("match", "refined"))  # noqa: E731
    def rate(rows, lenient=False):
        return round(sum(hit(r, lenient) for r in rows) / len(rows), 3) if rows else None
    v2020 = [r for r in results if r["version"] == "2020"]
    v2025 = [r for r in results if r["version"] == "2025"]
    errs = [r["year_error"] for r in results if r["year_error"] is not None and r["verdict"] in ("match", "refined")]
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category_row"], []).append(r)
    summary = {
        "condition": rm.condition, "model": rm.model, "n_gt": len(results),
        "recall_strict": rate(results), "recall_lenient": rate(results, True),
        "recall_2020_strict": rate(v2020), "recall_2020_lenient": rate(v2020, True),
        "recall_2025_strict": rate(v2025), "recall_2025_lenient": rate(v2025, True),   # ← foresight
        "year_mae": round(float(np.mean(errs)), 2) if errs else None,
        "by_category": {k: rate(v, True) for k, v in by_cat.items()},
        "matched_with_evidence": sum(1 for r in results if r["node_id"] and r["node_evidence"] > 0),
        "judge_cost_usd": round(llm.ledger.total_usd - cost0, 4),
        "results": results,
    }
    return summary


def evaluate_run(run_dir: str | Path, llm: LLM, **kw) -> dict:
    from ..roadmap import generate as G
    out = {}
    for cond in ("initial", "advanced"):
        rm = G.load(run_dir, cond)
        if rm:
            out[cond] = align(rm, llm, **kw)
    Path(run_dir, "eval_alignment.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
