# ground_truth — IonQ 공식 로드맵 (평가 정답표와 1차 원본)

- `ionq_roadmap_milestones.json`: 평가에 쓰는 마일스톤 19건 (2020년판 9, 2025년판 10). 항목마다 `source_file`이 아래 원본을 가리킵니다.
- `src_*.md`: 원본에서 뽑은 본문 텍스트 (참고용).
- `originals/`: 1차 원본 파일. 수집: `python scripts/fetch_roadmap_originals.py`. 파일별 sha256은 `_manifest_ground_truth.json`.

## 2020년 12월 로드맵 (`originals/2020-12_roadmap/`)

| 폴더 | 내용 |
|---|---|
| `ionq_blog_wayback_2020/` | **최초 게시판.** ionq.com 블로그 "Scaling IonQ's Quantum Computers: The Roadmap"의 Internet Archive 2020-12-09 23:22 보관본. 원본 HTML, 로드맵 차트 원본 `IonQ-roadmap-20201208.jpg`, 화면 PDF |
| `ionq_blog_current/` | 현재 게시본(2022-02-23 수정판: #AQ 추정기 삭제). HTML, 차트, PDF |
| `edgar_2021-03-08_8k/` | dMY Technology Group III·IonQ 합병 발표 8-K. 보도자료(EX-99.1), 투자자 발표(EX-99.2) 원본 htm과 슬라이드 이미지 49장 |

차트 내용: 연도별 #AQ 목표 2021년 22, 2022년 25, 2023년 29, 2024년 35, 2025년 64(16:1 오류정정 인코딩), 2026년 256(16:1), 2027년 384(32:1), 2028년 1,024(32:1).

## 2025년 6월 가속 로드맵 (`originals/2025-06_roadmap/`)

| 폴더 | 내용 |
|---|---|
| `ionq_blog_2025-06-13_wayback_2025-06/` | **게시 당시판.** 블로그 "IonQ's Accelerated Roadmap"의 Internet Archive 2025-06-17 보관본. 원본 HTML, 로드맵 이미지 `Roadmap_V_2_Light.png`(5760×4608), 화면 PDF |
| `ionq_blog_2025-06-13/` | 현재 게시본. 로드맵 이미지는 2025-08-26 재업로드본이며 내용은 6월판과 같음(해상도만 다름) |
| `ionq_roadmap_page_current/` | ionq.com/roadmap 현재판(수집일 2026-11-01). Internet Archive에 2025년 보관본이 없어 6월 당시판은 확보 불가 |
| `edgar_2025-06-09_8k/` | Oxford Ionics 인수 8-K 본문과 보도자료(EX-99.1) |
| `ionq_blog_2025-10-13_aq64/` | #AQ 64 달성과 지표 변경(물리·논리 큐비트, 충실도, 논리 오류율) 공지 |

로드맵 이미지 내용: 상단 "Original IonQ #AQ Roadmap"(2024년 36 ~ 2028년 1,024), 하단 "Updated Technology Roadmap" 연도별 물리 큐비트·충실도·논리 큐비트·논리 오류율·기능(2025년 마이크로파 게이트·2D 배열, 2028년부터 포토닉 인터커넥트 등)과 응용 기회.

공식 보도자료 형태의 2020년 12월 로드맵 발표문과 2025년 6월 웨비나 슬라이드는 찾지 못했습니다(Business Wire·SEC 검색 결과 없음, investors.ionq.com은 자동 접근 차단).
