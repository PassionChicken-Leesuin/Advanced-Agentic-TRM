"""
trmkb.replay — events.jsonl 재생기. 실시간 실행과 기록 재생이 같은 인터페이스로 시각화에 공급된다.

사용:
    for ev in replay(run_dir, speed=20.0): ...      # 기록 간격을 1/20로 압축해 재생
    for ev in replay(run_dir, speed=None): ...      # 지연 없이 순서대로
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

from .schema import Event
from .store import EventLog


def replay(run_dir: str | Path, *, speed: float | None = 10.0,
           max_gap_s: float = 2.0, start_seq: int = 0) -> Iterator[Event]:
    log = EventLog(Path(run_dir) / "events.jsonl")
    prev_ts = None
    for ev in log.read():
        if ev.seq <= start_seq:
            continue
        if speed and prev_ts is not None:
            gap = (ev.ts - prev_ts).total_seconds() / speed
            time.sleep(min(max(gap, 0.0), max_gap_s))
        prev_ts = ev.ts
        yield ev


def tail(run_dir: str | Path, *, poll_s: float = 0.5, start_seq: int = 0) -> Iterator[Event]:
    """실시간 실행 중인 run의 events.jsonl 을 꼬리 추적."""
    path = Path(run_dir) / "events.jsonl"
    seen = start_seq
    while True:
        if path.exists():
            for ev in EventLog(path).read():
                if ev.seq > seen:
                    seen = ev.seq
                    yield ev
        time.sleep(poll_s)
