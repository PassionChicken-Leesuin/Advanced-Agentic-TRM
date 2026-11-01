"""
trmkb.corpus.originals — 공개 자료 259건의 원본 파일 확보 (바이트 단위 보존).

data/corpus/real_data/originals/
  edgar/<doc_id>/<원본 파일명>.htm  + 문서가 참조하는 이미지(슬라이드 jpg 등)
  arxiv/<doc_id>.pdf
  ionq_web/<doc_id>/page.html + 본문 이미지 + page.pdf (Chrome 인쇄본, 화면 그대로)
  _manifest_originals.json   doc_id → {source, url, files:[{path, sha256, bytes, content_type}], retrieved_at, status}

정규화 텍스트(real_data/text/*.md)는 이 원본에서 추출한 것이다. 재실행 시 이미 받은 문서는 건너뛴다.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from .common import CORPUS_ROOT, Throttle, iter_docs, log

ORIG = CORPUS_ROOT / "real_data" / "originals"
MANIFEST = ORIG / "_manifest_originals.json"
UA_SEC = "Suin Lee leesuin9209@gmail.com (academic research, SNU DDSI Lab)"
UA_WEB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) research-archiver (leesuin9209@gmail.com)"
CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
_t_sec, _t_arxiv, _t_web = Throttle(0.15), Throttle(3.0), Throttle(1.0)


def _fetch(url: str, ua: str, throttle: Throttle, timeout: int = 120) -> tuple[bytes, str]:
    throttle.wait()
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def _save(path: Path, data: bytes, ctype: str) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.relative_to(ORIG)).replace("\\", "/"), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "content_type": ctype}


def _imgs(html: bytes, base_url: str, container_class: str | None = None, limit: int = 80) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", class_=container_class) if container_class else soup
    root = root or soup
    out = []
    for im in root.find_all("img"):
        src = im.get("src") or im.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        out.append(urllib.parse.urljoin(base_url, src))
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq[:limit]


def _safe_name(url: str, i: int) -> str:
    name = Path(urllib.parse.urlparse(url).path).name or f"img_{i}"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80]
    return name if "." in name else name + ".bin"


def print_pdf(url: str, out_pdf: Path, profile: Path) -> dict | None:
    """Chrome 헤드리스로 화면 그대로 PDF 인쇄 (웹 페이지의 시각적 원본)."""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=15000", "--no-pdf-header-footer",
           f"--print-to-pdf={out_pdf}", url]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if out_pdf.exists() and out_pdf.stat().st_size > 5000:
        return _save(out_pdf, out_pdf.read_bytes(), "application/pdf")
    return None


def fetch_doc(fm: dict, profile: Path) -> dict:
    doc_id, url = fm["id"], fm.get("url")
    rec = {"doc_id": doc_id, "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(), "files": [], "status": "ok"}
    if doc_id.startswith("pub_edgar_"):
        rec["source"] = "edgar"
        data, ct = _fetch(url, UA_SEC, _t_sec)
        d = ORIG / "edgar" / doc_id
        rec["files"].append(_save(d / Path(urllib.parse.urlparse(url).path).name, data, ct))
        base = url.rsplit("/", 1)[0] + "/"
        for i, iu in enumerate(_imgs(data, base, limit=120)):
            if not iu.startswith(base):
                continue
            try:
                b, c = _fetch(iu, UA_SEC, _t_sec)
                rec["files"].append(_save(d / _safe_name(iu, i), b, c))
            except Exception as e:  # noqa: BLE001
                rec.setdefault("warnings", []).append(f"img {iu}: {e}")
    elif doc_id.startswith("pub_arxiv_"):
        rec["source"] = "arxiv"
        aid = fm.get("arxiv_id") or url.rsplit("/", 1)[-1]
        pdf_url = f"https://arxiv.org/pdf/{aid}"
        data, ct = _fetch(pdf_url, UA_WEB, _t_arxiv, timeout=180)
        rec["url_original"] = pdf_url
        rec["files"].append(_save(ORIG / "arxiv" / f"{doc_id}.pdf", data, ct))
    elif doc_id.startswith("pub_ionq_"):
        rec["source"] = "ionq_web"
        data, ct = _fetch(url, UA_WEB, _t_web)
        d = ORIG / "ionq_web" / doc_id
        rec["files"].append(_save(d / "page.html", data, ct))
        for i, iu in enumerate(_imgs(data, url, container_class="main-wrapper", limit=40)):
            try:
                b, c = _fetch(iu, UA_WEB, _t_web)
                if len(b) > 1500:
                    rec["files"].append(_save(d / _safe_name(iu, i), b, c))
            except Exception as e:  # noqa: BLE001
                rec.setdefault("warnings", []).append(f"img {iu}: {e}")
        # 열람용 PDF: DevTools 인쇄(쿠키 창 차단, 스크롤 애니메이션 본문 표시). 실패 시 단순 인쇄로 대체
        try:
            from .cdp_print import Printer
            pr = Printer(profile.with_name("_chrome_profile_cdp"))
            try:
                n = pr.print_pdf(url, d / "page.pdf")
            finally:
                pr.close()
            pdf = _save(d / "page.pdf", (d / "page.pdf").read_bytes(), "application/pdf"); pdf["text_chars"] = n
        except Exception:  # noqa: BLE001
            pdf = print_pdf(url, d / "page.pdf", profile)
        if pdf:
            rec["files"].append(pdf)
        else:
            rec.setdefault("warnings", []).append("pdf print failed")
    else:
        rec["status"] = "skipped (unknown source)"
    return rec


def collect(limit: int | None = None, only: set[str] | None = None) -> dict:
    ORIG.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    profile = ORIG.parent.parent.parent.parent / "runs" / "_chrome_profile_print"
    todo = [(p, fm) for p, fm, _ in iter_docs(CORPUS_ROOT, "public") if fm and not fm.get("is_synthetic")]
    if only:
        todo = [(p, fm) for p, fm in todo if fm["id"] in only]
    n = 0
    for p, fm in todo:
        if fm["id"] in man and man[fm["id"]].get("status") == "ok":
            continue
        if limit and n >= limit:
            break
        try:
            rec = fetch_doc(fm, profile)
        except Exception as e:  # noqa: BLE001
            rec = {"doc_id": fm["id"], "url": fm.get("url"), "status": f"error: {type(e).__name__}: {e}"[:300],
                   "retrieved_at": datetime.now(timezone.utc).isoformat(), "files": []}
        man[fm["id"]] = rec
        n += 1
        size = sum(f["bytes"] for f in rec["files"])
        log(f"[orig] {fm['id'][:60]:60s} {rec['status'][:30]:30s} files={len(rec['files'])} {size/1e6:.2f}MB")
        if n % 10 == 0:
            MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man
