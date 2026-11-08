"""영문 소개본(사용자가 손본 파일)에 부록(처리 시간·비용, 줄이는 방법, 500건 추정)을 덧붙인다. 기존 본문은 건드리지 않는다.

python scripts/add_appendix_cost.py "<docx 경로>"
서식은 문서 안의 원형을 복제한다: 절 제목('5. Limitations and next steps'), 소제목('3.1 Reading and routing'),
글머리('The pilot covers one firm'), 표(표 3 'Card line'), 캡션('Table 3.'). 참고문헌 뒤, 새 쪽에서 시작.
수치 출처: runs/struct5/cost_*.json, runs/struct5_build.log, cards_v2/selection/run_log.txt, cards_v2/roadmaps/rm_*.json,
          runs/bp_compare.md (40건 묶음 시범). 500건 값은 추정.
"""
from __future__ import annotations

import copy
import re
import sys

import docx
from docx.oxml.ns import qn

sys.stdout.reconfigure(encoding="utf-8")
SRC = sys.argv[1]
TEXT_W = 9638
d = docx.Document(SRC)
assert not any(p.text.startswith("Appendix") for p in d.paragraphs), "appendix already present"
body = d.element.body
sect = body.find(qn("w:sectPr"))


def find_p(prefix):
    hits = [p for p in d.paragraphs if p.text.startswith(prefix)]
    assert hits, prefix
    return hits[0]._p


P_HEAD, P_SUB, P_BUL, P_CAP = find_p("5. Limitations"), find_p("3.1 Reading"), find_p("The pilot covers one firm"), find_p("Table 3.")
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
    for r in p_el.findall(qn("w:r")) + p_el.findall(qn("w:hyperlink")):
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
    sect.addprevious(el)
    return el


def para(proto, text, bold_all=False, page_break=False):
    el = copy.deepcopy(proto)
    set_runs(el, text, plain_rpr(proto), bold_all=bold_all)
    if page_break:
        ppr = el.find(qn("w:pPr"))
        if ppr is None:
            ppr = docx.oxml.OxmlElement("w:pPr"); el.insert(0, ppr)
        pb = docx.oxml.OxmlElement("w:pageBreakBefore"); ppr.insert(0, pb)
    return add(el)


def table(header, rows, widths, bold_last=False):
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
        # 줄이 쪽 경계에서 갈라지지 않게
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
    for k, r in enumerate(rows):
        row(body_tr, r, bold_last and k == len(rows) - 1)
    return add(t)


H = lambda s, **k: para(P_HEAD, s, bold_all=True, **k)
SUB = lambda s: para(P_SUB, s, bold_all=True)
B = lambda s: para(P_BUL, s)
CAP = lambda s: para(P_CAP, s, bold_all=True)

# ============================================================================ Appendix
H("Appendix. Processing time and cost", page_break=True)
SUB("A.1 Measured time and cost of the 180-document pilot")
B("The figures below were measured on the IonQ pilot: 180 documents yielding 6,019 quoted sentences. Times are wall-clock times on one "
  "workstation calling the models through an API, with up to 20 calls in flight; manual inspection between stages is excluded.")
