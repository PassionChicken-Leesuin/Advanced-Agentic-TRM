# Cambridge Quantum Technology Roadmap Report 분석 — 로드맵이 요구하는 지식 단위

분석 대상: `선행문헌/My_Prior_Research/Quantum-Technologies-Roadmap-Report.pdf` (Trueman, IfM Cambridge, 2014. 런던 8/7·글래스고 8/21 워크숍 통합본, 76쪽)
목적: "역량 주장(capability claim)" 하나로는 부족하다는 전제 아래, **사람이 만든 로드맵이 실제로 무엇으로 구성되는지**를 산출물 단위로 역추적해 KB가 담아야 할 지식 단위 유형을 도출한다.
방법: 보고서의 산출물 종류(§1) → 각 산출물을 구성하는 원자 단위(§2) → 단위 간 관계와 속성(§3) → 역량 주장과의 차이(§4) → KB 설계 반영(§5).

---

## 1. 보고서가 담고 있는 산출물 (무엇이 로드맵인가)

| # | 산출물 | 쪽 | 형식 | 생성 방식 |
|---|---|---|---|---|
| P1 | 비전 문장 5개 + 이해관계자 집단별 지지표 | 16, 45 | 문장 × (Industry/Research/Public) 투표 | 참가자 투표 |
| P2 | 트렌드·드라이버 19개, 우선순위 % | 17, 48 | 순위표. STEEP(Social/Political-Legal-Regulatory/Environmental/Economic/Technological) 분류, 시간축 배치 | 포스트잇 → 투표 |
| P3 | 이해관계자 관점·니즈 14~15개, 우선순위 % | 18, 49 | 순위표. 행위자 유형(Government/Consumer&Market/Large Industry/SMEs/Universities/Other) | 투표 |
| P4 | 응용 기회 15개 군집, 득표 | 19, 50 | 순위표. 응용 범주(Imaging&Sensing/Navigation/Secure Comm/Computing/Components/Other) + 시장 예시 | 아이디에이션 → 군집 → 투표 |
| P5 | 역량 영역·인에이블러 | 14 | 역량(Components/Quantum Devices/Integration/Techniques/Manufacture/Research) vs 인에이블러(Knowledge/Communication/People&Skills/Finance/Support Orgs/Infrastructure/Partnerships) | 토픽 로드맵에서 수집 |
| P6 | 연계 그리드(Linkage Grid) 4종 + 통합 차트 | 20–25, 51–56 | 기회 × {드라이버, 니즈, 역량, 인에이블러} 행렬, 강도 1–3 | 드라이버·니즈 링크는 기회별로 **직접 질문**, 역량·인에이블러 링크는 **토픽 사업계획에서 유도** (p20, 51) |
| P7 | 랜드스케이프(통합 로드맵 차트) | 11–14 | 5층(Trends&Drivers / Stakeholder / Applications / Capability / Enablers) × 시간 밴드(Past / 2014–2019 / 2020–2030 / 2031–2045 / Vision) | P2~P5를 시간축에 배치. **우선순위 = 투표 + 우선 기회와의 링크 수** (p10) |
| P8 | 토픽 로드맵 10+9개 | 27–42, 58–75 | 템플릿: 열 = Current State / Short(5년 목표, When?) / Medium(When?) / Long(When?) / Vision. 행 = 시장(why, 분홍) / 제품(what, 파랑) / 기술(how, 초록) + 마일스톤 띠(DEMONSTRATOR → FIRST COMMERCIAL PRODUCT → SECOND COMMERCIAL PRODUCT) | 분과 작업 |
| P9 | 토픽별 Actions / Risks / Barriers × 시간 | 28, 31, 34… | 표 | 분과 작업 |
| P10 | 장벽–조치 쌍 (글래스고만) | 46–47 | Barrier → Action, 5개 범주(초기 산업 참여 / 연구→상용 전환 / 표준 / 칩 제조 / 입법·정책) | 분과 작업 |
| P11 | 참석자 명단 | 43, 76 | 이름·기관·부문 | 기록 |

핵심 관찰: 로드맵은 **(a) 층별 항목 목록, (b) 층 간 연계 행렬, (c) 기회별 경로(현재→마일스톤→비전), (d) 우선순위 가중치, (e) 장애·조치·위험**의 다섯 묶음이다. 역량 주장은 (c)의 기술 행 일부만 덮는다.

