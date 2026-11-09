"""사이트(agentic-trm-site) 정적 데이터 내보내기 — scripts/export_site.py·export_site_v2.py 와 업로드 작업(jobs)이 같은 함수를 쓴다.

  meta.json        문서 목록·계획 수·대상 이름·트리 영역·용어집·통계·프로필(회사·기준일·기간)
  events.jsonl     사건 기록 (그대로 복사; 사이트가 재생)
  cards.json       기회 카드 v1 (구조화; 옛 화면용)
  roadmaps.json    initial / kb 로드맵 (eval/<cond>/rm_1.json 또는 run/roadmap_<cond>.json)
  cards_v2.json    기회 카드 v2 (토픽 로드맵 한 장씩)
  candidates.json  후보 추출 요약 (기록 → 대상 → 제외 사유 → 카드)
  selection.json   세 질문 토론 선정 결과 (관점별 순위·프로파일·이유)
  roadmaps_v2.json 관점별 로드맵 + 인용 근거 문장
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from .store import SourceStore


def _evidence(st: SourceStore, rms: dict) -> dict:
    ev = {}
    for pid in {e for rm in rms.values() for n in rm.get("nodes", []) for e in n.get("evidence_ids", [])}:
        p = st.passages.get(pid)
        if p:
            ev[pid] = {"text": p.text, "doc_id": p.doc_id, "date": p.doc_date.isoformat(), "source_type": p.source_type, "synthetic": p.is_synthetic}
        else:
            f = st.facts.get(pid)
            if f and f.pid in st.passages:
                q = st.passages[f.pid]
                ev[pid] = {"text": f"[{f.attribute}: {f.value}] " + q.text, "doc_id": q.doc_id, "date": q.doc_date.isoformat(), "source_type": q.source_type, "synthetic": q.is_synthetic}
    return ev


def export_meta(st: SourceStore, dst: Path, *, copy_events: bool = True) -> dict:
    run = st.dir
    dst.mkdir(parents=True, exist_ok=True)
    read_ids = {p.doc_id for p in st.passages.values()} or set(st.docs)
    docs = [{"id": d["id"], "title": d["title"], "date": d["date"], "source_type": d["source_type"], "is_synthetic": d["is_synthetic"]}
            for d in sorted(st.docs.values(), key=lambda d: (d["date"], d["id"])) if d["id"] in read_ids]
    plan = run / "plan.json"
    years = sorted({int(d["date"][:4]) for d in st.docs.values()} | {int(str(st.profile["cutoff"])[:4])})
    meta = {"run": run.name, "documents": docs,
            "planned_total": json.loads(plan.read_text(encoding="utf-8")).get("total") if plan.exists() else len(st.docs),
            "profile": {"company": st.company, "cutoff": str(st.profile["cutoff"]), "horizon": st.profile["horizon"], "source": st.profile.get("source", "demo"),
                        "min_year": years[0] if years else None},
            "entities": {e.id: {"name": e.name, "layer": e.layer} for e in st.entities.values()},
            "tree": {"areas": [{"name": x["name"], "theme_ids": x["theme_ids"], "trend": x.get("trend"), "shares": x.get("shares", [])} for x in st.tree["areas"]],
                     "root": st.tree.get("root")} if st.tree else None,
            "glossary": [{"name": t.name, "type": t.type, "aliases": t.aliases, "unit": t.unit, "definition": t.definition, "status": t.status, "count": t.count}
                         for t in st.terms_by_type()],
            "stats": st.stats()}
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if copy_events and (run / "events.jsonl").exists():
        shutil.copyfile(run / "events.jsonl", dst / "events.jsonl")
    return meta


def export_cards_v1(st: SourceStore, dst: Path) -> int:
    from .cards import build_cards_json
    cards = build_cards_json(st) if st.grid else []
    (dst / "cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    return len(cards)


def export_roadmaps(st: SourceStore, dst: Path) -> list[str]:
    """initial / kb 로드맵: eval/Initial|ALL/rm_1.json (180건 평가) 또는 run/roadmap_initial.json·roadmap_advanced.json (업로드 작업)."""
    run = st.dir
    rms = {}
    for cond, key, alt in (("Initial", "initial", "roadmap_initial.json"), ("ALL", "kb", "roadmap_advanced.json")):
        p = run / "eval" / cond / "rm_1.json"
        if not p.exists():
            p = run / alt
        if p.exists():
            rms[key] = json.loads(p.read_text(encoding="utf-8"))
    (dst / "roadmaps.json").write_text(json.dumps({**rms, "evidence": _evidence(st, rms)}, ensure_ascii=False), encoding="utf-8")
    return list(rms)


def export_debate(cdir: Path, dst: Path) -> int:
    """debate.json — 세 에이전트의 카드별 토론 기록 (사이트의 '에이전트 토론' 화면). 토론이 끝난 순서(파일 수정 시각)로.
    각 기록: 1라운드 점수·이유, 2라운드 답변·최종 점수, 근거 있는 점수의 평균(profile). done 은 선정(순위)까지 끝났는가."""
    sel = cdir / "selection"
    files = sorted(sel.glob("debate_*.json"), key=lambda p: p.stat().st_mtime) if sel.exists() else []
    recs = []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recs.append({"eid": d["eid"], "name": d["name"],
                     "models": {m: {"r1": {k: v["r1"].get(k) for k in ("q1", "q2", "q3", "reasons", "contested")},
                                    "final": {k: v["final"].get(k) for k in ("q1", "q2", "q3", "reasons", "replies", "changed")}}
                                for m, v in d["models"].items()},
                     "profile": {k: d["profile"].get(k, 0.0) for k in ("q1", "q2", "q3")}})
    total = 0
    cj = cdir / "cards.json"
    if cj.exists():
        try:
            total = len(json.loads(cj.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            total = len(recs)
    dst.mkdir(parents=True, exist_ok=True)
    tmp = dst / "debate.json.tmp"
    tmp.write_text(json.dumps({"total": max(total, len(recs)), "done": (sel / "profiles.json").exists(),
                               "models": sorted({m for r in recs for m in r["models"]}), "records": recs}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dst / "debate.json")
    return len(recs)


def export_v2(st: SourceStore, dst: Path) -> dict:
    from .cards_v2 import Card
    from .grid import bad_column
    from .select import STANCES
    run = st.dir
    cdir = run / "cards_v2"
    out = {"cards": 0, "stances": [], "roadmaps": [], "evidence": 0}
    if not (cdir / "cards.json").exists():
        return out
    raw = json.loads((cdir / "cards.json").read_text(encoding="utf-8"))
    cards = []
    for d in raw:
        c = Card(**{k: (set(v) if k in ("pids", "elements") else v) for k, v in d.items()})
        cards.append({"eid": c.eid, "name": c.name, "kind": c.kind, "customers": c.customers[:4], "maturity": c.maturity,
                      "docs_public": c.docs_public, "docs_internal": c.docs_internal, "first_date": c.first_date, "last_date": c.last_date,
                      "lines": {k: getattr(c, k) for k in ("state", "why", "trend", "what", "when", "how", "resource", "actors", "issue")},
                      "digest": c.digest()})
    (dst / "cards_v2.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    out["cards"] = len(cards)
    # 후보 추출 요약: 기회 기록 → 대상별 집계 → 제외 사유 (일반어/조직·기술 이름, 구체 제품) → 카드가 된 후보
    kept = {c["eid"] for c in cards}
    recs = defaultdict(list)
    for o in st.opps.values():
        p = st.passages.get(o.pid)
        if p and p.status not in ("irrelevant", "duplicate") and o.eid in st.entities:
            recs[o.eid].append(o)
    cand_list = []
    for eid, os in recs.items():
        e = st.entities[eid]
        reason = "card" if eid in kept else ("generic name, organization, technology or metric" if bad_column(st, eid) else "concrete product (kept as an offering)")
        cand_list.append({"eid": eid, "name": e.name, "kind": max(set(o.kind for o in os), key=[o.kind for o in os].count), "records": len(os),
                          "docs": len({st.passages[o.pid].doc_id for o in os}), "customers": sorted({o.customer for o in os if o.customer})[:3],
                          "kept": eid in kept, "reason": reason})
    cand_list.sort(key=lambda c: (-c["kept"], -c["docs"], c["name"]))
    n_pass = sum(1 for p in st.passages.values() if p.status not in ("irrelevant", "duplicate") and "grid" in (p.systems or []))
    (dst / "candidates.json").write_text(json.dumps({"passages_routed": n_pass, "records": sum(len(v) for v in recs.values()), "subjects": len(recs),
                                                     "kept": len(kept), "list": cand_list}, ensure_ascii=False), encoding="utf-8")
    stances = {}
    for key, meta in STANCES.items():
        pf = cdir / "selection" / ("profiles.json" if key == "balanced" else f"profiles_{key}.json")
        if not pf.exists():
            continue
        rs = json.loads(pf.read_text(encoding="utf-8"))
        rs.sort(key=lambda r: r["profile"]["rank"])
        stances[key] = {"label": meta["label"], "desc": meta["desc"],
                        "order": [r["eid"] for r in rs],
                        "selected": [r["eid"] for r in rs if r["profile"]["selected"]],
                        "profiles": {r["eid"]: {"q1": r["profile"]["q1"], "q2": r["profile"]["q2"], "q3": r["profile"]["q3"], "rank": r["profile"]["rank"],
                                                "sd": [r["profile"]["q1_sd_final"], r["profile"]["q2_sd_final"], r["profile"]["q3_sd_final"]],
                                                "reasons": {m: v["final"]["reasons"] for m, v in r["models"].items()},
                                                "replies": {m: v["final"].get("replies", [])[:2] for m, v in r["models"].items()}}
                                     for r in rs}}
    (dst / "selection.json").write_text(json.dumps({"questions": {
        "q1": "Why should the company go for it? Who demands it, for what, under what conditions and by when; has the company stated this direction itself?",
        "q2": "Where is the company now? Offerings and their lifecycle stage, latest capability metrics, secured customers, partners and resources.",
        "q3": "Can the company get there? Is the gap between the requirement and current capability documented, with a dated plan to close it?"},
        "stances": stances}, ensure_ascii=False), encoding="utf-8")
    out["stances"] = list(stances)
    out["debates"] = export_debate(cdir, dst)
    rms = {}
    for key in STANCES:
        p = cdir / "roadmaps" / f"rm_{key}.json"
        if p.exists():
            rms[key] = json.loads(p.read_text(encoding="utf-8"))
    ev = _evidence(st, rms)
    # 근거 사슬: 로드맵 항목 ← 기회 카드(줄) ← 지식 구조 ← 원문 (provenance.py)
    from .provenance import chains
    for key, rm in rms.items():
        sel = stances.get(key, {}).get("selected", [])
        rm["provenance"] = chains(st, raw, rm, sel)
    (dst / "roadmaps_v2.json").write_text(json.dumps({**rms, "evidence": ev}, ensure_ascii=False), encoding="utf-8")
    out["roadmaps"], out["evidence"] = list(rms), len(ev)
    return out


def export_all(st: SourceStore, dst: str | Path) -> dict:
    dst = Path(dst)
    meta = export_meta(st, dst)
    res = {"docs": len(meta["documents"]), "cards_v1": export_cards_v1(st, dst), "roadmaps_basic": export_roadmaps(st, dst)}
    res.update(export_v2(st, dst))
    return res
