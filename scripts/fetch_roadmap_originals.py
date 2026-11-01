"""IonQ 공식 로드맵 원본 확보: 2020년 12월 로드맵, 2025년 6월 가속 로드맵 (정답표의 1차 출처).

python scripts/fetch_roadmap_originals.py

data/ground_truth/originals/
  2020-12_roadmap/
    ionq_blog_current/         현재 게시본 (2022-02-23 수정판): page.html, 차트 원본 이미지, page.pdf
    ionq_blog_wayback_2020/    Internet Archive 에 보관된 최초 게시 시점(2020-12) 스냅샷: page.html(원본 바이트), page.pdf, 이미지
    edgar_2021-03-08_8k/       dMY III·IonQ 합병 발표 8-K: 보도자료(EX-99.1), 투자자 발표(EX-99.2) 원본 htm + 슬라이드 이미지 전부
  2025-06_roadmap/
    ionq_blog_2025-06-13/      "IonQ's Accelerated Roadmap" 블로그: html, 이미지, pdf
    ionq_roadmap_page_wayback_2025-06/  ionq.com/roadmap 의 2025년 6월 보관 스냅샷
    ionq_roadmap_page_current/ ionq.com/roadmap 현재 판 (수집일 기준)
    edgar_2025-06-09_8k/       Oxford Ionics 인수 8-K 본문 + 보도자료(EX-99.1)
    ionq_blog_2025-10-13_aq64/ #AQ 64 달성·지표 변경 공지 블로그
  _manifest_ground_truth.json  파일별 sha256·URL·수집 시각
"""
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from bs4 import BeautifulSoup

from trmkb.corpus.originals import CHROME, UA_SEC, UA_WEB

ROOT = Path("data/ground_truth/originals")
MANIFEST = ROOT / "_manifest_ground_truth.json"
PROFILE = Path("runs/_chrome_profile_print").resolve()
EDGAR = "https://www.sec.gov/Archives/edgar/data/1824920"


def get(url: str, ua: str = UA_WEB, pause: float = 1.0) -> tuple[bytes, str]:
    time.sleep(pause)
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.headers.get("Content-Type", "")


def save(path: Path, data: bytes, ctype: str, url: str) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "url": url, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "content_type": ctype, "retrieved_at": datetime.now(timezone.utc).isoformat()}


def imgs(html: bytes, base: str, container: str | None = None, same_prefix: str | None = None, limit: int = 120) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    root = (soup.find("div", class_=container) if container else None) or soup
    out = []
    for im in root.find_all("img"):
        src = im.get("src") or im.get("data-src") or ""
        if src and not src.startswith("data:"):
            u = urllib.parse.urljoin(base, src)
            if (not same_prefix or u.startswith(same_prefix)) and u not in out:
                out.append(u)
    return out[:limit]


def name_of(url: str, i: int) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(urllib.parse.urlparse(url).path).name)[:90] or f"img_{i}"
    return n if "." in n else n + ".bin"


def print_pdf(url: str, out: Path) -> dict | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={PROFILE}",
                        "--virtual-time-budget=20000", "--no-pdf-header-footer", f"--print-to-pdf={out.resolve()}", url],
                       capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if out.exists() and out.stat().st_size > 5000:
        return save(out, out.read_bytes(), "application/pdf", url + " (Chrome print)")
    return None


def web_page(url: str, d: Path, container: str | None = "main-wrapper", pdf: bool = True) -> list[dict]:
    files = []
    html, ct = get(url)
    files.append(save(d / "page.html", html, ct, url))
    for i, iu in enumerate(imgs(html, url, container=container, limit=40)):
        try:
            b, c = get(iu)
            if len(b) > 1500:
                files.append(save(d / name_of(iu, i), b, c, iu))
        except Exception as e:  # noqa: BLE001
            print("   img fail", iu, e)
    if pdf:
        p = print_pdf(url, d / "page.pdf")
        if p:
            files.append(p)
    return files


def wayback(url: str, ts: str) -> tuple[str, str] | None:
    """가장 가까운 보관 스냅샷 (timestamp, 보관 URL)."""
    api = f"https://archive.org/wayback/available?url={urllib.parse.quote(url, safe='')}&timestamp={ts}"
    try:
        data, _ = get(api, pause=1.5)
        snap = json.loads(data).get("archived_snapshots", {}).get("closest")
        if snap and snap.get("available"):
            return snap["timestamp"], snap["url"]
    except Exception as e:  # noqa: BLE001
        print("   wayback api fail", url, e)
    return None