워크숍 절차 자체가 본 연구의 에이전트 파이프라인과 대응된다는 점도 기록해 둔다. 포스트잇 수집(Reader) → 층·범주로 군집(Router) → 연계 그리드(Linker) → 투표·우선순위(Critic) → 시간 밴드 배치(Timing) → 두 워크숍 통합(Summarizer). 특히 "역량·인에이블러 링크는 토픽 사업계획에서 유도했다"(p20)는 문장은 Linker가 문서(계획)에서 엣지를 추론하는 것과 같은 작업이다.

---

## 2. 산출물을 구성하는 원자 단위 (보고서 실례와 함께)

### 2.1 why 층

| 단위 | 정의 | 보고서 실례 | 역량 주장과 다른 점 |
|---|---|---|---|
| **외부 드라이버** (driver) | 기업 밖에서 오는 변화. STEEP 범주, 시간대, 우선순위 | "GPS Vulnerabilities" 17%, "Moore's Law reaches quantum regime", "Changing Security Threats"(p17), 시간축 배치(p12) | 역량이 아니라 환경. 측도·값이 없고 **방향과 시기**만 있음 |
| **이해관계자 니즈** (stakeholder need) | 특정 행위자 유형이 요구·기대하는 것 | "Defence: early adopters, building demonstrators", "Short-term ROI/Success Indicators", "Austerity/risk aversion"(p18) | 행위자에 귀속된 요구. 드라이버와 **별도 층**으로 취급됨 |
| **비전 문장** (vision) | 장기 목표 상태 + 집단별 지지 | "UK is a world leader creating wealth from a £1bn+ QT industry" Industry 23 / Research 13 / Public 17(p45) | 시간 끝점의 목표 상태. 지지표가 붙음 |

### 2.2 what 층

| 단위 | 정의 | 보고서 실례 | 역량 주장과 다른 점 |
|---|---|---|---|
| **응용 기회 / 제품** (opportunity) | 시장에 내놓을 것. 범주 + 시장 예시 + 시간 창 + 득표 | "Through Ground Imaging — Military advantage; Munition Clearance; Oil/Gas; Civil Engineering" 2020–2030(p13), 득표 17(p19) | 시장 세그먼트 목록을 거느림 |
| **목표 사양 벡터** (target spec) | 한 제품·단계에 대한 **다차원** 요구 사양 | 관성항법: "Shoebox size, 1–10 m accuracy over 1 hour, £1–10k, reliability not critical"(p32); 항법 W2: "Power 10 mW, Size 1 cm³, accuracy <0.1 m, $5"(p60); P2P QKD: "$1000 Bob, $10 Alice"(p38); 중력계: 국방 "~m³, ~1 E/√Hz, ~£2M" vs 토목 "10 cm pipes at 2 m depth, ~£30k"(p68) | 역량 주장은 측도 1개. 로드맵 칸은 **크기·정확도·가격·신뢰도·전력이 묶인 벡터**이고 세그먼트마다 다름 |
| **마일스톤** (milestone) | 단계 유형이 있는 사건 | DEMONSTRATOR "NPL/HCF 10⁻¹¹ 2015" → FIRST PRODUCT "2016" → SECOND "10⁻¹⁴ vapour optical clock by 2018"(p29); "Thermal clock demo 2015/16 → 1st product **within 2 years from demo**; Cold matter clock demo in Airbus by 2020 → 1st product by 2022"(p62) | 단계 유형(demo/1st/2nd) + **상대 시점**("demo 후 2년") |
| **시장 규모 주장** (market size) | 수량 × 가격 × 연도 × 세그먼트 | "200 new set-ups p.a. at £500K = £100m"(p64); "UK 30 million, Global 4 billion"(p40); "Defence £20–50M for 10–20 units → 2030/35 1000s of units ~£100M"(p68); "UK cyber security £2.8bn 2013 → £3.4bn 2017"(p72) | 역량과 무관한 **수요 측 수치** |
| **채택 순서** (adoption sequence) | 비치헤드 → 확장 세그먼트의 순서 | "Military in GPS-denied → Industrial/emergency → Specialist vehicles → Agricultural → Consumer"(p32); "Government, corporate financial, critical infrastructure, ultimately SME domestic"(p72); "After technology proven for non-consumer applications"(p41) | 세그먼트 간 **precedes** 관계 |

### 2.3 how 층

