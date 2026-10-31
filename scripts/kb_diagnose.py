"""KB 품질 진단: Router 병합 품질(유사 라벨 중복), router_log 통계, 문서 유형별 기여, 노드 증가 곡선.

python scripts/kb_diagnose.py --run runs/full [--dup-sim 0.85]
산출: runs/<run>/diagnose.json + 콘솔 요약
"""
import argparse
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.agents.embed import embed
from trmkb.schema import NODE_LAYER, NodeType
from trmkb.store import KBStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--dup-sim", type=float, default=0.85)
    args = ap.parse_args()
    run = Path(args.run)
    kb = KBStore(run)
    nodes = list(kb.nodes.values())
    out = {"run": run.name, "stats": kb.stats()}

    # 1) 유사 라벨 중복 (같은 층 안, 라벨만 임베딩)
    by_layer = defaultdict(list)
    for n in nodes:
        by_layer[NODE_LAYER[NodeType(n.type)].value].append(n)
    dups = []
    for layer, ns in by_layer.items():
        if len(ns) < 2:
            continue
        v = embed([n.label for n in ns])
        sims = v @ v.T
        for i in range(len(ns)):
            for j in range(i + 1, len(ns)):
                if sims[i, j] >= args.dup_sim:
                    dups.append({"layer": layer, "a": ns[i].label, "b": ns[j].label, "sim": round(float(sims[i, j]), 3),
                                 "a_claims": len(kb.claims_for(ns[i].id)), "b_claims": len(kb.claims_for(ns[j].id))})
    dups.sort(key=lambda d: -d["sim"])
    out["near_duplicate_pairs"] = len(dups)
    out["near_duplicate_rate"] = round(len(dups) / max(1, len(nodes)), 3)
    out["near_duplicates_top"] = dups[:40]

    # 2) router_log
    rl = [json.loads(l) for l in (run / "router_log.jsonl").read_text(encoding="utf-8").splitlines()] if (run / "router_log.jsonl").exists() else []
    dec = Counter(r["decision"] for r in rl)
    band = defaultdict(lambda: [0, 0])
    for r in rl:
        s = r["candidates"][0][1] if r["candidates"] else 0.0
        k = "≥0.80" if s >= 0.80 else "0.65–0.80" if s >= 0.65 else "<0.65"
        band[k][0] += 1; band[k][1] += r["decision"] == "merge"
    out["router"] = {"decisions": dict(dec), "merge_rate": round(dec.get("merge", 0) / max(1, len(rl)), 3),
                     "by_similarity_band": {k: {"n": v[0], "merge": v[1]} for k, v in band.items()},
                     "llm_judged": sum(1 for r in rl if r["candidates"] and 0.65 <= r["candidates"][0][1] < 0.80)}

    # 3) 문서 유형별 기여
    docs = {d.id: d for d in kb.documents.values()}
    contrib = defaultdict(lambda: {"docs": 0, "nodes_created": 0, "claims": 0})
    for d in docs.values():
        contrib[d.source_type.value]["docs"] += 1
    for n in nodes:
        if n.created_by_doc in docs:
            contrib[docs[n.created_by_doc].source_type.value]["nodes_created"] += 1
    for c in kb.claims.values():
        if c.doc_id in docs:
            contrib[docs[c.doc_id].source_type.value]["claims"] += 1
    out["by_source_type"] = {k: {**v, "claims_per_doc": round(v["claims"] / max(1, v["docs"]), 1)} for k, v in contrib.items()}

    # 4) 노드 증가 곡선 (episodes.jsonl 누적)
    eps = [json.loads(l) for l in (run / "episodes.jsonl").read_text(encoding="utf-8").splitlines()] if (run / "episodes.jsonl").exists() else []
    cum, curve = 0, []
    for i, e in enumerate(eps, 1):
        cum += e["nodes_created"]
        if i % 20 == 0 or i == len(eps):
            curve.append({"docs": i, "nodes": cum, "merge_rate_so_far": round(sum(x["nodes_merged"] for x in eps[:i]) / max(1, sum(x["nodes_merged"] + x["nodes_created"] for x in eps[:i])), 3)})
    out["growth"] = curve
    out["errors"] = sum(1 for e in eps if e.get("error"))
    out["time_coverage"] = round(sum(1 for n in nodes if n.es is not None) / max(1, len(nodes)), 3)
    out["conflict_nodes"] = sum(1 for n in nodes if "conflict" in n.flags)
    out["infeasible_nodes"] = sum(1 for n in nodes if "infeasible" in n.flags)

    (run / "diagnose.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "near_duplicates_top"}, ensure_ascii=False, indent=1))
    print("\nnear-duplicate samples:")
    for d in dups[:15]:
        print(f"  [{d['layer']}] {d['sim']:.2f}  {d['a']}  ~  {d['b']}")


if __name__ == "__main__":
    main()
