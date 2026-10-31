# Quantum 기업 KB 자율구축 데모 — 구현 계획

작성: 2026-10-31. 대상: `연구계획/CambridgeDemo.png` 3막 구성을 실제로 돌아가는 시스템으로 구현.
전제: 결과물은 KB가 아니라 **KB를 자율 구축하는 Agentic System**(Reader→Router→Linker→Critic). KB와 로드맵은 그 산출물.

---

## 0. 데모가 보여줘야 하는 것 (3막)

| 막 | 화면 | 입력 | 산출 |
|---|---|---|---|
| ① Initial Roadmap | why/what/how × 단·중·장기 격자 | 기업 한 줄 소개 + 동일 프롬프트, KB 없음 | `roadmap_initial.json` |
| ② KB가 자라는 장면 | 3레인(why/what/how) × 시간축 그래프, 우측 에이전트 패널, 문서 진행바 | 기업 자료 N건을 순서대로 투입 | `kb/` + `events.jsonl` |
| ③ 달라진 로드맵 | 같은 격자에 Gantt + 근거 배지 + Critic 플래그, ①과의 diff 하이라이트 | ②의 KB를 검색해 같은 프롬프트로 재생성 | `roadmap_advanced.json` + diff |

핵심 메시지: "같은 LLM, 같은 프롬프트인데 **에이전트가 구조화해 쌓은 지식** 때문에 로드맵이 근거 있는 것으로 바뀐다." 그래서 ①과 ③은 모델·프롬프트·출력 스키마를 완전히 고정하고 KB 유무만 바꾼다.

---

## 1. 결정 사항 (사용자 확정 필요)

### 1.1 기업 선정 — 추천: **IonQ** (대안: Quantinuum, Rigetti)

