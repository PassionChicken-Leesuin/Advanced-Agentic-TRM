"""
trmkb.corpus.common — 코퍼스 문서의 공통 포맷.

모든 문서는 data/corpus/<public|synthetic>/<doc_id>.md 로 저장되며 YAML frontmatter를 가진다:

---
id: pub_edgar_8k_2024-08-07_ex99_1
title: IonQ Announces Second Quarter 2024 Financial Results
source_type: press_release
date: 2024-08-07
url: https://www.sec.gov/Archives/...
actor: IonQ
is_synthetic: false
planted_fact_ids: []
n_chars: 12345
---
본문 (markdown/plain text)

index.jsonl 에 Document 레코드가 한 줄씩 쌓인다 (trmkb.schema.Document 호환).
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import yaml

from ..schema import Document, SourceType

CORPUS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "corpus"
CUTOFF = date(2024, 12, 31)
UA = "Suin Lee leesuin9209@gmail.com (academic research, SNU DDSI Lab)"


def slugify(text: str, maxlen: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:maxlen].rstrip("-")


def clean_text(t: str) -> str:
    t = t.replace("\xa0", " ").replace("​", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


@dataclass
class CorpusDoc:
    id: str
    title: str
    source_type: SourceType
    date: date
    url: str | None
    body: str
    actor: str = "IonQ"
    is_synthetic: bool = False
    planted_fact_ids: list[str] | None = None
    extra: dict[str, Any] | None = None

    @property
    def subdir(self) -> str:
        return "synthetic" if self.is_synthetic else "public"

    def path(self, root: Path = CORPUS_ROOT) -> Path:
        return root / self.subdir / f"{self.id}.md"

    def to_document(self, root: Path = CORPUS_ROOT) -> Document:
        return Document(
            id=self.id, title=self.title, source_type=self.source_type, date=self.date,
            path=str(self.path(root).relative_to(root)).replace("\\", "/"), url=self.url,
            actor_id=None, is_synthetic=self.is_synthetic,
            planted_fact_ids=self.planted_fact_ids or [], n_chars=len(self.body),
        )

    def write(self, root: Path = CORPUS_ROOT) -> Path:
        p = self.path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = {
            "id": self.id, "title": self.title, "source_type": self.source_type.value,
            "date": self.date.isoformat(), "url": self.url, "actor": self.actor,
            "is_synthetic": self.is_synthetic, "planted_fact_ids": self.planted_fact_ids or [],
            "n_chars": len(self.body),
        }
        if self.extra:
            fm.update(self.extra)
        text = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + self.body + "\n"
        p.write_text(text, encoding="utf-8")
        return p


def read_doc(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", text, flags=re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def iter_docs(root: Path = CORPUS_ROOT, subdir: str | None = None) -> Iterator[tuple[Path, dict[str, Any], str]]:
    dirs = [root / subdir] if subdir else [root / "public", root / "synthetic"]
    for d in dirs:
        for p in sorted(d.glob("*.md")):
            fm, body = read_doc(p)
            yield p, fm, body


def rebuild_index(root: Path = CORPUS_ROOT) -> Path:
    """frontmatter에서 index.jsonl 재생성."""
    out = root / "index.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for p, fm, body in iter_docs(root):
            if not fm:
                continue
            d = Document(
                id=fm["id"], title=fm["title"], source_type=SourceType(fm["source_type"]),
                date=date.fromisoformat(str(fm["date"])), path=str(p.relative_to(root)).replace("\\", "/"),
                url=fm.get("url"), is_synthetic=bool(fm.get("is_synthetic")),
                planted_fact_ids=fm.get("planted_fact_ids") or [], n_chars=len(body),
            )
            f.write(d.model_dump_json(exclude_none=True) + "\n")
    return out


class Throttle:
    def __init__(self, min_interval_s: float):
        self.min = min_interval_s
        self._last = 0.0

    def wait(self) -> None:
        now = time.time()
        if now - self._last < self.min:
            time.sleep(self.min - (now - self._last))
        self._last = time.time()


def log(msg: str) -> None:
    print(msg, flush=True)


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
