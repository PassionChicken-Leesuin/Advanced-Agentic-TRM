# -*- coding: utf-8 -*-
"""진행 보고서 docx 빌드 — 원본 계획서를 템플릿으로 열어 본문을 비우고 같은 스타일로 채운다."""
import io, sys, re, copy, shutil, os, json, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.shared import Pt, Emu, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "..", "연구계획", "이수인_Cambridge 연구계획 초안.docx")
OUT = os.path.join(HERE, "..", "..", "연구계획", "이수인_KB구축시스템_진행보고_1031.docx")
import os, json, argparse
_ap = argparse.ArgumentParser(); _ap.add_argument("--run", default=None); _ap.add_argument("--date", default="2026. 10. 31")
_args, _ = _ap.parse_known_args()
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..", "docs", "screenshots")
FIG_KB = os.path.join(SCR, "viz_kb_pilotD.png"); FIG_RM = os.path.join(SCR, "viz_roadmap_diff_pilotD.png")
RES = None   # 전체 run 결과 (summary.json) — 있으면 표 7·Summary 를 그 수치로 채움
if _args.run and os.path.exists(os.path.join(_args.run, "summary.json")):
    RES = json.load(open(os.path.join(_args.run, "summary.json"), encoding="utf-8"))
    if os.path.exists(os.path.join(SCR, "viz_kb_full.png")): FIG_KB = os.path.join(SCR, "viz_kb_full.png")
    if os.path.exists(os.path.join(SCR, "viz_roadmap_diff_full.png")): FIG_RM = os.path.join(SCR, "viz_roadmap_diff_full.png")

def pct(x): return "—" if x is None else f"{round(x*100)}%"
def _res_rows():
    if not RES:
        return ("7> 파일럿 D (20건 KB) 결과", [
            ["항목 수", "30", "36"], ["근거 문서를 인용한 항목", "0", "33"],
            ["심은 사실 회수율 (KB)", "—", "엄격 89% / 관대 100%"],
            ["diff", "—", "신규 23(전부 근거 있음) · 세분화 8 · 동일 1 · 일반화 4 · 탈락 17"],
            ["공식 로드맵 recall 엄격/관대", "21% / 53%", "21% / 42%"],
            ["2025년판 recall (관대, 선견)", "60%", "50%"], ["연도 오차 MAE", "3.25년", "1.0년"]])
    ai, aa = RES["alignment"].get("initial", {}), RES["alignment"].get("advanced", {})
    d, r = RES["diff"], RES["recovery"]; c = d["counts"]
    conf = r.get("conflict_detection"); conf_s = "측정 불가" if conf is None else pct(conf)
    return (f"7> 전체 실행 ({RES['kb']['documents']}건 KB) 결과", [
        ["항목 수", str(RES["initial"]["nodes"]), str(RES["advanced"]["nodes"])],
        ["근거 문서를 인용한 항목", str(RES["initial"]["with_evidence"]), str(RES["advanced"]["with_evidence"])],
        ["심은 사실 회수율 (KB)", "—", f"엄격 {pct(r.get('recovery_rate'))} / 관대 {pct(r.get('recovery_rate_lenient'))}"],
        ["모순 탐지율 (모순 쌍 3개)", "—", conf_s],
        ["diff", "—", f"신규 {c.get('new',0)}(근거 있음 {d['new_with_evidence']}) · 세분화 {c.get('refined',0)} · 동일 {c.get('same',0)} · 일반화 {c.get('generalized',0)} · 탈락 {c.get('dropped',0)}"],
        ["공식 로드맵 recall 엄격/관대", f"{pct(ai.get('recall_strict'))} / {pct(ai.get('recall_lenient'))}", f"{pct(aa.get('recall_strict'))} / {pct(aa.get('recall_lenient'))}"],
        ["2020년판 recall (관대)", pct(ai.get('recall_2020_lenient')), pct(aa.get('recall_2020_lenient'))],
        ["2025년판 recall (관대, 선견)", pct(ai.get('recall_2025_lenient')), pct(aa.get('recall_2025_lenient'))],
        ["연도 오차 MAE", f"{ai.get('year_mae')}년", f"{aa.get('year_mae')}년"]])
FIG_FW = r"C:/Users/User/OneDrive/문서/이수인/서울대학교/Agentic AI_TRM/연구계획/그림_연구프레임워크.png"
FIG_DEMO = r"C:/Users/User/OneDrive/문서/이수인/서울대학교/Agentic AI_TRM/연구계획/CambridgeDemo.png"

doc = Document(TEMPLATE)
body = doc.element.body
for child in list(body):
    if child.tag != qn("w:sectPr"):
        body.remove(child)

J, C, R = WD_ALIGN_PARAGRAPH.JUSTIFY, WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.RIGHT
BULLET_NUM, CIRCLE_NUM = 5, 8   # 템플릿의 • 목록 / ①② 목록

def _rich(p, text, size, bold=False, highlight=False):
    """**굵게**, __밑줄__ 마크업 지원."""
    tokens = re.split(r"(\*\*.*?\*\*|__.*?__)", text)
    for tok in tokens:
        if not tok:
            continue
        b, u, s = bold, False, tok
        if tok.startswith("**") and tok.endswith("**"):
            b, s = True, tok[2:-2]
        elif tok.startswith("__") and tok.endswith("__"):
            u, s = True, tok[2:-2]
            if s.startswith("**") and s.endswith("**"):
                b, s = True, s[2:-2]
        r = p.add_run(s); r.font.size = Pt(size); r.bold = b; r.underline = u
        if highlight:
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return p

def para(text, size=8, bold=False, align=J, style="Normal", highlight=False, indent=None, space_after=None):
    p = doc.add_paragraph(style=style); p.alignment = align
    if indent is not None:
        p.paragraph_format.left_indent = Emu(indent)
    if space_after is not None:
        p.paragraph_format.space_after = Pt(space_after)
    return _rich(p, text, size, bold, highlight)

def _num(p, num_id, lvl):
    pPr = p._p.get_or_add_pPr(); numPr = OxmlElement("w:numPr")
    il = OxmlElement("w:ilvl"); il.set(qn("w:val"), str(lvl)); nid = OxmlElement("w:numId"); nid.set(qn("w:val"), str(num_id))
    numPr.append(il); numPr.append(nid); pPr.append(numPr)