| 후보 | 공개 자료 | 공식 로드맵(정답 대조용) | 비고 |
|---|---|---|---|
| **IonQ** (NYSE: IONQ) | 10-K/10-Q 연 4건+, 보도자료 연 50건+, arXiv 논문(IonQ 저자) 수십 편, 특허, 투자자 설명회 | 2020년 발표 로드맵(~2028, #AQ 지표) → 2024·2025 갱신판. 시점이 명시된 마일스톤이 있어 **시점 오차 측정 가능** | 2025년 인수 다수(Oxford Ionics, Lightsynq, Qubitekk, ID Quantique, Capella) → why/what/how 전 층에 사건이 풍부 |
| Quantinuum | 보도자료·논문 많음, 비상장이라 재무공시 없음 | 2024 로드맵(Helios 2025 → Sol 2027 → Apollo 2029) | 로드맵이 선명하나 시장(why) 자료가 얇음 |
| Rigetti (NASDAQ: RGTI) | 10-K, 보도자료 | 2024 로드맵(36→100→336 큐비트) | 규모가 작아 코퍼스가 적음 |
| D-Wave | 10-K 등 | 어닐링 중심이라 게이트형 산업 트렌드와 어긋남 | 제외 권장 |

IonQ 추천 이유: (a) 상장사라 **시간이 찍힌 1차 자료**가 가장 많고, (b) 공식 로드맵이 수치·연도로 되어 있어 ③의 정량 비교가 되며, (c) 인수·협력·규제(수출통제) 등 why 층 자료가 있어 3레인이 모두 찬다.

### 1.2 코퍼스 구성 — 실제 자료 + 가상 내부자료 혼합

| 구분 | 출처 | 건수(안) | 역할 |
|---|---|---|---|
| 공개 1차 | 10-K/10-Q, 보도자료, 투자자 발표, 공식 로드맵 블로그 | 60–80 | why/what 층, 시점 |
| 공개 기술 | arXiv(IonQ 저자), 특허 초록 | 40–60 | how 층 |
| 산업 맥락 | Cambridge Quantum Technology Roadmap Report(폴더 보유), McKinsey Quantum Monitor, 정부 전략 요약 | 5–10 | why 층 전역 트렌드 |
| **가상 내부자료** | LLM으로 생성: 회의록, R&D 주간보고, 고객 요청 메일, 공급사 메일, 내부 기술평가서 | 40–60 | "기업 내부 자료가 들어온다"를 재현. **심은 사실(planted facts) 원장**을 따로 두어 KB가 그것을 회수했는지 측정 |
| 합계 | | 150–200 | 데모 그림의 "문서 137/200"과 일치 |

가상 자료 생성 규칙: 심을 사실을 먼저 `facts_ledger.json`에 적고(예: "2027 Q2 광자 인터커넥트 시제품", "고객 X가 오류율 요구"), 그 사실을 문서 2–3건에 분산·일부는 서로 모순되게 넣는다. 모순은 Critic이 잡아야 할 장면이 된다.

### 1.3 시간 설정
- **코퍼스 cutoff**: 2024-12-31. 그 이전 문서만 투입.
- **로드맵 지평**: 2025–2030.
- **정답**: IonQ 공식 로드맵 3판을 모두 수집해 쓴다 (2026-10-31 검색으로 확인).
  - 2020-12 초판(SPAC 상장기 투자자 자료, EDGAR dMY III S-4·보도자료): #AQ 지표, 2025 #AQ 64 → 2028 #AQ 1,024, 물리큐비트 2026 ~4,000 / 2028 ~32,000.
  - 2023 갱신(AQ 로드맵 조정), 2025-06 "Accelerated Roadmap"(Oxford Ionics 인수 후): 지표를 #AQ에서 **물리/논리 큐비트**로 교체. 2026 256큐비트 99.99% → 2027 10,000물리/800논리 → 2028 20,000물리(2칩 연결) → 2030 200만 물리/8만 논리. #AQ 64는 2025년 Tempo에서 조기 달성.
  - 주의: 판마다 **지표가 바뀌므로** 정렬은 숫자가 아니라 마일스톤·역량 단위(모듈화, 포토닉 인터커넥트, 오류정정 시연 등)로 한다. cutoff(2024-12-31) 기준 ①·③이 2025-06 갱신판의 변화(지표 교체·인수 기반 가속)를 예측했는지가 가장 흥미로운 비교점.
  - 모델의 사전지식 오염은 Jansen 2026 방식으로 cutoff 전후 구간을 나눠 보고.

### 1.4 모델
- 제안자(Reader/Linker/로드맵 생성)와 Critic은 **다른 모델**로 분리(연구구상 §7). OpenRouter 경유. 임베딩은 로컬 sentence-transformers(설치됨)로 비용 0.
- 후보: 제안자 = 중급 모델(비용), Critic = 상위 모델. 최종 선택은 1차 20문서 파일럿 비용을 보고 확정.

---

## 2. 시스템 구조

```
docs/ ──▶ Reader ──▶ Router ──▶ [KB 4구조] ◀── Linker ◀── Critic
                        │                         │
                        └──── events.jsonl ◀──────┘   ──▶ Timing(ES/LS 재계산)
                                   │
                                   ▼
                          Live Viz (SSE) ── 2막
roadmap_prompt + (KB 검색 | 없음) ──▶ Generator ──▶ roadmap_{initial,advanced}.json ──▶ Diff Viz ── 1·3막
```

### 2.1 에이전트 역할 (ReAct, 문서 1건 = 1 에피소드)

| 에이전트 | 입력 | 판단 | 출력 → 이벤트 |
|---|---|---|---|
| **Reader** | 문서 청크 | 후보 노드(라벨, 층 why/what/how, 시간 단서, 성숙도)·근거 문장 추출. EDC(2024) 3단계 중 Extract | `node.proposed`, `evidence.added` |
| **Router** | 후보 노드 + 기존 KB 요약 | 기존 노드와 병합(canonicalize)인지 신규인지, 어느 구조에 쓸지(①근거청크 / ②계층요약 갱신 / ③④그래프 / ⑤시간인덱스). Mem-α의 "어디에 어떤 연산으로" 결정 | `node.merged` / `node.created` / `summary.updated` / `time.indexed` |
| **Linker** | 신규·갱신 노드 + 이웃 | enables / requires / precedes 후보 엣지 + 논증 스킴 태그(0918 Walton) | `edge.proposed` |
| **Critic** | 제안 엣지·노드 + 근거 | 근거 충분성·모순·층 위반(why→how 직결 등) 판정 → 수락/반려/보류 | `edge.accepted` / `edge.rejected(reason)` / `conflict.flagged` |
| **Timing** | 수락된 precedes/requires | ES/LS 증분 재계산(CPM) | `time.recomputed` |

Router가 연구의 핵심 변수이므로 **Router 판단 로그**(어느 구조에 왜 썼는지)를 별도로 남긴다.

### 2.1-b 지식 단위와 구축 원칙 (2026-10-31 추가 — §1.3 역량 표가 KB에서 나오게 하는 조건)

§2.1의 "후보 노드 추출"은 엔티티 추출에 머물면 안 된다. 로드맵의 칸 하나는 트리플이 아니라 **주장**이므로 아래 5원칙을 따른다.

| # | 원칙 | 담당 | 표의 어느 축을 지탱하나 | 빼면(ablation) |
|---|---|---|---|---|
| 1 | 지식 단위 = **역량 주장(capability claim)**: {actor, capability, measure, value, target_time, modality(plan/achieved/requirement/forecast), doc_date, evidence} | Reader | 칸(수치+한정어) | 키워드 엔티티만 남음 |
| 2 | 주장을 **역량 행(capability node)** 에 정규화: 병합 / 신규 / 근거청크로만 보류. 범주는 TRM 시드(규모·충실도·오류정정·모듈화·제어·제조·상업화) + Router 제안·Critic 승인으로 성장 | Router | 행 | 키워드 더미 |
| 3 | 같은 역량의 주장은 **발언 시점 순 타임라인으로 보존**, 덮어쓰지 않음. 측도(measure) 변화가 곧 "지표 교체" 탐지 | Router/Store | 열(시간)·트렌드 ② | 최신 주장만 남아 궤적·지표교체 소실 |
| 4 | 층간 링크(enables/requires/precedes)는 **근거 문서 ≥1** 있어야 수락, why→how 직결은 층 위반으로 반려 | Linker/Critic | 행 사이의 이유 ④ | 행은 있으나 근거 사슬 없음 |
| 5 | **역량 행 단위 계층 요약**을 해당 행이 바뀔 때만 증분 갱신 | Summarizer(Router 호출) | Generator 입력 | 평면 RAG로 퇴화 |

생성(③) 검색은 top-k 청크가 아니라 **행 단위 구조화 컨텍스트**(요약 + 주장 타임라인 + 수락 엣지 + 근거 ID)이고, Generator는 행 단위로 격자를 채운다. 기회 생성은 why는 있는데 what이 없는 행, what은 있는데 how가 없는 행을 찾는다.

**개정 예고(2026-10-31)**: Cambridge 양자 로드맵 보고서 분석(`2026-10-31_분석_Cambridge양자로드맵_지식단위.md`) 결과, 지식 단위를 "역량 주장" 1종에서 **노드 10종(driver/need/vision/opportunity/milestone/capability/component/enabler/actor/issue) + 주장 7종(spec/capability_claim/market_size/maturity/priority/comparison/action) + 관계 11종**으로 확장한다. Reader는 2단 추출(층·유형 분류 → 유형별 슬롯), 보고서의 Current/Short/Medium/Long/Vision × 시장·제품·기술 격자를 체크리스트로 사용. 상세는 분석 문서 §5.

미결(파일럿 20건에서 확정): 주장 입도(문장 1 = 주장 1?), 모순 주장 처리(현 방침: 둘 다 보존 + conflict 플래그 → 대안 경로 표현에 유리), 양태를 노드 속성으로(현 방침).

### 2.2 KB 저장 스키마 (연구구상 §4.2 공통 뼈대의 구현)

평문 JSONL + 마크다운(naite처럼 git에 그대로 들어가는 형태). DB 없음.

```
kb/
  nodes.jsonl        # 역량 노드 {id, label, layer: why|what|how, category, desc, es, ls, maturity, confidence, created_by_doc, updated}
  claims.jsonl       # 역량 주장 {id, node_id, actor, measure, value, target_time, modality, doc_id, doc_date, evidence_id}  ← 타임라인(원칙 3)
  edges.jsonl        # {id, src, dst, type: enables|requires|precedes, scheme, critic: accepted|rejected|pending, reason, evidence_ids}
  evidence/          # {id, doc_id, chunk, span, node_ids, edge_ids}  ← ① 근거 부착
  summaries/         # 층별·군집별 계층 요약 md (② RAPTOR식, 갱신 이력 포함)
  time_index.json    # 연도·분기 → 노드 id (⑤)
  candidates.jsonl   # Linker가 낸 결측 링크 후보 + 점수 (③)
events.jsonl         # append-only, 시각화와 재생의 단일 소스 (naite rings.md 역할)
router_log.jsonl     # Router 판단 근거
facts_ledger.json    # 가상 자료에 심은 사실 (평가용)
```

이 스키마는 S4(제안 구조). 데모에서는 S4만 쓰고, 본 실험의 S0~S3는 같은 events에서 구조를 빼는 방식으로 뒤에 붙인다.

### 2.3 시각화 (2막) — naite 그래프뷰 참고

- **기술**: FastAPI가 `events.jsonl`을 SSE로 흘리고, 단일 HTML + D3 force 그래프가 받아 그린다. 빌드 도구 없음.
- **배치**: naite식 force layout을 쓰되 **y축은 층(why/what/how 3레인)으로 고정, x축은 ES가 있으면 시간축에 고정**, 없으면 force에 맡김. 데모 그림 ②와 동일.
- **애니메이션**: 노드 생성(페이드인) → Linker 점선 → Critic 수락(실선)/반려(붉은 X + 사유 툴팁) → 근거 배지 숫자 증가.
- **우측 패널**: 에이전트 5종 상태등 + 마지막 행동 한 줄 + 문서 진행바(137/200).
- **재생 제어**: 실시간 실행 / 기록 재생(속도 조절). 발표 때는 기록 재생을 쓴다(API 지연·실패 차단).
- naite 데스크톱 앱 자체는 폐쇄 앱이라 코드를 가져오진 못하고, Obsidian 호환 마크다운 + wikilink 관행만 차용. 필요하면 `kb/`를 Obsidian vault로도 열리게 노드마다 md 1장을 같이 쓴다(선택).

### 2.3-b KB 사용 설계 — 출력 ← 연산 ← 구조 (2026-10-31 추가)

연구는 "뽑을 것 → 그것을 위해 KB를 이렇게 구축 → 그 구조를 이 연산으로 사용 → 출력"의 한 사슬이다(연구구상 §5.2의 S → probe → Q). 구축(§2.1)과 출력(§2.4) 사이의 **연산 집합**을 명시한다.

| 뽑을 출력 (Cambridge 분석 §1의 다섯 묶음) | KB 연산 (사용) | 요구 구조 (구축) | 구현 | 없으면 |
|---|---|---|---|---|
| 근거 붙은 why/what/how 항목 | ① 노드→근거 조회 | evidence_ids | 코드 | 출처 없는 항목 |
| 행별 트렌드·지표 교체 | ② 역량 행 타임라인 요약 | claims 타임라인 + 범주 노드 | LLM | 최신 주장만 남음 |
| 행 사이 이유(why→what→how) | ④ 층 횡단 경로 탐색·설명 | 타입 있는 층간 엣지 + 근거 | 코드(탐색) + LLM(설명) | 연결 없는 행 |
| 마일스톤 배치·순서 | ⑤ precedes+lag CPM, TRL | 시간 속성, precedes, 단계 | 코드 | 임의 시점 |
| 기회·공백 | ③ 구조적 공백 탐색(why有what無, what有how無, open_question) | 층 타입 + 계층 + issue 노드 | 코드(탐색) + LLM(제안) | 기회 생성 불가 |
| 위험·장벽·대안 경로 | issue 순회(threatens, decided_over) | issue 노드, 조건부 엣지 | 코드 | 낙관적 단일 경로 |
| 우선순위 | 링크 차수 + 언급 빈도 + 투입 자본 | 그래프 + claims | 코드 | 전 항목 동등 |

- Generator는 ①→②→④→⑤→③ 순으로 연산을 호출해 격자를 채운다(Kostoff 절차: 노드 식별→속성→링크→링크 속성). 검색은 top-k 청크가 아니라 이 연산 결과다.
- ①④⑤는 결정적 그래프 연산(코드), ②③만 LLM. 구조 효과와 프롬프트 효과를 분리하기 위함.
- S0(평면 RAG)는 top-k만 지원하므로 ②~⑤를 걸 수 없음 → 출력의 어느 요소가 결손되는지 예측 가능. 이것이 ablation의 논리.
- 3막 화면: 로드맵 요소마다 "어느 연산이 만들었는가" 배지 → KB 효과 분해 표시.

### 2.4 로드맵 생성 (1·3막)

- 출력 스키마 고정: `{nodes:[{id,label,layer,start,end,evidence_ids[]}], edges:[{src,dst,type}]}` — KB 스키마의 부분집합.
- ① 조건: 프롬프트 + 기업 소개 1문단. ③ 조건: 프롬프트 + KB 검색 결과(층별 요약 + 관련 노드·엣지·근거). 생성 모델·온도·프롬프트 동일.
- Diff: 라벨 임베딩 + LLM 정렬로 ①↔③ 노드를 Jansen 5범주(동일/세분/통합/신규/삭제)로 매칭. 3막 화면에서 신규=진한색, 변경=테두리, 삭제=회색, 근거 배지, Critic infeasible 플래그.

---

## 3. 평가 (데모용 경량 지표)

| 지표 | 측정 | 답하는 질문 |
|---|---|---|
| 심은 사실 회수율 | facts_ledger 중 KB 노드·엣지로 등장한 비율 | 에이전트가 내부 자료를 제대로 축적했나 |
| 근거 부착률 | ③ 로드맵 노드 중 evidence_id가 있는 비율 (①은 0) | 로드맵이 근거 있는가 |
| 공식 로드맵 정렬 | ①·③ 각각 IonQ 공식 마일스톤과 노드 recall / 시점 MAE(연) | KB가 정확도를 올렸나 |
| 모순 탐지 | 심은 모순 중 Critic이 flag한 비율 | Critic이 일하나 |
| Router 분포 | 구조별 쓰기 건수, 병합 vs 신규 비율 | 어느 구조가 실제로 쓰이나 (본 실험의 예비 데이터) |
| 비용 | 문서당 토큰·달러, 전체 소요시간 | 본 실험 규모 추정 |

---

## 4. 단계와 순서

| 단계 | 할 일 | 산출물 | 의존 |
|---|---|---|---|
| **P0 확정** | 기업, 코퍼스 비율, cutoff, 모델 2종 | 이 문서 §1 체크 | 사용자 |
| **P1 스키마·골격** ✅ 2026-10-31 | pydantic 모델(노드 10·주장 7·엣지 11·이벤트·로드맵·심은 사실), kb/ JSONL 저장소, events 기록기, OpenRouter 클라이언트(키 20개 로테이션·구조화 출력·비용 집계), 재생기, i18n | `Code/trmkb/` 패키지, 테스트 11개 통과, smoke 호출 확인 | 완료 |
| **P2 코퍼스** ✅ 2026-10-31 | 공개 259건(EDGAR 104: 10-K 6·10-Q 13·8-K EX-99 42·425/DEFA14A 45 / arXiv 80 / ionq.com 블로그·리소스 75, 2020-12 로드맵 원문 포함) + 가상 50건(회의록 14·R&D 14·고객메일 8·공급사메일 7·기술평가 7, claude-sonnet-4.6, $1.4). facts_ledger 42건(날짜 창, 모순 3쌍), 사실당 2~3문서. 공개 원문은 git 제외(재수집 가능) | `Code/data/corpus/`, `facts_ledger.json`, manifests | 완료. P4에서는 2021 SPAC 통신문 45건 등 저가치 문서를 제외한 부분집합 사용 예정 |
| **P3 Initial roadmap** ✅ 2026-10-31 | `trmkb/roadmap/generate.py`: 고정 프롬프트(기업 소개 2024-12 기준·지평 2025–2030·층 안내·출력 스키마) + context 블록만 가변, prompt_hash로 동일성 증명. 모델 **openai/gpt-4.1**(cutoff 2024-06 → 2025-06 가속 로드맵 모름). ① 생성: 30노드(why5/what8/how9/resource8)·71엣지·근거 0·$0.035. 내용은 예상대로 일반적("AQ 64 target 2026–2028" 등 수치 없음) | `data/roadmaps/roadmap_initial_gpt-4.1_2026-10-31.json` | 완료 |
| **P4 에이전트** ✅ 코드 2026-10-31 | `trmkb/agents/` + `pipeline.py`. Reader 2단(nano 트리아지 → 유형별 슬롯 추출, 청크 병렬) → Router(MiniLM 유사도 ≥0.80 병합·0.65–0.80 LLM·<0.65 신규, router_log) → Critic 모순 → Linker(층 규칙) → Critic(결정적 층 위반 + LLM 근거 판정) → Timing(ES/LS 전파, infeasible) → Summarizer(3문서마다 dirty 행). 다음 문서 Reader 프리페치. **파일럿 20건 × 설정 A/B/D**: D 선정(Reader haiku-5.5 / Router·Linker·Summarizer gpt-4.1-mini / Critic sonnet-4.6) — 오류 0, 심은 사실 회수율 엄격 89%·관대 100%, 수락 링크 133, 수치 주장 35, $0.032/문서, 약 100초/문서(최적화 전). 첫 파일럿 17% → 수정(트리아지 recall, JSON 복구, 수치 보존, node_type 추정) 후 89% | `runs/pilot*/`, `eval_recovery.json` | 전량 실행은 우선순위 부분집합 ~180건 |
| **P5 라이브 시각화** ✅ 2026-10-31 | `viz/server.py`(runs·snapshot·events·SSE 재생/실시간 추적·roadmaps·i18n) + `viz/static/index.html`(D3: why/what/how/resource/cross 5레인 × 시간축, 수락/제안/반려 링크, 모순 링, 에이전트 6종 상태등·마지막 행동, 진행바, 로그, 로드맵 Gantt 뷰(produced_by 색·근거 배지·infeasible 테두리), URL 파라미터로 자동재생). 데모 run(`scripts/demo_run.py`, LLM 없음)으로 검증, 스크린샷 `Code/docs/screenshots/` | `Code/viz/`, `runs/demo/` | 완료. 실행: `python -m uvicorn viz.server:app --port 8765` |
| **P6 Advanced + diff** ✅ 코드 2026-10-31 | `roadmap/retrieve.py`: 연산 ①~⑦ 결정적 컨텍스트(행 요약·측도 변화, 노드+주장+근거 id, 수락 링크·why→what→how 사슬, precedes·infeasible, 구조적 공백, 이슈; id→연산 매핑으로 produced_by 태깅). `roadmap/diff.py`: 임베딩+LLM 정렬 same/refined/generalized/new/dropped + 시점 이동. 3막 화면 diff 색상. pilotD 검증: advanced 36노드(근거 33) vs initial 30 → 신규 23(전부 근거)·세분화 8·탈락 17 | `roadmap_advanced.json`, `roadmap_diff.json` | 전체 run 결과로 재생성 예정 |
| **P7 평가** 🔄 | 회수율·모순 탐지(`eval/recovery.py`) ✅, 공식 로드맵 정렬(`eval/alignment.py` + `data/ground_truth/ionq_roadmap_milestones.json` 19건, 2020판 9·2025판 10; recall 엄격/관대·2025판 전용=선견·연도 MAE) ✅. 전체 run(180건, 설정 D) 2026-10-31 저녁 실행 중. 남은 것: 전체 run 지표표, 재생 녹화, Cambridge docx 데모 절 | `eval_*.json` | 전체 run 완료 후 |

병렬 가능: P1 → (P2 ‖ P3 ‖ P5 골격) → P4 → P6 → P7.

---

## 5. 폴더·기술 스택

```
Code/
  .env                      # OpenRouter 키 (있음)
  trmkb/                    # 패키지
    schema.py               # pydantic: Node, Edge, Evidence, Event, Roadmap
    store.py                # kb/ 읽기쓰기, events append
    llm.py                  # OpenRouter 클라이언트, 키 로테이션, 비용 집계
    agents/{reader,router,linker,critic,timing}.py
    pipeline.py             # 문서 1건 에피소드 실행
    roadmap/{generate,retrieve,diff}.py
    eval/metrics.py
  data/corpus/{public,synthetic}/   # md + 메타(날짜·출처)
  data/facts_ledger.json
  runs/<timestamp>/kb/, events.jsonl, roadmap_*.json
  viz/server.py, viz/static/index.html   # FastAPI + D3
```

- Python 3.14, openai SDK(OpenRouter base_url), pydantic, networkx(CPM), sentence-transformers(검색), FastAPI(SSE). 모두 설치돼 있음.
- Code/를 git 저장소로 초기화 권장(OneDrive 동기화와 git은 공존하나 `runs/`는 .gitignore).

---

## 6. 위험과 대응

| 위험 | 대응 |
|---|---|
| LLM이 IonQ를 이미 알아서 ①도 그럴듯함 | 가상 내부자료의 심은 사실은 모델이 알 수 없음 → 회수율로 KB 효과를 분리. 공개 사실은 cutoff 전후 구간 분리 보고 |
| 문서 200건 × 에이전트 5종 = 비용·시간 | 20건 파일럿으로 문서당 비용 측정 후 모델 등급 조정. 발표는 기록 재생 |
| Critic이 다 반려하거나 다 수락 | 심은 모순 회수율을 Critic 튜닝의 기준으로 사용 |
| 시각화가 노드 수백 개에서 읽히지 않음 | 층 고정 레이아웃 + 시간축 + 줌/필터(층·연도·에이전트별) |
| OneDrive 경로의 한글·공백 | 스크립트는 `C:/` 슬래시 절대경로, Python은 `-I`와 utf-8 명시 |

---

## 7. 확정 사항 (2026-10-31 사용자 답변)

1. 기업: **IonQ** 확정.
2. 실제:가상 비율 2:1, 가상 자료 유형(회의록·R&D 주간보고·고객/공급사 메일·내부 기술평가서) 확정.
3. 모델: 20건 파일럿 비용을 보고 Claude가 선정.
4. 0918 Phase 1 코드 없음 → **Generator 신규 작성**.
5. 문서 영어, 화면 한국어(추후 영어 전환 예정 → 라벨은 i18n 사전으로 분리해 둘 것).

## 7-구. 열린 질문 (원문)

1. 기업: IonQ로 가도 되는가? (대안 Quantinuum)
2. 실제:가상 비율을 약 2:1로 두는 것에 동의하는가? 가상 자료 유형 중 빼거나 더할 것?
3. 모델: 제안자·Critic 후보를 정해줄 것인지, 파일럿 비용을 보고 내가 고를 것인지.
4. 이진수 0918 프레임워크 Phase 1 코드가 실제로 있는가(폴더에는 pdf만 있음). 있으면 Generator로 재사용, 없으면 새로 짠다.
5. 코퍼스·UI 언어: 문서는 영어, 화면 라벨은 한국어로 가정.
