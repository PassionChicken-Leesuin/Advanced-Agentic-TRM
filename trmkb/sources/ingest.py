"""업로드 문서 받아들이기 — 파일(PDF·HTML·DOCX·Markdown·텍스트)을 코퍼스와 같은 꼴(frontmatter + 본문 md)로 바꿔 run 폴더에 둔다.

문서 메타데이터는 파일에서 읽어낸다:
  날짜      파일 이름의 YYYY-MM-DD / YYYYMMDD / YYYY-MM → 없으면 본문 첫 3,000자에서 날짜 표현 → 없으면 업로드 날짜
  제목      frontmatter title → PDF 메타 title → HTML <title>/<h1> → 첫 줄 → 파일 이름
  문서 유형 파일 이름·내용의 단서로 추정 (10-K/10-Q/8-K → sec_filing, press/announce → press_release, arxiv → arxiv,
            memo/minutes/meeting → syn_meeting 류의 내부 유형, 그 외 document). 유형은 Reader 의 청킹(sec_filing)과 화면 표시에만 쓰인다.
  내부 문서 파일 이름에 internal/memo/minutes/email 이 있거나 사용자가 내부로 표시하면 is_synthetic=True (화면·카드에서 'internal' 로 표시;
            이름은 데모 코퍼스의 가상 내부 문서와 같은 필드를 그대로 쓴다).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

import yaml

from ..corpus.common import clean_text, read_doc, slugify

ALLOWED = {".pdf", ".html", ".htm", ".md", ".markdown", ".txt", ".docx"}
MAX_BYTES = 25 * 1024 * 1024
MAX_FILES = 30
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _date_in(s: str) -> date | None:
    for pat, fn in (
        (r"(20\d{2})[-_./](\d{1,2})[-_./](\d{1,2})", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
        (r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
        (r"\b([A-Z][a-z]{2,8})\.? (\d{1,2}),? (20\d{2})\b", lambda m: date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])) if m[1][:3].lower() in MONTHS else None),
        (r"\b(\d{1,2}) ([A-Z][a-z]{2,8}),? (20\d{2})\b", lambda m: date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])) if m[2][:3].lower() in MONTHS else None),
        (r"(20\d{2})[-_./](\d{1,2})(?![-_./]?\d)", lambda m: date(int(m[1]), int(m[2]), 1)),
        (r"\b([A-Z][a-z]{2,8}) (20\d{2})\b", lambda m: date(int(m[2]), MONTHS[m[1][:3].lower()], 1) if m[1][:3].lower() in MONTHS else None),
    ):
        for m in re.finditer(pat, s):
            try:
                d = fn(m)
            except (ValueError, KeyError):
                continue
            if d and 2000 <= d.year <= 2100:
                return d
    return None


def _pdf(data: bytes) -> tuple[str, str | None, date | None]:
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    parts = [page.get_text("text") for page in doc]
    meta = doc.metadata or {}
    title = (meta.get("title") or "").strip() or None
    d = None
    cd = meta.get("creationDate") or ""
    m = re.search(r"D:(\d{4})(\d{2})(\d{2})", cd)
    if m:
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            d = None
    return "\n\n".join(parts), title, d


def _html(data: bytes) -> tuple[str, str | None, date | None]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data.decode("utf-8", errors="ignore"), "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        t.decompose()
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True) if not title else title
    d = None
    for tag in soup.find_all("meta"):
        if str(tag.get("property", "")).endswith("published_time") or tag.get("name") in ("date", "pubdate", "publish-date", "article:published_time"):
            d = _date_in(str(tag.get("content", "")))
            if d:
                break
    if not d:
        tt = soup.find("time")
        if tt:
            d = _date_in(str(tt.get("datetime", "")) + " " + tt.get_text(" ", strip=True))
    text = soup.get_text("\n")
    return text, title, d


def _docx(data: bytes) -> tuple[str, str | None, date | None]:
    import io
    import docx
    d = docx.Document(io.BytesIO(data))
    paras = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            paras.append(" | ".join(c.text.strip() for c in row.cells))
    title = (d.core_properties.title or "").strip() or None
    cd = d.core_properties.created
    return "\n".join(paras), title, cd.date() if isinstance(cd, datetime) else None


def _md(data: bytes) -> tuple[str, str | None, date | None, dict]:
    text = data.decode("utf-8", errors="ignore")
    m = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", text, flags=re.S)
    fm = {}
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        text = m.group(2)
    title = str(fm.get("title")).strip() if fm.get("title") else None
    if not title:
        h = re.search(r"^#\s+(.+)$", text, flags=re.M)
        title = h.group(1).strip() if h else None
    d = None
    if fm.get("date"):
        d = fm["date"] if isinstance(fm["date"], date) else _date_in(str(fm["date"]))
    return text, title, d, fm


INTERNAL_WORDS = ("internal", "memo", "minutes", "meeting", "email", "e-mail", "assessment", "weekly", "review-note", "confidential")


def guess_type(name: str, text: str, is_internal: bool) -> str:
    low = name.lower() + " " + text[:1500].lower()
    if is_internal:
        if "email" in low or "e-mail" in low or re.search(r"^\s*(from|to|subject):", text[:600], flags=re.M | re.I):
            return "syn_customer_email" if "customer" in low else "syn_supplier_email" if "supplier" in low else "syn_customer_email"
        if "minutes" in low or "meeting" in low or "agenda" in low:
            return "syn_meeting"
        if "assessment" in low or "evaluation" in low:
            return "syn_tech_assessment"
        return "syn_rd_report"
    if re.search(r"\b(form\s+)?(10-k|10-q|8-k|20-f|6-k|s-1|def 14a|annual report|quarterly report)\b", low):
        return "sec_filing"
    if "arxiv" in low or re.search(r"\babstract\b", text[:3000], flags=re.I) and re.search(r"\breferences\b", text, flags=re.I):
        return "arxiv"
    if re.search(r"press release|announces|announced today|for immediate release", low):
        return "press_release"
    if re.search(r"investor (day|presentation|deck)|earnings call|q[1-4] 20\d\d (results|update)", low):
        return "investor_deck"
    if re.search(r"\bblog\b|posted by|read more", low):
        return "blog"
    if re.search(r"market report|industry report|whitepaper|white paper|outlook", low):
        return "industry_report"
    if re.search(r"\bpatent\b|claims?\s+\d+\.", low):
        return "patent"
    return "document"


def convert(name: str, data: bytes) -> tuple[str, str | None, date | None, dict]:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        t, title, d = _pdf(data); fm = {}
    elif ext in (".html", ".htm"):
        t, title, d = _html(data); fm = {}
    elif ext == ".docx":
        t, title, d = _docx(data); fm = {}
    else:
        t, title, d, fm = _md(data)
    return clean_text(t), title, d, fm


def ingest(run_dir: str | Path, files: list[tuple[str, bytes]], *, company: str, internal_names: set[str] | None = None,
           upload_date: date | None = None) -> list[dict]:
    """files = [(원 파일 이름, 바이트)]. runs/<run>/docs/<id>.md 로 저장하고 SourceStore.docs 꼴의 dict 목록을 돌려준다 (날짜순)."""
    run_dir = Path(run_dir)
    out_dir = run_dir / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = upload_date or date.today()
    internal_names = {n.lower() for n in (internal_names or set())}
    docs = []
    seen_ids: set[str] = set()
    for name, data in files:
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED:
            raise ValueError(f"unsupported file type: {name}")
        if len(data) > MAX_BYTES:
            raise ValueError(f"file too large (> {MAX_BYTES // 1024 // 1024} MB): {name}")
        body, title, d, fm = convert(name, data)
        if len(body.strip()) < 200:
            raise ValueError(f"no readable text in {name} (scanned PDF? images only?)")
        stem = Path(name).stem
        d = _date_in(stem) or d or _date_in(body[:3000]) or today
        title = (title or next((ln.strip("# ").strip() for ln in body.splitlines() if 8 <= len(ln.strip()) <= 160), None) or stem)[:200]
        is_internal = Path(name).name.lower() in internal_names or any(w in stem.lower() for w in INTERNAL_WORDS) or bool(fm.get("is_synthetic"))
        stype = str(fm.get("source_type") or guess_type(name, body, is_internal))
        base = f"up_{d.isoformat()}_{slugify(stem, 40)}"
        did = base
        n = 2
        while did in seen_ids:
            did = f"{base}_{n}"; n += 1
        seen_ids.add(did)
        meta = {"id": did, "title": title, "source_type": stype, "date": d.isoformat(), "url": fm.get("url"), "actor": company,
                "is_synthetic": is_internal, "original_name": Path(name).name, "sha256": hashlib.sha256(data).hexdigest(), "n_chars": len(body)}
        p = out_dir / f"{did}.md"
        p.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n", encoding="utf-8")
        docs.append({"id": did, "title": title, "date": d.isoformat(), "source_type": stype, "is_synthetic": is_internal,
                     "path": str(p.resolve()), "original_name": Path(name).name, "n_chars": len(body)})
    docs.sort(key=lambda x: (x["date"], x["id"]))
    return docs


__all__ = ["ingest", "convert", "guess_type", "ALLOWED", "MAX_FILES", "MAX_BYTES", "read_doc"]
