"""업로드 작업 — 사용자가 올린 문서로 지식베이스를 짓고 카드·선정·로드맵까지 한 번에 돌린다 (viz.server 의 /api/v2/jobs 가 부른다).

단계 (job.json 의 stage):   ingest → read → build → finish → cards → select → make → export → done
  ingest  파일 → md (trmkb.sources.ingest)                           read    새 Reader 가 문장 인용
  build   문서별 K0 → Router → K2·K4·K5(+기회 기록) 추출             finish  LLM 병합 → K2 요약 트리 → 연계 그리드
  cards   기회 카드 v2 조립 (코드)                                     select  세 모델 토론 (Phaal 세 질문) → 관점별 순위
  make    선정 카드로 로드맵 (balanced·q1·q2·q3) + 지식베이스 없는 Initial 로드맵
  export  runs/<run>/site/*.json (사이트가 서버 모드에서 읽음)
진행 상황은 job.json 과 events.jsonl 의 job.stage 사건 둘 다에 남긴다 (화면 로그에 보이게).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from ..llm import LLM
from . import profile as P
from .store import SourceStore

_LOCK = threading.Lock()
_RUNNING: dict[str, threading.Thread] = {}
SELECT_MODELS = ["openai/gpt-4.1", "anthropic/claude-sonnet-4.6", "google/gemini-2.5-flash"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.path = run_dir / "job.json"
        self.state: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "run": run_dir.name, "status": "queued", "stage": "ingest", "progress": {"done": 0, "total": 0}, "stages": {},
            "started": _now(), "updated": _now(), "cost_usd": 0.0, "error": None, "message": ""}

    def save(self) -> None:
        self.state["updated"] = _now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def stage(self, st: SourceStore | None, name: str, message: str = "", **extra) -> None:
        prev = self.state.get("stage")
        if prev and prev != name and prev in self.state["stages"] and "ended" not in self.state["stages"][prev]:
            self.state["stages"][prev]["ended"] = _now()
            self.state["stages"][prev]["seconds"] = round(time.time() - self.state["stages"][prev]["_t0"], 1)
        self.state["stage"] = name
        self.state["status"] = "running"
        self.state["message"] = message
        self.state["stages"].setdefault(name, {"started": _now(), "_t0": time.time()})
        self.state.update(extra)
        self.save()
        if st is not None:
            st.emit("job.stage", stage=name, msg=message)

    def done(self, st: SourceStore | None, message: str) -> None:
        self.stage(st, "done", message)
        self.state["status"] = "done"
        self.state["ended"] = _now()
        self.save()

    def fail(self, st: SourceStore | None, err: str) -> None:
        self.state["status"] = "error"
        self.state["error"] = err[:2000]
        self.state["ended"] = _now()
        self.save()
        if st is not None:
            st.emit("job.stage", stage="error", msg=err[:300])


def open_job(runs_root: Path, company: str, *, descriptor: str = "", brief: str = "", cutoff: str | None = None) -> dict:
    """나눠 올리기 1단계: 빈 작업을 연다 (상태 receiving). 파일은 add_files 로 묶음씩 받고 finish_ingest 로 변환한다.
    요청 하나의 크기 제한(예: Cloudflare 100MB)을 넘는 많은 문서를 올리기 위함."""
    run = runs_root / f"up_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{P.slug(company)}"
    run.mkdir(parents=True, exist_ok=False)
    job = Job(run)
    job.state.update(status="receiving", stage="upload", company=company, request={"descriptor": descriptor, "brief": brief, "cutoff": cutoff},
                     received=0, message="waiting for files")
    job.save()
    return job.state


def add_files(run_dir: Path, files: list[tuple[str, bytes]], max_files: int) -> int:
    """나눠 올리기 2단계: 받은 파일을 incoming/ 에 그대로 둔다. 반환: 지금까지 받은 파일 수."""
    from pathlib import Path as _P
    job = Job(run_dir)
    if job.state.get("status") != "receiving":
        raise ValueError("this job is not accepting files")
    inc = run_dir / "incoming"; inc.mkdir(exist_ok=True)
    have = len(list(inc.iterdir()))
    if have + len(files) > max_files:
        raise ValueError(f"at most {max_files} files per run")
    for k, (name, data) in enumerate(files):
        safe = _P(name).name.replace("/", "_").replace("\\", "_") or "upload.txt"
        (inc / f"{have + k:04d}__{safe}").write_bytes(data)
    job.state["received"] = have + len(files); job.state["message"] = f"{have + len(files)} files received"
    job.save()
    return have + len(files)


def finish_ingest(run_dir: Path, *, internal_names: set[str] | None = None) -> dict:
    """나눠 올리기 3단계: incoming/ 의 파일을 변환해 작업을 만든다 (create 와 같은 결과)."""
    job = Job(run_dir)
    inc = run_dir / "incoming"
    files = [(p.name.split("__", 1)[-1], p.read_bytes()) for p in sorted(inc.iterdir())] if inc.exists() else []
    if not files:
        raise ValueError("no files were uploaded")
    rq = job.state.get("request", {})
    state = _ingest_into(run_dir, job, job.state.get("company", ""), files, descriptor=rq.get("descriptor", ""), brief=rq.get("brief", ""),
                         internal_names=internal_names, cutoff=rq.get("cutoff"))
    import shutil
    shutil.rmtree(inc, ignore_errors=True)      # 변환본(docs/)이 남으므로 원본 바이트는 지움
    return state


def create(runs_root: Path, company: str, files: list[tuple[str, bytes]], *, descriptor: str = "", brief: str = "",
           internal_names: set[str] | None = None, cutoff: str | None = None) -> dict:
    """run 폴더를 만들고 문서를 받아들인 뒤 (LLM 호출 없음) 작업 상태를 돌려준다. 이어서 start() 로 파이프라인을 띄운다."""
    run = runs_root / f"up_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{P.slug(company)}"
    run.mkdir(parents=True, exist_ok=False)
    return _ingest_into(run, Job(run), company, files, descriptor=descriptor, brief=brief, internal_names=internal_names, cutoff=cutoff)


def _ingest_into(run: Path, job: "Job", company: str, files: list[tuple[str, bytes]], *, descriptor: str = "", brief: str = "",
                 internal_names: set[str] | None = None, cutoff: str | None = None) -> dict:
    from .export import export_meta
    from .ingest import ingest
    job.state["status"] = "queued"
    try:
        skipped: list = []
        docs = ingest(run, files, company=company, internal_names=internal_names, skipped=skipped)
        if not docs:
            raise ValueError("none of the files could be read: " + "; ".join(f"{s['file']} ({s['reason']})" for s in skipped[:5]))
    except Exception as e:  # noqa: BLE001
        job.fail(None, f"ingest: {e}")
        raise
    job.state["skipped"] = skipped
    dated = [d["date"] for d in docs if not d.get("date_guessed")] or [d["date"] for d in docs]   # 날짜를 못 찾은 문서는 기준일 계산에서 뺌
    prof = P.for_upload(company, dated, descriptor=descriptor, brief=brief, cutoff=cutoff)
    job.state["undated"] = sum(1 for d in docs if d.get("date_guessed"))
    P.save(run, prof)
    st = SourceStore(run)
    for d in docs:
        st.docs[d["id"]] = d
    st.save()
    (run / "plan.json").write_text(json.dumps({"total": len(docs)}), encoding="utf-8")
    job.state["progress"] = {"done": 0, "total": len(docs)}
    job.state["company"] = company
    job.state["documents"] = [{k: d[k] for k in ("id", "title", "date", "source_type", "is_synthetic", "original_name", "n_chars")} for d in docs]
    job.stage(st, "ingest", f"{len(docs)} documents converted" + (f", {len(skipped)} skipped" if skipped else ""))
    export_meta(st, run / "site")
    return job.state


def run_pipeline(run_dir: Path, *, top: int = 10, select_rounds: int = 2, select_models: list[str] | None = None,
                 router_model: str = "openai/gpt-4.1-mini", batch: int = 1) -> dict:
    """create() 뒤의 전체 파이프라인. 같은 스레드에서 끝까지 돈다 (start() 가 배경 스레드로 부름)."""
    from ..roadmap import generate as G
    from .build import build_docs, finish, read_docs
    from .cards_v2 import Card, build_cards, dump
    from .export import export_all
    from .make import build_context, generate as make_rm
    from .select import STANCES, debate_card, rank, write_outputs
    job = Job(run_dir)
    st = SourceStore(run_dir)
    llm = LLM()
    t0 = time.time()
    try:
        order = sorted(st.docs.values(), key=lambda d: (d["date"], d["id"]))
        # ---- read
        job.stage(st, "read", f"reading {len(order)} documents (quote-only reader)")
        n_read = [0]

        def on_read(d, n):
            n_read[0] += 1
            job.state["progress"] = {"done": n_read[0], "total": len(order)}; job.state["cost_usd"] = round(llm.ledger.total_usd, 4); job.save()
        read_docs(st, llm, order, workers=20, on_doc=on_read)
        llm.ledger.dump(run_dir / "cost_read.json")
        job.state["passages"] = len(st.passages)
        # ---- build
        job.stage(st, "build", f"routing {len(st.passages)} passages into the structures")
        n_built = [0]

        def on_doc(d, r, secs):
            n_built[0] += 1
            job.state["progress"] = {"done": n_built[0], "total": len(order)}; job.state["cost_usd"] = round(llm.ledger.total_usd, 4); job.save()
        build_docs(st, llm, order, model=router_model, glossary=True, on_doc=on_doc, batch=batch)
        # ---- finish
        job.stage(st, "finish", "consolidating subjects, summarising themes, building the opportunity grid")
        fin = finish(st, llm, on_stage=lambda s: job.stage(st, "finish", f"finish: {s}"))
        job.state["finish"] = fin
        job.state["cost_usd"] = round(llm.ledger.total_usd, 4)
        # ---- cards
        job.stage(st, "cards", "assembling one topic-roadmap card per opportunity")
        cards = build_cards(st, min_docs=1)
        cdir = run_dir / "cards_v2"
        stats = dump(cards, cdir)
        job.state["cards"] = stats.get("cards", len(cards))
        # ---- select
        prof = st.profile
        if cards:
            models = select_models or SELECT_MODELS
            job.stage(st, "select", f"panel of {len(models)} models debating {len(cards)} cards on three questions")
            raw = json.loads((cdir / "cards.json").read_text(encoding="utf-8"))
            texts = {c["eid"]: Card(**{k: (set(v) if k in ("pids", "elements") else v) for k, v in c.items()}).text() for c in raw}
            out = cdir / "selection"; out.mkdir(parents=True, exist_ok=True)
            records = []
            from concurrent.futures import ThreadPoolExecutor

            def deb(c):
                p = out / f"debate_{c['eid']}.json"
                if p.exists():
                    return json.loads(p.read_text(encoding="utf-8"))
                rec = debate_card(llm, c, texts[c["eid"]], models, rounds=select_rounds)
                p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                st.emit("job.stage", stage="select", msg=f"debated: {c['name'][:60]} (why {rec['profile']['q1']:.0f} / now {rec['profile']['q2']:.0f} / path {rec['profile']['q3']:.0f})")
                return rec
            with ThreadPoolExecutor(max_workers=4) as ex:
                records = list(ex.map(deb, raw))
            support = sorted(raw, key=lambda c: -(c["docs_public"] + c["docs_internal"]))
            support_rank = {c["eid"]: i for i, c in enumerate(support, 1)}
            kinds = {c["eid"]: c["kind"] for c in raw}
            n_top = min(top, len(raw))
            for stance in STANCES:
                recs = rank([dict(r, profile=dict(r["profile"])) for r in records], top=n_top, stance=stance, kinds=kinds, quota=None)
                write_outputs(recs, out, n_top, support_rank)
            job.state["cost_usd"] = round(llm.ledger.total_usd, 4)
            # ---- make
            job.stage(st, "make", "writing the roadmap from the selected cards (four stances) and a no-knowledge-base roadmap")
            (cdir / "roadmaps").mkdir(exist_ok=True)
            for stance in STANCES:
                ctx = build_context(st, cdir, selection="debate", top=n_top, stance=stance, label=f"cards_v2-debate-{stance}")
                rm = make_rm(llm, ctx, profile=prof)
                (cdir / "roadmaps" / f"rm_{stance}.json").write_text(rm.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")
                if stance == "balanced":
                    (run_dir / "roadmap_advanced.json").write_text(rm.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")
                st.emit("job.stage", stage="make", msg=f"roadmap written: {STANCES[stance]['label']} ({len(rm.nodes)} items)")
        else:
            job.stage(st, "make", "no opportunity cards could be assembled; writing roadmaps without cards")
        rm0 = G.generate(llm, condition="initial", profile=prof)
        (run_dir / "roadmap_initial.json").write_text(rm0.model_dump_json(indent=1, exclude_none=True), encoding="utf-8")
        job.state["cost_usd"] = round(llm.ledger.total_usd, 4)
        # ---- export
        job.stage(st, "export", "exporting site data")
        res = export_all(st, run_dir / "site")
        job.state["export"] = res
        job.state["cost_usd"] = round(llm.ledger.total_usd, 4)
        job.state["seconds"] = round(time.time() - t0, 1)
        job.state["kb"] = st.stats()
        llm.ledger.dump(run_dir / "cost_job.json")
        job.done(st, f"done in {job.state['seconds']:.0f}s, ${job.state['cost_usd']:.2f}")
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        print(tb)
        try:
            llm.ledger.dump(run_dir / "cost_job.json")
            job.state["cost_usd"] = round(llm.ledger.total_usd, 4)
        except Exception:  # noqa: BLE001
            pass
        job.fail(st, f"{e.__class__.__name__}: {e}")
    return job.state


def start(run_dir: Path, **kw) -> bool:
    """배경 스레드로 run_pipeline 을 띄운다. 이미 돌고 있는 작업이 있으면 False (한 번에 하나: API 키 한도·CPU 보호)."""
    with _LOCK:
        for k, t in list(_RUNNING.items()):
            if not t.is_alive():
                _RUNNING.pop(k)
        if _RUNNING:
            return False
        t = threading.Thread(target=run_pipeline, args=(run_dir,), kwargs=kw, daemon=True, name=f"job-{run_dir.name}")
        _RUNNING[run_dir.name] = t
        t.start()
        return True


def spent_today(runs_root: Path) -> float:
    """오늘(서버 시각) 시작한 업로드 작업들이 쓴 비용 합계 (job.json 의 cost_usd)."""
    today = datetime.now().strftime("%Y%m%d")
    total = 0.0
    for p in runs_root.glob(f"up_{today}_*/job.json"):
        try:
            total += float(json.loads(p.read_text(encoding="utf-8")).get("cost_usd") or 0)
        except (OSError, ValueError):
            pass
    return round(total, 2)


def busy() -> str | None:
    with _LOCK:
        for k, t in _RUNNING.items():
            if t.is_alive():
                return k
    return None


def status(run_dir: Path) -> dict | None:
    p = run_dir / "job.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