def bullet(text, lvl=0, size=8):
    p = doc.add_paragraph(style="List Paragraph"); p.alignment = J; _num(p, BULLET_NUM, lvl); return _rich(p, text, size)

_circle_num = [CIRCLE_NUM]
def circle_restart():
    """①부터 다시 시작하는 새 번호 인스턴스(abstractNum 2 재사용)."""
    numbering = doc.part.numbering_part.element
    ids = [int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))]
    new_id = max(ids) + 1
    num = OxmlElement("w:num"); num.set(qn("w:numId"), str(new_id))
    an = OxmlElement("w:abstractNumId"); an.set(qn("w:val"), "2"); num.append(an)
    ov = OxmlElement("w:lvlOverride"); ov.set(qn("w:ilvl"), "0")
    so = OxmlElement("w:startOverride"); so.set(qn("w:val"), "1"); ov.append(so); num.append(ov)
    numbering.append(num); _circle_num[0] = new_id

def circle(text, size=8):
    p = doc.add_paragraph(style="List Paragraph"); p.alignment = J; _num(p, _circle_num[0], 0); return _rich(p, text, size)

def h1(text): return para(text, 11, True)
def h2(text): return para(text, 10, True)
def arrow(text): return para("→ " + text, 8, True, highlight=True, indent=63500)
def caption(text, align=None, size=10): return para(text, size, align=align if align else WD_ALIGN_PARAGRAPH.LEFT)

def _shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr(); shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill); tcPr.append(shd)

def table(cap, header, rows, widths, first_col_shade=False, size=8):
    caption("<표 %s" % cap)
    t = doc.add_table(rows=1 + len(rows), cols=len(header)); t.style = doc.styles["Table Grid"]
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.width = Emu(widths[i]); _shade(c, "D9D9D9")
        c.paragraphs[0].text = ""; _rich(c.paragraphs[0], h, size, True); c.paragraphs[0].alignment = C
    for r in t.rows:
        trPr = r._tr.get_or_add_trPr(); cs = OxmlElement("w:cantSplit"); trPr.append(cs)
    for ri, row in enumerate(rows, 1):
        for ci, val in enumerate(row):
            c = t.rows[ri].cells[ci]; c.width = Emu(widths[ci]); c.paragraphs[0].text = ""
            lines = val.split("\n")
            _rich(c.paragraphs[0], lines[0], size, bold=(ci == 0 and first_col_shade))
            for ln in lines[1:]:
                _rich(c.add_paragraph(), ln, size)
            if ci == 0 and first_col_shade:
                _shade(c, "FAE2D5")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t

def summary_box(paragraphs):
    t = doc.add_table(rows=1, cols=1); t.style = doc.styles["Table Grid"]
    cell = t.rows[0].cells[0]; cell.width = Emu(9016 * 635)
    cell.paragraphs[0].text = ""; _rich(cell.paragraphs[0], "**[Summary]**", 8)
    for txt in paragraphs:
        p = cell.add_paragraph(); p.alignment = J; _rich(p, txt, 8)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def figure(path, cap, width_in=6.3):
    p = doc.add_paragraph(); p.alignment = C; p.add_run().add_picture(path, width=Inches(width_in))
    caption(cap, C, 9)

EMU = 635  # dxa → EMU
W4 = [2200 * EMU, 2600 * EMU, 2200 * EMU, 2016 * EMU]

# ============================================================== 본문
para("**[진행 보고] TRM-Specific Knowledge Base Construction Agentic AI System — 구현 현황과 첫 결과**", 14, True, C)
para(f"DDSI Lab 이수인 ({_args.date})", 10, align=R)

summary_box([
    "10월 21일 세미나와 10월 23일 Cambridge 연구계획 초안에서 제안한 **TRM-Specific Knowledge Base Construction Agentic AI System**을 실제로 구현해 첫 결과를 얻었음. 결과물은 지식베이스(Knowledge Base, 에이전트가 읽고 추론하는 조직된 지식) 자체가 아니라 __그 지식베이스를 문서로부터 자율적으로 구축하는 에이전트 시스템__이며, 지식베이스와 로드맵은 그 시스템의 산출물임.",
    "대상 산업은 양자기술(Quantum Technology), 대상 기업은 미국 상장사 **IonQ**로 정함. 2024년 12월 31일 이전의 공개 자료 259건(공시·보도자료·논문·블로그)과 LLM으로 생성한 가상 내부자료 50건(회의록·주간보고·고객/공급사 메일·기술평가서)을 코퍼스로 구성함. 가상 자료에는 모델이 알 수 없는 사실 42건을 미리 심어 두어, 시스템이 그것을 회수했는지로 구축 품질을 측정함.",
    "Cambridge IfM의 2014년 양자기술 로드맵 워크숍 보고서(76쪽)를 전수 분석해 __로드맵이 요구하는 지식 단위를 노드 10종·주장 8종·관계 11종__으로 도출했고, 이를 그대로 지식베이스 스키마로 삼음. 지식베이스는 **Reader → Router → Linker → Critic → Timing → Summarizer** 여섯 에이전트가 문서 한 건씩 읽으며 쌓고, 모든 변화는 이벤트 로그로 남겨 실시간 화면으로 재생함.",
    (f"같은 LLM, 같은 프롬프트로 지식베이스 없이 만든 **Initial Roadmap**과 지식베이스를 연산 ①~⑦로 읽어 만든 **Advanced Roadmap**을 비교함. "
     f"{RES['kb']['documents']}건 전체 실행에서 KB는 노드 {RES['kb']['nodes']}개·주장 {RES['kb']['claims']}개·수락 링크 {RES['kb']['edges_by_status'].get('accepted',0)}개가 되었고, "
     f"__심은 사실 회수율 {pct(RES['recovery'].get('recovery_rate'))}(관대 기준 {pct(RES['recovery'].get('recovery_rate_lenient'))})__, "
     f"Advanced의 {RES['advanced']['nodes']}개 항목 중 {RES['advanced']['with_evidence']}개가 근거 문서를 인용했으며(Initial은 {RES['initial']['with_evidence']}개), "
     f"공식 로드맵 마일스톤 재현율(관대)은 Initial {pct(RES['alignment'].get('initial',{}).get('recall_lenient'))} → Advanced {pct(RES['alignment'].get('advanced',{}).get('recall_lenient'))}, "
     f"2025년판(cutoff 이후) 선견 재현율은 {pct(RES['alignment'].get('initial',{}).get('recall_2025_lenient'))} → {pct(RES['alignment'].get('advanced',{}).get('recall_2025_lenient'))}, "
     f"연도 오차는 {RES['alignment'].get('initial',{}).get('year_mae')}년 → {RES['alignment'].get('advanced',{}).get('year_mae')}년임(6절).") if RES else
    "같은 LLM, 같은 프롬프트로 지식베이스 없이 만든 **Initial Roadmap**과 지식베이스를 연산 ①~⑦로 읽어 만든 **Advanced Roadmap**을 비교함. 20건 파일럿에서 __심은 사실 회수율 89%(관대 기준 100%)__, Advanced의 36개 항목 중 33개가 근거 문서를 인용했으며(Initial은 0개), 공식 로드맵 마일스톤과의 연도 오차가 3.25년에서 1.0년으로 줄었음. 180건 전체 실행은 보고서 작성 시점에 진행 중임(2절·9절).",
    "비용은 지금까지 약 $5.3, 전체 실행 완료까지 약 $12 수준으로 예상됨. 코드는 GitHub(PassionChicken-Leesuin/Advanced-Agentic-TRM)에 공개되어 있음.",
])

