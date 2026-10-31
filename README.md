# trmkb — TRM 특화 KB 자율구축 에이전트 시스템 (IonQ 데모)

계획: `../연구계획/2026-10-31_구현계획_QuantumKB_Demo.md`
지식 단위 근거: `../연구계획/2026-10-31_분석_Cambridge양자로드맵_지식단위.md`

## 구조

```
trmkb/
  schema.py     노드 10종 · 주장 7종 · 엣지 11종 · 이벤트 · 로드맵 · 심은 사실 (pydantic)
  store.py      JSONL KB 저장소 + append-only 이벤트 로그
  llm.py        OpenRouter 클라이언트 (키 로테이션, 구조화 출력, 비용 집계)
  replay.py     events.jsonl 재생 / 꼬리 추적
  i18n.py       화면 라벨 (ko 기본, en 전환 예정)
  agents/       (P4) reader, router, linker, critic, timing, summarizer
  roadmap/      (P3·P6) generate, retrieve(연산 ①~⑤), diff
  eval/         (P7) metrics
data/corpus/{public,synthetic}/   문서 md
data/facts_ledger.json            가상 자료의 심은 사실
runs/<run_id>/                    kb/, events.jsonl, router_log.jsonl, roadmap_*.json
viz/                              (P5) FastAPI SSE + D3
```

## 실행

```powershell
$env:PYTHONUTF8 = "1"
python -m pytest -q
```

.env 에 `Open_Router_key1..N` 이 있어야 LLM 호출이 된다 (테스트는 네트워크 없이 통과).

## 핵심 규약

- 주장(claim)은 노드에 **발언 시점 순으로 쌓이고 덮어쓰지 않는다**. 같은 노드에서 측도가 바뀌면 지표 교체다.
- 엣지는 근거 id와 Critic 판정을 반드시 가진다. `neighbors()` 기본값은 수락된 엣지만 본다.
- `events.jsonl` 이 시각화·재생·평가의 단일 소스다. 모든 상태 변화는 이벤트를 남긴다.
- 시간은 `TimeExpr` 로 받는다 (원문 + 유형 + 정규화 연도).