| 단위 | 정의 | 보고서 실례 | 역량 주장과 다른 점 |
|---|---|---|---|
| **역량 / 기술** (capability) | 할 수 있는 것. 영역 범주 + 시간 + 링크 수 | "Miniature ultra high vacuum cells", "Error-tolerant control", "Design for Manufacture"(p14, 24) | 역량 주장이 덮는 부분 |
| **구성 요소 / 서브시스템** (component) | 제품이 요구하는 부품 수준 항목 | 시계: "Frequency comb, chip scale, miniature laser, power source, reliability engineering"(p29); 중력 이미저: "vacuum cells with laser feed-throughs, atomic cloud inject, packaged lasers, inversion algorithms"(p35); "Geiger mode array 256×256 / 512×512 pixels"(p47) | 역량 아래 **part_of** 계층. 로드맵의 how 행은 대개 이 수준으로 적힘 |
| **현재 상태 / 성숙도** (baseline, TRL) | as-is 기준점과 성숙 단계 | "Quartz 10⁻⁹ matchbox; CSAC 10⁻¹⁰; cold atom 10⁻¹⁸ big room"(p29); "TRL2 quantum → surface gravimeter TRL9 but not suitable"(p36); "Very early stage quantum: TRL 1→3"(p66); "Push to TRL 5"(p29); "TRL valley of death"(p46) | 역량 주장의 modality=achieved에 해당하나 **TRL 순서 척도**가 별도로 필요 |

### 2.4 자원 층 (Phaal의 resources: 보고서의 Enablers)

| 단위 | 정의 | 보고서 실례 | 비고 |
|---|---|---|---|
| **인에이블러 / 자원** (enabler) | 기술이 아닌 전제 조건: 자금, 인력, 표준, 시설, 파트너십, 규제 | "Funding £270m from Defence, EPSRC and TSB", "QKD Standards (ETSI)", "UK chip-scale fabrication facilities", "Consistent regulatory environment (Export controls)", "EPSRC Hubs"(p14, 25) | 보고서는 역량과 인에이블러를 **별도 층**으로 그리고 별도 연계 그리드를 만듦(p24 vs p25). 자금은 금액·출처·기간 속성 |
| **규제 / 표준 게이트** (regulatory gate) | 통과해야 하는 승인·표준 | "CESG approval for QKD devices", "Space qualification of QT components", "Medical regulatory/acceptance, NHS to decide"(p47, 67) | 인에이블러의 하위 유형이지만 **게이트키퍼 기관**이 붙고 마일스톤을 막음 |

### 2.5 층을 가로지르는 단위

| 단위 | 정의 | 보고서 실례 | 비고 |
|---|---|---|---|
| **행위자 / 조직** (actor) | 역할이 있는 조직: 공급자, 통합자, 자금원, 규제자, 고객, 경쟁자 | 공급자 "Kromek, Teraview, Oxford Instruments, E2V"(p30); 경쟁 "Thor Labs, AOSense, Cold Quanta, Toptica"(p64); 자금 "MOD/DSTL, EPSRC, TSB"; 통합자 "UTAS, Airbus, LM"(p62); "No UK version of Philips, Siemens, GE"(p30) | 연구구상은 know-who를 범위 밖으로 뒀으나, **기업 로드맵에서는 인수·협력·고객이 how/what의 실현 수단**이므로 조직 수준 행위자는 포함해야 함(개인은 제외) |
| **경쟁 대안 / 기존 기술** (incumbent) | 같은 니즈를 채우는 대체 기술과 그 사양 | "MEMS low price low precision; RLG high price medium precision"(p32); "Lockheed Martin gravity gradiometer; Scintrex FG5"(p68); "D-wave $10m, ~1000 qubit"(p74); "What's wrong with TomTom?"(p40); "Incumbent technology (silicon) continues to improve and move the goal posts"(p65) | 목표 사양의 **비교 기준점**. competes_with 관계 + 사양 벡터 |
| **위험** (risk) | 실현을 위협하는 사건. 유형: 기술/시장/정치/경쟁 | "Quantum repeaters do not work"(p34); "No market / Quantum not the answer / Over-valued IP"(p28); "Change of government"(p37); "Benefits move overseas"(p65) | threatens(위험→마일스톤) |
| **장벽** (barrier) | 현재 막고 있는 구조적 제약 | "IP no freedom to operate", "No dedicated quantum platform foundries", "Lack of clarity on export controls"(p28, 47) | 위험과 구분: 위험은 미래 사건, 장벽은 현재 상태 |
| **조치** (action) | 장벽·위험에 대응하는 행위 + 책임 행위자 + 시기 | "MOD requirement specs letter of intent to buy product → MOD places an order"(p35); "Establish quantum foundry"(p47); "EPSRC fund quantum repeater research"(p34) | addressed_by(장벽→조치). 조치에는 **책임 행위자**가 붙음 |
| **결정 지점 / 다운셀렉션** (decision) | 대안 중 선택이 필요한 지점, 선택 조건 | "Technology down-selection to a single concept per application"(p74); "Disagreement about down-selection — should it happen early (<3 years)?"(p75); "Technology decisions"(p36) | decided [[A]] over [[B]] when [[조건]] 형태. 로드맵의 **대안 경로** 표현 |
| **열린 질문** (open question) | 미해결 불확실성 | "Is it important to reduce the dose? What's the market?"(p30); "Why is chip cost so high (£10)? Why not $1?"(p62); "Shor/Grover what size is the market?"(p74) | 사람 로드맵은 **모르는 것을 기록**함. KB도 보존해야 ③ 기회 생성의 입력이 됨 |
| **가정 / 조건** (assumption) | "X이면 Y" 조건부 의존 | "Consumers if price is right"(p33); "Civilian aerospace most likely earlier adopter — regulation a barrier"(p32); "After technology proven for non-consumer applications"(p41) | 엣지에 **condition** 속성 |