# ------------------------------------------------------------------ 1
h1("1. [무엇을 만들고 있는가: 한 문장과 용어]")
para("한 문장으로 쓰면, **‘기업의 자료가 들어올 때마다 그 내용을 로드맵이 요구하는 구조로 정리해 쌓고, 그렇게 쌓인 지식으로 더 나은 로드맵을 만들게 하는 시스템’**임. 이 문장에 들어 있는 말들을 먼저 정리함(<표 1>). 이하 본문에서 처음 나오는 용어도 같은 방식으로 괄호 안에 풀어 씀.")
table("1> 이 보고서에서 쓰는 용어", ["용어", "뜻", "이 연구에서의 역할"], [
    ["TRM\n(Technology Roadmap, 기술 로드맵)", "시장·제품·기술을 시간축 위에 배치하고 서로 연결한 도표. Cambridge T-Plan 방식은 why(시장·동인), what(제품·기능), how(기술)의 세 층으로 그림", "시스템의 최종 산출물이자 평가 대상"],
    ["LLM\n(Large Language Model)", "대량의 글을 학습해 글을 읽고 쓰는 인공지능 모델(GPT, Claude 등). 질문(프롬프트)을 주면 답을 생성함", "에이전트의 ‘두뇌’. 여러 모델을 역할별로 나눠 씀"],
    ["에이전트(Agent) / Agentic AI", "LLM이 한 번 답하고 끝나는 것이 아니라, 상황을 보고 다음 행동을 스스로 고르며 도구를 쓰고 결과를 확인하는 방식으로 작동하는 것", "Reader·Router 등 여섯 에이전트가 문서를 읽고 지식베이스를 고침"],
    ["Knowledge Base(KB, 지식베이스)", "에이전트가 읽고 추론할 수 있도록 ‘구조를 갖춰’ 저장한 지식. 단순한 문서 더미가 아니라 노드·링크·시간 정보가 있는 저장소", "본 연구의 변수. 구조를 어떻게 잡느냐가 로드맵 품질을 좌우한다는 가설"],
    ["RAG\n(Retrieval-Augmented Generation)", "질문과 비슷한 문서 조각을 찾아 LLM에 붙여 주고 답하게 하는 기법. 가장 단순한 KB 사용법", "비교 기준선(S0). 선행 TRM 연구는 대부분 이 방식"],
    ["노드 / 링크(엣지)", "노드는 로드맵의 한 항목(예: ‘포토닉 인터커넥트’), 링크는 항목 간 관계(예: ‘A가 B를 요구한다’)", "KB의 기본 단위. 로드맵도 결국 노드·링크의 망"],
    ["주장(claim)", "어떤 문서가 어떤 노드에 대해 말한 구체적 진술(수치·날짜·조건 포함). 예: ‘2025년까지 #AQ 64 달성’", "노드 아래 시간순으로 쌓임. 덮어쓰지 않음"],
    ["근거(evidence)", "주장이 나온 원문 문장과 그 위치", "로드맵 항목마다 출처를 달 수 있게 함"],
    ["Initial / Advanced Roadmap", "KB 없이 LLM의 사전지식만으로 만든 로드맵 / 구축된 KB를 읽어 만든 로드맵. 프롬프트·모델은 동일", "1막과 3막. 둘의 차이가 KB의 효과"],
    ["cutoff(기준일)", "KB에 넣는 문서의 날짜 상한. 본 연구는 2024-12-31", "그 이후 공개된 공식 로드맵을 ‘정답’으로 써서 예측력을 봄"],
], [2000 * EMU, 4300 * EMU, 2716 * EMU], first_col_shade=True)

