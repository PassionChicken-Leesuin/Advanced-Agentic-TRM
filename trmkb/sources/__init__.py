"""trmkb.sources — v2 지식베이스: 소스(근거 문장)가 기본 단위이고 why/what/how/resource 는 태그.

  store.py   Passage(근거 문장 + 태그), Entity(같은 대상을 말하는 문장들의 색인), SourceStore(파일 저장·이벤트)
  router.py  문서 단위 판단: 태그(층 다중·종류·시점·양태), 대상 연결(기존/신규), 기존 진술 대비 상태(신규·중복·갱신·충돌)
  grid.py    Cambridge 식 연계 그리드: 열 = 응용 기회(what), 행 = 드라이버·니즈(why)·역량(how)·인에이블러(resource)
  context.py 2단 사용: 주제 선정(계획자) → 주제별 다중 출처 블록 + 그리드 연결
"""
