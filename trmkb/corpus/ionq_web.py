"""
trmkb.corpus.ionq_web — ionq.com 블로그·리소스 수집 (why/what/how 전 층; 2020 로드맵 원문 포함).

/blog       약 100건. 로드맵·AQ 마일스톤·기술 결정(바륨, 전자식 제어)·주주서한.
/resources  약 80건. 백서·벤치마크 보고서·웨비나 요약.
/news       최신 12건만 노출(페이지네이션 없음) → 보도자료는 EDGAR 8-K EX-99로 대체.

구조: <h1> 제목, <div class="main-wrapper"> 본문, 본문 첫 "Month D, YYYY"가 게시일,
"Related blogs" 헤딩 이후는 제외.
"""
from __future__ import annotations

import re
import urllib.request
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from ..schema import SourceType
from .common import CORPUS_ROOT, CUTOFF, CorpusDoc, Throttle, clean_text, log, save_json

BASE = "https://ionq.com"
_throttle = Throttle(1.0)
DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                     r" (\d{1,2}), (20\d\d)")


def _get(url: str) -> str:
    _throttle.wait()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research crawler; leesuin9209@gmail.com)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="ignore")


def list_posts(section: str) -> list[str]:
    html = _get(f"{BASE}/{section}")
    links = sorted(set(re.findall(rf'href="(/{section}/[^"#?]+)"', html)))
    return [BASE + l for l in links]


def parse_post(html: str) -> tuple[str, date | None, str]:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        t.decompose()
    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else clean_text(soup.title.get_text() if soup.title else "")
    title = re.sub(r"^IonQ \| ", "", title)
    container = soup.find("div", class_="main-wrapper") or soup.body
    # "Related blogs" 이후 제거
    for h in container.find_all(["h2", "h3"]):
        if re.match(r"(?i)related", h.get_text(strip=True)):
            for sib in list(h.find_all_next()):
                sib.decompose()
            h.decompose()
            break
    full_text = container.get_text("\n", strip=True)
    m = DATE_RE.search(full_text)
    d = None
    if m:
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
        except ValueError:
            d = None
    # 본문: 제목과 날짜 이후의 p/li/h 텍스트
    blocks = []
    for el in container.find_all(["h2", "h3", "h4", "p", "li", "blockquote"]):
        t = clean_text(el.get_text(" ", strip=True))
        if not t or len(t) < 2:
            continue
        if el.name in ("h2", "h3", "h4"):
            blocks.append(f"\n## {t}\n")
        elif el.name == "li":
            blocks.append(f"- {t}")
        else:
            blocks.append(t)
    body = clean_text("\n".join(blocks))
    return title, d, body


def collect(cutoff: date = CUTOFF, root: Path = CORPUS_ROOT, sections: tuple[str, ...] = ("blog", "resources"),
            limit: int | None = None) -> list[CorpusDoc]:
    docs, manifest, skipped = [], [], []
    for section in sections:
        urls = list_posts(section)
        if limit:
            urls = urls[:limit]
        log(f"[ionq_web] {section}: {len(urls)} links")
        for url in urls:
            try:
                html = _get(url)
            except Exception as e:  # noqa: BLE001
                log(f"[ionq_web] fetch fail {url}: {e}"); continue
            title, d, body = parse_post(html)
            slug = url.rsplit("/", 1)[-1]
            if d is None:
                skipped.append({"url": url, "reason": "no date"}); continue
            if d > cutoff:
                skipped.append({"url": url, "reason": f"after cutoff {d}"}); continue
            if len(body) < 300:
                skipped.append({"url": url, "reason": "too short"}); continue
            st = SourceType.BLOG if section == "blog" else SourceType.INDUSTRY_REPORT
            doc_id = f"pub_ionq_{section}_{d.isoformat()}_{re.sub(r'[^a-z0-9]+', '_', slug)[:40]}"
            doc = CorpusDoc(id=doc_id, title=title, source_type=st, date=d, url=url, body=body,
                            extra={"section": section, "slug": slug})
            doc.write(root)
            docs.append(doc)
            manifest.append({"id": doc_id, "date": d.isoformat(), "title": title, "url": url, "chars": len(body)})
            log(f"[ionq_web] {doc_id} ({len(body):,} chars)")
    save_json(root / "public" / "_manifest_ionq_web.json", {"collected": manifest, "skipped": skipped})
    return docs


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    collect()
