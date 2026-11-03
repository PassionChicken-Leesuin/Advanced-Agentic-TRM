"""다섯 지식 구조 비교 평가: 조건마다 생성 n회 × 판정 모델 3종, 평균 ± 표준편차.

python scripts/eval_v2.py --run runs/struct5 --src runs/full_clean [--n 3] [--conditions ...] [--force]
조건
  Initial   : 지식베이스 없음
  S0raw     : 원문 청크 벡터 검색 (단순 RAG, runs/full_clean 문서)
  K1        : 근거 저장소만
  ALL       : 다섯 구조 모두
  ALL-K1..5 : 구조 하나씩 제거 (그 작업지와 읽기 규칙이 빠지고, 글자 예산은 K1 로)
  ALL-real  : 다섯 구조, 실제 공개 자료만 (가상 내부 문서 제외, 트리·그리드도 실제 자료로 다시 만든 것)
  ALL-nocards: 다섯 구조 모두, 같은 글자 예산, 기회 카드만 없음 (카드 제거 실험)
산출: runs/struct5/eval/<조건>/{context.txt, context_stats.json, rm_<i>.json, align_<i>_<judge>.json}, eval/summary.{json,md}
"""
import argparse
import io
import json
import statistics as S
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

import numpy as np

from trmkb.agents.embed import embed
from trmkb.eval.alignment import align
from trmkb.llm import LLM
from trmkb.roadmap import generate as G
from trmkb.roadmap import retrieve as R
from trmkb.schema import Roadmap
from trmkb.sources import generate as SG
from trmkb.sources import make as MK
from trmkb.sources.store import SourceStore
from trmkb.sources.worksheets import STRUCTS, build_worksheets
from trmkb.store import KBStore

ALL = set(STRUCTS)
CONDS = {
    "Initial": None, "S0raw": "S0raw", "K1": {"evidence"}, "ALL": ALL,
    "ALL-K1": ALL - {"evidence"}, "ALL-K2": ALL - {"tree"}, "ALL-K3": ALL - {"grid"},
    "ALL-K4": ALL - {"graph"}, "ALL-K5": ALL - {"time"}, "ALL-real": ALL,
    "ALL-K0": ALL,     # 다섯 구조 모두, 단 K0 용어집 없이 구축한 run (--run-nok0) 에서 작업지를 만듦 (구축 단계 제거 실험)
    "ALL-nocards": ALL,  # 다섯 구조 모두, 같은 예산, 기회 카드만 조립하지 않음 (카드 제거 실험)
    # 카드 v2 파이프라인 (Landscaping → 카드 추출 → 선정 → 제작). runs/<run>/cards_v2/{cards.json, selection/profiles.json} 필요
    "CARDS-debate": "cards_v2:debate",     # 세 질문 토론으로 고른 상위 10장 전문 + 랜드스케이프
    "CARDS-support": "cards_v2:support",   # 문서 수 순 상위 10장 (선정 방식 제거 실험)
    "CARDS-all": "cards_v2:all",           # 62장 전부 전문 (선정 제거 실험)
}
JUDGES = ["openai/gpt-4.1-mini", "anthropic/claude-haiku-5.5", "google/gemini-2.5-flash"]
JTAG = {j: j.split("/")[1].split("-")[0] + "-" + j.split("-")[-1] for j in JUDGES}


def cite_info(st: SourceStore, cid: str):
    """인용 id → (유효 여부, 문서 키, 가상 여부, 소스 문장 or None)"""
    p = st.passages.get(cid)
    if p:
        return True, p.doc_id, p.is_synthetic, p
    if cid.startswith("chunk_"):
        doc = cid[6:].rsplit("_", 1)[0]
        return True, doc, doc.startswith("syn_"), None
    return False, None, None, None