# ------------------------------------------------------------------ 2
h1("2. [대상 기업과 자료: 왜 IonQ인가, 무엇을 넣었나]")
h2("2.1 기업 선정")
bullet("양자기술 산업에서 기업 하나를 고르는 기준은 세 가지였음. (a) 날짜가 찍힌 1차 자료가 많을 것, (b) 회사가 공식 로드맵을 수치·연도로 공개해 ‘정답’으로 쓸 수 있을 것, (c) 시장·규제·인수처럼 why 층 자료가 있을 것.")
bullet("**IonQ**(미국 메릴랜드, 이온트랩 방식 양자컴퓨터 상장사, NYSE: IONQ)가 세 기준을 모두 충족함. 2020년 12월 로드맵을 공개했고, 2025년 6월 가속 로드맵으로 갱신했으며, 2025년 인수(Oxford Ionics, Lightsynq 등)가 많아 전 층의 사건이 풍부함. 대안으로 Quantinuum, Rigetti를 검토했으나 자료량에서 밀림.")
bullet("주의할 점 하나. IonQ의 로드맵은 판마다 측정 단위가 다름. 2020년판은 **#AQ(Algorithmic Qubits, IonQ가 만든 ‘실제 알고리즘에 쓸 수 있는 유효 큐비트 수’ 지표)**로, 2025년판은 물리 큐비트 수와 논리 큐비트 수로 말함. 따라서 생성 로드맵을 정답과 맞출 때는 숫자가 아니라 마일스톤·역량 단위(모듈화, 오류정정, 지표 교체 자체 등)로 정렬함(6절).")
h2("2.2 코퍼스 구성")
para("코퍼스(corpus, 시스템에 투입하는 문서 모음)는 실제 공개 자료와 가상 내부자료를 약 2:1로 섞음(<표 2>). 공개 자료는 SEC EDGAR(미국 증권거래위원회 공시 시스템), arXiv(물리·CS 논문 공개 서버), ionq.com에서 스크립트로 내려받아 날짜·출처 메타데이터를 붙인 텍스트로 정규화함. 모두 2024-12-31 이전 자료만 씀.")
table("2> 코퍼스 구성 (2026-10-31 기준)", ["구분", "출처", "건수", "로드맵에서의 역할"], [
    ["공개 공시", "10-K(연차보고서) 6, 10-Q(분기보고서) 13, 8-K 첨부 보도자료 42, SPAC 합병 통신문 45", "106", "why·what 층, 위험요인(Risk Factors)·시장 규모"],
    ["공개 논문", "arXiv에서 ‘IonQ’가 언급된 논문 80편(본문 12쪽까지)", "80", "how 층(기술·구성요소·사양)"],
    ["공개 블로그·자료", "ionq.com 블로그 71(2020년 로드맵 원문, #AQ 마일스톤, 바륨 이온 결정 포함), 리소스 4", "75", "what·how 층, 공식 마일스톤"],
    ["가상 내부자료", "회의록 14, R&D 주간보고 14, 고객 메일 8, 공급사 메일 7, 기술평가서 7 (2024년 1~12월)", "50", "공개 자료에 드문 유형: 고객 요구, 공급 지연, 결정, 열린 질문, 위험"],
    ["합계", "", "309", "전체 실행에는 저가치 문서(짧은 합병 공지 등)를 뺀 우선순위 부분집합 180건 투입"],
], [1500 * EMU, 3900 * EMU, 700 * EMU, 2916 * EMU], first_col_shade=True)
h2("2.3 가상 내부자료와 ‘심은 사실’")
bullet("‘기업의 자료가 들어온다’는 상황을 재현하려면 내부 문서가 필요하지만 실제 내부 문서는 구할 수 없음. 그래서 LLM(claude-sonnet-4.6)에게 날짜·유형·등장 역할을 지정해 영어 문서 50건을 쓰게 함. 사람 이름은 쓰지 않고 역할(VP Hardware 등)만 씀.")
bullet("핵심은 **심은 사실(planted facts)** 원장임. 문서를 쓰기 전에 ‘Harbor 2D 트랩 칩 수율 23%(2024년 1분기)’, ‘Northfield Pharma가 2큐비트 충실도 99.9% 이상과 #AQ 60 이상을 요구’처럼 허구이지만 그럴듯한 사실 42건을 먼저 적고, 각 사실을 2~3개 문서에 나눠 자연스럽게 녹이게 함. 모델이 학습한 적 없는 사실이므로, 나중에 KB에 들어 있으면 그것은 사전지식이 아니라 시스템이 읽어서 쌓은 것임.")
bullet("사실마다 ‘등장 가능 날짜 창’을 두어 2024년 9월의 결정이 2월 문서에 나오는 시점 오류를 막았고, 3쌍은 일부러 서로 모순되게 넣음(예: 칩 수율 목표 60%→45%로 하향, Tempo 출하 1분기→2분기 지연, 얽힘률 측정 12/s vs 자료 주장 100/s). 모순은 Critic이 잡아야 할 장면임.")
arrow("가상 자료의 심은 사실 회수율이 KB 구축 품질의 가장 깨끗한 측정치이고, 공식 로드맵과의 정렬은 그것을 보강하는 두 번째 증거로 둠.")

