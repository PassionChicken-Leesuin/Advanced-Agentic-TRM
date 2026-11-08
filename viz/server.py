"""
viz.server — FastAPI: run 목록, KB 스냅샷, 이벤트(SSE 재생/실시간 꼬리), 로드맵, i18n.

python -m uvicorn viz.server:app --reload --port 8765   (Code/ 에서)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
# 사이트(Next.js, 다른 포트/도메인)가 업로드 모드에서 이 서버를 부른다
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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

    job_path = _run_dir(run) / "job.json"

    def job_over() -> bool:      # 업로드 작업이 끝났으면(또는 실패) follow 를 끝낸다
        if not job_path.exists():
            return False
        try:
            return json.loads(job_path.read_text(encoding="utf-8")).get("status") in ("done", "error")
        except (OSError, ValueError):
            return False

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
            if not follow or (not new and job_over()):
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------- 업로드 작업 (사용자 문서 → 지식베이스 → 카드 → 로드맵)
from trmkb.sources import jobs as J  # noqa: E402
from trmkb.sources.ingest import ALLOWED, MAX_FILES  # noqa: E402


@app.post("/api/v2/jobs")
async def create_job(company: str = Form(...), descriptor: str = Form(""), brief: str = Form(""), cutoff: str = Form(""),
                     internal: str = Form(""), dry_run: bool = Form(False), files: list[UploadFile] = File(...)) -> JSONResponse:
    """multipart: company(필수), descriptor·brief·cutoff(선택), internal(내부 문서로 볼 파일 이름, 줄바꿈 구분), files[].
    dry_run=true (또는 환경 변수 TRMKB_JOB_DRY_RUN=1): 문서 변환·작업 생성까지만 하고 LLM 파이프라인은 띄우지 않음 (시험용)."""
    company = company.strip()
    if not company or len(company) > 80:
        raise HTTPException(400, "company name is required (max 80 chars)")
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"1 to {MAX_FILES} files")
    if not any(Path(f.filename or "").suffix.lower() in ALLOWED for f in files):
        raise HTTPException(400, f"no supported files (allowed: {', '.join(sorted(ALLOWED))})")
    # 지원하지 않는 형식·읽을 수 없는 파일은 거절하지 않고 건너뜀 (job.json 의 skipped 에 이유와 함께 남음)
    if J.busy():
        raise HTTPException(409, f"another job is running ({J.busy()}); try again when it finishes")
    data = [(f.filename or "upload.txt", await f.read()) for f in files]
    try:
        state = J.create(RUNS, company, data, descriptor=descriptor, brief=brief, cutoff=cutoff.strip() or None,
                         internal_names={x.strip() for x in internal.splitlines() if x.strip()})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    import os
    if dry_run or os.environ.get("TRMKB_JOB_DRY_RUN") == "1":
        job = J.Job(RUNS / state["run"])
        job.state.update(status="done", stage="ingest", message=f"dry run: {len(state['documents'])} documents converted, pipeline not started")
        job.save()
        return JSONResponse(job.state)
    _budget_check(len(state["documents"]))
    if not J.start(RUNS / state["run"]):
        raise HTTPException(409, "another job is running; try again when it finishes")
    return JSONResponse(state)


# 공개 운영용 안전장치: 하루 비용 상한 (USD, 환경 변수 TRMKB_DAILY_USD, 기본 40) · 문서당 예상 비용으로 시작 전에 점검
PER_DOC_USD = 0.06


def _budget_check(n_docs: int) -> None:
    import os
    cap = float(os.environ.get("TRMKB_DAILY_USD", "40"))
    spent = J.spent_today(RUNS)
    need = round(n_docs * PER_DOC_USD, 2)
    if spent + need > cap:
        raise HTTPException(429, f"daily budget reached: about ${spent} used today, this run needs about ${need}, limit ${cap:g}. Try fewer documents or tomorrow.")


@app.post("/api/v2/jobs/new")
async def job_new(company: str = Form(...), descriptor: str = Form(""), brief: str = Form(""), cutoff: str = Form("")) -> JSONResponse:
    """나눠 올리기 1단계: 빈 작업을 연다. 이어서 /files 로 묶음씩, 마지막에 /start."""
    company = company.strip()
    if not company or len(company) > 80:
        raise HTTPException(400, "company name is required (max 80 chars)")
    if J.busy():
        raise HTTPException(409, f"another job is running ({J.busy()}); try again when it finishes")
    return JSONResponse(J.open_job(RUNS, company, descriptor=descriptor, brief=brief, cutoff=cutoff.strip() or None))


@app.post("/api/v2/jobs/{run}/files")
async def job_files(run: str, files: list[UploadFile] = File(...)) -> dict:
    data = [(f.filename or "upload.txt", await f.read()) for f in files]
    try:
        n = J.add_files(_run_dir(run), data, MAX_FILES)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"run": run, "received": n}


@app.post("/api/v2/jobs/{run}/start")
async def job_start(run: str, internal: str = Form(""), dry_run: bool = Form(False)) -> JSONResponse:
    import os
    d = _run_dir(run)
    try:
        state = J.finish_ingest(d, internal_names={x.strip() for x in internal.splitlines() if x.strip()})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if dry_run or os.environ.get("TRMKB_JOB_DRY_RUN") == "1":
        job = J.Job(d)
        job.state.update(status="done", stage="ingest", message=f"dry run: {len(state['documents'])} documents converted, pipeline not started")
        job.save()
        return JSONResponse(job.state)
    _budget_check(len(state["documents"]))
    if not J.start(d):
        raise HTTPException(409, "another job is running; try again when it finishes")
    return JSONResponse(state)


@app.get("/api/v2/jobs/{run}")
def job_status(run: str) -> dict:
    s = J.status(_run_dir(run))
    if s is None:
        raise HTTPException(404, "no job for this run")
    return s


@app.get("/api/v2/runs/{run}/site/{name}")
def site_file(run: str, name: str) -> FileResponse:
    """업로드 작업이 내보낸 사이트 데이터 (meta.json, events.jsonl, cards_v2.json, candidates.json, selection.json, roadmaps.json, roadmaps_v2.json)."""
    if name not in {"meta.json", "events.jsonl", "cards.json", "cards_v2.json", "candidates.json", "selection.json", "roadmaps.json", "roadmaps_v2.json"}:
        raise HTTPException(404, "unknown file")
    d = _run_dir(run)
    p = d / "site" / name
    if name == "events.jsonl":            # 사건 기록은 항상 run 의 원본 (작업 중에도 최신)
        p = d / "events.jsonl"
    if not p.exists():
        raise HTTPException(404, f"{name} not ready")
    return FileResponse(p, media_type="application/json" if name.endswith(".json") else "application/x-ndjson")


@app.get("/api/i18n")
def i18n(lang: str = "ko") -> dict:
    base = dict(_LABELS["ko"])
    base.update(_LABELS.get(lang, {}))
    return base
