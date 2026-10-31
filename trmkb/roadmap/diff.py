"""
trmkb.roadmap.diff — 1막(initial) vs 3막(advanced) 로드맵 정렬·차이 (Jansen 2026 식 5범주).

  same        : 같은 항목 (라벨·의미 일치)
  refined     : advanced 가 더 구체적 (수치·날짜·명칭 추가)
  generalized : advanced 가 더 포괄적
  new         : advanced 에만 있음
  dropped     : initial 에만 있음
짝이 지어진 항목은 시점 이동(start/end 차이)도 기록한다.

절차: 같은 층 안에서 라벨+설명 임베딩 유사도 상위 후보 → LLM 판정(same/refined/generalized/different).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field

from ..agents.embed import embed
from ..llm import LLM
from ..schema import Roadmap, RoadmapNode

JUDGE_SYSTEM = "You align items between two versions of a technology roadmap. JSON only."
JUDGE_USER = """Initial item: "{a_label}" — {a_desc} ({a_start}–{a_end}, row {a_cat})
Advanced candidates (same layer):
{cands}

For the initial item, pick the candidate that refers to the same roadmap item, if any, and classify:
- same: same item at the same specificity
- refined: candidate says the same thing but more specifically (adds numbers, dates, names, splits into a concrete milestone)
- generalized: candidate is a broader version of the initial item
- none: no candidate refers to the same item

Return JSON: {{"match": int|null, "category": "same"|"refined"|"generalized"|"none", "reason": str (<=20 words)}}"""


class Judge(BaseModel):
    match: int | None = None
    category: str = "none"
    reason: str = ""


def _vec(nodes: list[RoadmapNode]) -> np.ndarray:
    return embed([f"{n.label}. {n.description}" for n in nodes]) if nodes else np.zeros((0, 384), dtype=np.float32)


def compute_diff(initial: Roadmap, advanced: Roadmap, llm: LLM, *, model: str = "openai/gpt-4.1-mini",
                 k: int = 4, min_sim: float = 0.35) -> dict:
    pairs = []
    matched_adv: set[str] = set()
    cost0 = llm.ledger.total_usd
    for layer in ("why", "what", "how", "resource"):
        a_nodes = [n for n in initial.nodes if n.layer.value == layer]
        b_nodes = [n for n in advanced.nodes if n.layer.value == layer]
        if not a_nodes or not b_nodes:
            for n in a_nodes:
                pairs.append({"initial_id": n.id, "advanced_id": None, "category": "dropped", "sim": None})
            continue
        va, vb = _vec(a_nodes), _vec(b_nodes)
        sims = va @ vb.T
        for i, a in enumerate(a_nodes):
            order = np.argsort(-sims[i])[:k]
            cands = [(int(j), float(sims[i, j])) for j in order if sims[i, j] >= min_sim and b_nodes[j].id not in matched_adv]
            if not cands:
                pairs.append({"initial_id": a.id, "advanced_id": None, "category": "dropped", "sim": float(sims[i].max())})
                continue
            cand_txt = "\n".join(f"[{idx}] \"{b_nodes[j].label}\" — {b_nodes[j].description} ({b_nodes[j].start}–{b_nodes[j].end}, row {b_nodes[j].category}) sim={s:.2f}"
                                 for idx, (j, s) in enumerate(cands))
            out = llm.structured(model, JUDGE_SYSTEM, JUDGE_USER.format(
                a_label=a.label, a_desc=a.description, a_start=a.start, a_end=a.end, a_cat=a.category, cands=cand_txt),
                Judge, purpose="roadmap_diff", max_tokens=200)
            if out.category in ("same", "refined", "generalized") and out.match is not None and 0 <= out.match < len(cands):
                j, s = cands[out.match]
                b = b_nodes[j]
                matched_adv.add(b.id)
                pairs.append({"initial_id": a.id, "advanced_id": b.id, "category": out.category, "sim": s,
                              "start_shift": (b.start or 0) - (a.start or 0), "end_shift": (b.end or 0) - (a.end or 0),
                              "advanced_has_evidence": bool(b.evidence_ids), "advanced_ops": [o.value for o in b.produced_by],
                              "reason": out.reason})
            else:
                pairs.append({"initial_id": a.id, "advanced_id": None, "category": "dropped", "sim": cands[0][1], "reason": out.reason})
    for b in advanced.nodes:
        if b.id not in matched_adv:
            pairs.append({"initial_id": None, "advanced_id": b.id, "category": "new", "sim": None,
                          "advanced_has_evidence": bool(b.evidence_ids), "advanced_ops": [o.value for o in b.produced_by]})
    counts: dict[str, int] = {}
    for p in pairs:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    by_layer: dict[str, dict[str, int]] = {}
    adv_by_id = {n.id: n for n in advanced.nodes}
    ini_by_id = {n.id: n for n in initial.nodes}
    for p in pairs:
        n = adv_by_id.get(p.get("advanced_id")) or ini_by_id.get(p.get("initial_id"))
        d = by_layer.setdefault(n.layer.value, {})
        d[p["category"]] = d.get(p["category"], 0) + 1
    new_with_ev = sum(1 for p in pairs if p["category"] == "new" and p.get("advanced_has_evidence"))
    return {
        "initial_id": initial.id, "advanced_id": advanced.id, "pairs": pairs, "counts": counts, "by_layer": by_layer,
        "initial_nodes": len(initial.nodes), "advanced_nodes": len(advanced.nodes),
        "advanced_with_evidence": sum(1 for n in advanced.nodes if n.evidence_ids),
        "new_with_evidence": new_with_ev,
        "mean_start_shift": float(np.mean([p["start_shift"] for p in pairs if "start_shift" in p])) if any("start_shift" in p for p in pairs) else None,
        "judge_cost_usd": round(llm.ledger.total_usd - cost0, 4),
    }


def save(diff: dict, run_dir: str | Path) -> Path:
    p = Path(run_dir) / "roadmap_diff.json"
    p.write_text(json.dumps(diff, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