def wayback_page(orig_urls: list[str], ts: str, d: Path, window: tuple[str, str]) -> list[dict]:
    """원본 바이트(id_) html + 보관 화면 pdf + 원본 이미지. window 안의 스냅샷만 채택."""
    for u in orig_urls:
        hit = wayback(u, ts)
        if not hit:
            continue
        snap_ts, snap_url = hit
        if not (window[0] <= snap_ts[:8] <= window[1]):
            print(f"   wayback {u}: nearest {snap_ts} outside window {window}")
            continue
        raw_url = f"https://web.archive.org/web/{snap_ts}id_/{u}"
        files = []
        html, ct = get(raw_url, pause=2)
        files.append(save(d / "page.html", html, ct, raw_url))
        for i, iu in enumerate(imgs(html, u, limit=30)):
            wiu = f"https://web.archive.org/web/{snap_ts}id_/{iu}"
            try:
                b, c = get(wiu, pause=1.5)
                if len(b) > 1500:
                    files.append(save(d / name_of(iu, i), b, c, wiu))
            except Exception as e:  # noqa: BLE001
                print("   wb img fail", iu, e)
        p = print_pdf(f"https://web.archive.org/web/{snap_ts}/{u}", d / "page.pdf")
        if p:
            files.append(p)
        (d / "SNAPSHOT.txt").write_text(f"original_url: {u}\nsnapshot: {snap_ts}\narchive_url: {snap_url}\n", encoding="utf-8")
        return files
    return []


def edgar_filing(acc: str, docs: list[str], d: Path) -> list[dict]:
    base = f"{EDGAR}/{acc.replace('-', '')}/"
    files = []
    for fn in docs:
        html, ct = get(base + fn, ua=UA_SEC, pause=0.2)
        files.append(save(d / fn, html, ct, base + fn))
        for i, iu in enumerate(imgs(html, base, same_prefix=base)):
            b, c = get(iu, ua=UA_SEC, pause=0.15)
            files.append(save(d / name_of(iu, i), b, c, iu))
    return files


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    jobs = {
        "2020-12_roadmap/ionq_blog_current": lambda d: web_page("https://ionq.com/blog/december-09-2020-scaling-quantum-computer-roadmap", d),
        "2020-12_roadmap/ionq_blog_wayback_2020": lambda d: wayback_page(
            ["ionq.com/posts/december-09-2020-scaling-quantum-computer-roadmap",
             "https://ionq.com/posts/december-09-2020-scaling-quantum-computer-roadmap",
             "ionq.com/blog/december-09-2020-scaling-quantum-computer-roadmap"], "20201210", d, ("20201209", "20220222")),
        "2020-12_roadmap/edgar_2021-03-08_8k": lambda d: edgar_filing("0001193125-21-072373",
                                                                      ["d142872d8k.htm", "d142872dex991.htm", "d142872dex992.htm"], d),
        "2025-06_roadmap/ionq_blog_2025-06-13": lambda d: web_page("https://ionq.com/blog/ionqs-accelerated-roadmap-turning-quantum-ambition-into-reality", d),
        "2025-06_roadmap/ionq_blog_2025-06-13_wayback_2025-06": lambda d: wayback_page(
            ["https://www.ionq.com/blog/ionqs-accelerated-roadmap-turning-quantum-ambition-into-reality",
             "ionq.com/blog/ionqs-accelerated-roadmap-turning-quantum-ambition-into-reality"], "20250617", d, ("20250613", "20250630")),
        "2025-06_roadmap/ionq_roadmap_page_wayback_2025-06": lambda d: wayback_page(
            ["ionq.com/roadmap", "https://ionq.com/roadmap", "https://www.ionq.com/roadmap"], "20250620", d, ("20250609", "20250815")),
        "2025-06_roadmap/ionq_roadmap_page_current": lambda d: web_page("https://ionq.com/roadmap", d, container=None),
        "2025-06_roadmap/edgar_2025-06-09_8k": lambda d: edgar_filing("0001193125-25-137398", ["d17095d8k.htm", "d17095dex991.htm"], d),
        "2025-06_roadmap/ionq_blog_2025-10-13_aq64": lambda d: web_page(
            "https://ionq.com/blog/ionq-hits-aq-64-milestone-ahead-of-schedule-and-sets-its-sights-even-higher", d),
    }
    for key, fn in jobs.items():
        if man.get(key, {}).get("files"):
            print("skip", key); continue
        d = ROOT / key
        try:
            files = fn(d)
            man[key] = {"status": "ok" if files else "not found", "files": files}
        except Exception as e:  # noqa: BLE001
            man[key] = {"status": f"error: {type(e).__name__}: {e}"[:300], "files": []}
        size = sum(f["bytes"] for f in man[key]["files"])
        print(f"{key:55s} {man[key]['status'][:40]:40s} files={len(man[key]['files'])} {size/1e6:.2f}MB")
        MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