# ------------------------------------------------------------------ 3
h1("3. [지식베이스는 무엇으로 이루어지나: Cambridge 보고서에서 도출한 지식 단위]")
para("처음에는 ‘역량 주장’(어떤 기술이 언제 어느 수준이 된다는 진술) 하나를 KB의 단위로 생각했음. 그러나 TRM은 훨씬 많은 것을 요구함. 그것이 정확히 무엇인지 보려고 **Cambridge IfM(Institute for Manufacturing)이 2014년 영국 양자기술 상용화를 위해 런던·글래스고에서 연 로드맵 워크숍의 통합 보고서(Trueman, 76쪽)**를 처음부터 끝까지 분석함. 사람이 실제로 만든 로드맵이 무엇으로 구성되는지 산출물 단위로 역추적한 것임.")
h2("3.1 보고서가 담고 있는 것")
bullet("보고서의 산출물은 다섯 묶음임. (a) 층별 항목 목록(트렌드·드라이버 19개, 이해관계자 니즈 15개, 응용 기회 15개, 역량·인에이블러), (b) 층 간 연계 행렬(기회 × 드라이버/니즈/역량/인에이블러, 강도 1~3), (c) 기회별 경로(현재 상태 → 데모 → 1차 제품 → 2차 제품 → 비전), (d) 투표와 링크 수로 계산한 우선순위, (e) 장벽·조치·위험·결정·열린 질문.")
bullet("특히 눈에 띈 것은 사람 로드맵이 **모르는 것도 기록한다**는 점임(‘칩 가격이 왜 £10인가? 왜 $1이 아닌가?’, ‘다운셀렉션을 3년 안에 해야 하는가?’). 그리고 사양은 단일 수치가 아니라 **다차원 묶음**임(관성항법: ‘구두상자 크기, 1시간에 1~10m 정확도, £1~10k, 신뢰도는 중요하지 않음’). 마일스톤에는 단계와 상대 시점이 붙음(‘데모 후 2년 안에 1차 제품’).")
bullet("워크숍 절차 자체가 본 시스템과 같다는 점도 확인함. 포스트잇 수집(Reader) → 층·범주로 군집(Router) → 연계 그리드(Linker) → 투표·우선순위(Critic) → 시간 밴드 배치(Timing) → 두 워크숍 통합(Summarizer). 보고서 20쪽의 ‘역량·인에이블러 링크는 토픽 사업계획에서 유도했다’는 문장은 Linker가 문서에서 엣지를 추론하는 작업 그대로임.")
h2("3.2 도출한 지식 단위: 노드 10종, 주장 8종, 관계 11종")
table("3> 지식베이스 스키마 (KB에 저장되는 것의 종류)", ["구분", "종류", "뜻 (괄호는 예)"], [
    ["노드\nwhy 층", "driver, need, vision", "driver는 기업 밖의 변화(수출통제 강화), need는 특정 고객·이해관계자의 요구(제약사의 충실도 99.9% 요구), vision은 장기 목표 상태"],
    ["노드\nwhat 층", "opportunity, milestone", "opportunity는 제품·응용(Forte Enterprise 온프레미스), milestone은 단계가 있는 날짜 사건(Tempo 첫 출하 2025년 2분기)"],
    ["노드\nhow 층", "capability, component", "capability는 할 수 있는 기술(포토닉 인터커넥트), component는 그 부품(1550nm 주파수 변환기)"],
    ["노드\n자원 층", "enabler", "기술이 아닌 전제 조건: 자금·시설·표준·규제 승인·인력·파트너십(시애틀 제조시설 2단계 클린룸)"],
    ["노드\n횡단", "actor, issue", "actor는 역할이 있는 조직(공급사 Helion Photonics, 경쟁사), issue는 위험·장벽·열린 질문·결정·가정(레이저 vs 전자식 제어 결정)"],
    ["주장 8종", "statement, spec, capability_claim, market_size, maturity, priority, comparison, action", "노드에 붙는 진술. spec은 다차원 사양 묶음, capability_claim은 측도·값(#AQ=64), market_size는 수량×가격×연도, maturity는 TRL(기술성숙도 1~9), action은 책임자가 있는 조치"],
    ["관계 11종", "drives, requires, enables, precedes, part_of, competes_with, threatens, addressed_by, provides, endorsed_by, decided_over", "drives는 why→what(수요가 제품을 유발), requires는 what→how(제품이 기술을 요구), enables는 how→what, precedes는 시간 선후(지연 연수 포함), threatens는 이슈→대상, decided_over는 결정→선택안"],
    ["시간 표현", "absolute / relative / band / unknown", "‘2027년’, ‘데모 후 2년’, ‘중기’, ‘미정’을 구분해 원문을 보존하고 연도 실수로 정규화(2025.25 = 2025년 2분기)"],
], [1300 * EMU, 2700 * EMU, 5016 * EMU], first_col_shade=True)
h2("3.3 구축 5원칙 (이 표가 KB에서 나오게 하는 조건)")
circle("지식의 단위는 엔티티(이름)가 아니라 **주장**임. ‘포토닉 인터커넥트’라는 이름만 있으면 로드맵 칸을 채울 수 없고, ‘2025년 말까지 원격 얽힘률 1,000/s 목표’라는 주장이 있어야 함.")
circle("Router는 새 주장을 **기존 역량 행에 정규화**함. 같은 것을 다른 말로 쓴 문서가 와도 같은 노드에 쌓이게 함.")
circle("같은 노드의 주장은 **발언 시점 순으로 보존하고 덮어쓰지 않음**. 같은 노드에서 측도가 #AQ에서 물리 큐비트로 바뀌면 그것이 곧 ‘지표 교체’이며, 타임라인에 그대로 드러남.")
circle("층을 가로지르는 링크는 **근거 문서가 하나 이상** 있어야 수락하고, why→how 직결은 층 위반으로 반려함.")
circle("역량 행 단위 **요약을 바뀐 행만 증분 갱신**함. 전체를 다시 쓰지 않음.")
arrow("원칙을 하나씩 빼면 표가 어떻게 무너지는지가 예측됨. 타임라인을 빼면 시간 열이, 정규화를 빼면 행이, 링크를 빼면 행 사이 이유가, 요약을 빼면 생성기 입력이 사라짐. 이것이 본 실험의 ablation(구성요소 제거 실험) 논리임.")

# ------------------------------------------------------------------ 4
h1("4. [지식베이스를 짓는 에이전트 여섯]")
para("문서 한 건이 들어오면 아래 순서로 처리함. 이것을 에피소드(episode)라 부르고, 에피소드 안의 모든 상태 변화는 **이벤트 로그(events.jsonl, 한 줄에 사건 하나를 시간순으로 덧붙이기만 하는 파일)**에 남김. 화면 재생·평가가 모두 이 로그 하나를 읽음.")
table("4> 에이전트별 역할과 사용 모델 (설정 D)", ["에이전트", "하는 일", "판단 방식", "모델"], [
    ["Reader", "문서를 2,200자 안팎의 청크(chunk, 문단 경계로 자른 조각)로 나누고, 청크마다 후보 노드·주장·근거 인용을 뽑음", "2단: 싼 모델이 ‘로드맵 관련 내용이 있는가’를 먼저 거르고(트리아지), 관련 청크만 본 모델이 유형별 슬롯을 채움. 인용은 원문에 실제로 있는지 대조", "트리아지 gpt-4.1-nano\n추출 claude-haiku-5.5"],
    ["Router", "후보가 기존 노드와 같은 것인지(병합), 새 것인지(신규) 정하고, 근거·그래프·요약·시간 인덱스 중 어디에 쓸지 결정. 모든 판단을 router_log에 남김", "임베딩(문장을 숫자 벡터로 바꿔 비슷한 정도를 재는 기법) 유사도 0.80 이상이면 병합, 0.65 미만이면 신규, 그 사이만 LLM에 물음", "gpt-4.1-mini"],
    ["Critic(모순)", "병합된 노드에 수치가 있는 새 주장이 오면 기존 주장과 상충하는지 판정해 conflict 표시", "LLM, 제안 모델과 다른 모델", "claude-sonnet-4.6"],
    ["Linker", "이 문서에서 생긴 노드와 이웃 노드 사이의 링크를 유형·방향·근거 인용과 함께 제안", "LLM. 층 규칙을 프롬프트에 명시", "gpt-4.1-mini"],
    ["Critic(링크)", "층 위반은 코드로 즉시 반려, 나머지는 근거 인용이 그 관계를 지지하는지 판정해 수락/반려/보류", "결정적 규칙 + LLM", "claude-sonnet-4.6"],
    ["Timing", "주장의 시간에서 노드의 ES/LS(earliest/latest start, 가장 빠른·늦은 시작 연도)를 구하고, precedes 링크로 전파. 제품이 요구하는 기술의 ES가 제품보다 늦으면 ‘infeasible’ 표시", "코드(네트워크 위상 정렬). LLM 없음", "—"],
    ["Summarizer", "이번 문서로 바뀐 역량 행의 요약을 다시 씀(3문서마다, 행당 150단어)", "LLM", "gpt-4.1-mini"],
], [1300 * EMU, 3300 * EMU, 2800 * EMU, 1616 * EMU], first_col_shade=True)
bullet("제안자(Reader·Linker)와 판정자(Critic)의 모델을 다르게 둔 이유는, 같은 모델이 자기 제안을 심사하면 관대해지기 때문임. 모델 조합은 20건 파일럿 세 가지를 비교해 정함(6.1).")
bullet("속도를 위해 두 가지를 병렬화함. 청크 추출은 8개를 동시에 돌리고, 다음 문서의 Reader 단계를 현재 문서의 Router 이후 단계와 겹침(Router 이후는 KB 상태에 의존하므로 한 문서씩). .env의 OpenRouter 키 20개를 호출마다 돌아가며 써서 키별 속도 제한에 걸리지 않게 함. 결과적으로 문서당 22~63초, 전체 180건은 약 1시간 반.")
arrow("연구의 핵심 관찰 대상은 Router의 판단 로그임. ‘이 주장을 어느 행에, 어느 구조에 썼는가’가 곧 ‘에이전트가 KB를 어떻게 구축하는가’의 기록임.")

