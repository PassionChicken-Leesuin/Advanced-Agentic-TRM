"""영문 소개본에 부록 B(구축 화면 읽는 법: 그래프 그림 + 범례 설명)를 덧붙인다. 기존 본문은 건드리지 않는다.

python scripts/add_appendix_legend.py "<docx>" <evidence.png> <themes.png> <relations.png> <temporal.png>
서식 원형은 부록 A 와 같다 (add_appendix_cost.py 의 도우미 재사용).
"""
from __future__ import annotations

import copy
import sys

import docx
from docx.oxml.ns import qn
from docx.shared import Cm

sys.stdout.reconfigure(encoding="utf-8")
SRC, IMG = sys.argv[1], dict(zip(("evidence", "themes", "relations", "temporal"), sys.argv[2:6]))
TEXT_W = 9638
d = docx.Document(SRC)
assert any(p.text.startswith("Appendix. Processing time") for p in d.paragraphs), "appendix A missing"
assert not any(p.text.startswith("Appendix B") for p in d.paragraphs), "appendix B already present"
body = d.element.body
sect = body.find(qn("w:sectPr"))


def find_p(prefix):
    return next(p for p in d.paragraphs if p.text.startswith(prefix))._p


P_HEAD, P_SUB, P_BUL, P_CAP = find_p("Appendix. Processing"), find_p("A.1 Measured"), find_p("The figures below were measured"), find_p("Table A1.")
T_PROTO = next(t._tbl for t in d.tables if t.rows[0].cells[0].text.strip() == "Card line")


def plain_rpr(p_el):
    for r in p_el.findall(qn("w:r")):
        rp = r.find(qn("w:rPr"))
        rp = copy.deepcopy(rp) if rp is not None else docx.oxml.OxmlElement("w:rPr")
        for tag in ("w:b", "w:bCs", "w:u", "w:highlight", "w:i", "w:iCs"):
            for e in rp.findall(qn(tag)):
                rp.remove(e)
        return rp
    return docx.oxml.OxmlElement("w:rPr")


def set_runs(p_el, text, rpr, bold_all=False):
    import re
    for r in p_el.findall(qn("w:r")):
        p_el.remove(r)
    for i, seg in enumerate(re.split(r"\*\*", text)):
        if not seg:
            continue
        r = docx.oxml.OxmlElement("w:r"); rp = copy.deepcopy(rpr)
        if bold_all or i % 2:
            rp.insert(0, docx.oxml.OxmlElement("w:b"))
        r.append(rp)
        t = docx.oxml.OxmlElement("w:t"); t.text = seg; t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t); p_el.append(r)


def add(el):
    sect.addprevious(el); return el


def para(proto, text, bold_all=False, page_break=False):
    el = copy.deepcopy(proto)
    ppr = el.find(qn("w:pPr"))
    if ppr is not None:
        for pb in ppr.findall(qn("w:pageBreakBefore")):
            ppr.remove(pb)
    set_runs(el, text, plain_rpr(proto), bold_all=bold_all)
    if page_break:
        if ppr is None:
            ppr = docx.oxml.OxmlElement("w:pPr"); el.insert(0, ppr)
        ppr.insert(0, docx.oxml.OxmlElement("w:pageBreakBefore"))
    return add(el)


def table(header, rows, widths):
    t = copy.deepcopy(T_PROTO)
    trs = t.findall(qn("w:tr")); head_tr, body_tr = trs[0], trs[1]
    for tr in trs:
        t.remove(tr)
    grid = t.find(qn("w:tblGrid"))
    for g in list(grid):
        grid.remove(g)
    tot = sum(widths); dxa = [int(TEXT_W * w / tot) for w in widths]
    for w in dxa:
        g = docx.oxml.OxmlElement("w:gridCol"); g.set(qn("w:w"), str(w)); grid.append(g)

    def row(tr_proto, cells, bold):
        tr = copy.deepcopy(tr_proto)
        tcs = tr.findall(qn("w:tc")); first, other = tcs[0], tcs[-1]
        for tc in tcs:
            tr.remove(tc)
        trpr = tr.find(qn("w:trPr"))
        if trpr is None:
            trpr = docx.oxml.OxmlElement("w:trPr"); tr.insert(0, trpr)
        if trpr.find(qn("w:cantSplit")) is None:
            trpr.append(docx.oxml.OxmlElement("w:cantSplit"))
        for j, txt in enumerate(cells):
            tc = copy.deepcopy(first if j == 0 else other)
            tcw = tc.find(qn("w:tcPr")).find(qn("w:tcW"))
            tcw.set(qn("w:w"), str(dxa[j])); tcw.set(qn("w:type"), "dxa")
            ps = tc.findall(qn("w:p"))
            for extra in ps[1:]:
                tc.remove(extra)
            set_runs(ps[0], txt, plain_rpr(ps[0]), bold_all=bold)
            tr.append(tc)
        t.append(tr)
    row(head_tr, header, True)
    for r in rows:
        row(body_tr, r, False)
    return add(t)


def picture(path, width_cm):
    p = d.add_paragraph(); p.alignment = 1
    p.add_run().add_picture(path, width=Cm(width_cm))
    p.paragraph_format.keep_with_next = True
    el = p._p; body.remove(el); return add(el)


