"""다섯 지식 구조 지식베이스 구축 (Router 분배 + 구조 전용 추출기).

python scripts/build_v2.py --src runs/full_clean --dst runs/struct5 [--limit 5] [--only doc_id_prefix ...] [--reader new|old]
  - 소스 문장 = 새 Reader(인용 전용)가 문서를 다시 읽어 원문 그대로 인용한 문장 (--reader old 면 src run 의 근거 재사용)
  - 문서를 날짜 순으로 하나씩: Router 가 문장마다 저장 여부·태그·공유 대상·보낼 구조를 판단
    → 구조 전용 추출기(K2 주제, K3 기회, K4 관계, K5 시간 사실)를 병렬 호출 → 저장소에 순차 반영 (재개 가능)
  - 끝나면: python scripts/build_v2.py --dst runs/struct5 --finish   (K2 요약 트리 + K3 연계 그리드)
"""
import argparse
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.llm import LLM
from trmkb.sources.extract import EXTRACTORS
from trmkb.sources.resolve import Resolver
from trmkb.sources.router import Router
from trmkb.sources.store import SYSTEMS, Entity, Passage, SourceStore
from trmkb.store import KBStore


def seed(src: Path, st: SourceStore) -> None:
    kb = KBStore(src)
    claim_by_ev = {}
    for c in kb.claims.values():
        if c.evidence_id:
            claim_by_ev.setdefault(c.evidence_id, c)
    seen: dict[tuple, str] = {}
    n = 0
    for ev in kb.evidence.values():
        if ev.edge_ids or not ev.node_ids or not ev.text.strip():
            continue
        d = kb.documents.get(ev.doc_id)
        if d is None:
            continue
        node = kb.nodes.get(ev.node_ids[0])
        hint = {"label": node.label, "kind": node.type} if node else {}
        key = (ev.doc_id, re.sub(r"\s+", " ", ev.text.lower())[:200])
        if key in seen:
            p = st.passages[seen[key]]
            if hint and hint not in p.reader_hints:
                p.reader_hints.append(hint)
            continue
        c = claim_by_ev.get(ev.id)
        st.passages[ev.id] = Passage(id=ev.id, doc_id=ev.doc_id, doc_date=d.date, source_type=d.source_type.value,
                                     is_synthetic=d.is_synthetic, text=ev.text, claim=c.text if c else None,
                                     reader_hints=[hint] if hint else [])
        seen[key] = ev.id
        n += 1
    for d in kb.documents.values():
        st.docs[d.id] = {"id": d.id, "title": d.title, "date": d.date.isoformat(), "source_type": d.source_type.value,
                         "is_synthetic": d.is_synthetic, "path": d.path}
    st.save()
    print(f"seeded {n} passages from {len(st.docs)} documents")


def seed_docs(src: Path, st: SourceStore) -> None:
    """새 Reader 용: 문서 메타데이터만 가져온다 (소스 문장은 새로 읽음)."""
    kb = KBStore(src)
    for d in kb.documents.values():
        st.docs[d.id] = {"id": d.id, "title": d.title, "date": d.date.isoformat(), "source_type": d.source_type.value,
                         "is_synthetic": d.is_synthetic, "path": d.path}
    st.save()
    print(f"seeded {len(st.docs)} documents (new reader)")


def read_docs(st: SourceStore, llm: LLM, docs: list[dict], workers: int = 4) -> None:
    from trmkb.sources.reader import QuoteReader
    reader = QuoteReader(llm)
    todo = [d for d in docs if not d.get("read")]

    def job(d):
        try:
            return d, reader.read(d)
        except Exception as e:  # noqa: BLE001
            print("READ ERR", d["id"], e)
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
    st.save()


def ensure_company(st: SourceStore) -> None:
    """회사 자체를 공유 대상으로 둠 (K5 전략 마일스톤의 대상, K4 customer_of 의 끝점)."""
    from trmkb.sources.resolve import norm
    if not any(norm(e.name) == "ionq" for e in st.entities.values()):
        e = Entity(name="IonQ", aliases=["IonQ, Inc.", "the Company"])
        st.entities[e.id] = e


