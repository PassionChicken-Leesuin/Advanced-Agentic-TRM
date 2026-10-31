"""
시간 표현 정규화 (결정적). Reader가 숫자를 못 주면 이걸로 보완한다.

"2027" → 2027.0–2028.0 | "Q2 2025" → 2025.25–2025.5 | "H2 2025" → 2025.5–2026.0 | "mid-2026" → 2026.4–2026.6
"by 2028" / "by end of 2028" → end 2028.99, start None | "2025-2030" → 2025–2030 | "within 2 years" → relative lag 2
"""
from __future__ import annotations

import re
from datetime import date

from ..schema import TimeExpr, TimeExprKind

_Q = {"1": (0.0, 0.25), "2": (0.25, 0.5), "3": (0.5, 0.75), "4": (0.75, 1.0)}
_H = {"1": (0.0, 0.5), "2": (0.5, 1.0)}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_time(raw: str | None, doc_date: date | None = None) -> TimeExpr:
    if not raw or not raw.strip():
        return TimeExpr.unknown("")
    s = raw.strip()
    low = s.lower()
    m = re.search(r"\b(?:q([1-4])\s*(?:of\s*)?(20\d\d)|(20\d\d)\s*q([1-4]))\b", low)
    if m:
        q, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        a, b = _Q[q]
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=int(y) + a, end=int(y) + b)
    m = re.search(r"\b(?:h([12])\s*(20\d\d)|(20\d\d)\s*h([12])|(first|second)\s+half\s+(?:of\s+)?(20\d\d))\b", low)
    if m:
        if m.group(5):
            h, y = ("1" if m.group(5) == "first" else "2"), m.group(6)
        else:
            h, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        a, b = _H[h]
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=int(y) + a, end=int(y) + b)
    m = re.search(r"\b(early|mid|late|end of|end-)\s*-?\s*(20\d\d)\b", low)
    if m:
        y = int(m.group(2)); w = m.group(1)
        rng = {"early": (0.0, 0.33), "mid": (0.4, 0.6), "late": (0.67, 1.0), "end of": (0.9, 1.0), "end-": (0.9, 1.0)}[w]
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=y + rng[0], end=y + rng[1])
    m = re.search(r"\b(20\d\d)\s*[-–to]+\s*(20\d\d)\b", low)
    if m:
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=float(m.group(1)), end=float(m.group(2)) + 1.0)
    m = re.search(r"\b(?:by|before|no later than|until)\s+(?:the\s+)?(?:end\s+of\s+)?(20\d\d)\b", low)
    if m:
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=None, end=int(m.group(1)) + 0.99)
    m = re.search(r"\b(" + "|".join(_MONTHS) + r")[a-z]*\.?\s+(20\d\d)\b", low)
    if m:
        y = int(m.group(2)); mo = _MONTHS[m.group(1)]
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=y + mo / 12, end=y + (mo + 1) / 12)
    m = re.search(r"\b(20\d\d)\b", low)
    if m:
        y = int(m.group(1))
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=float(y), end=y + 1.0)
    # 연도 없는 분기/반기 → 문서 연도 (이미 지난 분기면 다음 해)
    m = re.search(r"\b(?:q([1-4])|h([12]))\b", low)
    if m and doc_date and not re.search(r"20\d\d", low):
        if m.group(1):
            a, b = _Q[m.group(1)]
        else:
            a, b = _H[m.group(2)]
        y = doc_date.year
        if (doc_date.month - 1) / 12 > b:
            y += 1
        return TimeExpr(raw=s, kind=TimeExprKind.ABSOLUTE, start=y + a, end=y + b)
    m = re.search(r"\b(?:within|in|over the next|next)\s+(\d+(?:\.\d+)?)\s*(year|month|week)s?\b", low)
    if m:
        n = float(m.group(1)); unit = m.group(2)
        lag = n if unit == "year" else n / 12 if unit == "month" else n / 52
        te = TimeExpr(raw=s, kind=TimeExprKind.RELATIVE, lag_years=round(lag, 2))
        if doc_date:
            base = doc_date.year + (doc_date.month - 1) / 12
            te.start, te.end = base, base + lag
        return te
    m = re.search(r"\b(short|medium|near|mid|long)[\s-]*term\b", low)
    if m:
        band = {"short": "short", "near": "short", "medium": "medium", "mid": "medium", "long": "long"}[m.group(1)]
        te = TimeExpr(raw=s, kind=TimeExprKind.BAND)
        if doc_date:
            y = doc_date.year
            te.start, te.end = {"short": (y, y + 2), "medium": (y + 2, y + 5), "long": (y + 5, y + 10)}[band]
        return te
    return TimeExpr.unknown(s)