---

## 3. 관계와 속성

### 3.1 관계 유형 (보고서에서 실제로 쓰인 것)

| 관계 | 방향 | 보고서 근거 | 속성 |
|---|---|---|---|
| **drives / links** | 드라이버·니즈 → 기회 | 연계 그리드 강도 1–3(p22, 23) | 강도, 도출 방식(직접 질문 vs 계획에서 유도) |
| **requires** | 기회 → 역량·구성요소; 역량 → 구성요소 | 역량 연계 그리드(p24), 토픽 로드맵 how 행 | 강도 |
| **enables** | 인에이블러 → 기회·역량 | 인에이블러 그리드(p25) | |
| **precedes** | 마일스톤 → 마일스톤, 세그먼트 → 세그먼트 | "1st product within 2 years from demo"(p62); 채택 순서(p32) | **lag**(상대 시간), 조건 |
| **part_of / instance_of** | 구성요소 → 역량; 기회 → 범주; 시장 예시 → 기회 | 범주 → 항목 → 예시 3단(p11, 13) | |
| **competes_with** | 기존 기술 ↔ 제품 | p32, 64, 68, 74 | 비교 사양 |
| **threatens / blocks** | 위험·장벽 → 마일스톤·기회 | Risks/Barriers 표 | 유형 |
| **addressed_by** | 장벽 → 조치 | p46–47 Barrier→Action 표 | 책임 행위자 |
| **provides / owns** | 행위자 → 역량·자원·제품 | 공급자·자금원 열거 | 역할 |
| **endorsed_by** | 비전·기회 → 이해관계자 집단 | 집단별 투표(p16, 45) | 가중치 |
| **decided_over** | 결정 → 선택안, 기각안 | 다운셀렉션(p74–75) | 조건 |

### 3.2 속성 (노드·엣지 공통 봉투)

| 속성 | 보고서 근거 | KB 처리 |
|---|---|---|
| **시간 표현 유형** | 절대("2018"), 상대("within 2 years from demo", "5 years", "15–20 yrs"), 밴드(Short 2014–19 / Medium 2020–30 / Long 2031–45), 미정("When?" 공란) | 원문 보존 + 문서 날짜 기준 정규화(ES/LS) + 유형 태그 |
| **모달리티** | Current State / goal / Vision 열 구분; "demonstrated already (HP labs 2007)" vs "by 2020" | current / planned / achieved / required / forecast / vision |
| **단계** | Demonstrator / 1st / 2nd commercial; TRL 1–9 | 순서 척도 두 개 병행 |
| **우선순위** | 투표 %, 득표 수, 그리고 **링크 수와 결합**(p10) | 기업 KB에서는 투표가 없으므로 대체: 문서 언급 빈도·투입 자본·경영진 강조 + 링크 차수. 계산 속성 |
| **출처·분기** | 런던 vs 글래스고 순위가 다름(센서 20% vs 16%, Data Security 3% vs 9%); 통합본은 둘을 나란히 유지 | 다중 출처 불일치를 **병존 + 플래그**(계획서 방침과 일치) |
| **범위 한정** | "Fully UK based", "non-ITAR", "IP outside UK", "on-shoring" | geography / ownership 한정어 |
| **책임 행위자** | 조치마다 MOD / TSB / EPSRC / 대학 | actor 링크 |

