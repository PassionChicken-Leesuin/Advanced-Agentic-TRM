"""run 프로필 — 지식베이스가 어느 회사·어느 시점의 문서로 만들어지는지 (업로드 모드에서 IonQ 와 분리).

runs/<run>/profile.json 이 있으면 그 값을, 없으면 IonQ 데모 기본값을 쓴다. 프롬프트의 "Company: ..." 줄, 생성기의 기업 소개(brief),
지식 기준일(cutoff)·로드맵 기간(horizon)이 모두 여기서 나온다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..roadmap import generate as G

DEFAULT: dict = {
    "company": G.COMPANY,
    "descriptor": "trapped-ion quantum computing",      # 회사 한 줄 설명 (용어집 프롬프트에 쓰임)
    "aliases": ["IonQ, Inc.", "the Company"],
    "cutoff": "2024-12-31",                               # 문서 기준일 (이 날 이후 지식은 쓰지 않음)
    "horizon": list(G.HORIZON),                           # 로드맵 기간 (십진 연도)
    "brief": G.BRIEF,                                     # 생성기에 주는 기업 소개 (두 조건에 동일)
    "source": "demo",                                     # demo | upload
}


def load(run_dir: str | Path) -> dict:
    p = Path(run_dir) / "profile.json"
    prof = dict(DEFAULT)
    if p.exists():
        prof.update(json.loads(p.read_text(encoding="utf-8")))
    prof["horizon"] = [float(prof["horizon"][0]), float(prof["horizon"][1])]
    return prof


def save(run_dir: str | Path, prof: dict) -> Path:
    p = Path(run_dir) / "profile.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def for_upload(company: str, dates: list[str], *, descriptor: str = "", brief: str = "", cutoff: str | None = None) -> dict:
    """업로드 문서용 프로필: 기준일 = 가장 늦은 문서 날짜(또는 지정값), 기간 = 기준일 다음 해부터 5년."""
    cut = cutoff or (max(dates) if dates else DEFAULT["cutoff"])
    y = int(cut[:4])
    return {"company": company.strip(), "descriptor": descriptor.strip(), "aliases": [f"{company.strip()}, Inc.", "the Company"],
            "cutoff": cut, "horizon": [float(y + 1), float(y + 6)],
            "brief": brief.strip() or f"{company.strip()} is the company whose documents form the knowledge base. No other background is given: rely on the knowledge base context.",
            "source": "upload"}


def slug(s: str, maxlen: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:maxlen] or "company"


def cutoff_year(prof: dict) -> int:
    return int(str(prof["cutoff"])[:4])
