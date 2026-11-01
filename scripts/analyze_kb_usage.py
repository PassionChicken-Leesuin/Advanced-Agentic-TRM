"""KB → 컨텍스트 → 로드맵 추적 분석: 구축된 KB 가 Advanced 로드맵에 실제로 어떻게 쓰였는가.

python scripts/analyze_kb_usage.py --run runs/full
산출: runs/<run>/kb_usage.json, kb_usage.md
"""
import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.agents.embed import embed
from trmkb.roadmap import generate as G
from trmkb.roadmap import retrieve as R
from trmkb.schema import NODE_LAYER, NodeType
from trmkb.store import KBStore


def src_kind(doc) -> str:
    if doc is None:
        return "?"
    if doc.is_synthetic:
        return "synthetic"
    return {"sec_filing": "sec(10-K/10-Q)", "press_release": "8-K press", "investor_deck": "SPAC 425/DEFA14A",
            "arxiv": "arxiv", "blog": "ionq blog", "industry_report": "ionq resources"}.get(doc.source_type.value, doc.source_type.value)


def sections(text: str) -> dict:
    out, cur = {}, "preamble"
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:60]
        out[cur] = out.get(cur, 0) + len(line) + 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--run", default="runs/full"); args = ap.parse_args()
    run = Path(args.run); kb = KBStore(run)
    adv, ini = G.load(run, "advanced"), G.load(run, "initial")
    ctx_text = (run / "context_advanced.txt").read_text(encoding="utf-8")
    full_ctx = R.build_context(kb, condition="S4", max_chars=10_000_000)   # 잘리지 않은 판 (무엇이 잘렸나)
    rep: dict = {}

    # ---------- 1. 깔때기: KB → 컨텍스트 → 인용
    ctx_node_ids = set(re.findall(r"^- (n_[0-9a-f]{10}) \|", ctx_text, flags=re.M))
    ctx_ev_ids = set(re.findall(r"evidence (ev_[0-9a-f]{10})", ctx_text))
    ctx_claim_ids = set(re.findall(r"claim (c_[0-9a-f]{10})", ctx_text))
    cited = [(n, i) for n in adv.nodes for i in n.evidence_ids]
    cited_ev = [kb.evidence[i] for _, i in cited if i in kb.evidence]
    cited_nodes = {nid for ev in cited_ev for nid in ev.node_ids}
    cited_docs = {ev.doc_id for ev in cited_ev}
    ctx_docs = {kb.evidence[e].doc_id for e in ctx_ev_ids if e in kb.evidence}
    rep["funnel"] = {
        "kb_documents": len(kb.documents), "kb_nodes": len(kb.nodes), "kb_claims": len(kb.claims), "kb_evidence": len(kb.evidence),
        "context_chars": len(ctx_text), "context_untruncated_chars": len(full_ctx.text),
        "context_nodes": len(ctx_node_ids), "context_claims": len(ctx_claim_ids), "context_evidence": len(ctx_ev_ids),
        "context_documents": len(ctx_docs),
        "roadmap_items": len(adv.nodes), "items_with_citation": sum(1 for n in adv.nodes if n.evidence_ids),
        "citations": len(cited), "cited_evidence_in_context": sum(1 for _, i in cited if i in ctx_ev_ids),
        "cited_kb_nodes": len(cited_nodes), "cited_documents": len(cited_docs),
    }
    rep["context_sections_chars"] = sections(ctx_text)
    rep["untruncated_sections_chars"] = sections(full_ctx.text)

    # ---------- 2. 출처 구성: KB 전체 vs 컨텍스트 vs 인용
    docs = kb.documents
    def mix(doc_ids):
        c = Counter(src_kind(docs.get(d)) for d in doc_ids); t = sum(c.values()) or 1
        return {k: f"{v} ({round(100*v/t)}%)" for k, v in c.most_common()}
    kb_ev_docs = [e.doc_id for e in kb.evidence.values()]
    rep["source_mix"] = {"kb_evidence": mix(kb_ev_docs), "context_evidence": mix([kb.evidence[e].doc_id for e in ctx_ev_ids if e in kb.evidence]),
                         "cited_evidence": mix([e.doc_id for e in cited_ev])}

    # ---------- 3. 항목별 추적
    items = []
    lab_vecs = embed([f"{n.label}. {n.description}" for n in adv.nodes])
    for k, n in enumerate(adv.nodes):
        row = {"label": n.label, "layer": n.layer.value, "start": n.start, "end": n.end, "ops": [o.value for o in n.produced_by]}
        if n.evidence_ids and n.evidence_ids[0] in kb.evidence:
            ev = kb.evidence[n.evidence_ids[0]]
            kn = kb.nodes.get(ev.node_ids[0]) if ev.node_ids else None
            d = docs.get(ev.doc_id)
            row.update({"evidence": ev.text[:160], "doc": ev.doc_id, "doc_date": d.date.isoformat() if d else None, "source": src_kind(d),
                        "kb_node": kn.label if kn else None, "kb_layer": NODE_LAYER[NodeType(kn.type)].value if kn else None,
                        "kb_type": kn.type if kn else None, "kb_es": kn.es if kn else None,
                        "kb_claims": len(kb.claims_for(kn.id)) if kn else 0, "kb_degree": kb.degree(kn.id) if kn else 0,
                        "kb_priority": round(R.priority(kb, kn), 1) if kn else None})
            if kn:
                v = embed([f"{kn.label}. {kn.description or ''}"])[0]
                row["label_sim_to_kb_node"] = round(float(lab_vecs[k] @ v), 2)
        items.append(row)
    rep["items"] = items
    lay_agree = [r for r in items if r.get("kb_layer")]
    rep["layer_agreement"] = {"same": sum(1 for r in lay_agree if r["kb_layer"] == r["layer"]), "n": len(lay_agree),
                              "pairs": Counter(f"{r['kb_layer']}→{r['layer']}" for r in lay_agree).most_common()}
    tm = [r for r in items if r.get("kb_es") is not None and r["start"] is not None]
    rep["time"] = {"items_with_kb_time": len(tm), "mean_abs_diff_start_vs_kb_es": round(float(np.mean([abs(r["start"] - r["kb_es"]) for r in tm])), 2) if tm else None,
                   "kb_es_before_2025": sum(1 for r in tm if r["kb_es"] < 2025)}

    # ---------- 4. 쓰이지 않은 것: 정답 마일스톤 관련 KB 지식이 컨텍스트·로드맵에 있었나
    from trmkb.eval.alignment import load_gt
    al = json.loads((run / "eval_alignment.json").read_text(encoding="utf-8"))["advanced"]["results"]
    verdict = {r["gt_id"]: r["verdict"] for r in al}
    claims = list(kb.claims.values())
    cv = embed([f"{kb.nodes[c.node_id].label}: {c.text}" for c in claims])
    gt_rows = []
    for g in load_gt():
        q = embed([f"{g['label']}. {g['description']}"])[0]
        sims = cv @ q; j = int(np.argmax(sims)); c = claims[j]
        gt_rows.append({"gt": g["id"], "version": g["version"], "label": g["label"][:60], "best_kb_claim": c.text[:120],
                        "sim": round(float(sims[j]), 2), "kb_node": kb.nodes[c.node_id].label, "doc": c.doc_id[:40],
                        "node_in_context": c.node_id in ctx_node_ids, "claim_in_context": c.id in ctx_claim_ids,
                        "roadmap_verdict": verdict.get(g["id"])})
    rep["ground_truth_trace"] = gt_rows

    # ---------- 5. 우선순위 상위(컨텍스트 선택)의 출처
    sel = [kb.nodes[i] for i in ctx_node_ids if i in kb.nodes]
    def node_src(n):
        d = docs.get(n.created_by_doc); return src_kind(d)
    rep["context_node_sources"] = dict(Counter(node_src(n) for n in sel).most_common())
    rep["context_node_layers"] = dict(Counter(NODE_LAYER[NodeType(n.type)].value for n in sel).most_common())

    (run / "kb_usage.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    f = rep["funnel"]
    print(json.dumps({"funnel": f, "context_sections_chars": rep["context_sections_chars"], "untruncated_sections_chars": rep["untruncated_sections_chars"],
                      "source_mix": rep["source_mix"], "layer_agreement": rep["layer_agreement"], "time": rep["time"],
                      "context_node_sources": rep["context_node_sources"], "context_node_layers": rep["context_node_layers"]}, ensure_ascii=False, indent=1))
    print("\nITEMS")
    for r in items:
        print(f"  [{r['layer']:8s}] {r['label'][:38]:38s} {r['start']}-{r['end']} | {r.get('source','-'):16s} {str(r.get('doc_date')):10s} | KB: {str(r.get('kb_node'))[:30]:30s} ({r.get('kb_layer')}/{r.get('kb_type')}, claims {r.get('kb_claims')}, ES {r.get('kb_es')}) sim {r.get('label_sim_to_kb_node')}")
    print("\nGT TRACE")
    for g in gt_rows:
        print(f"  {g['gt']} v{g['version']} {g['roadmap_verdict']:11s} ctx_node={g['node_in_context']!s:5s} ctx_claim={g['claim_in_context']!s:5s} sim={g['sim']} | {g['label'][:40]:40s} | KB: {g['kb_node'][:28]} :: {g['best_kb_claim'][:70]}")


if __name__ == "__main__":
    main()