table(["Stage", "What runs", "Models", "Time", "Cost (USD)"], [
    ["Reading", "180 documents quoted verbatim into 6,019 sentences (1,936 calls)", "Claude Haiku 5.5 (quoting); GPT-4.1 nano (screening)", "10.7 min", "1.12"],
    ["Construction", "Glossary, Router and four extractors per document, one document at a time in date order (1,076 calls)", "GPT-4.1 mini; GPT-4.1 (temporal facts)", "94.5 min", "5.39"],
    ["Consolidation", "Merging subjects and themes; theme summaries and areas (321 calls)", "GPT-4.1 mini; GPT-4.1", "4 min", "0.56"],
    ["Repair pass", "One-off fix after inspection: undoing over-merged subjects, re-planning theme areas", "GPT-4.1 mini; GPT-4.1", "—", "0.46"],
    ["Opportunity cards", "59 cards assembled by code", "none", "seconds", "0"],
    ["Selection", "62 cards × 3 AI agents × 2 rounds", "GPT-4.1; Claude Sonnet 4.6; Gemini 2.5 Flash", "7.2 min", "2.85"],
    ["Roadmap writing", "One roadmap per stance (4 stances)", "GPT-4.1", "1.5 min", "0.36"],
    ["Total", "", "", "about 2 hours", "about 10.7 (≈0.06 per document)"],
], [2.4, 6.2, 4.2, 1.9, 2.3], bold_last=True)
CAP("Table A1. Time and cost of each stage, 180-document pilot")
B("**Construction takes about 80% of the time.** It runs one document at a time on purpose: each document is routed against the knowledge base built "
  "from the documents before it, so that a fact already stored is recognised as a duplicate and a revised target is chained to the earlier one. "
  "The median document takes 25 s (mean 33 s, slowest 250 s).")
B("**Construction is also about half of the cost, and selection about a quarter.** Evaluation runs, which compare roadmaps with those the firm published "
  "later, are research costs and are not included.")

SUB("A.2 How time and cost can be reduced")
B("**Batched construction (implemented, under test).** In each of the three rounds (glossary, Router, extractors), the model calls for 20 documents are "
  "sent at once and their results are applied in date order. On a 40-document sample with identical quoted sentences, construction fell from 880 s to "
  "155 s at the same cost, and the Router's decisions agreed with a one-at-a-time run as closely as two one-at-a-time runs agree with each other. "
  "Themes come out about twice as fine-grained, because documents in the same batch cannot see each other's new themes; assigning themes one document "
  "at a time within each batch is the next fix.")
B("**Parallel reading (implemented).** Reading is independent for each document, so 20 documents are now read at once instead of 4.")
B("**Prompt caching (planned).** Every construction call repeats the same instructions and glossary. Caching that shared prefix lowers the input cost "
  "with providers that support it.")
B("**Debating only supported candidates (option).** About half of the cards rest on a single document. Debating only cards supported by at least two "
  "documents would roughly halve the selection cost; single-document cards would still be shown, unranked.")
B("**Incremental updates (option).** New documents can be routed into the existing knowledge base instead of rebuilding it, so that only "
  "consolidation and the cards that change are redone.")

SUB("A.3 Projection to 500 documents")
B("Assuming the same mix of documents, reading and construction grow in proportion to the number of documents. Consolidation grows somewhat faster, "
  "because the pairs of subjects to compare grow with the size of the knowledge base, while the number of opportunity cards grows more slowly than "
  "the number of documents. The values in Table A2 are estimates, not measurements.")
table(["Stage", "Time, one document at a time", "Time, batched construction", "Cost (USD)"], [
    ["Reading (20 documents at once)", "≈10 min", "≈10 min", "≈3"],
    ["Construction", "≈4.4 h", "≈50–60 min", "≈15"],
    ["Consolidation", "≈10–20 min", "≈10–20 min", "≈1.5–3"],
    ["Selection (≈100–150 cards)", "≈12–18 min", "≈12–18 min", "≈4.5–7"],
    ["Roadmap writing", "≈2 min", "≈2 min", "≈0.4"],
    ["Total", "≈5 h", "≈1.5–2 h", "≈24–28 (≈0.05 per document)"],
], [4.4, 4.0, 4.0, 4.6], bold_last=True)
CAP("Table A2. Estimated time and cost for 500 documents")
B("With batched construction and the debate limited to candidates supported by at least two documents, a 500-document run would take about "
  "1.5 hours and cost roughly US$22–25.")

for rp in body.iter(qn("w:rPr")):      # 영문 맞춤법 검사 언어
    lang = rp.find(qn("w:lang"))
    if lang is None:
        lang = docx.oxml.OxmlElement("w:lang"); rp.append(lang)
    if lang.get(qn("w:val")) is None:
        lang.set(qn("w:val"), "en-US")
d.save(SRC)
print("appendix added to", SRC)
