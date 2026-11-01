"""
trmkb.corpus.arxiv — arXiv에서 IonQ 관련 논문 수집 (how 층: capability·component·spec).

검색: all:IonQ (제목·초록·저자 소속 텍스트에 IonQ가 등장). cutoff 이전 제출분만.
PDF → pymupdf 텍스트. 본문은 max_pages 쪽까지만 (참고문헌·부록은 KB에 거의 기여하지 않음).
arXiv API 예절: 요청 간격 ≥ 3s.
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pymupdf

from ..schema import SourceType
from .common import CORPUS_ROOT, CUTOFF, UA, CorpusDoc, Throttle, clean_text, log, save_json, slugify

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_throttle = Throttle(3.0)


def _get(url: str) -> bytes:
    _throttle.wait()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def search(query: str = "all:IonQ", cutoff: date = CUTOFF, max_results: int = 400) -> list[dict]:
    out = []
    start = 0
    while start < max_results:
        url = (f"{API}?search_query={urllib.request.quote(query)}&start={start}&max_results=100"
               f"&sortBy=submittedDate&sortOrder=descending")
        root = ET.fromstring(_get(url))
        entries = root.findall("a:entry", NS)
        if not entries:
            break
        for e in entries:
            pub = date.fromisoformat(e.findtext("a:published", default="", namespaces=NS)[:10])
            if pub > cutoff:
                continue
            aid = e.findtext("a:id", default="", namespaces=NS).rsplit("/", 1)[-1]
            pdf = next((l.get("href") for l in e.findall("a:link", NS) if l.get("title") == "pdf"), None)
            out.append({
                "arxiv_id": aid,
                "title": clean_text(e.findtext("a:title", default="", namespaces=NS).replace("\n", " ")),
                "published": pub,
                "summary": clean_text(e.findtext("a:summary", default="", namespaces=NS)),
                "authors": [a.findtext("a:name", default="", namespaces=NS) for a in e.findall("a:author", NS)],
                "affiliations": [x.text for a in e.findall("a:author", NS)
                                 for x in a.findall("arxiv:affiliation", NS) if x.text],
                "pdf": pdf or f"https://arxiv.org/pdf/{aid}",
                "categories": [c.get("term") for c in e.findall("a:category", NS)],
            })
        start += 100
    return out


def pdf_to_text(data: bytes, max_pages: int = 12) -> str:
    doc = pymupdf.open(stream=data, filetype="pdf")
    parts = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        t = page.get_text("text")
        t = re.sub(r"-\n(?=[a-z])", "", t)
        t = re.sub(r"(?<![.\n])\n(?!\n)", " ", t)
        parts.append(t.strip())
    return clean_text("\n\n".join(parts))


def collect(cutoff: date = CUTOFF, root: Path = CORPUS_ROOT, query: str = "all:IonQ",
            max_pages: int = 12, limit: int | None = None) -> list[CorpusDoc]:
    hits = search(query, cutoff)
    if limit:
        hits = hits[:limit]
    log(f"[arxiv] {len(hits)} papers up to {cutoff}")
    docs, manifest = [], []
    for h in hits:
        aid_clean = re.sub(r"[^0-9a-zA-Z]+", "_", h["arxiv_id"])
        doc_id = f"pub_arxiv_{h['published'].isoformat()}_{aid_clean}"
        try:
            body = pdf_to_text(_get(h["pdf"]), max_pages)
        except Exception as e:  # noqa: BLE001
            log(f"[arxiv] pdf fail {h['arxiv_id']}: {e}; using abstract")
            body = ""
        header = (f"# {h['title']}\n\nAuthors: {', '.join(h['authors'])}\n"
                  f"Affiliations: {', '.join(sorted(set(h['affiliations'])))}\n"
                  f"arXiv: {h['arxiv_id']}  Published: {h['published']}\n\n"
                  f"## Abstract\n\n{h['summary']}\n\n## Body (first {max_pages} pages)\n\n")
        doc = CorpusDoc(
            id=doc_id, title=h["title"], source_type=SourceType.ARXIV, date=h["published"],
            url=f"https://arxiv.org/abs/{h['arxiv_id']}", body=header + body,
            actor="IonQ-affiliated authors",
            extra={"arxiv_id": h["arxiv_id"], "authors": h["authors"], "categories": h["categories"]},
        )
        doc.write(root)
        docs.append(doc)
        manifest.append({"id": doc_id, "arxiv_id": h["arxiv_id"], "date": h["published"].isoformat(),
                         "title": h["title"], "chars": len(doc.body)})
        log(f"[arxiv] {doc_id} ({len(doc.body):,} chars)")
    save_json(root / "real_data" / "_manifest_arxiv.json", manifest)
    return docs


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    collect()
