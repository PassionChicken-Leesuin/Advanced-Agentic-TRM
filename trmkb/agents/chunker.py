"""
문서 → 청크. 문단 경계를 지키며 target_chars 안팎으로 자른다.
SEC 10-K/10-Q 는 Business / Risk Factors / MD&A 절만 뽑고 절마다 상한을 둔다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    idx: int
    text: str
    start: int   # 문서 내 문자 오프셋
    end: int
    section: str | None = None


SEC_SECTIONS = [
    ("business", r"item\s*1\.?\s*\|?\s*business", 40_000),
    ("risk_factors", r"item\s*1a\.?\s*\|?\s*risk\s+factors", 60_000),
    ("mdna", r"item\s*7\.?\s*\|?\s*management[’'`s]*\s+discussion", 50_000),
]


def select_sec_sections(text: str) -> list[tuple[str, int, int]]:
    """(절 이름, start, end). 목차의 항목은 건너뛰기 위해 본문에서 마지막 등장 이전의 '진짜' 헤더(뒤에 긴 본문)를 고른다."""
    low = text.lower()
    out = []
    for name, pat, cap in SEC_SECTIONS:
        best = None
        for m in re.finditer(pat, low):
            nxt = re.search(r"\n\s*item\s*\d+[ab]?\.", low[m.end(): m.end() + 200_000])
            seg_len = nxt.start() if nxt else min(len(low) - m.end(), 200_000)
            if seg_len > 3_000 and (best is None or seg_len > best[1]):
                best = (m.start(), seg_len)
        if best:
            s = best[0]; e = min(s + best[1], s + cap)
            out.append((name, s, e))
    return out


def chunk_text(text: str, target_chars: int = 2200, min_chars: int = 400, section: str | None = None,
               base_offset: int = 0, start_idx: int = 0) -> list[Chunk]:
    paras = [(m.start(), m.end()) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text)]
    chunks: list[Chunk] = []
    buf_s, buf_e = None, None
    idx = start_idx

    def flush():
        nonlocal buf_s, buf_e, idx
        if buf_s is not None and buf_e - buf_s >= min_chars:
            chunks.append(Chunk(idx, text[buf_s:buf_e].strip(), base_offset + buf_s, base_offset + buf_e, section)); idx += 1
        buf_s, buf_e = None, None

    for ps, pe in paras:
        if buf_s is None:
            buf_s, buf_e = ps, pe
        elif pe - buf_s > target_chars:
            flush(); buf_s, buf_e = ps, pe
        else:
            buf_e = pe
        if pe - ps > target_chars * 1.6:   # 거대 문단은 문장 단위로 쪼갬
            flush()
            sent_pos = ps
            for m in re.finditer(r"[^.!?]+[.!?]+(\s|$)", text[ps:pe]):
                s_abs = ps + m.start(); e_abs = ps + m.end()
                if buf_s is None:
                    buf_s, buf_e = s_abs, e_abs
                elif e_abs - buf_s > target_chars:
                    flush(); buf_s, buf_e = s_abs, e_abs
                else:
                    buf_e = e_abs
            flush()
    flush()
    if not chunks and text.strip():
        chunks.append(Chunk(start_idx, text.strip()[:target_chars], base_offset, base_offset + min(len(text), target_chars), section))
    return chunks


def chunk_document(text: str, source_type: str, target_chars: int = 2200, max_chunks: int | None = None) -> list[Chunk]:
    if source_type == "sec_filing":
        secs = select_sec_sections(text)
        chunks: list[Chunk] = []
        if secs:
            for name, s, e in secs:
                chunks += chunk_text(text[s:e], target_chars, section=name, base_offset=s, start_idx=len(chunks))
        else:
            chunks = chunk_text(text[:120_000], target_chars)
    else:
        chunks = chunk_text(text, target_chars)
    if max_chunks and len(chunks) > max_chunks:
        chunks = chunks[:max_chunks]
    return chunks
