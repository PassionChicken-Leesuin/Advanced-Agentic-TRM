"""구축 단계 함수 모음 — scripts/build_v2.py(명령줄)와 trmkb.sources.jobs(업로드 작업)가 같은 코드를 쓴다.

read_docs      새 Reader(인용 전용)로 문서를 읽어 소스 문장(Passage)을 만든다
ensure_company 회사 자체를 공유 대상으로 둔다 (K5 전략 마일스톤의 대상, K4 customer_of 의 끝점)
process        문서 1건: K0 용어집 → Router → 구조 전용 추출기(K2·K3·K4·K5) 병렬 호출 → 순차 반영
build_docs     문서를 날짜순으로 process (재개 가능, 진행 콜백)
finish         마무리: 용어집 검토표, LLM 병합(consolidate), K2 요약 트리, K3 연계 그리드 (+ 실제 자료 전용 판)
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..llm import LLM
from .extract import EXTRACTORS
from .resolve import Resolver, norm
from .router import Router
from .store import SYSTEMS, Entity, Passage, SourceStore


def close_doc(st: SourceStore, d: dict, *, reason: str, n: int = 0, error: str | None = None) -> dict:
    """문장이 하나도 없거나(Reader 가 로드맵 문장을 못 찾음) 처리에 실패한 문서도 '처리됨'으로 닫는다.
    화면의 진행률은 doc.finished 사건으로 세므로, 이 사건이 없으면 2/3 처럼 끝나지 않은 것으로 보인다 (2026-11-08 수정).
    같은 문서를 두 번 닫지 않도록 st.docs 에 표시한다 (재개 시)."""
    meta = st.docs.get(d["id"], {})
    r = {"passages": n, "kept": 0, "routes": {s: 0 for s in SYSTEMS}, "status": {}, "extracted": {}, "skipped": reason}
    if meta.get("closed"):
        return r
    st.emit("doc.started", doc_id=d["id"], title=d["title"], date=d["date"], source_type=d["source_type"],
            synthetic=d.get("is_synthetic", False), n=n)
    if error:
        r["error"] = error[:200]
    st.emit("doc.finished", doc_id=d["id"], title=d["title"], **r)
    if d["id"] in st.docs:
        st.docs[d["id"]]["closed"] = True
    print(f"[closed] {d['date']} {d['id'][:44]:44s} {reason}", flush=True)
    return r


def read_docs(st: SourceStore, llm: LLM, docs: list[dict], workers: int = 20, on_doc: Callable[[dict, int], None] | None = None) -> None:
    from .reader import QuoteReader
    reader = QuoteReader(llm, company=st.company)
    todo = [d for d in docs if not d.get("read")]

    def job(d):
        try:
            return d, reader.read(d)
        except Exception as e:  # noqa: BLE001
            print("READ ERR", d["id"], e)
            st.emit("error", doc_id=d["id"], structure="reader", msg=str(e)[:200])
            return d, None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d, ps in ex.map(job, todo):
            if ps is None:
                continue
            for p in ps:
                st.passages[p.id] = p
            st.docs[d["id"]]["read"] = True
            st.emit("doc.read", doc_id=d["id"], title=d["title"], date=d["date"], n=len(ps))
            print(f"  read {d['date']} {d['id'][:50]:50s} quotes={len(ps)}", flush=True)
            if on_doc:
                on_doc(d, len(ps))
    st.save()


def ensure_company(st: SourceStore) -> None:
    if not any(norm(e.name) == norm(st.company) for e in st.entities.values()):
        e = Entity(name=st.company, aliases=list(st.profile.get("aliases") or []))
        st.entities[e.id] = e


def process(doc: dict, ps: list[Passage], router: Router, extractors: dict, pool: ThreadPoolExecutor, glossary=None) -> dict:
    st = router.store
    g = {}
    if glossary is not None:                      # K0: Router 앞에서 용어·별칭을 먼저 모음 (Router·추출기가 그 이름을 씀)
        try:
            g = glossary.apply(doc, ps, glossary.call(doc, ps))
        except Exception as e:  # noqa: BLE001
            st.emit("error", doc_id=doc["id"], structure="glossary", msg=str(e)[:200])
            print("  glossary error", e)
    r = router.route_doc(doc, ps)
    r["glossary"] = g
    routed = {s: [p for p in ps if s in p.systems] for s in SYSTEMS}
    futs = {s: pool.submit(extractors[s].call, doc, routed[s]) for s in SYSTEMS if routed[s]}
    got = {}
    for s in ("graph", "grid", "time", "tree"):      # 반영은 순차 (대상 생성 경합 방지)
        if s in futs:
            try:
                got[s] = extractors[s].apply(doc, routed[s], futs[s].result())
            except Exception as e:  # noqa: BLE001
                st.emit("error", doc_id=doc["id"], structure=s, msg=str(e)[:200])
                print("  extractor error", s, e)
                got[s] = 0
    r["extracted"] = got
    return r


def build_docs(st: SourceStore, llm: LLM, order: list[dict], *, model: str = "openai/gpt-4.1-mini", glossary: bool = True,
               limit: int | None = None, on_doc: Callable[[dict, dict, float], None] | None = None, batch: int = 1) -> int:
    """order 의 문서를 차례로 process. 이미 라우팅된 문서는 건넘. 반환: 이번에 처리한 문서 수.
    batch > 1 이면 build_docs_batched (문서 batch 건의 LLM 호출을 동시에, 반영은 날짜순)."""
    if batch > 1:
        return build_docs_batched(st, llm, order, model=model, glossary=glossary, limit=limit, on_doc=on_doc, batch=batch)
    ensure_company(st)
    res = Resolver(st)
    router = Router(llm, st, res, model=model)
    extractors = {s: EXTRACTORS[s](llm, st, res) for s in SYSTEMS}
    gl = None
    if glossary:
        from .glossary import GlossaryExtractor
        gl = GlossaryExtractor(llm, st, res)
    by_doc: dict[str, list[Passage]] = {}
    for p in st.passages.values():
        by_doc.setdefault(p.doc_id, []).append(p)
    (st.dir / "plan.json").write_text(json.dumps({"total": len(order)}), encoding="utf-8")
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for d in order:
            ps = by_doc.get(d["id"], [])
            if not ps:              # Reader 가 로드맵 문장을 하나도 찾지 못한 문서 (예: 짧은 위임장 공시): 처리됨으로 닫음
                r = close_doc(st, d, reason="no roadmap-relevant sentences")
                if on_doc:
                    on_doc(d, r, 0.0)
                continue
            if all(p.routed for p in ps):
                continue
            if limit and done >= limit:
                break
            t0, c0 = time.time(), llm.ledger.total_usd
            st.emit("doc.started", doc_id=d["id"], title=d["title"], date=d["date"], source_type=d["source_type"],
                    synthetic=d["is_synthetic"], n=len(ps))
            try:
                r = process(d, [p for p in ps if not p.routed], router, extractors, pool, gl)
            except Exception as e:  # noqa: BLE001
                st.emit("error", doc_id=d["id"], msg=str(e)[:200])
                print("ERR", d["id"], e)
                r = close_doc(st, d, reason="processing failed", n=len(ps), error=str(e))
                if on_doc:
                    on_doc(d, r, time.time() - t0)
                continue
            st.emit("doc.finished", doc_id=d["id"], title=d["title"], **r)
            st.docs[d["id"]]["closed"] = True
            done += 1
            print(f"[{done}] {d['date']} {d['id'][:44]:44s} p={r['passages']:3d} kept={r['kept']:3d} "
                  f"routes={r['routes']} extracted={r['extracted']} gloss={r.get('glossary')} {time.time() - t0:4.0f}s ${llm.ledger.total_usd - c0:.3f}", flush=True)
            if on_doc:
                on_doc(d, r, time.time() - t0)
            if done % 5 == 0:
                st.save(); llm.ledger.dump(st.dir / "cost_build.json")
    st.save(); llm.ledger.dump(st.dir / "cost_build.json")
    return done


def finish(st: SourceStore, llm: LLM, *, real_only_too: bool = True, on_stage: Callable[[str], None] | None = None) -> dict:
    from .consolidate import consolidate
    from .glossary import export_review
    from .grid import build_grid
    from .tree import build_tree
    out: dict = {}
    dst = st.dir
    if st.terms:
        out["glossary_review"] = str(export_review(st, dst / "glossary_review.md"))
    if on_stage:
        on_stage("consolidate")
    if not (dst / "consolidated.json").exists():      # 정리 단계는 한 번만 (재실행 안전)
        c = consolidate(st, llm); st.save()
        (dst / "consolidated.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        out["consolidate"] = c
    if on_stage:
        on_stage("tree")
    t = build_tree(st, llm); st.save()
    out["tree"] = {k: len(v) if isinstance(v, list) else v for k, v in t.items() if k in ("areas", "themes")}
    if on_stage:
        on_stage("grid")
    g = build_grid(st, llm); st.save()
    out["grid"] = {"columns": len(g["columns"]), "cells": len(g["cells"])}
    if real_only_too and any(d.get("is_synthetic") for d in st.docs.values()):
        tr = build_tree(st, llm, real_only=True, emit=False)
        (dst / "tree_real.json").write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
        gr = build_grid(st, llm, real_only=True, emit=False)
        (dst / "grid_real.json").write_text(json.dumps(gr, ensure_ascii=False, indent=1), encoding="utf-8")
    llm.ledger.dump(dst / "cost_finish.json")
    return out


def build_docs_batched(st: SourceStore, llm: LLM, order: list[dict], *, model: str = "openai/gpt-4.1-mini", glossary: bool = True,
                       limit: int | None = None, on_doc: Callable[[dict, dict, float], None] | None = None, batch: int = 20) -> int:
    """묶음 구축: 날짜순 문서 batch 건을 한 묶음으로, 세 라운드를 차례로 돈다.
      1) K0 용어집: batch 건 동시 호출 -> 날짜순 반영
      2) Router: batch 건 동시 호출 (1의 용어집을 봄) -> 날짜순 반영 (대상 생성·연결)
      3) 추출기 4종: batch x 4 동시 호출 (2의 대상을 봄) -> 날짜순·구조순 반영
    각 라운드의 호출은 그 시점 저장소를 읽기만 하므로 안전하다. 잃는 것은 같은 묶음 안의 앞 문서가 같은 라운드에서 쌓은 내용
    (예: 같은 묶음의 두 문서가 같은 사실을 말하면 Router 가 duplicate 대신 new 로 볼 수 있음, K5 갱신 사슬). 마무리 단계의
    병합(consolidate)과 시간 사슬 재연결이 그 일부를 되살린다."""
    ensure_company(st)
    res = Resolver(st)
    router = Router(llm, st, res, model=model)
    extractors = {s: EXTRACTORS[s](llm, st, res) for s in SYSTEMS}
    gl = None
    if glossary:
        from .glossary import GlossaryExtractor
        gl = GlossaryExtractor(llm, st, res)
    by_doc: dict[str, list[Passage]] = {}
    for p in st.passages.values():
        by_doc.setdefault(p.doc_id, []).append(p)
    (st.dir / "plan.json").write_text(json.dumps({"total": len(order), "batch": batch}), encoding="utf-8")
    todo = []
    for d in order:
        allps = by_doc.get(d["id"], [])
        if not allps:
            r = close_doc(st, d, reason="no roadmap-relevant sentences")
            if on_doc:
                on_doc(d, r, 0.0)
            continue
        ps = [p for p in allps if not p.routed]
        if ps:
            todo.append((d, ps))
    if limit:
        todo = todo[:limit]
    done = 0
    n_theme_before = len(st.themes)

    def par(fn, items):
        """items 마다 fn 을 동시에. 실패는 (None, 예외) 로 돌려 그 문서만 건넘."""
        def safe(x):
            try:
                return fn(x), None
            except Exception as e:  # noqa: BLE001
                return None, e
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=len(items)) as ex:
            return list(ex.map(safe, items))

    for b0 in range(0, len(todo), batch):
        group = todo[b0:b0 + batch]
        t0, c0 = time.time(), llm.ledger.total_usd
        st.emit("batch.started", n=len(group), docs=[d["id"] for d, _ in group])
        failed: set[str] = set()
        glo: dict[str, dict] = {}
        if gl is not None:
            for (d, ps), (out, err) in zip(group, par(lambda x: gl.call(x[0], x[1]), group)):
                if err is not None:
                    st.emit("error", doc_id=d["id"], structure="glossary", msg=str(err)[:200]); print("  glossary error", d["id"], err)
                    continue
                try:
                    glo[d["id"]] = gl.apply(d, ps, out)
                except Exception as e:  # noqa: BLE001
                    st.emit("error", doc_id=d["id"], structure="glossary", msg=str(e)[:200])
        t1 = time.time()
        routed: dict[str, dict] = {}
        for (d, ps), (called, err) in zip(group, par(lambda x: router.call_doc(x[0], x[1]), group)):
            if err is not None:
                st.emit("error", doc_id=d["id"], msg=str(err)[:200]); print("ERR router", d["id"], err)
                failed.add(d["id"])
                r = close_doc(st, d, reason="processing failed", n=len(ps), error=str(err))
                if on_doc:
                    on_doc(d, r, 0.0)
                continue
            st.emit("doc.started", doc_id=d["id"], title=d["title"], date=d["date"], source_type=d["source_type"],
                    synthetic=d["is_synthetic"], n=len(ps))
            r = router.apply_doc(d, ps, called)
            r["glossary"] = glo.get(d["id"], {})
            routed[d["id"]] = r
        t2 = time.time()
        jobs = []
        for d, ps in group:
            if d["id"] in failed:
                continue
            for s_ in SYSTEMS:
                sub = [p for p in ps if s_ in p.systems]
                if sub:
                    jobs.append((d, s_, sub))
        outs = par(lambda x: extractors[x[1]].call(x[0], x[2]), jobs)
        got = {(d["id"], s_): (sub, o, e) for (d, s_, sub), (o, e) in zip(jobs, outs)}
        secs = (time.time() - t0) / max(1, len(group))
        for d, ps in group:
            if d["id"] in failed:
                continue
            ex_ = {}
            for s_ in ("graph", "grid", "time", "tree"):      # 반영은 순차 (대상 생성 경합 방지)
                if (d["id"], s_) not in got:
                    continue
                sub, o, e = got[(d["id"], s_)]
                if e is not None:
                    st.emit("error", doc_id=d["id"], structure=s_, msg=str(e)[:200]); ex_[s_] = 0; continue
                try:
                    ex_[s_] = extractors[s_].apply(d, sub, o)
                except Exception as e2:  # noqa: BLE001
                    st.emit("error", doc_id=d["id"], structure=s_, msg=str(e2)[:200]); print("  extractor error", s_, e2); ex_[s_] = 0
            r = routed[d["id"]]; r["extracted"] = ex_
            st.emit("doc.finished", doc_id=d["id"], title=d["title"], **r)
            st.docs[d["id"]]["closed"] = True
            done += 1
            if on_doc:
                on_doc(d, r, secs)
        # 주제(K2)는 자유 이름이라 같은 묶음의 문서끼리 표현만 다른 주제를 따로 만든다 (시범: 40건에서 새 주제 155 대 35).
        # 묶음이 끝날 때마다 마무리 단계와 같은 LLM 주제 병합을 돌려, 다음 묶음이 정리된 주제 목록을 보게 한다.
        n_theme = len(st.themes)
        if n_theme > n_theme_before:
            from .consolidate import merge_themes
            try:
                mt = merge_themes(st, llm)
                print(f"  theme merge after batch: {n_theme} -> {len(st.themes)} ({mt})", flush=True)
            except Exception as e:  # noqa: BLE001
                st.emit("error", structure="tree", msg=f"batch theme merge: {e}"[:200])
        n_theme_before = len(st.themes)
        st.save(); llm.ledger.dump(st.dir / "cost_build.json")
        print(f"[batch {b0 // batch + 1}] docs {len(group)} ({done} done) {time.time() - t0:5.0f}s "
              f"(glossary {t1 - t0:.0f}s, router {t2 - t1:.0f}s, extract {time.time() - t2:.0f}s) ${llm.ledger.total_usd - c0:.3f} failed={len(failed)}", flush=True)
    st.save(); llm.ledger.dump(st.dir / "cost_build.json")
    return done