H = lambda s, **k: para(P_HEAD, s, bold_all=True, **k)
SUB = lambda s: para(P_SUB, s, bold_all=True)
B = lambda s: para(P_BUL, s)
CAP = lambda s: para(P_CAP, s, bold_all=True)
HDR = ["What you see", "What it means"]
W = [5.2, 11.8]

# ============================================================================ Appendix B
H("Appendix B. Reading the knowledge-structure screen", page_break=True)
B("The Knowledge structures screen of the pilot (Figure 4) shows four boxes that grow as each document is read, with a notation line under each box. "
  "This appendix shows each box as it looks part-way through the IonQ run and explains its notation.")
B("**Colour means the same thing in every box: the roadmap layer.** Shapes tell the kind of knowledge unit, and outlines or line styles tell its state.")
table(["Colour", "Roadmap layer and what it covers"], [
    ["Red", "why: external drivers, markets, customer and stakeholder needs, competition, vision"],
    ["Blue", "what: products and systems, service offerings, milestones and target specifications"],
    ["Green", "how: technologies, components, architectures and methods"],
    ["Yellow", "resource: funding, facilities, partners, standards, skills"],
    ["Pink dot (not a layer)", "the sentence or item comes from an internal document"],
], W)
CAP("Table B1. Colours on the knowledge-structure screen")

SUB("B.1 Evidence store")
picture(IMG["evidence"], 13.5)
CAP("Figure B1. Evidence store after 30 documents")
table(HDR, [
    ["One row", "One sentence quoted verbatim from a document; the newest rows are at the bottom."],
    ["Coloured bar at the left edge", "The roadmap layers the Router gave the sentence. A sentence tagged with two layers shows two colours."],
    ["Outlined tag (WHY, WHAT, HOW, RESOURCE)", "The same layers, written out."],
    ["Filled tag (TREE, GRAPH, TIME)", "The structures the sentence was also sent to: tree = theme summary tree, graph = relation graph, time = temporal knowledge graph. No filled tag means the sentence is kept as evidence only."],
    ["Pink dot and “internal”", "The sentence comes from an internal document."],
    ["new / duplicate / irrelevant (right)", "The Router's status: a new fact; the same fact already stored (row shown faded); boilerplate that is not used (row struck through)."],
], W)
CAP("Table B2. Notation of the evidence store")

SUB("B.2 Theme summary tree")
picture(IMG["themes"], 13.5)
CAP("Figure B2. Theme summary tree after 10 documents")
table(HDR, [
    ["Filled circle", "A theme: a strategic thread that several sentences talk about, for example error correction or cloud access."],
    ["Circle size", "Number of sentences assigned to the theme."],
    ["Circle colour", "The layer that most of the theme's sentences carry (Table B1)."],
    ["Large dashed circle with a name", "An area: a group of related themes formed after all documents are read."],
    ["White ring", "The theme has just received a sentence."],
    ["Hover", "Number of documents per year that touch the theme. No rising or declining label is given, by design: the direction is judged by the reader and the roadmap generator from these counts."],
], W)
CAP("Table B3. Notation of the theme summary tree")

SUB("B.3 Relation graph")
picture(IMG["relations"], 13.5)
CAP("Figure B3. Relation graph after 10 documents")
table(HDR, [
    ["Rounded square", "A shared subject: a product, technology, organisation or application. The same subject is linked across the boxes."],
    ["Square size", "Number of relations the subject takes part in."],
    ["Square colour", "The subject's main layer (Table B1)."],
    ["Arrow with a label", "A relation stated directly in one sentence, from subject to object; the label gives its type."],
    ["Solid line", "requires"],
    ["Long dashes", "enables"],
    ["Short dashes", "drives (creates demand for)"],
    ["Thick faint line", "part of"],
    ["Thin line", "other types: supplies, partners with, customer of, competes with, funds, threatens, addresses, precedes"],
], W)
CAP("Table B4. Notation of the relation graph")

SUB("B.4 Temporal knowledge graph")
picture(IMG["temporal"], 13.5)
CAP("Figure B4. Temporal knowledge graph after 30 documents")
table(HDR, [
    ["Row", "One subject. The small square before its name shows the subject's main layer."],
    ["Horizontal position", "The time the fact is valid, such as a target year or a launch date. The dashed vertical line marks the date of the last document; symbols to its right are statements about the future."],
    ["Circle", "A metric value, for example #AQ 36 or 99.9% fidelity; the value is printed next to it."],
    ["Square", "A lifecycle stage, for example general availability."],
    ["Diamond", "A milestone or event, for example broad quantum advantage."],
    ["Filled symbol", "achieved or current"],
    ["Hollow symbol", "planned or forecast"],
    ["Hollow symbol with a dot", "required: a customer or programme requirement"],
    ["Dashed symbol", "vision"],
    ["Grey curve between symbols", "A later statement about the same subject and attribute."],
    ["Dashed yellow curve", "Update: the value or date was revised."],
    ["Dashed red curve", "Conflict: two documents disagree."],
    ["Faded symbol at the left edge", "A fact without a usable date."],
], W)
CAP("Table B5. Notation of the temporal knowledge graph")

for rp in body.iter(qn("w:rPr")):
    lang = rp.find(qn("w:lang"))
    if lang is None:
        lang = docx.oxml.OxmlElement("w:lang"); rp.append(lang)
    if lang.get(qn("w:val")) is None:
        lang.set(qn("w:val"), "en-US")
d.save(SRC)
print("appendix B added")