def copy_passages(src: Path, st: SourceStore) -> None:
    """같은 Reader 결과 위에 다른 구축 조건(예: K0 없이)을 돌리기 위해 소스 문장과 문서(read 표시)를 복사한다 → 문장 id 가 같아짐."""
    s = SourceStore(src)
    for d in s.docs.values():
        st.docs[d["id"]] = {k: v for k, v in d.items()}
    for p in s.passages.values():
        st.passages[p.id] = Passage(id=p.id, doc_id=p.doc_id, doc_date=p.doc_date, source_type=p.source_type,
                                    is_synthetic=p.is_synthetic, text=p.text, claim=p.claim)
    st.save()
    print(f"copied {len(st.passages)} passages / {len(st.docs)} documents from {src}")


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="runs/full_clean")
    ap.add_argument("--dst", default="runs/struct5")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--finish", action="store_true")
    ap.add_argument("--model", default="openai/gpt-4.1-mini")
    ap.add_argument("--read-only", action="store_true")
    ap.add_argument("--reader", choices=["old", "new"], default="new", help="new = 인용 전용 새 Reader 로 문서를 다시 읽음")
    ap.add_argument("--no-glossary", action="store_true", help="K0 용어집 없이 구축 (ALL-K0 조건용)")
    ap.add_argument("--passages-from", default=None, help="이미 읽은 run 의 소스 문장을 복사해 시작 (Reader 재실행 없음, 같은 문장 id)")
    args = ap.parse_args()
    st = SourceStore(args.dst)
    llm = LLM()
    if args.finish:
        from trmkb.sources.glossary import export_review
        from trmkb.sources.grid import build_grid
        from trmkb.sources.tree import build_tree
        from trmkb.sources.consolidate import consolidate
        if st.terms:
            print("glossary review:", export_review(st, Path(args.dst) / "glossary_review.md"))
        if not (Path(args.dst) / "consolidated.json").exists():      # 정리 단계는 한 번만 (재실행 안전)
            c = consolidate(st, llm); st.save()
            (Path(args.dst) / "consolidated.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
            print("consolidate:", c)
        t = build_tree(st, llm); st.save()
        print("tree:", {k: len(v) if isinstance(v, list) else v for k, v in t.items() if k in ("areas", "themes")})
        g = build_grid(st, llm); st.save()
        print("grid:", {"columns": len(g["columns"]), "cells": len(g["cells"]), "rows": {k: len(v) for k, v in g["rows"].items()}, "meta": g["meta"]})
        # 실제 공개 자료 전용 조건용: 가상 내부 문서 문장을 뺀 트리·그리드
        tr = build_tree(st, llm, real_only=True, emit=False)
        (Path(args.dst) / "tree_real.json").write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
        gr = build_grid(st, llm, real_only=True, emit=False)
        (Path(args.dst) / "grid_real.json").write_text(json.dumps(gr, ensure_ascii=False, indent=1), encoding="utf-8")
        print("real-only:", {"areas": len(tr["areas"]), "columns": len(gr["columns"]), "cells": len(gr["cells"])})
        llm.ledger.dump(Path(args.dst) / "cost_finish.json")
        print("stats:", json.dumps(st.stats(), ensure_ascii=False), f"| cost ${llm.ledger.total_usd:.3f}")
        return
    if args.passages_from and not st.passages:
        copy_passages(Path(args.passages_from), st)
    elif args.reader == "old" and not st.passages:
        seed(Path(args.src), st)
    elif args.reader == "new" and not st.docs:
        seed_docs(Path(args.src), st)
    ensure_company(st)
    res = Resolver(st)
    router = Router(llm, st, res, model=args.model)
    extractors = {s: EXTRACTORS[s](llm, st, res) for s in SYSTEMS}
    glossary = None
    if not args.no_glossary:
        from trmkb.sources.glossary import GlossaryExtractor
        glossary = GlossaryExtractor(llm, st, res)
    by_doc: dict[str, list[Passage]] = {}
    for p in st.passages.values():
        by_doc.setdefault(p.doc_id, []).append(p)
    order = sorted(st.docs.values(), key=lambda d: (d["date"], d["id"]))
    if args.only:
        order = [d for d in order if any(d["id"].startswith(x) for x in args.only)]
    if args.reader == "new":
        read_docs(st, llm, order)
        if args.read_only:
            llm.ledger.dump(Path(args.dst) / "cost_read.json")
            print(f"read only: {len(st.passages)} passages | cost ${llm.ledger.total_usd:.3f}")
            return
        by_doc = {}
        for p in st.passages.values():
            by_doc.setdefault(p.doc_id, []).append(p)
    (Path(args.dst) / "plan.json").write_text(json.dumps({"total": len(order)}), encoding="utf-8")
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for d in order:
            ps = by_doc.get(d["id"], [])      # 문서 안 읽은 순서 유지
            if not ps or all(p.routed for p in ps):
                continue
            if args.limit and done >= args.limit:
                break
            t0, c0 = time.time(), llm.ledger.total_usd
            st.emit("doc.started", doc_id=d["id"], title=d["title"], date=d["date"], source_type=d["source_type"],
                    synthetic=d["is_synthetic"], n=len(ps))
            try:
                r = process(d, [p for p in ps if not p.routed], router, extractors, pool, glossary)
            except Exception as e:  # noqa: BLE001
                st.emit("error", doc_id=d["id"], msg=str(e)[:200])
                print("ERR", d["id"], e)
                continue
            st.emit("doc.finished", doc_id=d["id"], title=d["title"], **r)
            done += 1
            print(f"[{done}] {d['date']} {d['id'][:44]:44s} p={r['passages']:3d} kept={r['kept']:3d} "
                  f"routes={r['routes']} extracted={r['extracted']} gloss={r.get('glossary')} {time.time() - t0:4.0f}s ${llm.ledger.total_usd - c0:.3f}", flush=True)
            if done % 5 == 0:
                st.save(); llm.ledger.dump(Path(args.dst) / "cost_build.json")
    st.save(); llm.ledger.dump(Path(args.dst) / "cost_build.json")
    print("stats:", json.dumps(st.stats(), ensure_ascii=False), f"| cost ${llm.ledger.total_usd:.3f}")


if __name__ == "__main__":
    main()
