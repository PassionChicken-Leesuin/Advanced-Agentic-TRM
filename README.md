# trmkb — TRM 특화 KB 자율구축 에이전트 시스템 (IonQ 데모)

> **주의 / Disclaimer.** 이 저장소는 서울대 DDSI Lab의 연구용 데모입니다. 대상 기업 IonQ의 **공개 자료**(SEC 공시, 보도자료, arXiv, 블로그)와 함께
> **LLM이 생성한 허구의 내부 문서** 50건(`data/corpus/synthetic_data/text/`)을 투입합니다. 가상 문서와 그로부터 만들어진 지식베이스·로드맵 안의 내부 수치,
> 고객명, 공급사명, 의사결정은 모두 실제가 아닙니다. IonQ와는 무관하며, IonQ의 입장이나 계획을 대변하지 않습니다.
> This is a research demo. Synthetic internal documents and everything derived from them are fictional and unaffiliated with IonQ.

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
  corpus/       (P2) common(frontmatter·index), edgar(SEC 공시), arxiv, ionq_web(블로그·리소스), synth(가상 내부자료)
  agents/       (P4) chunker, embed, timeparse, reader(2단), router, linker, critic, timing(CPM), summarizer
  pipeline.py   (P4) 문서 1건 = 1 에피소드 오케스트레이션, 재개 가능, events.jsonl 기록
  roadmap/      (P3·P6) generate, retrieve(연산 ①~⑤), diff
  eval/         (P7) recovery(심은 사실 회수율·모순 탐지율)
data/corpus/real_data/            공개 자료 259건: originals/(원본 파일, 로컬 전용) + text/(정규화 md) — real_data/README.md
data/corpus/synthetic_data/       가상 내부자료 50건: text/(생성 원문 그 자체) — synthetic_data/README.md
data/ground_truth/                공식 로드맵 정답표 + originals/(2020-12·2025-06 로드맵 1차 원본) — ground_truth/README.md
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

### 코퍼스 (P2)

```powershell
python scripts/collect_public.py all            # EDGAR(10-K/10-Q/8-K EX-99/425/DEFA14A) + arXiv(all:IonQ) + ionq.com(blog/resources), cutoff 2024-12-31
python scripts/gen_synthetic.py plan            # 심은 사실 → 문서 배정 계획 (LLM 없음)
python scripts/gen_synthetic.py gen             # 가상 내부자료 50건 생성 (기본 anthropic/claude-sonnet-4.6, 약 $1)
```

- 문서는 `data/corpus/real_data/text/<id>.md`, `data/corpus/synthetic_data/text/<id>.md` + YAML frontmatter, 색인은 `data/corpus/index.jsonl`. 원본 파일은 `python scripts/fetch_originals.py` → `real_data/originals/`.
- 심은 사실 원장 `data/facts_ledger.json`: 42건, `not_before/not_after` 날짜 창, `contradicts` 모순 쌍 3개(pf07↔pf08, pf20↔pf21, pf02↔pf41), 생성 후 `planted_in_doc_ids` 역기록.
- 공개 코퍼스 원본(md)은 용량 때문에 git에 넣지 않는다. 재현은 위 명령으로.

### KB 구축 (P4)

```powershell
python scripts/run_pipeline.py --run runs/pilotA --pilot --config A      # 20건 파일럿 (가상 10 + 공개 10)
python scripts/run_pipeline.py --run runs/full --select priority --limit 180
python scripts/eval_run.py recovery --run runs/pilotA                     # 심은 사실 회수율
python scripts/eval_run.py compare runs/pilotA runs/pilotB
python -m uvicorn viz.server:app --port 8765                              # 시각화 (?run=pilotA&autoplay=1)
```

에피소드 순서: Reader(triage→extract) → Router(병합/신규, 구조 선택, router_log) → Critic(모순) → Linker → Critic(층 규칙·근거) → Timing(ES/LS, infeasible) → Summarizer(dirty 행만).
설정 A: gpt-4.1-nano triage / gpt-4.1-mini reader·router·linker·summarizer / claude-sonnet-4.6 critic. B: haiku-5.5 제안자 / gpt-4.1 critic.

### 화면 보기 (P5)

**온라인 (GitHub Pages, 서버 불필요)** — 저장소 Settings → Pages → *Deploy from a branch* → `main` / `/docs` 를 한 번 켜 두면 아래 주소가 열린다.

| 화면 | 주소 |
|---|---|
| 2막 KB 구축 재생 (파일럿 D) | https://passionchicken-leesuin.github.io/Advanced-Agentic-TRM/site/?run=pilotD&autoplay=1&speed=20 |
| 1막·3막 로드맵 diff (파일럿 D) | https://passionchicken-leesuin.github.io/Advanced-Agentic-TRM/site/?run=pilotD&view=rm |
| 전체 실행 (180건) | 위 주소에서 `run=full` (전체 실행 완료 후 내보냄) |

내보내기: `python scripts/export_static.py runs/pilotD runs/full` → `docs/site/` (이벤트·스냅샷·로드맵 JSON + 서버 없이 재생하는 index.html). 실시간 추적(follow)만 서버 모드 전용.

**로컬 (실시간 추적 포함)**

```powershell
python -m uvicorn viz.server:app --port 8765              # 이 PC에서만
python -m uvicorn viz.server:app --port 8765 --host 0.0.0.0   # 같은 네트워크의 다른 PC에서 http://<이 PC IP>:8765
```

- `http://127.0.0.1:8765/?run=full&autoplay=1&speed=0&follow=1` — 즉시 현재 상태 적용 후 실시간 추적
- `?speed=20` 기록 재생(20배속), `?view=rm` 로드맵 diff, `?lang=en` 영어 라벨

## 핵심 규약

- 주장(claim)은 노드에 **발언 시점 순으로 쌓이고 덮어쓰지 않는다**. 같은 노드에서 측도가 바뀌면 지표 교체다.
- 엣지는 근거 id와 Critic 판정을 반드시 가진다. `neighbors()` 기본값은 수락된 엣지만 본다.
- `events.jsonl` 이 시각화·재생·평가의 단일 소스다. 모든 상태 변화는 이벤트를 남긴다.
- 시간은 `TimeExpr` 로 받는다 (원문 + 유형 + 정규화 연도).
