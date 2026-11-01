# real_data — 공개 자료 259건 (실제 원본)

2024-12-31 이전에 공개된 IonQ 관련 자료입니다. 표 2(진행보고서)와 같은 구성입니다.

| 구분 | 출처 | 건수 | 원본 형식 |
|---|---|---|---|
| 공개 공시 | SEC EDGAR: 10-K 6, 10-Q 13, 8-K 첨부 보도자료 42, SPAC 합병 통신문 43 | 104 | 공시 원본 HTML + 문서 안 이미지(투자자 발표 슬라이드 등) |
| 공개 논문 | arXiv에서 'IonQ'가 언급된 논문 | 80 | 논문 PDF |
| 공개 블로그·자료 | ionq.com 블로그 71, 리소스 4 | 75 | 페이지 HTML + 본문 이미지 + 화면 그대로의 PDF 인쇄본 |
| 합계 | | 259 | |

## 폴더

```
real_data/
  originals/                 내려받은 원본 파일 (바이트 단위 그대로)
    edgar/<doc_id>/           공시 htm + 이미지
    arxiv/<doc_id>.pdf
    ionq_web/<doc_id>/        page.html, 이미지, page.pdf
    _manifest_originals.json  문서별 원본 URL, 파일별 sha256·크기·형식, 수집 시각
  text/<doc_id>.md            원본에서 추출한 정규화 텍스트 (시스템 입력). 머리말에 날짜·출처 URL
  _manifest_edgar.json, _manifest_arxiv.json, _manifest_ionq_web.json   수집 기록
```

## 공개 저장소(GitHub)에 올리지 않는 이유

`originals/`와 `text/`의 본문은 각 저작권자(IonQ, 논문 저자, arXiv)의 자료입니다. 이 저장소가 공개 상태이므로
매니페스트(URL·sha256)만 올리고 파일 자체는 연구자 로컬 폴더에만 둡니다. 같은 파일은 아래 명령으로 다시 받을 수 있고,
sha256으로 동일한지 확인할 수 있습니다(웹 페이지는 게시 후 수정되면 값이 달라질 수 있음).

```powershell
python scripts/collect_public.py all      # text/ 재생성
python scripts/fetch_originals.py         # originals/ 재수집
python scripts/fetch_originals.py --report
```

정답표(공식 로드맵)의 원본은 `../../ground_truth/originals/`에 따로 있습니다. 이 자료들은 기준일 이후 자료라 코퍼스에 넣지 않습니다.
