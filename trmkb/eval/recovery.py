"""
심은 사실 회수율 (planted-fact recovery) — 파일럿 모델 선정과 P7 평가에 사용.

사실 f 가 회수됨 := 그 사실이 심긴 문서 중 하나라도 처리된 run 에서, KB 의 주장(claim) 텍스트 가운데
임베딩 유사도 상위 k 개를 LLM 판정자가 보고 "같은 사실이 KB 에 들어 있다"고 판정.
모순 탐지율 := contradicts 쌍 중 양쪽 사실이 회수되고 Critic 가 conflict 를 플래그한 비율.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ..agents.embed import embed
from ..corpus.synth import load_ledger
from ..llm import LLM
from ..store import KBStore

JUDGE_SYSTEM = "You judge whether a knowledge base contains a given fact. JSON only."
JUDGE_USER = """Fact to find:
"{fact}"

Knowledge-base entries (claim text, with node label):
{entries}

Is the fact present in the knowledge base — i.e. at least one entry states the same fact with the same key numbers/dates/qualifiers (paraphrase ok)? Partial = the entity is there but a key number/date/qualifier is missing or different.

Return JSON: {{"verdict": "present"|"partial"|"absent", "best_entry": int|null, "reason": str}}"""


class Judge(BaseModel):
    verdict: str
    best_entry: int | None = None
    reason: str = ""


def evaluate(run_dir: str | Path, llm: LLM, model: str = "openai/gpt-4.1-mini", k: int = 8) -> dict:
    kb = KBStore(run_dir)
    ledger = load_ledger()
    processed = set(kb.documents)
    claims = list(kb.claims.values())
    if not claims:
        return {"error": "no claims"}
    # 후보 풀 = 주장 + 노드에 부착된 근거 청크 (둘 다 KB의 구성 요소: ③ 타임라인, ① 근거 부착)
    texts = [f"{kb.nodes[c.node_id].label}: {c.text}" for c in claims]
    entries: list[tuple[str, str | None]] = [("claim", c.id) for c in claims]
    for ev in kb.evidence.values():
        if ev.node_ids and ev.text:
            texts.append(f"{kb.nodes[ev.node_ids[0]].label} [evidence]: {ev.text[:400]}")
            entries.append(("evidence", ev.id))
    vecs = embed(texts)
    results = []
    for f in ledger["facts"]:
        docs = [d for d in f.get("planted_in_doc_ids", []) if d in processed]
        if not docs:
            continue
        q = embed([f["text"]])[0]
        sims = vecs @ q
        top = sims.argsort()[::-1][:k]
        listing = "\n".join(f"[{i}] {texts[j][:260]}" for i, j in enumerate(top))
        out = llm.structured(model, JUDGE_SYSTEM, JUDGE_USER.format(fact=f["text"], entries=listing), Judge,
                             purpose="eval_recovery", max_tokens=300)
        best_claim = None; best_node = None
        if out.best_entry is not None and 0 <= out.best_entry < len(top):
            kind, oid = entries[int(top[out.best_entry])]
            if kind == "claim":
                best_claim = kb.claims[oid]; best_node = kb.nodes[best_claim.node_id].label
            else:
                ev = kb.evidence[oid]; best_node = kb.nodes[ev.node_ids[0]].label
                best_claim = next((kb.claims[c] for c in ev.claim_ids if c in kb.claims), None)
        results.append({"fact_id": f["id"], "verdict": out.verdict, "top_sim": float(sims[top[0]]),
                        "expected_node_type": f["expected_node_type"], "docs_processed": docs,
                        "best_claim_id": best_claim.id if best_claim else None,
                        "best_node": best_node, "reason": out.reason})
    n = len(results)
    present = sum(r["verdict"] == "present" for r in results)
    partial = sum(r["verdict"] == "partial" for r in results)
    by_type: dict[str, list[int]] = {}
    for r in results:
        by_type.setdefault(r["expected_node_type"], []).append(1 if r["verdict"] == "present" else 0)
    # 모순 탐지
    facts = {f["id"]: f for f in ledger["facts"]}
    conflict_pairs = sorted({tuple(sorted((f["id"], f["contradicts"]))) for f in facts.values() if f.get("contradicts")})
    flagged_nodes = {n.id for n in kb.nodes.values() if "conflict" in n.flags}
    conflict_rows = []
    for a, b in conflict_pairs:
        ra = next((r for r in results if r["fact_id"] == a), None)
        rb = next((r for r in results if r["fact_id"] == b), None)
        both = bool(ra and rb and ra["verdict"] != "absent" and rb["verdict"] != "absent")
        node_flagged = False
        if both:
            for r in (ra, rb):
                c = kb.claims.get(r["best_claim_id"]) if r["best_claim_id"] else None
                if c and c.node_id in flagged_nodes:
                    node_flagged = True
        conflict_rows.append({"pair": [a, b], "both_recovered": both, "flagged": node_flagged})
    summary = {
        "facts_evaluated": n, "present": present, "partial": partial, "absent": n - present - partial,
        "recovery_rate": round(present / n, 3) if n else None,
        "recovery_rate_lenient": round((present + partial) / n, 3) if n else None,
        "by_node_type": {k: round(sum(v) / len(v), 2) for k, v in by_type.items()},
        "conflicts": conflict_rows,
        "conflict_detection": (sum(c["flagged"] for c in conflict_rows) / max(1, sum(c["both_recovered"] for c in conflict_rows))
                               if conflict_rows else None),
        "results": results,
    }
    Path(run_dir, "eval_recovery.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
