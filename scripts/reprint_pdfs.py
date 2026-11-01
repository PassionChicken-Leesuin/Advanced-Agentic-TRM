"""웹 페이지 원본의 열람용 PDF 를 DevTools 인쇄로 다시 만든다 (쿠키 창 제거, 스크롤 애니메이션 본문 표시).

python scripts/reprint_pdfs.py            # real_data ionq_web 75건 + ground_truth 웹 페이지
매니페스트의 page.pdf 항목(sha256·크기)을 갱신하고, 본문 글자 수를 text_chars 로 남긴다.
"""
import hashlib
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.corpus.cdp_print import Printer
from trmkb.corpus.originals import MANIFEST, ORIG

GT_ROOT = Path("data/ground_truth/originals")
GT_MAN = GT_ROOT / "_manifest_ground_truth.json"


def file_rec(path: Path, rel_root: Path, url: str, n: int) -> dict:
    data = path.read_bytes()
    return {"path": str(path.relative_to(rel_root)).replace("\\", "/"), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "content_type": "application/pdf", "url": url + " (Chrome DevTools print)", "text_chars": n}


def main() -> None:
    pr = Printer(Path("runs/_chrome_profile_cdp").resolve())
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        jobs = [(k, r) for k, r in man.items() if r.get("source") == "ionq_web"]
        bad = []
        for i, (k, r) in enumerate(jobs, 1):
            out = ORIG / "ionq_web" / k / "page.pdf"
            try:
                n = pr.print_pdf(r["url"], out)
            except Exception as e:  # noqa: BLE001
                print("  FAIL", k, e); bad.append(k); continue
            r["files"] = [f for f in r["files"] if not f["path"].endswith("page.pdf")] + [file_rec(out, ORIG, r["url"], n)]
            r.pop("warnings", None) if n > 500 else r.setdefault("warnings", []).append(f"pdf text only {n} chars")
            print(f"[{i}/{len(jobs)}] {k[:60]:60s} text={n}")
            if i % 10 == 0:
                MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        # ground truth web pages (current pages; wayback snapshots printed from archive URL)
        gt = json.loads(GT_MAN.read_text(encoding="utf-8"))
        for key, rec in gt.items():
            html = next((f for f in rec.get("files", []) if f["path"].endswith("page.html")), None)
            if not html:
                continue
            url = html["url"]
            if "web.archive.org" in url:
                url = url.replace("id_/", "/")  # 보관 화면(툴바 포함) 인쇄
            out = GT_ROOT / key / "page.pdf"
            try:
                n = pr.print_pdf(url, out, settle=8.0 if "web.archive.org" in url else 4.0)
            except Exception as e:  # noqa: BLE001
                print("  FAIL", key, e); bad.append(key); continue
            rec["files"] = [f for f in rec["files"] if not f["path"].endswith("page.pdf")] + [file_rec(out, GT_ROOT, url, n)]
            print(f"[gt] {key:55s} text={n}")
        GT_MAN.write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
        print("failures:", bad)
    finally:
        pr.close()


if __name__ == "__main__":
    main()
