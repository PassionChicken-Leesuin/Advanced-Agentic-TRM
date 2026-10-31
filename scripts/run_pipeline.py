"""KB 구축 파이프라인 실행 CLI.

python scripts/run_pipeline.py --run runs/pilotA --pilot                # 파일럿 20건 (가상 10 + 공개 10)
python scripts/run_pipeline.py --run runs/pilotB --pilot --config B
python scripts/run_pipeline.py --run runs/full --select priority --limit 180
python scripts/run_pipeline.py --run runs/x --ids syn_meeting_2024-02-26_02 pub_ionq_blog_2020-12-09_...
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus import CORPUS_ROOT
from trmkb.pipeline import Pipeline, PipelineConfig

CONFIGS = {
    "A": PipelineConfig(name="A", model_reader="openai/gpt-4.1-mini"),
    "B": PipelineConfig(name="B", model_reader="anthropic/claude-haiku-5.5", model_router="anthropic/claude-haiku-5.5",
                        model_linker="anthropic/claude-haiku-5.5", model_summarizer="anthropic/claude-haiku-5.5",
                        model_critic="openai/gpt-4.1"),
    "D": PipelineConfig(name="D", model_reader="anthropic/claude-haiku-5.5", model_router="openai/gpt-4.1-mini",
                        model_linker="openai/gpt-4.1-mini", model_summarizer="openai/gpt-4.1-mini",
                        model_critic="anthropic/claude-sonnet-4.6"),
    "C": PipelineConfig(name="C", model_reader="anthropic/claude-sonnet-4.6", model_router="openai/gpt-4.1-mini",
                        model_linker="anthropic/claude-sonnet-4.6", model_summarizer="openai/gpt-4.1-mini",
                        model_critic="openai/gpt-4.1"),
}


def load_index() -> list[dict]:
    return [json.loads(l) for l in (CORPUS_ROOT / "index.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def pilot_selection(rows: list[dict]) -> list[dict]:
    syn = [r for r in rows if r["is_synthetic"]]
    by_type: dict[str, list[dict]] = {}
    for r in sorted(syn, key=lambda r: r["date"]):
        by_type.setdefault(r["source_type"], []).append(r)
    chosen = []
    for t, lst in by_type.items():
        chosen += [lst[0], lst[len(lst) // 2]] if len(lst) > 1 else lst[:1]
    pub = {r["id"]: r for r in rows if not r["is_synthetic"]}
    wants = [
        lambda r: r["id"].startswith("pub_ionq_blog_2020-12-09"),
        lambda r: r["source_type"] == "blog" and ("algorithmic" in r["id"] or "performance_tar" in r["id"] or "aq_" in r["id"]),
        lambda r: r["id"].startswith("pub_ionq_blog_2024-10-03"),
        lambda r: r["source_type"] == "press_release" and r["date"] >= "2024-06",
        lambda r: r["source_type"] == "press_release" and "2023" <= r["date"] < "2024",
        lambda r: r["id"].startswith("pub_edgar_10-k_2024-02-28"),
        lambda r: r["source_type"] == "arxiv" and r["date"] >= "2024-06",
        lambda r: r["source_type"] == "arxiv" and "2023" <= r["date"] < "2024",
        lambda r: r["source_type"] == "investor_deck" and r["n_chars"] > 60_000,
        lambda r: r["source_type"] == "blog" and "barium" in r["id"],
    ]
    used = set()
    for w in wants:
        for r in sorted(pub.values(), key=lambda r: r["date"]):
            if r["id"] not in used and w(r):
                chosen.append(r); used.add(r["id"]); break
    return chosen[:20]


def priority_selection(rows: list[dict], limit: int) -> list[dict]:
    """저가치 문서 제외: 2021 SPAC 425/DEFA14A 중 짧은 것, 10-Q(10-K로 대체), 너무 짧은 블로그."""
    keep = []
    for r in rows:
        st = r["source_type"]
        if r["is_synthetic"]:
            keep.append((0, r)); continue
        if st == "investor_deck":
            if r["n_chars"] < 40_000:
                continue
            keep.append((3, r)); continue
        if st == "sec_filing" and "10-q" in r["id"]:
            continue
        if r["n_chars"] < 1_500:
            continue
        rank = {"blog": 1, "press_release": 1, "sec_filing": 2, "arxiv": 4, "industry_report": 2}.get(st, 3)
        keep.append((rank, r))
    keep.sort(key=lambda x: (x[0], x[1]["date"]))
    return [r for _, r in keep][:limit]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--config", default="D", choices=list(CONFIGS))
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--select", choices=["priority"], default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--dry", action="store_true", help="선택 목록만 출력")
    ap.add_argument("--stop-on-error", action="store_true")
    args = ap.parse_args()

    rows = load_index()
    if args.pilot:
        sel = pilot_selection(rows)
    elif args.select == "priority":
        sel = priority_selection(rows, args.limit or 10_000)
    elif args.ids:
        sel = [r for r in rows if r["id"] in set(args.ids)]
    else:
        sel = rows[: args.limit] if args.limit else rows
    sel.sort(key=lambda r: r["date"])   # 시간 순 투입 → 주장 타임라인이 자연스럽게 쌓임
    print(f"{len(sel)} docs selected")
    for r in sel:
        print(f"  {r['date']} {r['source_type']:18s} {r['id']} ({r['n_chars']:,} chars)")
    if args.dry:
        return
    cfg = CONFIGS[args.config]
    pipe = Pipeline(args.run, cfg)
    stats = pipe.run([r["path"] for r in sel], stop_on_error=args.stop_on_error)
    tot = pipe.llm.ledger.total_usd
    print(f"\n=== done: {len(stats)} episodes | cost ${tot:.3f} | {pipe.kb.stats()}")
    for s in stats:
        print(f"  {s.doc_id[:48]:48s} ch {s.chunks_relevant}/{s.chunks} prop {s.proposals:3d} new {s.nodes_created:3d} "
              f"merge {s.nodes_merged:3d} claims {s.claims:3d} edges +{s.edges_accepted}/-{s.edges_rejected} conf {s.conflicts} "
              f"{s.seconds:5.0f}s ${s.cost_usd:.3f}{' ERR ' + s.error if s.error else ''}")
    print("by purpose:", json.dumps(pipe.llm.ledger.by("purpose"), indent=1))


if __name__ == "__main__":
    main()
