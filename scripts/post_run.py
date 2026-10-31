"""전체 실행 완료 후 자동 마무리 (사용자 사전 승인 2026-10-31).

python scripts/post_run.py --run runs/full [--skip ablation,contrast,model2,report,static,commit]

단계 (각 단계는 실패해도 다음으로 진행, post_run.log 에 기록):
  1 finalize   : Advanced → diff → 회수율 → 정렬 → summary.json/md
  2 diagnose   : KB 품질 진단 (중복·router·기여·증가곡선)
  3 screenshot : 시각화 서버(8765)에서 KB·로드맵 화면 캡처 → docs/screenshots/viz_*_full.png
  4 report     : 사용자 보고서 docx 제자리 갱신 + PDF (Word COM)
  5 static     : docs/site 재내보내기 (pilotD + full)
  6 ablation   : S0~S4d 9조건 Advanced + 평가 → runs/full/ablation/summary.md
  7 contrast   : 대조 과업 3종 (S0 vs S4)
  8 model2     : Generator 2번째 모델(claude-sonnet-4.6)로 Initial/Advanced + 정렬 → runs/full/model2/
  9 commit     : git add/commit/push
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, ".")

PY = sys.executable
ENV = {**os.environ, "PYTHONUTF8": "1"}
LOG = None


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    if LOG:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def sh(cmd: list[str], timeout: int = 3600) -> tuple[int, str]:
    log("$ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV, timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    tail = "\n".join([l for l in out.splitlines() if not any(k in l for k in ("Warning", "Loading weights", "BertModel", "UNEXPECTED", "Notes:", "can be ignored"))][-25:])
    log(tail)
    return p.returncode, out


def step(name, fn, skip):
    if name in skip:
        log(f"== {name}: skipped"); return
    log(f"== {name}: start")
    try:
        fn()
        log(f"== {name}: done")
    except Exception as e:  # noqa: BLE001
        log(f"== {name}: FAILED {type(e).__name__}: {e}")


def main() -> None:
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/full")
    ap.add_argument("--skip", default="")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    run = Path(args.run); LOG = run / "post_run.log"
    skip = set(s.strip() for s in args.skip.split(",") if s.strip())
    initial_src = "data/roadmaps/roadmap_initial_gpt-4.1_v2_2026-10-31.json"

    def finalize():
        sh([PY, "scripts/finalize_run.py", "--run", str(run), "--initial-from", initial_src])
        assert (run / "summary.json").exists(), "summary.json missing"

    def diagnose():
        sh([PY, "scripts/kb_diagnose.py", "--run", str(run)])

    def screenshot():
        chrome = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
        prof = str(ROOT / "runs" / "_chrome_profile")
        shutil.rmtree(prof, ignore_errors=True)
        base = "http://127.0.0.1:8765/"
        try:
            import urllib.request
            urllib.request.urlopen(base + "api/runs", timeout=5)
        except Exception:
            log("viz server not running on 8765 → starting one")
            subprocess.Popen([PY, "-m", "uvicorn", "viz.server:app", "--port", "8765", "--log-level", "warning"], env=ENV,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            time.sleep(8)
        for name, url, budget in (("viz_kb_full.png", f"?run={run.name}&autoplay=1&speed=0&v={int(time.time())}", 60000),
                                  ("viz_roadmap_diff_full.png", f"?run={run.name}&view=rm&v={int(time.time())}", 15000)):
            out = str(ROOT / "docs" / "screenshots" / name)
            sh([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars", f"--user-data-dir={prof}",
                "--window-size=1600,900", f"--virtual-time-budget={budget}", f"--screenshot={out}", base + url], timeout=300)
            assert Path(out).exists() and Path(out).stat().st_size > 20000, f"screenshot failed {name}"

    def report():
        cmd = [PY, "scripts/update_report_results.py", "--run", str(run)]
        if args.date:
            cmd += ["--date", args.date]
        sh(cmd)
        docx = (ROOT / ".." / "연구계획" / "이수인_KB구축시스템_진행보고_1031.docx").resolve()
        pdf = docx.with_suffix(".pdf")
        ps = (f'$w = New-Object -ComObject Word.Application; $w.Visible = $false; $d = $w.Documents.Open("{docx}", $false, $true); '
              f'$d.SaveAs([ref]"{pdf}", [ref]17); $d.Close($false); $w.Quit(); "pdf ok"')
        sh(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=300)
        shutil.copy(docx, ROOT / "docs" / "reports" / docx.name); shutil.copy(pdf, ROOT / "docs" / "reports" / pdf.name)

    def static():
        sh([PY, "scripts/export_static.py", "runs/pilotD", str(run)])

    def ablation():
        sh([PY, "scripts/ablation.py", "--run", str(run)], timeout=7200)

    def contrast():
        sh([PY, "scripts/eval_run.py", "contrast", "--run", str(run)], timeout=3600)

    def model2():
        d = run / "model2"; d.mkdir(exist_ok=True)
        m = "anthropic/claude-sonnet-4.6"
        sh([PY, "scripts/gen_roadmap.py", "initial", "--run", str(d), "--model", m])
        sh([PY, "-c", (
               "import sys,json; sys.path.insert(0,'.');"
               "from trmkb.llm import LLM; from trmkb.store import KBStore; from trmkb.roadmap import generate as G, retrieve as R, diff as D;"
               "from trmkb.eval.alignment import evaluate_run;"
               f"kb=KBStore('{run.as_posix()}'); llm=LLM(); ctx=R.build_context(kb);"
               f"adv=G.generate(llm, condition='advanced', context=ctx.text, model='{m}', ops_by_evidence=ctx.ops_by_ref); G.save(adv, '{d.as_posix()}');"
               f"ini=G.load('{d.as_posix()}','initial'); D.save(D.compute_diff(ini, adv, llm), '{d.as_posix()}');"
               f"al=evaluate_run('{d.as_posix()}', llm); print(json.dumps({{c:{{k:v for k,v in s.items() if k!='results'}} for c,s in al.items()}}, ensure_ascii=False, indent=1))"
           )], timeout=1800)

    def commit():
        sh(["git", "add", "-A"])
        sh(["git", "commit", "-q", "-m", f"full run ({run.name}) results: finalize, ablation, contrast tasks, model2, report update, static site"])
        sh(["git", "push", "-q", "origin", "main"])

    for name, fn in (("finalize", finalize), ("diagnose", diagnose), ("screenshot", screenshot), ("report", report),
                     ("static", static), ("ablation", ablation), ("contrast", contrast), ("model2", model2), ("commit", commit)):
        step(name, fn, skip)
    log("post_run complete")


if __name__ == "__main__":
    main()
