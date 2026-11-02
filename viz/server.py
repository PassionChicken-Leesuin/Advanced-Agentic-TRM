"""
viz.server — FastAPI: run 목록, KB 스냅샷, 이벤트(SSE 재생/실시간 꼬리), 로드맵, i18n.

python -m uvicorn viz.server:app --reload --port 8765   (Code/ 에서)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trmkb.i18n import _LABELS  # noqa: E402
from trmkb.roadmap import generate as G  # noqa: E402
from trmkb.store import EventLog, KBStore  # noqa: E402

RUNS = ROOT / "runs"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="trmkb viz")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.middleware("http")
async def _no_cache(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _run_dir(run: str) -> Path:
    p = (RUNS / run).resolve()
    if not p.exists() or RUNS.resolve() not in p.parents:
        raise HTTPException(404, f"run not found: {run}")
    return p


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/runs")
def runs() -> list[dict]:
    out = []
    for p in sorted(RUNS.glob("*/")):
        if not p.is_dir() or p.name.startswith("."):
            continue
        ev = p / "events.jsonl"
        n = sum(1 for _ in ev.open(encoding="utf-8")) if ev.exists() else 0
        out.append({"run": p.name, "events": n, "has_kb": (p / "kb" / "nodes.jsonl").exists(),
                    "roadmaps": [c for c in ("initial", "advanced") if (p / f"roadmap_{c}.json").exists()]})
    return out


@app.get("/api/runs/{run}/snapshot")
def snapshot(run: str) -> dict:
    kb = KBStore(_run_dir(run))
    snap = kb.snapshot()
    snap["stats"] = kb.stats()
    snap["documents"] = [{"id": d.id, "title": d.title, "date": d.date.isoformat(), "source_type": d.source_type.value,
                          "is_synthetic": d.is_synthetic} for d in kb.documents.values()]
    plan = _run_dir(run) / "plan.json"
    snap["planned_total"] = json.loads(plan.read_text(encoding="utf-8")).get("total") if plan.exists() else None
    return snap


@app.get("/api/runs/{run}/events")
def events(run: str, since: int = 0, limit: int = 5000) -> list[dict]:
    log = EventLog(_run_dir(run) / "events.jsonl")
    out = []
    for ev in log.read():
        if ev.seq > since:
            out.append(json.loads(ev.model_dump_json(exclude_none=True)))
            if len(out) >= limit:
                break
    return out


@app.get("/api/runs/{run}/stream")
async def stream(run: str, speed: float = Query(10.0, ge=0), start: int = 0, max_gap: float = 2.0,
                 follow: bool = False) -> StreamingResponse:
    """SSE. speed>0: 기록 간격/speed 로 재생 (상한 max_gap 초). speed=0: 지연 없음. follow: 끝난 뒤 새 이벤트 꼬리 추적."""
    path = _run_dir(run) / "events.jsonl"

    async def gen():
        seen = start
        prev_ts = None
        yield "event: hello\ndata: {}\n\n"
        while True:
            log = EventLog(path)
            new = [ev for ev in log.read() if ev.seq > seen]
            for ev in new:
                if speed and prev_ts is not None:
                    gap = (ev.ts - prev_ts).total_seconds() / speed
                    await asyncio.sleep(min(max(gap, 0.0), max_gap))
                prev_ts = ev.ts
                seen = ev.seq
                yield f"id: {ev.seq}\nevent: kb\ndata: {ev.model_dump_json(exclude_none=True)}\n\n"
            if not follow:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run}/roadmaps")
def roadmaps(run: str) -> dict:
    d = _run_dir(run)
    out = {}
    for cond in ("initial", "advanced"):
        rm = G.load(d, cond)
        if rm:
            out[cond] = json.loads(rm.model_dump_json(exclude_none=True))
            out[cond]["summary"] = G.summary(rm)
    diff_p = d / "roadmap_diff.json"
    if diff_p.exists():
        out["diff"] = json.loads(diff_p.read_text(encoding="utf-8"))
    return out


# ---------------------------------------------------------------------------- v2: 다섯 지식 구조 (sources store, 평면 JSON 이벤트)
def _jsonl(path: Path):
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


@app.get("/structures")
def structures_page() -> FileResponse:
    return FileResponse(STATIC / "structures.html")


@app.get("/api/v2/runs")
def v2_runs() -> list[dict]:
    out = []
    for p in sorted(RUNS.glob("*/")):
        if not p.is_dir() or not (p / "documents.jsonl").exists() or not (p / "passages.jsonl").exists():
            continue
        ev = p / "events.jsonl"
        n = sum(1 for _ in ev.open(encoding="utf-8")) if ev.exists() else 0
        out.append({"run": p.name, "events": n, "finished": (p / "tree.json").exists() and (p / "grid.json").exists()})
    return out


@app.get("/api/v2/runs/{run}/meta")
def v2_meta(run: str) -> dict:
    d = _run_dir(run)
    docs = [x for x in _jsonl(d / "documents.jsonl")]
    plan = d / "plan.json"
    ents = {e["id"]: {"name": e["name"], "layers": e.get("layer_counts", {})} for e in _jsonl(d / "entities.jsonl")}
    tree = json.loads((d / "tree.json").read_text(encoding="utf-8")) if (d / "tree.json").exists() else None
    grid = json.loads((d / "grid.json").read_text(encoding="utf-8")) if (d / "grid.json").exists() else None
    return {"documents": [{k: x.get(k) for k in ("id", "title", "date", "source_type", "is_synthetic", "read")} for x in docs],
            "planned_total": json.loads(plan.read_text(encoding="utf-8")).get("total") if plan.exists() else None,
            "entities": ents,
            "tree": {"areas": [{"name": a["name"], "theme_ids": a["theme_ids"], "trend": a.get("trend")} for a in tree["areas"]],
                     "themes": [{"id": t["id"], "name": t["name"], "trend": t.get("trend")} for t in tree["themes"]]} if tree else None,
            "grid": {"columns": [{"eid": c["eid"], "name": c["name"], "tier": c.get("tier"), "links": c.get("links")} for c in grid["columns"]]} if grid else None}


@app.get("/api/v2/runs/{run}/events")
def v2_events(run: str, since: int = 0, limit: int = 20000) -> list[dict]:
    out = []
    for ev in _jsonl(_run_dir(run) / "events.jsonl"):
        if ev.get("seq", 0) > since:
            out.append(ev)
            if len(out) >= limit:
                break
    return out


@app.get("/api/v2/runs/{run}/stream")
async def v2_stream(run: str, speed: float = Query(10.0, ge=0), start: int = 0, max_gap: float = 1.5,
                    follow: bool = False, min_gap: float = 0.03) -> StreamingResponse:
    """SSE (평면 JSON 이벤트). speed>0: 기록 간격/speed 로 재생 (min_gap~max_gap 초). speed=0: 지연 없음. follow: 새 이벤트 꼬리 추적."""
    from datetime import datetime
    path = _run_dir(run) / "events.jsonl"

    async def gen():
        seen, prev = start, None
        yield "event: hello\ndata: {}\n\n"
        while True:
            new = [ev for ev in _jsonl(path) if ev.get("seq", 0) > seen]
            for ev in new:
                ts = datetime.fromisoformat(ev["ts"]) if ev.get("ts") else None
                if speed and prev is not None and ts is not None:
                    gap = (ts - prev).total_seconds() / speed
                    await asyncio.sleep(min(max(gap, min_gap), max_gap))
                elif speed:
                    await asyncio.sleep(min_gap)
                prev, seen = ts, ev["seq"]
                yield f"id: {ev['seq']}\nevent: kb\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if not follow:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/i18n")
def i18n(lang: str = "ko") -> dict:
    base = dict(_LABELS["ko"])
    base.update(_LABELS.get(lang, {}))
    return base
