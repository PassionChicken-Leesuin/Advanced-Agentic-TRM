"""run 하나의 처리 시간·비용·결과물 품질을 한 표로 모은다 (180건 struct5 와 업로드 run 둘 다).

python scripts/measure_run.py --run runs/struct5 [--build-log runs/struct5_build.log] [--out 연구계획/측정.md]
산출: runs/<run>/measure.json + (옵션) markdown 표

측정 항목
  시간   events.jsonl 의 단계별 첫·끝 사건 시각 (read / build / finish), 문서별 doc.started→doc.finished 초 분포 (build 로그가 있으면 로그 값),
         업로드 run 은 job.json 의 단계별 초
  비용   cost_*.json (단계별 달러·호출 수), cards_v2/roadmaps/*.json 의 cost_usd, eval/*/align_*.json 의 judge_cost_usd
  크기   SourceStore.stats(): 문서·문장·대상·용어·관계·시간 사실·주제·영역·기회 기록
  내재 품질 (정답표 없이 계산)  문장 유지율(irrelevant·duplicate 비율), 다층 태그 비율, 구조 배정 비율, K5 갱신·충돌 사슬 수,
         K0 확정 비율, 병합 횟수, 카드 수·줄 채움률, 선정 토론의 모델 편차(sd)·근거 있는 모델 수, 로드맵의 근거 부착률·다중 출처율·내부 자료 인용률·기간 밖 항목
  정답 대비 품질 (있을 때)  eval/summary.json 의 조건별 recall·연도 MAE (180건 IonQ 평가)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import statistics as S
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.store import SourceStore


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _span(evs: list[dict], types: set[str]) -> tuple[str | None, str | None, float | None]:
    ts = [e["ts"] for e in evs if e["type"] in types]
    if not ts:
        return None, None, None
    a, b = min(ts), max(ts)
    return a, b, round((_ts(b) - _ts(a)).total_seconds(), 1)


def _dist(xs: list[float]) -> dict:
    if not xs:
        return {}
    xs = sorted(xs)
    return {"n": len(xs), "sum": round(sum(xs), 1), "mean": round(S.mean(xs), 1), "median": round(S.median(xs), 1),
            "p90": round(xs[min(len(xs) - 1, int(len(xs) * 0.9))], 1), "max": round(xs[-1], 1)}


def timing(run: Path, evs: list[dict], build_log: Path | None) -> dict:
    out: dict = {}
    r0, r1, rs = _span(evs, {"doc.read"})
    out["read"] = {"start": r0, "end": r1, "seconds": rs, "documents": sum(1 for e in evs if e["type"] == "doc.read")}
    b0, b1, bs = _span(evs, {"doc.started", "doc.finished"})
    out["build"] = {"start": b0, "end": b1, "seconds": bs, "documents": len({e["doc_id"] for e in evs if e["type"] == "doc.finished"})}
    f0, f1, fs = _span(evs, {"entity.merged", "tree.theme_merged", "tree.started", "tree.built", "grid.started", "grid.built", "tree.area_built", "tree.theme_summarized"})
    out["finish"] = {"start": f0, "end": f1, "seconds": fs, "note": "병합·트리·그리드 (재실행·보정 포함: redo_tree·unmerge 가 있었다면 그 시각까지)"}
    # 문서별 처리 시간: 사건 시각 (doc.started → 같은 문서의 doc.finished)
    started: dict[str, str] = {}
    per_doc: list[float] = []
    for e in evs:
        if e["type"] == "doc.started":
            started[e["doc_id"]] = e["ts"]
        elif e["type"] == "doc.finished" and e["doc_id"] in started and not e.get("reconstructed"):
            per_doc.append((_ts(e["ts"]) - _ts(started.pop(e["doc_id"]))).total_seconds())
    out["per_document_seconds_from_events"] = _dist(per_doc)
    if build_log and build_log.exists():
        ts, cs, ps = [], [], []
        for l in build_log.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.search(r"^\[(\d+)\].*?p=\s*(\d+).*?\s(\d+)s \$([0-9.]+)", l)
            if m:
                ps.append(int(m.group(2))); ts.append(int(m.group(3))); cs.append(float(m.group(4)))
        out["per_document_from_log"] = {"seconds": _dist([float(x) for x in ts]), "usd": _dist(cs), "passages": _dist([float(x) for x in ps]),
                                        "seconds_per_passage": round(sum(ts) / max(1, sum(ps)), 2)}
    job = run / "job.json"
    if job.exists():
        j = json.loads(job.read_text(encoding="utf-8"))
        out["job"] = {"status": j.get("status"), "seconds_total": j.get("seconds"), "cost_usd": j.get("cost_usd"),
                      "stages": {k: v.get("seconds") for k, v in j.get("stages", {}).items()}}
    return out


def costs(run: Path) -> dict:
    out: dict = {"stages": {}, "total_usd": 0.0}
    for p in sorted(run.glob("cost_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out["stages"][p.stem[5:]] = {"usd": round(d.get("total_usd", 0), 3), "calls": d.get("n_calls"),
                                     "by_purpose": {k: round(v["cost_usd"], 3) for k, v in (d.get("by_purpose") or {}).items()} if isinstance(d.get("by_purpose"), dict) else None}
    # 업로드 run: cost_read/build/finish/job 은 같은 원장의 누적 스냅샷 → 단계별 증분으로 바꾸고 합계는 job 값
    if "job" in out["stages"]:
        order = [k for k in ("read", "build", "finish", "job") if k in out["stages"]]
        prev = 0.0
        for k in order:
            cum = out["stages"][k]["usd"]
            out["stages"][k]["usd_cumulative"] = cum
            out["stages"][k]["usd"] = round(cum - prev, 3)
            prev = cum
        out["stages"]["job"]["note"] = "cards+select+make+initial (증분); usd_cumulative 가 작업 전체"
        out["total_usd"] = prev
    else:
        out["total_usd"] = round(sum(v["usd"] for k, v in out["stages"].items()), 3)
    rm_cost = 0.0
    for p in list((run / "cards_v2" / "roadmaps").glob("rm_*.json")) + list(run.glob("roadmap_*.json")):
        rm_cost += json.loads(p.read_text(encoding="utf-8")).get("cost_usd") or 0
    out["roadmaps_usd"] = round(rm_cost, 3)
    sel = run / "cards_v2" / "selection"
    out["select_debates"] = len(list(sel.glob("debate_*.json"))) if sel.exists() else 0
    ev = run / "eval"
    if ev.exists():
        gen = judge = 0.0
        for c in ev.iterdir():
            for p in c.glob("rm_*.json"):
                gen += json.loads(p.read_text(encoding="utf-8")).get("cost_usd") or 0
            for p in c.glob("align_*.json"):
                judge += json.loads(p.read_text(encoding="utf-8")).get("judge_cost_usd") or 0
        out["eval"] = {"generation_usd": round(gen, 3), "judge_usd": round(judge, 3), "conditions": sum(1 for c in ev.iterdir() if c.is_dir())}
    return out


def intrinsic(st: SourceStore, run: Path, evs: list[dict]) -> dict:
    stats = st.stats()
    n = max(1, stats["passages"])
    kept = stats["routed_to_system"].get("evidence", 0)
    out: dict = {"kb": stats,
                 "passage_keep_rate": round(kept / n, 3),
                 "irrelevant_rate": round(stats["status"].get("irrelevant", 0) / n, 3),
                 "duplicate_rate": round(stats["status"].get("duplicate", 0) / n, 3),
                 "multi_layer_rate": round(stats["multi_layer_passages"] / n, 3),
                 "routed_share": {k: round(v / max(1, kept), 3) for k, v in stats["routed_to_system"].items() if k != "evidence"},
                 "glossary_confirmed_rate": round(sum(1 for t in st.terms.values() if t.status == "confirmed") / max(1, len(st.terms)), 3),
                 "entity_merges": sum(1 for e in evs if e["type"] == "entity.merged"),
                 "time_chains": {"update": stats["time_fact_status"].get("update", 0), "conflict": stats["time_fact_status"].get("conflict", 0)},
                 "errors": Counter(e.get("structure") or "doc" for e in evs if e["type"] == "error")}
    # 대상(Entity) 지지도 분포: 문서 1건짜리 대상이 얼마나 많은가 (잡음 지표)
    sup = [len(set(e.doc_ids)) for e in st.entities.values()]
    out["entities_single_doc_rate"] = round(sum(1 for s in sup if s <= 1) / max(1, len(sup)), 3)
    # 카드
    cdir = run / "cards_v2"
    if (cdir / "cards.json").exists():
        cards = json.loads((cdir / "cards.json").read_text(encoding="utf-8"))
        lines = ("why", "trend", "what", "when", "how", "resource", "actors", "issue")
        out["cards"] = {"n": len(cards),
                        "line_fill_rate": {k: round(sum(1 for c in cards if c.get(k)) / max(1, len(cards)), 2) for k in lines},
                        "single_doc_cards": sum(1 for c in cards if (c.get("docs_public", 0) + c.get("docs_internal", 0)) <= 1),
                        "chars_mean": round(S.mean([len(json.dumps(c)) for c in cards])) if cards else 0}
        prof = cdir / "selection" / "profiles.json"
        if prof.exists():
            recs = json.loads(prof.read_text(encoding="utf-8"))
            sd = [r["profile"][f"q{i}_sd_final"] for r in recs for i in (1, 2, 3)]
            gr = [r["profile"][f"q{i}_n_grounded"] for r in recs for i in (1, 2, 3)]
            out["selection"] = {"cards_debated": len(recs), "selected": sum(1 for r in recs if r["profile"].get("selected")),
                                "panel_sd_mean": round(S.mean(sd), 2) if sd else None, "panel_sd_max": max(sd) if sd else None,
                                "grounded_models_mean": round(S.mean(gr), 2) if gr else None,
                                "path_needed": sum(1 for r in recs if r["profile"].get("path_needed"))}
    # 로드맵 (관점별 + initial)
    rms = {}
    for p in sorted((cdir / "roadmaps").glob("rm_*.json")) if (cdir / "roadmaps").exists() else []:
        rms[p.stem[3:]] = json.loads(p.read_text(encoding="utf-8"))
    for name in ("initial", "advanced"):
        p = run / f"roadmap_{name}.json"
        if p.exists():
            rms[name] = json.loads(p.read_text(encoding="utf-8"))
    h0, h1 = st.profile["horizon"]
    out["roadmaps"] = {}
    for k, rm in rms.items():
        nodes = rm.get("nodes", [])
        ev_ok = ev_bad = multi = syn = 0
        for nd in nodes:
            docs = set(); s = 0
            for cid in nd.get("evidence_ids", []):
                p = st.passages.get(cid); f = st.facts.get(cid)
                if p is None and f is not None:
                    p = st.passages.get(f.pid)
                if p is None:
                    ev_bad += 1; continue
                ev_ok += 1; docs.add(p.doc_id); s += p.is_synthetic
            multi += len(docs) >= 2
            syn += s
        out["roadmaps"][k] = {"nodes": len(nodes), "edges": len(rm.get("edges", [])),
                              "by_layer": dict(Counter(nd["layer"] for nd in nodes)),
                              "evidence_rate": round(sum(1 for nd in nodes if nd.get("evidence_ids")) / max(1, len(nodes)), 2),
                              "multi_source_rate": round(multi / max(1, len(nodes)), 2),
                              "invalid_cite_rate": round(ev_bad / max(1, ev_ok + ev_bad), 3),
                              "internal_cite_share": round(syn / max(1, ev_ok), 2),
                              "outside_horizon": sum(1 for nd in nodes if (nd.get("start") or h0) < h0 - 0.01 or (nd.get("end") or h1) > h1 + 1.01),
                              "flags": dict(Counter(f for nd in nodes for f in nd.get("flags", []))),
                              "cost_usd": rm.get("cost_usd")}
    return out


def ground_truth(run: Path) -> dict | None:
    p = run / "eval" / "summary.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = {}
    for r in d["rows"]:
        rows[r["condition"]] = {k: r[k] for k in ("nodes", "evidence_rate", "multi_source_rate", "edge_grounded_rate", "recall_strict", "recall_lenient",
                                                 "recall_2020_lenient", "recall_2025_lenient", "year_mae") if k in r}
        rows[r["condition"]]["recall_strict_by_judge"] = r.get("recall_strict_by_judge")
    return {"generator": d.get("generator"), "judges": d.get("judges"), "rows": rows}


def markdown(m: dict) -> str:
    L = [f"# 측정 — {m['run']} ({m['profile']['company']}, 기준일 {m['profile']['cutoff']})", ""]
    t = m["timing"]
    L += ["## 처리 시간", "", "| 단계 | 시작 | 끝 | 초 | 문서 |", "|---|---|---|---|---|"]
    for k in ("read", "build", "finish"):
        v = t[k]
        L.append(f"| {k} | {(v['start'] or '')[:19]} | {(v['end'] or '')[:19]} | {v['seconds']} | {v.get('documents', '')} |")
    if t.get("job"):
        L += ["", f"업로드 작업 전체: {t['job']['seconds_total']}초, ${t['job']['cost_usd']} · 단계별 초 {t['job']['stages']}"]
    pd = t.get("per_document_from_log", {}).get("seconds") or t.get("per_document_seconds_from_events")
    if pd:
        L += ["", f"문서별 구축 시간(초): n={pd['n']}, 평균 {pd['mean']}, 중앙값 {pd['median']}, p90 {pd['p90']}, 최대 {pd['max']}"]
    c = m["costs"]
    L += ["", "## 비용 (USD)", "", "| 단계 | 달러 | 호출 |", "|---|---|---|"]
    for k, v in c["stages"].items():
        L.append(f"| {k} | {v['usd']} | {v['calls']} |")
    L.append(f"| 로드맵 생성(카드 v2·initial) | {c['roadmaps_usd']} | |")
    if c.get("eval"):
        L.append(f"| 평가 (생성 {c['eval']['conditions']}조건) | 생성 {c['eval']['generation_usd']} + 판정 {c['eval']['judge_usd']} | |")
    L.append(f"| **합계(구축)** | **{c['total_usd']}** | |")
    q = m["intrinsic"]
    kb = q["kb"]
    L += ["", "## 지식베이스 크기", "", f"문서 {kb['documents']} · 문장 {kb['passages']} (유지 {q['passage_keep_rate']:.0%}, 무관 {q['irrelevant_rate']:.1%}, 중복 {q['duplicate_rate']:.1%}, 다층 {q['multi_layer_rate']:.0%})",
          f"대상 {kb['entities']} (문서 1건짜리 {q['entities_single_doc_rate']:.0%}) · 용어 {kb['glossary_terms']} (확정 {q['glossary_confirmed_rate']:.0%}) · 관계 {kb['graph_relations']} · 시간 사실 {kb['time_facts']} (갱신 {q['time_chains']['update']}, 충돌 {q['time_chains']['conflict']}) · 주제 {kb['tree_themes']} / 영역 {kb['tree_areas']} · 기회 기록 {kb['grid_opportunities']}",
          f"구조 배정 비율(유지 문장 대비): {q['routed_share']} · 병합 {q['entity_merges']}회 · 오류 {dict(q['errors'])}"]
    if q.get("cards"):
        cd = q["cards"]
        L += ["", "## 기회 카드·선정", "", f"카드 {cd['n']}장 (문서 1건짜리 {cd['single_doc_cards']}), 줄 채움률 {cd['line_fill_rate']}"]
        if q.get("selection"):
            s = q["selection"]
            L.append(f"토론 {s['cards_debated']}장 → 선정 {s['selected']} · 모델 편차 평균 {s['panel_sd_mean']} (최대 {s['panel_sd_max']}) · 근거 있는 모델 수 평균 {s['grounded_models_mean']}/3 · 경로 없음 {s['path_needed']}")
    if q.get("roadmaps"):
        L += ["", "## 로드맵 (내재 지표)", "", "| 로드맵 | 항목 | 연결 | 층 | 근거 부착 | 다중 출처 | 잘못된 인용 | 내부 인용 | 기간 밖 | 플래그 | 달러 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in q["roadmaps"].items():
            L.append(f"| {k} | {v['nodes']} | {v['edges']} | {v['by_layer']} | {v['evidence_rate']:.0%} | {v['multi_source_rate']:.0%} | {v['invalid_cite_rate']:.1%} | {v['internal_cite_share']:.0%} | {v['outside_horizon']} | {v['flags']} | {v['cost_usd']} |")
    g = m.get("ground_truth")
    if g:
        L += ["", f"## 정답표 대비 (생성 {g['generator']} × 3, 판정 {len(g['judges'])}종)", "", "| 조건 | 항목 | 근거 부착 | 근거 있는 연결 | recall 엄격 | recall 관대 | 2020판 | 2025판 | 연도 MAE |", "|---|---|---|---|---|---|---|---|---|"]
        for c_, r in g["rows"].items():
            f = lambda x: f"{x[0]:.0%}±{x[1]:.0%}" if isinstance(x, list) and x[0] <= 1 else (f"{x[0]:.2f}±{x[1]:.2f}" if isinstance(x, list) else x)
            L.append(f"| {c_} | {r['nodes'][0]:.0f} | {f(r['evidence_rate'])} | {f(r.get('edge_grounded_rate', [0, 0]))} | {f(r['recall_strict'])} | {f(r['recall_lenient'])} | {f(r['recall_2020_lenient'])} | {f(r['recall_2025_lenient'])} | {f(r['year_mae'])} |")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--build-log", default=None)
    ap.add_argument("--out", default=None, help="markdown 출력 경로 (없으면 표준 출력)")
    a = ap.parse_args()
    run = Path(a.run)
    st = SourceStore(run)
    evs = [json.loads(l) for l in (run / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    m = {"run": run.name, "profile": st.profile, "timing": timing(run, evs, Path(a.build_log) if a.build_log else None),
         "costs": costs(run), "intrinsic": intrinsic(st, run, evs), "ground_truth": ground_truth(run)}
    (run / "measure.json").write_text(json.dumps(m, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = markdown(m)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print("wrote", a.out)
    else:
        print(md)


if __name__ == "__main__":
    main()