def structural(rm: Roadmap, st: SourceStore, valid_extra: set[str], areas: list[tuple[str, np.ndarray]]) -> dict:
    n = len(rm.nodes) or 1
    cited = valid = syn = 0
    with_ev = multi = 0
    ents_of = {}
    for nd in rm.nodes:
        docs, ents, ok_n = set(), set(), 0
        for cid in nd.evidence_ids:
            cited += 1
            ok, doc, is_syn, p = cite_info(st, cid)
            if not ok and cid not in valid_extra:
                continue
            valid += 1; ok_n += 1
            syn += bool(is_syn)
            if doc:
                docs.add(doc)
            if p:
                ents |= set(p.entity_ids)
        with_ev += ok_n > 0
        multi += len(docs) >= 2
        ents_of[nd.id] = ents
    pairs = set()
    for r in st.relations.values():
        pairs.add((r.src, r.dst)); pairs.add((r.dst, r.src))
    for c in st.grid.get("cells", []):
        pairs.add((c["row"], c["col"])); pairs.add((c["col"], c["row"]))
    grounded = sum(1 for e in rm.edges if any((a, b) in pairs for a in ents_of.get(e.src, ()) for b in ents_of.get(e.dst, ())))
    cov = None
    if areas and rm.nodes:
        nv = embed([f"{x.label}. {x.description}" for x in rm.nodes])
        cov = round(sum(1 for _, av in areas if float((nv @ av).max()) >= 0.5) / len(areas), 3)
    flags = [f for x in rm.nodes for f in x.flags]
    return {"nodes": len(rm.nodes), "edges": len(rm.edges), "by_layer": G.summary(rm)["by_layer"],
            "evidence_rate": round(with_ev / n, 3), "multi_source_rate": round(multi / n, 3),
            "invalid_cite_rate": round((cited - valid) / cited, 3) if cited else None,
            "synthetic_share": round(syn / valid, 3) if valid else None,
            "edge_grounded_rate": round(grounded / len(rm.edges), 3) if rm.edges else None,
            "area_coverage": cov, "revised": flags.count("revised"), "conflict": flags.count("conflict"),
            "infeasible": flags.count("infeasible")}


