"""
새 Reader (인용 전용) — 문서를 다시 읽어 로드맵에 쓸 수 있는 문장을 스키마 없이 모두 원문 그대로 인용한다.
  - 분류하지 않는다 (층·종류·구조 판단은 Router 몫). 돌려주는 것은 원문 문장(quote)과 다시 쓴 진술(claim)뿐.
  - 문서 전체를 읽는다 (이전 파이프라인의 문서당 14청크 상한 없음). 상투 문구 청크만 저가 모델이 걸러낸다.
  - 인용은 청크의 실제 부분 문자열인지 확인하고, 찾지 못한 인용은 버린다.
정의: 연구계획/2026-11-01_설계_TRM지식구조5종_Router_생성기.md §4 ①
"""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from pydantic import BaseModel, Field

from ..agents.chunker import chunk_document
from ..agents.reader import TRIAGE_SYSTEM, TRIAGE_USER, Triage, locate_quote
from ..corpus.common import read_doc, resolve_path
from ..llm import LLM
from .store import Passage

MODEL = "anthropic/claude-haiku-5.5"
TRIAGE_MODEL = "openai/gpt-4.1-nano"


class Quote(BaseModel):
    quote: str
    claim: str = ""


class Quotes(BaseModel):
    quotes: list[Quote] = Field(default_factory=list)


SYSTEM = ("You read company documents for a technology-roadmapping knowledge base. You quote; you do not classify. "
          "JSON only.")
USER = """Company: {company}. Document: "{title}" ({date}, {stype}{syn}). Part {i} of {n}.

Text:
\"\"\"{chunk}\"\"\"

Quote EVERY sentence that carries information a technology roadmap of {company} could use: markets, customers and their
needs, competitors, regulation and policy, products and services, milestones, targets and specifications, technical
results and methods, components and suppliers, partners, funding, facilities, people and skills, plans, schedules,
risks and decisions. Include internal details (requirements, lead times, yields, budgets, delays) when they bear on
products, technology or customers.
Skip legal disclaimers and safe-harbor language, generic risk wording that names no specific product, technology or
market, accounting-policy descriptions, statements about the company's stock, financing transactions or internal
controls, navigation text, author bios, reference lists, signatures and pure financial tables.
Rules:
- quote: copy one sentence (or two if they only make sense together) EXACTLY as written: no edits, no ellipses.
- claim: one self-contained sentence restating it. Resolve "we", "it", "this system" to names; keep every number,
  date, unit and name; if the sentence relies on "today" or "this year", anchor it to the document date.
- Do not merge different facts into one quote and do not quote the same fact twice.

Return JSON: {{"quotes": [{{"quote": str, "claim": str}}]}}"""


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()[:220]


class QuoteReader:
    def __init__(self, llm: LLM, model: str = MODEL, triage_model: str | None = TRIAGE_MODEL, chunk_chars: int = 3000,
                 workers: int = 6, company: str = "IonQ"):
        self.llm, self.model, self.triage_model, self.chunk_chars, self.workers = llm, model, triage_model, chunk_chars, workers
        self.company = company

    def _chunk(self, doc: dict, ch, i: int, n: int) -> list[tuple[str, str, int]]:
        if self.triage_model:
            tri = self.llm.structured(self.triage_model, TRIAGE_SYSTEM, TRIAGE_USER.format(
                company=self.company, doc_date=doc["date"], source_type=doc["source_type"], chunk=ch.text[:4000]),
                Triage, purpose="reader2_triage", max_tokens=300)
            if not tri.relevant:
                return []
        out = self.llm.structured(self.model, SYSTEM, USER.format(
            company=self.company, title=doc["title"][:120], date=doc["date"], stype=doc["source_type"],
            syn=", internal document" if doc.get("is_synthetic") else "", i=i, n=n, chunk=ch.text),
            Quotes, purpose="reader2_quote", max_tokens=6000)
        res = []
        for q in out.quotes:
            text, (s, e) = locate_quote(ch, q.quote)
            if s == e or len(text) < 25:      # 원문에서 찾지 못한 인용은 버림
                continue
            res.append((text, q.claim.strip() or text, s))
        return res

    def read(self, doc: dict) -> list[Passage]:
        _, body = read_doc(resolve_path(doc["path"]))
        chunks = chunk_document(body, doc["source_type"], self.chunk_chars, None)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            parts = list(ex.map(lambda x: self._chunk(doc, x[1], x[0] + 1, len(chunks)), enumerate(chunks)))
        seen, out = set(), []
        for part in parts:
            for text, claim, s in part:
                k = _key(text)
                if k in seen:
                    continue
                seen.add(k)
                pid = "ps_" + hashlib.sha1(f"{doc['id']}:{s}:{k[:60]}".encode("utf-8")).hexdigest()[:10]
                out.append(Passage(id=pid, doc_id=doc["id"], doc_date=date.fromisoformat(doc["date"]),
                                   source_type=doc["source_type"], is_synthetic=bool(doc.get("is_synthetic")),
                                   text=text, claim=claim))
        return out