# ------------------------------------------------------------------ 5
h1("5. [지식베이스를 어떻게 ‘쓰는가’: 연산 ①~⑦과 로드맵 생성]")
para("KB를 잘 짓는 것만으로는 연구가 되지 않음. ‘무엇을 뽑겠다 → 그러려면 KB를 이렇게 짓고 → 그 구조를 이 연산으로 읽어 → 이런 결과물을 뽑는다’가 한 사슬로 이어져야 함. 연구구상의 다섯 기능(①grounding ②트렌드 종합 ③기회 생성 ④링크 추론 ⑤시점 배치)에 ⑥이슈·⑦우선순위를 더해 일곱 연산으로 구현함(<표 5>). 연산은 모두 코드이고(결정적), LLM은 마지막 생성 단계에서만 씀. 그래야 ‘구조의 효과’가 ‘프롬프트의 효과’와 섞이지 않음.")
table("5> KB 사용 연산: 출력 ← 연산 ← 구조", ["뽑을 출력", "연산 (KB에 거는 질문)", "요구 구조", "없으면"], [
    ["근거 붙은 항목", "① 노드 → 근거 문장 조회", "근거 부착", "출처 없는 항목"],
    ["행별 트렌드·지표 교체", "② 역량 행 요약 + 주장 타임라인의 측도 변화", "주장 타임라인, 행 요약", "최신 주장만 남음"],
    ["행 사이의 이유", "④ why→what→how 사슬 탐색", "타입 있는 층간 링크 + 근거", "연결 없는 행"],
    ["마일스톤 배치·순서", "⑤ precedes 전파, infeasible 플래그", "ES/LS, precedes", "임의 시점"],
    ["기회·공백", "③ why는 있는데 what이 없는 행, what은 있는데 how가 없는 행, 열린 질문", "층 타입 + issue 노드", "기회 생성 불가"],
    ["위험·대안 경로", "⑥ issue와 threatens/decided_over 순회", "issue 노드, 조건부 링크", "낙관적 단일 경로"],
    ["우선순위", "⑦ 주장 수 + 링크 차수 + 수치 주장 가중", "그래프 + 주장", "전 항목 동등"],
], [1900 * EMU, 3200 * EMU, 2000 * EMU, 1916 * EMU], first_col_shade=True)
bullet("연산 결과는 항목마다 id를 달고 생성기(gpt-4.1)에 넘김. 생성기는 로드맵 항목에 인용한 id를 적게 되어 있어, 각 항목이 **어느 연산이 만든 것인지**(produced_by)를 역추적할 수 있음. KB 없이 사전지식으로 만든 항목은 llm_prior로 표시됨.")
bullet("**1막과 3막의 공정성**: 기업 소개(2024년 말 기준 한 문단), 지평(2025~2030), 층 안내, 출력 형식, 모델(gpt-4.1), 온도를 모두 고정하고 KB 컨텍스트 블록 하나만 넣고 뺌. 고정 부분의 해시(hash, 내용이 조금만 달라도 값이 바뀌는 지문)를 두 로드맵에 기록해 같은 프롬프트였음을 증명함. gpt-4.1을 고른 이유는 지식 기준일이 2024년 6월이라 2025년 6월의 가속 로드맵을 모르기 때문임.")
bullet("**diff(차이 계산)**: Initial과 Advanced의 항목을 같은 층 안에서 임베딩 유사도로 짝짓고 LLM이 Jansen(2026)식 다섯 범주로 분류함. 동일(same), 세분화(refined, Advanced가 더 구체적), 일반화(generalized), 신규(new, Advanced에만), 탈락(dropped, Initial에만). 짝이 지어진 항목은 시점 이동도 기록함.")