def ms(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    return round(S.mean(xs), 3), round(S.stdev(xs), 3) if len(xs) > 1 else 0.0


def fmt(m, sd, pct=True):
    if m is None:
        return "—"
    return f"{round(m * 100)}±{round(sd * 100)}%" if pct else f"{m:.2f}±{sd:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--src", default="runs/full_clean")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--conditions", nargs="*", default=list(CONDS))
    ap.add_argument("--judges", nargs="*", default=JUDGES)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--run-nok0", default=None, help="K0 없이 구축한 run (ALL-K0 조건). 없으면 ALL-K0 는 건너뜀")
    args = ap.parse_args()
    run = Path(args.run)
    st = SourceStore(run)
    st_nok0 = SourceStore(args.run_nok0) if args.run_nok0 and Path(args.run_nok0).exists() else None
    if st_nok0 is None and "ALL-K0" in args.conditions:
        args.conditions = [c for c in args.conditions if c != "ALL-K0"]
        print("ALL-K0 skipped (no --run-nok0)")
    stores = {c: (st_nok0 if c == "ALL-K0" else st) for c in args.conditions}
    tree_real = json.loads((run / "tree_real.json").read_text(encoding="utf-8")) if (run / "tree_real.json").exists() else None
    grid_real = json.loads((run / "grid_real.json").read_text(encoding="utf-8")) if (run / "grid_real.json").exists() else None
    llm = LLM()
    root = run / "eval"
    ctxs, extra_valid = {}, {}
    for c in args.conditions:
        d = root / c; d.mkdir(parents=True, exist_ok=True)
        spec = CONDS[c]
        if spec is None:
            ctxs[c] = None; continue
        if spec == "S0raw":
            ctx = R.build_context(KBStore(args.src), condition="S0raw")
        elif isinstance(spec, str) and spec.startswith("cards_v2:"):
            ctx = MK.build_context(stores[c], run / "cards_v2", selection=spec.split(":")[1], top=10, label=c)
        elif c == "ALL-real":
            ctx = build_worksheets(st, spec, tree=tree_real, grid=grid_real, real_only=True, label=c)
        else:
            ctx = build_worksheets(stores[c], spec, label=c, cards=(c != "ALL-nocards"))
        (d / "context.txt").write_text(ctx.text, encoding="utf-8")
        (d / "context_stats.json").write_text(json.dumps(ctx.stats, ensure_ascii=False, indent=1), encoding="utf-8")
        ctxs[c] = ctx
        extra_valid[c] = set(ctx.ops_by_ref)
        print(f"[{c}] context {ctx.stats.get('chars')} chars {ctx.stats.get('chars_by_structure', '')}", flush=True)

    def gen_job(c, i):
        p = root / c / f"rm_{i}.json"
        if p.exists() and not args.force:
            return c, i, Roadmap.model_validate_json(p.read_text(encoding="utf-8"))
        ctx = ctxs[c]
        if ctx is None:
            rm = G.generate(llm, condition="initial")
        elif CONDS[c] == "S0raw":
            rm = G.generate(llm, condition="advanced", context=ctx.text, ops_by_evidence=ctx.ops_by_ref)
        elif isinstance(CONDS[c], str) and CONDS[c].startswith("cards_v2:"):
            rm = MK.generate(llm, ctx)
        else:
            rm = SG.generate(llm, ctx)
        p.write_text(rm.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")
        return c, i, rm

    jobs = [(c, i) for c in args.conditions for i in range(1, args.n + 1)]
    rms = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for c, i, rm in ex.map(lambda x: gen_job(*x), jobs):
            rms[(c, i)] = rm
            print(f"  gen {c} #{i}: {len(rm.nodes)} nodes, {len(rm.edges)} edges, cost {rm.cost_usd}", flush=True)

    def judge_job(c, i, j):
        p = root / c / f"align_{i}_{JTAG[j]}.json"
        if p.exists() and not args.force:
            return c, i, j, json.loads(p.read_text(encoding="utf-8"))
        a = align(rms[(c, i)], llm, model=j)
        p.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
        return c, i, j, a

    jj = [(c, i, j) for (c, i) in jobs for j in args.judges]
    al = {}
    with ThreadPoolExecutor(max_workers=args.workers + 2) as ex:
        for c, i, j, a in ex.map(lambda x: judge_job(*x), jj):
            al[(c, i, j)] = a
    tree = st.tree or {}
    areas = [(a["name"], embed([f"{a['name']}. {a.get('summary', '')[:300]}"])[0]) for a in tree.get("areas", []) if a["name"] != "Other topics"]
    rows = []
    for c in args.conditions:
        stc = [structural(rms[(c, i)], stores[c], extra_valid.get(c, set()), areas) for i in range(1, args.n + 1)]
        alc = [al[(c, i, j)] for i in range(1, args.n + 1) for j in args.judges]
        row = {"condition": c, "n_gen": args.n, "n_judge": len(args.judges)}
        for k in ("nodes", "edges", "evidence_rate", "multi_source_rate", "invalid_cite_rate", "synthetic_share",
                  "edge_grounded_rate", "area_coverage", "revised", "conflict", "infeasible"):
            row[k] = ms([s[k] for s in stc])
        for k in ("recall_strict", "recall_lenient", "recall_2020_lenient", "recall_2025_lenient", "year_mae"):
            row[k] = ms([a[k] for a in alc])
            row[k + "_by_judge"] = {JTAG[j]: ms([al[(c, i, j)][k] for i in range(1, args.n + 1)])[0] for j in args.judges}
        row["context"] = ctxs[c].stats if ctxs.get(c) else None
        rows.append(row)
    summ = {"run": run.name, "generator": G.DEFAULT_MODEL, "judges": args.judges, "rows": rows, "cost_usd": round(llm.ledger.total_usd, 4)}
    (root / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    hdr = ("| 조건 | 항목 수 | 근거 부착률 | 다중 출처 | 내부 자료 인용 | 근거 있는 연결 | 영역 포괄 | recall 관대 | recall 엄격 | "
           "2020판 | 2025판 | 연도 MAE | revised |")
    md = [f"# 다섯 지식 구조 비교 — {run.name} (생성 {G.DEFAULT_MODEL} × {args.n}회, 판정 {len(args.judges)}종)", "",
          "값 = 평균±표준편차 (구조 지표는 생성 n회, 정렬 지표는 생성 n회 × 판정 모델 수)", "", hdr, "|" + "---|" * 13]
    for r in rows:
        md.append(f"| {r['condition']} | {fmt(*r['nodes'], pct=False)} | {fmt(*r['evidence_rate'])} | {fmt(*r['multi_source_rate'])} | "
                  f"{fmt(*r['synthetic_share'])} | {fmt(*r['edge_grounded_rate'])} | {fmt(*r['area_coverage'])} | "
                  f"{fmt(*r['recall_lenient'])} | {fmt(*r['recall_strict'])} | {fmt(*r['recall_2020_lenient'])} | "
                  f"{fmt(*r['recall_2025_lenient'])} | {fmt(*r['year_mae'], pct=False)} | {fmt(*r['revised'], pct=False)} |")
    md.append("\n판정 모델별 관대 recall 평균")
    md.append("| 조건 | " + " | ".join(JTAG[j] for j in args.judges) + " |")
    md.append("|---|" + "---|" * len(args.judges))
    for r in rows:
        md.append(f"| {r['condition']} | " + " | ".join(f"{round((r['recall_lenient_by_judge'][JTAG[j]] or 0) * 100)}%" for j in args.judges) + " |")
    md.append(f"\n이번 실행 비용 ${llm.ledger.total_usd:.3f}")
    (root / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
