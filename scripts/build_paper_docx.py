# -*- coding: utf-8 -*-
"""논문 초안(markdown) → docx. 학회지 투고 전 초고용 단순 양식 (바탕 10pt, 제목 가운데, 표는 Table Grid).
python scripts/build_paper_docx.py
"""
import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.abspath(os.path.join(HERE, "..", "..", "연구계획"))
SRC = os.path.join(PLAN, "논문초안_2026-11-03_지식구조기반_에이전틱TRM.md")
OUT = os.path.join(PLAN, "논문초안_2026-11-03_지식구조기반_에이전틱TRM.docx")
FIG1 = os.path.join(PLAN, "그림", "Fig_Framework_TRM_KB_v1.png")

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.5); sec.top_margin = sec.bottom_margin = Cm(2.5)
st = doc.styles["Normal"]; st.font.name = "바탕"; st.font.size = Pt(10)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "바탕")
st.paragraph_format.line_spacing = 1.5


def run(p, text, bold=False, italic=False, size=None):
    for tok in re.split(r"(\*\*.*?\*\*)", text):
        if not tok:
            continue
        b, s = bold, tok
        if tok.startswith("**") and tok.endswith("**"):
            b, s = True, tok[2:-2]
        r = p.add_run(s); r.bold = b; r.italic = italic
        if size:
            r.font.size = Pt(size)


def para(text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, bold=False, size=None, indent=True, italic=False):
    p = doc.add_paragraph(); p.alignment = align
    if indent and align == WD_ALIGN_PARAGRAPH.JUSTIFY:
        p.paragraph_format.first_line_indent = Cm(0.5)
    run(p, text, bold, italic, size)
    return p


def table(header, rows):
    t = doc.add_table(rows=1 + len(rows), cols=len(header)); t.style = doc.styles["Table Grid"]
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.paragraphs[0].text = ""; run(c.paragraphs[0], h, True, size=9); c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for ri, row in enumerate(rows, 1):
        for ci, val in enumerate(row):
            c = t.rows[ri].cells[ci]; c.paragraphs[0].text = ""; run(c.paragraphs[0], val, size=9)
    doc.add_paragraph()


lines = open(SRC, encoding="utf-8").read().split("\n")
i = 0
while i < len(lines):
    ln = lines[i].rstrip()
    if not ln.strip():
        i += 1; continue
    if ln.startswith("# "):
        para(ln[2:], WD_ALIGN_PARAGRAPH.CENTER, True, 15, indent=False); doc.add_paragraph()
    elif ln.startswith("## "):
        p = para(ln[3:], WD_ALIGN_PARAGRAPH.LEFT, True, 12, indent=False); p.paragraph_format.space_before = Pt(14)
    elif ln.startswith("### "):
        p = para(ln[4:], WD_ALIGN_PARAGRAPH.LEFT, True, 10.5, indent=False); p.paragraph_format.space_before = Pt(8)
    elif ln.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            if not all(re.fullmatch(r"-{3,}", c) for c in cells):
                rows.append(cells)
            i += 1
        table(rows[0], rows[1:]); continue
    elif ln.startswith("<표") or ln.startswith("<그림"):
        para(ln, WD_ALIGN_PARAGRAPH.CENTER, False, 9.5, indent=False)
        if ln.startswith("<그림 1>") and os.path.exists(FIG1):
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.add_run().add_picture(FIG1, width=Cm(15.5))
    elif ln.startswith("---"):
        doc.add_page_break()
    elif ln.startswith("주제어:") or ln.startswith("Key Words"):
        para(ln, WD_ALIGN_PARAGRAPH.LEFT, False, 9.5, indent=False)
    elif ln.startswith("이수인*") or ln.startswith("Lee*"):
        para(ln, WD_ALIGN_PARAGRAPH.CENTER, False, 10.5, indent=False)
    elif re.match(r"^[A-Z가-힣].*\(\d{4}\)", ln) and i > len(lines) * 0.6 and "참고문헌" in "\n".join(lines[:i]) and not ln.startswith("본 연구"):
        p = para(ln, WD_ALIGN_PARAGRAPH.LEFT, False, 9.5, indent=False); p.paragraph_format.left_indent = Cm(1.0); p.paragraph_format.first_line_indent = Cm(-1.0); p.paragraph_format.line_spacing = 1.15
    elif ln.startswith("[") and ln.endswith("]"):
        para(ln, WD_ALIGN_PARAGRAPH.JUSTIFY, False, 9.5, italic=True)
    elif re.match(r"^(재현율|연도 오차) = ", ln):
        para(ln, WD_ALIGN_PARAGRAPH.CENTER, False, 10, indent=False)
    else:
        para(ln)
    i += 1

doc.save(OUT)
print("saved", OUT)