# ------------------------------------------------------------------ 6
h1("6. [검증: 파일럿 결과와 평가 방법]")
h2("6.1 모델 설정 선정 (같은 20건에 세 설정)")
para("가상 10건 + 공개 10건(2020년 로드맵 블로그, 2024년 10-K, 논문 2편, 보도자료 등)을 같은 순서로 넣고 세 설정을 비교함(<표 6>). 회수율은 심은 사실 중 KB의 주장·근거에서 판정자(gpt-4.1-mini)가 ‘같은 사실이 있다’고 본 비율임(엄격: 수치·날짜까지 일치, 관대: 대상은 있으나 일부 수치 누락 포함).")
table("6> 파일럿 비교 (20건 동일)", ["설정", "Reader / Critic", "오류", "회수율 엄격/관대", "수락 링크", "수치 주장", "문서당 비용"], [
    ["A2", "gpt-4.1-mini / claude-sonnet-4.6", "0", "72% / 83%", "106", "20", "$0.033"],
    ["B3", "claude-haiku-5.5 / gpt-4.1", "2", "89% / 94%", "43", "30", "$0.021"],
    ["**D (채택)**", "claude-haiku-5.5 / claude-sonnet-4.6\n(Router·Linker·Summarizer는 gpt-4.1-mini)", "0", "89% / 100%", "133", "35", "$0.032"],
], [900 * EMU, 2700 * EMU, 600 * EMU, 1500 * EMU, 1000 * EMU, 1000 * EMU, 1316 * EMU], first_col_shade=True)
bullet("haiku는 사실을 잘 건지고 싸지만 긴 입력에서 빈 응답을 내는 일이 있어 Reader에만 쓰고, 나머지 역할은 JSON 출력이 안정적인 gpt-4.1-mini로 둠. Critic은 sonnet이 가장 엄격함(A2에서 링크 123건 반려).")
bullet("첫 파일럿의 회수율은 17%였음. 원인은 트리아지가 보도자료·내부 메일을 ‘무관’으로 걸러낸 것, 긴 문서에서 Reader의 출력이 잘린 것, 주장에서 수치가 빠진 것, 모델이 잘못된 유형 이름을 써서 제안이 통째로 버려진 것이었음. 네 가지를 고친 뒤 89%가 됨.")
h2("6.2 공식 로드맵과의 정렬 (정답표)")
bullet("IonQ 공식 로드맵에서 마일스톤 19건을 역량 단위로 뽑아 정답표를 만듦. 2020년판 9건(#AQ 지표 도입, 32큐비트/22AQ 시스템, 2023년 모듈화, 2025년 광범위 양자우위 등)과 2025년판 10건(2027년 단일 칩 1만 물리 큐비트, 2028년 두 칩 연결 2만, 2030년 200만 물리/4~8만 논리, 지표 교체 자체 등). 2025년판은 cutoff 이후 자료이므로 ‘KB가 변화를 앞서 봤는가’(선견)의 지표가 됨.")
bullet("정렬 절차: 정답 마일스톤마다 로드맵 항목을 임베딩으로 추려 LLM이 match/refined/generalized/missed로 판정. 지표는 recall(엄격 = match+refined, 관대 = generalized 포함), 판별(2020/2025) recall, 짝이 지어진 항목의 연도 오차 MAE.")
_cap7, _rows7 = _res_rows()
h2("6.3 1막 vs 3막" + (" (전체 실행)" if RES else " (파일럿 D)"))
table(_cap7, ["지표", "Initial (KB 없음)", "Advanced (KB 사용)"], _rows7, [3200 * EMU, 2900 * EMU, 2916 * EMU], first_col_shade=True)
if RES:
    _ai, _aa = RES["alignment"].get("initial", {}), RES["alignment"].get("advanced", {})
    _better = (_aa.get("recall_lenient") or 0) >= (_ai.get("recall_lenient") or 0)
    _mae_ok = (_aa.get("year_mae") is not None and _ai.get("year_mae") is not None and _aa["year_mae"] <= _ai["year_mae"])
    bullet(f"20건 파일럿에서는 Advanced가 내부 가상 항목에 치우쳐 공식 마일스톤 재현율이 Initial보다 낮았음. {RES['kb']['documents']}건 KB에서는 "
           + ("Advanced가 Initial과 같거나 앞섬. " if _better else "여전히 Initial이 앞섬. ")
           + f"근거 부착률은 Initial {RES['initial']['with_evidence']} → Advanced {RES['advanced']['with_evidence']}/{RES['advanced']['nodes']}, 연도 오차는 {_ai.get('year_mae')} → {_aa.get('year_mae')}년으로 "
           + ("개선됨." if _mae_ok else "연도 오차는 개선되지 않음."))
    _cd = RES["recovery"].get("conflict_detection")
    bullet("모순 탐지율은 모순 쌍 3개 중 양쪽 사실이 모두 회수된 쌍에서 Critic이 conflict를 표시한 비율임: " + ("측정 불가(양쪽이 회수된 쌍 없음)." if _cd is None else f"{pct(_cd)}."))
    arrow("전체 실행에서 확인된 KB 효과는 ‘근거가 붙은 항목’과 ‘시점의 정확도’에서 가장 크고, 공식 마일스톤 재현율은 " + ("개선되었음." if _better else "아직 Initial과 비슷하거나 낮음. 연산 ⑦(우선순위)이 공개 자료의 큰 마일스톤을 내부 세부 항목보다 위로 올리도록 손봐야 함."))
else:
    bullet("20건짜리 작은 KB로는 Advanced가 내부 가상 항목(Harbor 칩 로트, Northfield 파일럿, 공급사 납기)에 치우쳐 공식 마일스톤 재현율이 Initial보다 낮게 나옴. 이는 KB가 ‘읽은 것’을 충실히 반영한다는 뜻이기도 함. 근거 부착률(0→33/36)과 연도 오차(3.25→1.0년)는 분명히 개선됨.")
    bullet("모순 탐지율은 파일럿에서 측정 불가였음. 모순 쌍의 양쪽이 같은 20건 안에 들어 있지 않았기 때문이며, 전체 실행에서 측정함.")
    arrow("공식 로드맵 재현율은 180건 전체 실행 결과로 다시 봐야 함. 작은 KB에서 Advanced가 Initial을 못 이기는 것은 정상이고, 전체 실행에서도 그렇다면 연산 ⑦(우선순위)이 공개 자료의 큰 마일스톤을 내부 세부 항목보다 위로 올리도록 손봐야 함.")