### 3.3 구조적 요구

- **세 시간 앵커**: Where are we now(현재 상태) / How can we get there(경로) / Where do we want to go(비전)(p9). KB는 노드마다 as-is 기준점과 목표 상태를 구분해 보존해야 한다. 역량 주장의 modality만으로는 "현재 10⁻⁹인데 2018년 10⁻¹⁴를 목표"라는 **쌍**이 안 잡힌다.
- **2~3단 계층**: 범주(Imaging & Sensing) → 기회(Through Ground Imaging) → 시장 예시(Munition Clearance). 역량도 영역 → 역량 → 구성요소. ② 계층 요약과 시각화 줌의 단위.
- **토픽 로드맵 → 랜드스케이프 롤업**: 기회별 상세 경로가 상위 차트로 통합됨. KB에서는 기회(what) 노드가 하위 그래프(spec·milestone·component·risk)를 거느리는 **서브그래프 단위**가 필요.

---

## 4. 역량 주장과의 차이 정리

역량 주장 `{actor, capability, measure, value, target_time, modality, doc_date, evidence}`가 덮는 것은 §2.3 역량·구성요소의 수치 주장과 §2.2 목표 사양의 단일 차원뿐이다. 빠지는 것을 중요도 순으로 적으면:

1. **why 층 전체**: 드라이버(STEEP)·이해관계자 니즈·비전. 역량 주장은 환경과 수요를 말하지 못한다.
2. **다차원 사양 벡터와 세그먼트 종속**: 같은 제품도 국방용·토목용 사양이 다르다(p68). 측도 하나씩 쪼개면 "어느 세그먼트의 어느 단계 사양"이라는 묶음이 사라진다.
3. **마일스톤 단계와 상대 시점**: demo → 1st → 2nd, "demo 후 2년". precedes + lag.
4. **자원 층**: 자금·표준·시설·규제·파트너십. 보고서는 이걸 별도 층과 별도 그리드로 다룬다.
5. **행위자와 경쟁 대안**: 공급자·고객·자금원·규제자·경쟁자. 기업 로드맵에서는 인수(Oxford Ionics)가 곧 how의 실현 수단이므로 제외할 수 없다.
6. **위험·장벽·조치·결정·열린 질문**: 로드맵의 절반은 "무엇이 막고 있고 무엇을 할 것이며 무엇을 모르는가"다.
7. **시장 규모·채택 순서**: 수요 측 수치와 비치헤드 순서.
8. **현재 상태 기준점(TRL)과 목표의 쌍**.
9. **우선순위의 계산 규칙**: 투표 + 링크 차수. 기업 KB에서는 대체 신호가 필요.

---

## 5. KB 설계에 반영할 것 (계획서 §2.1-b 개정안)

### 5.1 노드 유형 (10종, 4층 + 횡단)

| 층 | 유형 | 핵심 슬롯 |
|---|---|---|
| why | driver | steep_category, direction, time_band, priority |
| why | need | stakeholder_type / segment, requirement_text, priority |
| why | vision | target_state, horizon, endorsement |
| what | opportunity (제품·응용) | category, segments[], time_window, priority |
| what | milestone | stage(demo/1st/2nd/…), date(절대·상대), parent_opportunity |
| how | capability | area_category, maturity(TRL), time |
| how | component | parent_capability, spec |
| resource | enabler | kind(funding/skills/standard/facility/partnership/regulation), amount, source, gatekeeper |
| 횡단 | actor | org_type, roles[](supplier/customer/funder/regulator/competitor/partner/acquiree) |
| 횡단 | issue | kind(risk/barrier/open_question/decision), issue_type(technical/market/political/competitive), status |

### 5.2 주장 유형 (노드에 붙는 타임라인 항목; 공통 봉투 + 유형별 슬롯)

