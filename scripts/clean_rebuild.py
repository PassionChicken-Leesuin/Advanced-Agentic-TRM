"""runs/full 에서 지정 문서들의 흔적을 제거하고, 새 판 문서를 기존 파이프라인으로 다시 넣은 정리본을 만든다.

python scripts/clean_rebuild.py --src runs/full --dst runs/full_clean
  대상 문서 = 원장에서 leak_fixed 표시된 사실이 심긴 가상 문서 (2026-11-01 재생성분)
  1) dst 로 복사  2) 대상 문서의 근거·주장·문서기록·이벤트 제거, 그 문서가 만든 링크 제거, 근거가 남지 않은 노드 제거
  3) 대상 문서(새 판)를 Pipeline 으로 처리  4) 영향받은 행 요약 강제 갱신  5) Timing 재계산
"""
import argparse
import io
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.agents import timing
from trmkb.agents.router import row_key
from trmkb.corpus.synth import load_ledger
from trmkb.pipeline import Pipeline, PipelineConfig
from trmkb.store import KBStore, _write_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="runs/full"); ap.add_argument("--dst", default="runs/full_clean")
    args = ap.parse_args()
    src, dst = Path(args.src), Path(args.dst)
    led = load_ledger()
    targets = sorted({d for f in led["facts"] if f.get("leak_fixed") for d in f.get("planted_in_doc_ids", [])})
    print("target docs:", len(targets))
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("ablation", "model2", "real_only", "*.png"))

    kb = KBStore(dst)
    T = set(targets)
    touched_rows = set()
    for n in kb.nodes.values():
        if any(e.doc_id in T for e in kb.evidence_for_node(n.id)):
            touched_rows.add(row_key(n))
    ev_keep = {k: e for k, e in kb.evidence.items() if e.doc_id not in T}
    cl_keep = {k: c for k, c in kb.claims.items() if c.doc_id not in T}
    for c in cl_keep.values():
        c.conflicts_with = [x for x in c.conflicts_with if x in cl_keep]
    live_nodes = {nid for e in ev_keep.values() for nid in e.node_ids}
    nodes_keep = {k: n for k, n in kb.nodes.items() if k in live_nodes}
    edges_keep = {k: e for k, e in kb.edges.items() if e.created_by_doc not in T and e.src in nodes_keep and e.dst in nodes_keep}
    removed = {"evidence": len(kb.evidence) - len(ev_keep), "claims": len(kb.claims) - len(cl_keep),
               "nodes": len(kb.nodes) - len(nodes_keep), "edges": len(kb.edges) - len(edges_keep)}
    print("removed:", removed, "| rows to refresh:", len(touched_rows))
    kbd = dst / "kb"
    _write_jsonl(kbd / "evidence.jsonl", ev_keep.values())
    _write_jsonl(kbd / "claims.jsonl", cl_keep.values())
    _write_jsonl(kbd / "nodes.jsonl", nodes_keep.values())
    _write_jsonl(kbd / "edges.jsonl", edges_keep.values())
    (kbd / "time_index.json").write_text("{}", encoding="utf-8")
    docs = [json.loads(l) for l in (dst / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    (dst / "documents.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs if d["id"] not in T), encoding="utf-8")
    evs = [l for l in (dst / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    keep_ev = [l for l in evs if json.loads(l).get("doc_id") not in T]
    (dst / "events.jsonl").write_text("\n".join(keep_ev) + "\n", encoding="utf-8")
    rl = [l for l in (dst / "router_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    (dst / "router_log.jsonl").write_text("\n".join(l for l in rl if json.loads(l)["doc_id"] not in T) + "\n", encoding="utf-8")
    eps = [l for l in (dst / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    (dst / "episodes.jsonl").write_text("\n".join(l for l in eps if json.loads(l)["doc_id"] not in T) + "\n", encoding="utf-8")
    for p in ("summary.json", "summary.md", "eval_recovery.json", "eval_alignment.json", "roadmap_advanced.json", "roadmap_diff.json",
              "eval_contrast.json", "diagnose.json", "kb_usage.json", "context_advanced.txt", "cost.json", "key_usage.json"):
        (dst / p).unlink(missing_ok=True)

    # 새 판 문서 재처리
    pipe = Pipeline(dst, PipelineConfig())
    idx = {json.loads(l)["id"]: json.loads(l) for l in Path("data/corpus/index.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    paths = [idx[d]["path"] for d in sorted(targets, key=lambda d: idx[d]["date"])]
    stats = pipe.run(paths)
    print("reprocessed:", len(stats), "errors:", sum(1 for s in stats if s.error), f"cost ${pipe.llm.ledger.total_usd:.3f}")
    # 영향받은 행 요약 강제 갱신 (옛 가상 사실이 요약 문장에 남아 있을 수 있음)
    rows = touched_rows | set(pipe.router.dirty_rows)
    done = pipe.summarizer.refresh(rows, doc_id="clean_rebuild", max_rows=len(rows))
    print("summaries refreshed:", len(done))
    tr = timing.recompute(pipe.kb); pipe.kb.save()
    pipe.llm.ledger.dump(dst / "cost_clean_rebuild.json")
    print("final:", pipe.kb.stats(), "| timing", {k: v for k, v in tr.items() if k != "infeasible"}, f"| total cost ${pipe.llm.ledger.total_usd:.3f}")


if __name__ == "__main__":
    main()
