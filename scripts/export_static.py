"""run 들을 서버 없이 보는 정적 사이트로 내보내기 (GitHub Pages 용).

python scripts/export_static.py runs/pilotD runs/full [--out docs/site]

생성물:
  docs/site/index.html            (viz/static/index.html 에 window.STATIC=true 주입)
  docs/site/data/runs.json, i18n_ko.json, i18n_en.json
  docs/site/data/<run>/snapshot.json, events.json, roadmaps.json
  docs/site/.nojekyll
GitHub 저장소 Settings → Pages → Source: Deploy from a branch → main / (docs) 로 켜면
  https://<user>.github.io/<repo>/site/?run=<run>&autoplay=1&speed=20   로 열린다.
"""
import argparse
import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.i18n import _LABELS
from trmkb.roadmap import generate as G
from trmkb.store import EventLog, KBStore

ROOT = Path(__file__).resolve().parent.parent


def export_run(run_dir: Path, out: Path) -> dict:
    kb = KBStore(run_dir)
    d = out / "data" / run_dir.name
    d.mkdir(parents=True, exist_ok=True)
    snap = kb.snapshot(); snap["stats"] = kb.stats()
    snap["documents"] = [{"id": x.id, "title": x.title, "date": x.date.isoformat(), "source_type": x.source_type.value,
                          "is_synthetic": x.is_synthetic} for x in kb.documents.values()]
    plan = run_dir / "plan.json"
    snap["planned_total"] = json.loads(plan.read_text(encoding="utf-8")).get("total") if plan.exists() else None
    (d / "snapshot.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    evs = [json.loads(e.model_dump_json(exclude_none=True)) for e in EventLog(run_dir / "events.jsonl").read()]
    (d / "events.json").write_text(json.dumps(evs, ensure_ascii=False), encoding="utf-8")
    rms = {}
    for cond in ("initial", "advanced"):
        rm = G.load(run_dir, cond)
        if rm:
            rms[cond] = json.loads(rm.model_dump_json(exclude_none=True)); rms[cond]["summary"] = G.summary(rm)
    diff_p = run_dir / "roadmap_diff.json"
    if diff_p.exists():
        rms["diff"] = json.loads(diff_p.read_text(encoding="utf-8"))
    (d / "roadmaps.json").write_text(json.dumps(rms, ensure_ascii=False), encoding="utf-8")
    return {"run": run_dir.name, "events": len(evs), "has_kb": True, "roadmaps": [c for c in ("initial", "advanced") if c in rms]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default="docs/site")
    args = ap.parse_args()
    out = Path(args.out); (out / "data").mkdir(parents=True, exist_ok=True)
    html = (ROOT / "viz" / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head>", "<head>\n<script>window.STATIC = true;</script>", 1)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    for lang in ("ko", "en"):
        base = dict(_LABELS["ko"]); base.update(_LABELS.get(lang, {}))
        (out / "data" / f"i18n_{lang}.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    runs = [export_run(Path(r), out) for r in args.runs]
    (out / "data" / "runs.json").write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"exported {len(runs)} runs → {out} ({total/1e6:.1f} MB)")
    for r in runs:
        print("  ", r)


if __name__ == "__main__":
    main()