공통 봉투: `{claim_id, node_id, claim_type, actor(발화자), modality, time_expr(원문), time_norm(ES/LS), scope, doc_id, doc_date, evidence_id, confidence}`

| claim_type | 유형별 슬롯 | 예 |
|---|---|---|
| spec | dims{size, accuracy, cost, power, reliability, …}, segment, stage | 관성항법 shoebox·1–10 m·£1–10k |
| capability_claim | measure, value | #AQ 64 by 2025 |
| market_size | volume, unit_price, total, segment, year | 200 set-ups × £500K = £100m |
| maturity | trl, stage | TRL 1→3 |
| priority | score, method(vote/mention/capital/degree) | 17% |
| comparison | vs_node, dims | MEMS vs quantum accelerometer |
| action | responsible_actor, due | MOD places an order |

### 5.3 관계 (11종) — §3.1 표 그대로. 모든 엣지에 `{strength, derivation(direct/derived), condition, lag, evidence_ids, critic_status}`.

### 5.4 Reader 설계에 주는 함의

- 노드 유형 10개 + 주장 유형 7개를 한 프롬프트에 다 넣으면 추출 품질이 떨어진다. **2단 추출**: 1차는 "이 문단이 말하는 것이 why/what/how/resource/actor/issue 중 무엇인가"를 분류하고, 2차는 유형별 전용 스키마로 슬롯을 채운다. EDC(Extract→Define→Canonicalize)의 Define 단계를 유형 분류로 쓰는 셈.
- 보고서 템플릿(Current / Short / Medium / Long / Vision × 시장·제품·기술)을 **Reader의 체크리스트**로 쓴다. 문서 하나에서 이 격자의 어느 칸을 채울 수 있는지 묻는 방식이 "무엇을 뽑을지"를 안정시킨다.
- **열린 질문·결정·가정**은 추출 대상에서 빠지기 쉬우니 전용 질문을 둔다("이 문서가 미결로 남긴 것은?", "선택지 중 무엇을 골랐고 조건은?").

### 5.5 IonQ 코퍼스에 적용하면 (예시 매핑)

| 보고서 단위 | IonQ 실례 (cutoff 2024-12 이전 문서에서 기대) |
|---|---|
| driver | 수출통제 강화, NIST PQC 표준화, DARPA QBI, 경쟁사 논리 큐비트 시연(Google Willow 2024-12) |
| need | 국방(AFRL) 온프레미스 요구, 제약(AstraZeneca) 화학 시뮬레이션, 클라우드 3사 가용성 |
| opportunity | Forte Enterprise, Tempo, 양자 네트워킹(IDQ), 데이터센터 설치형 |
| milestone | Tempo 납품 → #AQ 64 → 256큐비트(2026) |
| spec | #AQ, 2큐비트 충실도, 큐비트 수, 오류율, 랙 크기·냉각 요구 |
| capability / component | 포토닉 인터커넥트, 전자식 제어(Oxford Ionics), 2D 트랩, 바륨 이온 |
| enabler | 자본조달($1B+ 2025), 시애틀 제조시설, 수출허가, ETSI/NIST 표준 |
| actor | Oxford Ionics(인수), Lightsynq, Qubitekk, IDQ, AWS/Azure/GCP, AFRL, EPB, Quantinuum/IBM/Google(경쟁) |
| issue | 결정: 레이저 → 전자식 제어(2025); 위험: 10-K Risk Factors 전체; 열린 질문: 오류정정 코드 선택 |
| market_size | 10-K TAM 서술, 수주잔고(bookings) |
| comparison | 이온트랩 vs 초전도 vs 중성원자 사양 비교 기사 |

IonQ 10-K의 Risk Factors 절과 MD&A는 issue·enabler·market_size의 1차 출처이고, 보도자료는 milestone·actor, arXiv는 capability·spec, 인수 공시는 decision·actor의 출처가 된다. 가상 내부자료는 need·open_question·assumption처럼 공개 문서에 드물게 나오는 유형을 채우는 데 쓴다.

---

## 6. 범위 밖으로 둘 것

- 참석자 개인 명단(p43, 76): 조직만 actor로 쓰고 개인은 제외.
- 워크숍 투표 수치 자체: 기업 KB에는 없음. 우선순위는 §3.2의 대체 신호로 계산.
- 국가 전략 수준 인에이블러(EPSRC Hubs 등): 기업 KB에서는 외부 driver 또는 enabler(funding)로 흡수.