# ------------------------------------------------------------------ 7
h1("7. [화면: 지식이 쌓이는 장면과 달라진 로드맵]")
para("데모 3막 구성(10월 23일 초안 <그림 2>)을 그대로 웹 화면으로 구현함. FastAPI(파이썬 웹 서버)가 이벤트 로그를 SSE(Server-Sent Events, 서버가 브라우저로 사건을 한 줄씩 밀어주는 방식)로 흘리고, D3(브라우저 그래프 그리기 라이브러리)가 받아 그림. 기록 재생(속도 조절)과 실시간 추적을 같은 화면으로 처리하므로 발표 때는 기록 재생을 써서 API 지연·실패를 차단함.")
figure(FIG_KB, "<그림 1> 2막: KB가 구축되는 장면 " + ("(전체 실행, 180건 투입 완료 시점)" if "full" in FIG_KB else "(파일럿 D, 20건 투입 완료 시점)"))
bullet("세로는 다섯 레인(why / what / how / 자원 / 횡단), 가로는 시간축(know-when). 시간 정보가 있는 노드는 ES 위치에 고정되고 없는 노드는 레인 안에서 힘 기반 배치(force layout)로 퍼짐. 노드 크기는 근거 수, 라벨은 두 문서 이상이 말한 행만 상시 표시하고 나머지는 마우스를 올리면 보임.")
bullet("Linker의 제안은 점선, Critic이 수락하면 실선, 반려하면 붉은 점선으로 바뀐 뒤 사라짐. 모순이 잡힌 노드는 주황 테두리. 오른쪽에는 에이전트 여섯의 상태등과 마지막 행동, 문서 진행바, KB 통계, 이벤트 로그가 있음.")
figure(FIG_RM, "<그림 2> 1막·3막: Initial(왼쪽)과 Advanced(오른쪽) 로드맵과 diff 색상" + (" (전체 실행)" if "full" in FIG_RM else " (파일럿 D)"))
bullet("오른쪽 Advanced에서 초록은 신규, 파랑 테두리는 세분화, 회색은 동일, 점선은 일반화. 왼쪽 Initial에서 점선 테두리는 탈락한 항목. 막대 끝의 숫자 배지는 근거 문서 수이고, 기술이 수요보다 늦은 항목은 붉은 테두리(infeasible)로 표시됨. 범례의 ‘근거 있는 신규 23/23’이 3막의 핵심 메시지임.")
bullet("화면 라벨은 사전 파일 하나(i18n)에 모아 두어 영어 전환 시 그 파일만 채우면 됨.")

# ------------------------------------------------------------------ 8
h1("8. [비용과 속도]")
table("8> 지금까지의 비용 (OpenRouter 실측)", ["항목", "비용"], [
    ["가상 내부자료 50건 생성 + 재생성 11건 (claude-sonnet-4.6)", "$1.39"],
    ["파일럿 6회 + 스모크 3회 (설정 비교·디버깅)", "$2.80"],
    ["로드맵 생성·diff·평가 판정자", "약 $0.35"],
    ([f"전체 실행 {RES['kb']['documents']}건 (완료, 문서당 약 ${RES.get('full_cost_usd', 6.3)/max(1,RES['kb']['documents']):.3f})", f"${RES.get('full_cost_usd', 6.3):.2f}"] if RES else ["전체 실행 180건 (진행 중, 문서당 약 $0.035)", "약 $6.3 예상"]),
    ([f"합계", f"약 ${1.39+2.80+0.35+RES.get('full_cost_usd', 6.3)+RES.get('finalize_cost_usd',0):.1f}"] if RES else ["합계 (전체 실행 완료 시)", "약 $11~12"]),
], [6000 * EMU, 3016 * EMU], first_col_shade=True)
bullet("문서당 비용의 약 40%가 Critic(sonnet)임. 본 실험에서 구조 조건(S0~S4)별로 KB를 여러 번 지어야 한다면 Critic을 gpt-4.1이나 배치 가격으로 바꾸는 것이 절감 지점임. 데모 한 세트에는 그대로 둠.")
bullet("속도는 문서당 55초(최적화 전)에서 22~63초로 줄었고, 가장 긴 것은 14청크짜리 10-K·논문(약 60초)임.")

# ------------------------------------------------------------------ 9
h1("9. [남은 일과 열린 질문]")
circle_restart()
if RES:
    circle("**전체 실행 결과 반영 완료**: 180건 KB로 Advanced를 생성하고 회수율·모순 탐지율·공식 로드맵 정렬을 산출해 <표 7>과 Summary에 반영함. 남은 것은 결과 해석과 본 실험 설계로의 연결임.")
else:
    circle("**전체 실행 결과 반영**: 180건 KB로 Advanced를 다시 생성하고, 회수율·모순 탐지율·공식 로드맵 정렬(특히 2025년판 선견)을 산출해 <표 7>을 갱신함. 마무리 스크립트 한 번으로 돌아가게 준비되어 있음.")
circle("**Generator 모델 2종**: 연구구상 §5.1의 요구대로 gpt-4.1 외에 한 모델을 더 돌려 결과가 모델에 의존하지 않는지 확인함(약 $0.3).")
circle("**본 실험과의 연결**: 지금의 KB는 S4(제안 구조)임. 같은 이벤트 로그에서 구조를 하나씩 빼는 방식(S0 평면 RAG, S1 계층 요약만, S2 엔티티 그래프만, S3 합집합, S4-a~d ablation)으로 비교 조건을 만들 수 있음. 연산 ①~⑦이 구조별로 어디서 막히는지가 곧 ‘로드맵이 이 구조를 요구한다’의 증거가 됨.")
circle("**한계**: (a) 공개 자료의 사실은 모델이 이미 알 수 있으므로 사전지식 오염은 심은 사실과 cutoff 전후 구간 분리로만 통제됨. (b) 가상 자료가 KB의 1/3이라 Advanced가 내부 세부 항목에 치우칠 수 있음(6.3). (c) Router의 병합 임계값(0.80/0.65)은 파일럿 로그로 정한 값이라 다른 도메인에서는 재조정이 필요함. (d) 모순 탐지는 수치가 있는 주장에만 걸어 두어 서술형 모순은 놓침.")
circle("**패키징**: 재생 녹화, 화면 영어 전환, Cambridge 계획서 docx에 데모 절 반영.")
para("지금까지의 코드는 모두 GitHub(PassionChicken-Leesuin/Advanced-Agentic-TRM, main)에 단계별 커밋으로 올라가 있고, 테스트 25개가 통과하며, 공개 코퍼스는 스크립트 한 번으로 재수집됩니다. 전체 실행이 끝나는 대로 결과표를 채워 다시 공유드리겠습니다!")

doc.save(OUT)
print("saved", OUT)
