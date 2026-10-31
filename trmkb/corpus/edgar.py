"""
trmkb.corpus.edgar — SEC EDGAR에서 IonQ 공시 수집.

대상 (cutoff 이전):
  10-K            연차보고서 (Business, Risk Factors, MD&A → issue·enabler·market_size의 1차 출처)
  10-Q            분기보고서 (MD&A 위주; 본문 길이 제한)
  8-K + EX-99.*   보도자료 (milestone·actor)
  425             SPAC 합병 커뮤니케이션 2021 (투자자 발표 → 2020 로드맵 원문)
  DEFA14A         합병 위임장 추가자료

CIK 1824920 (dMY Technology Group III → IonQ, Inc.). SEC 요청 간격 ≥ 0.12s, User-Agent 필수.
HTML → 텍스트: bs4. 10-Q/10-K는 XBRL 표가 많아 표를 '|' 구분 줄로 평탄화한다.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from ..schema import SourceType
from .common import CORPUS_ROOT, CUTOFF, UA, CorpusDoc, Throttle, clean_text, log, save_json

CIK = "1824920"
SUBMISSIONS = f"https://data.sec.gov/submissions/CIK{int(CIK):010d}.json"
ARCHIVE = f"https://www.sec.gov/Archives/edgar/data/{CIK}"

FORM_MAP = {
    "10-K": SourceType.SEC_FILING, "10-K/A": SourceType.SEC_FILING,
    "10-Q": SourceType.SEC_FILING,
    "8-K": SourceType.PRESS_RELEASE,
    "425": SourceType.INVESTOR_DECK,
    "DEFA14A": SourceType.INVESTOR_DECK,
}

_throttle = Throttle(0.13)
MERGER_CLOSE = date(2021, 10, 1)   # dMY III · IonQ 합병 종결 2021-09-30


def _strip_exhibit_header(text: str) -> str:
    """EX-99.1 / 파일명 / 숫자만 있는 앞머리 줄 제거."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (
        not lines[i].strip()
        or re.fullmatch(r"(?i)(ex[-_.]?\d+(\.\d+)?|exhibit \d+(\.\d+)?|\d+|[\w.-]+\.html?)", lines[i].strip())
    ):
        i += 1
    return "\n".join(lines[i:]).strip()


def _get(url: str, binary: bool = False) -> bytes | str:
    _throttle.wait()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", errors="ignore")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "head", "noscript"]):
        t.decompose()
    # XBRL hidden facts
    for t in soup.find_all(style=re.compile(r"display:\s*none")):
        t.decompose()
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with(soup.new_string("\n" + "\n".join(rows) + "\n"))
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "tr"]):
        p.append("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return clean_text(text)


def list_filings(cutoff: date = CUTOFF, forms: set[str] | None = None) -> list[dict]:
    forms = forms or set(FORM_MAP)
    d = json.loads(_get(SUBMISSIONS))
    r = d["filings"]["recent"]
    out = []
    for i in range(len(r["form"])):
        fd = date.fromisoformat(r["filingDate"][i])
        if r["form"][i] in forms and fd <= cutoff:
            out.append({
                "form": r["form"][i], "date": fd, "acc": r["accessionNumber"][i],
                "primary": r["primaryDocument"][i], "desc": r["primaryDocDescription"][i],
                "report_date": r["reportDate"][i],
            })
    return sorted(out, key=lambda x: x["date"])


def _folder_files(acc: str) -> list[str]:
    idx = json.loads(_get(f"{ARCHIVE}/{acc.replace('-', '')}/index.json"))
    return [it["name"] for it in idx["directory"]["item"]]


def _title_from(text: str, fallback: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if 15 < len(s) < 160 and not s.isupper() and re.search(r"[A-Za-z]", s) and "|" not in s:
            if re.match(r"(?i)(ionq|dmy)", s) or re.search(r"(?i)announc|report|result|quarter|annual|roadmap", s):
                return s
    return fallback


def collect(cutoff: date = CUTOFF, root: Path = CORPUS_ROOT, forms: set[str] | None = None,
            max_chars: dict[str, int] | None = None, limit: int | None = None) -> list[CorpusDoc]:
    """공시를 내려받아 md로 저장. 반환: 저장된 CorpusDoc 목록."""
    max_chars = max_chars or {"10-K": 400_000, "10-Q": 150_000, "8-K": 60_000, "425": 120_000, "DEFA14A": 120_000}
    filings = list_filings(cutoff, forms)
    if limit:
        filings = filings[:limit]
    log(f"[edgar] {len(filings)} filings up to {cutoff}")
    docs: list[CorpusDoc] = []
    manifest = []
    for f in filings:
        acc_nodash = f["acc"].replace("-", "")
        base = f"{ARCHIVE}/{acc_nodash}"
        targets: list[tuple[str, str]] = []  # (filename, kind)
        if f["form"] == "8-K":
            # 8-K 본문은 짧은 공시문; 보도자료는 EX-99.x
            try:
                files = _folder_files(f["acc"])
            except Exception as e:  # noqa: BLE001
                log(f"[edgar] index fail {f['acc']}: {e}"); continue
            ex = [n for n in files if re.search(r"(?i)ex[-_]?99", n) and n.lower().endswith((".htm", ".html"))]
            if not ex:
                targets.append((f["primary"], "8k_body"))
            for n in ex:
                targets.append((n, "ex99"))
        else:
            targets.append((f["primary"], f["form"].lower().replace("/", "")))
        for fname, kind in targets:
            url = f"{base}/{fname}"
            try:
                html = _get(url)
            except Exception as e:  # noqa: BLE001
                log(f"[edgar] fetch fail {url}: {e}"); continue
            text = _strip_exhibit_header(html_to_text(html))
            if len(text) < 500:
                continue
            cap = max_chars.get(f["form"], 100_000)
            truncated = len(text) > cap
            text = text[:cap]
            suffix = re.sub(r"[^a-z0-9]+", "_", Path(fname).stem.lower())[:30]
            doc_id = f"pub_edgar_{f['form'].lower().replace('/', '')}_{f['date'].isoformat()}_{suffix}"
            title = _title_from(text, f"{f['form']} {f['date']} {fname}")
            if f["form"] in ("10-K", "10-Q"):
                title = f"IonQ {f['form']} for period ending {f['report_date']}"
            actor = "IonQ" if f["date"] >= MERGER_CLOSE else "dMY Technology Group III (SPAC, pre-merger with IonQ)"
            doc = CorpusDoc(
                id=doc_id, title=title, source_type=FORM_MAP[f["form"]], date=f["date"], url=url,
                body=text, actor=actor,
                extra={"form": f["form"], "accession": f["acc"], "exhibit_kind": kind,
                       "truncated": truncated, "report_date": f["report_date"]},
            )
            doc.write(root)
            docs.append(doc)
            manifest.append({"id": doc_id, "form": f["form"], "date": f["date"].isoformat(),
                             "url": url, "chars": len(text), "truncated": truncated})
            log(f"[edgar] {doc_id} ({len(text):,} chars{', truncated' if truncated else ''})")
    save_json(root / "public" / "_manifest_edgar.json", manifest)
    return docs


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    collect()
