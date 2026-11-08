"""영문 소개본 (Cambridge 협업 후보용) — 진행보고 1103_19시.docx 의 서식을 복제해 새 docx 를 만든다.

python scripts/build_intro_en.py
  입력  연구계획/이수인_KB구축시스템_진행보고_1103_19시.docx  (읽기만 함; 사용자가 손본 원본은 바꾸지 않음)
        연구계획/그림/Fig_Framework_TRM_KB_v2_en.png
  출력  연구계획/SuinLee_Agentic_TRM_KB_Introduction_EN.docx
서식 원형: 제목(0) 작성자(1) 본문(2) 절 제목(6) 글머리(7: numId 17 lvl0, 36: lvl1) 표(8) 캡션(9) 그림 문단(19,23,26,27,30,33)
"""
from __future__ import annotations

import copy
import re
import shutil
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import Cm

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "연구계획" / "이수인_KB구축시스템_진행보고_1103_19시.docx"
FIG1 = ROOT / "연구계획" / "그림" / "Fig_Framework_TRM_KB_v2_en.png"
OUT = ROOT / "연구계획" / "SuinLee_Agentic_TRM_KB_Introduction_EN.docx"
if len(sys.argv) > 1:      # 출력 이름 지정 (예: 열려 있는 파일을 피할 때)
    OUT = ROOT / "연구계획" / sys.argv[1]
TEXT_W = 9638  # 17 cm in dxa

shutil.copyfile(SRC, OUT)          # 복사본 위에서 작업 (원본은 그대로)
d = docx.Document(OUT)
body = d.element.body
kids = [k for k in body.iterchildren() if k.tag != qn("w:sectPr")]
P = {name: kids[i] for name, i in dict(title=0, author=1, text=2, head=6, bullet=7, table=8, caption=9, sub=36,
                                         img_landing=19, img_docs=23, img_build_a=26, img_build_b=27, img_cards=30, img_roadmap=33).items()}
for k in kids:
    body.remove(k)
sect = body.find(qn("w:sectPr"))


def plain_rpr(p_el):
    """원형 문단에서 굵지 않은 첫 run 의 서식 (없으면 첫 run) — 굵게·강조는 지움."""
    runs = p_el.findall(qn("w:r"))
    pick = None
    for r in runs:
        rp = r.find(qn("w:rPr"))
        if rp is None or rp.find(qn("w:b")) is None:
            pick = r; break
    pick = pick if pick is not None else (runs[0] if runs else None)
    rp = copy.deepcopy(pick.find(qn("w:rPr"))) if pick is not None and pick.find(qn("w:rPr")) is not None else docx.oxml.OxmlElement("w:rPr")
    for tag in ("w:b", "w:bCs", "w:highlight", "w:u", "w:i", "w:iCs"):
        for e in rp.findall(qn(tag)):
            rp.remove(e)
    return rp


def runs_into(p_el, text: str, rpr, *, bold_all=False, size_pt: float | None = None, italic=False):
    """**굵게** 표기를 run 으로 나눠 넣는다."""
    for r in p_el.findall(qn("w:r")) + p_el.findall(qn("w:hyperlink")):
        p_el.remove(r)
    for i, seg in enumerate(re.split(r"\*\*", text)):
        if not seg:
            continue
        r = docx.oxml.OxmlElement("w:r")
        rp = copy.deepcopy(rpr)
        if bold_all or i % 2 == 1:
            rp.insert(0, docx.oxml.OxmlElement("w:b"))
        if italic:
            rp.append(docx.oxml.OxmlElement("w:i"))
        if size_pt:
            for e in rp.findall(qn("w:sz")) + rp.findall(qn("w:szCs")):
                rp.remove(e)
            for tag in ("w:sz", "w:szCs"):
                e = docx.oxml.OxmlElement(tag); e.set(qn("w:val"), str(int(size_pt * 2))); rp.append(e)
        r.append(rp)
        t = docx.oxml.OxmlElement("w:t"); t.text = seg; t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t)
        p_el.append(r)
    return p_el


def para(kind: str, text: str, **kw):
    el = copy.deepcopy(P[kind])
    runs_into(el, text, plain_rpr(P[kind]) if kind not in ("title", "head", "caption") else plain_rpr(P[kind]),
              bold_all=kind in ("title", "head", "caption") or kw.pop("bold", False), **kw)
    body.insert(list(body).index(sect), el)
    return el


def image(kind: str):
    el = copy.deepcopy(P[kind])
    body.insert(list(body).index(sect), el)


def picture(path: Path, width_cm: float):
    tmp = d.add_paragraph()
    tmp.alignment = 1
    tmp.add_run().add_picture(str(path), width=Cm(width_cm))
    el = tmp._p
    body.remove(el)
    body.insert(list(body).index(sect), el)


def table(header: list[str], rows: list[list[str]], widths_cm: list[float]):
    proto = P["table"]
    t = copy.deepcopy(proto)
    trs = t.findall(qn("w:tr"))
    head_tr, body_tr = trs[0], trs[1]
    for tr in trs:
        t.remove(tr)
    grid = t.find(qn("w:tblGrid"))
    for g in list(grid):
        grid.remove(g)
    tot = sum(widths_cm)
    dxa = [int(TEXT_W * w / tot) for w in widths_cm]
    for w in dxa:
        g = docx.oxml.OxmlElement("w:gridCol"); g.set(qn("w:w"), str(w)); grid.append(g)
    tblw = t.find(qn("w:tblPr")).find(qn("w:tblW"))
    if tblw is not None:
        tblw.set(qn("w:w"), str(TEXT_W)); tblw.set(qn("w:type"), "dxa")

    def make_row(tr_proto, cells, header_row):
        tr = copy.deepcopy(tr_proto)
        tcs = tr.findall(qn("w:tc"))
        first, other = tcs[0], tcs[-1]
        for tc in tcs:
            tr.remove(tc)
        for j, txt in enumerate(cells):
            tc = copy.deepcopy(first if j == 0 else other)
            tcpr = tc.find(qn("w:tcPr"))
            tcw = tcpr.find(qn("w:tcW")) if tcpr is not None else None
            if tcw is not None:
                tcw.set(qn("w:w"), str(dxa[j])); tcw.set(qn("w:type"), "dxa")
            ps = tc.findall(qn("w:p"))
            for extra in ps[1:]:
                tc.remove(extra)
            p0 = ps[0]
            rpr = plain_rpr(p0)
            lines = txt.split("\n")
            runs_into(p0, lines[0], rpr, bold_all=header_row)
            for ln in lines[1:]:
                pn = copy.deepcopy(p0); runs_into(pn, ln, rpr, bold_all=header_row); tc.append(pn)
            tr.append(tc)
        t.append(tr)
    make_row(head_tr, header, True)
    for r in rows:
        make_row(body_tr, r, False)
    body.insert(list(body).index(sect), t)


def box(title: str, text: str):
    """요약 상자: 원형 표의 본문 칸 하나짜리 표."""
    proto = P["table"]
    t = copy.deepcopy(proto)
    trs = t.findall(qn("w:tr"))
    for tr in trs:
        t.remove(tr)
    grid = t.find(qn("w:tblGrid"))
    for g in list(grid):
        grid.remove(g)
    g = docx.oxml.OxmlElement("w:gridCol"); g.set(qn("w:w"), str(TEXT_W)); grid.append(g)
    tr = copy.deepcopy(trs[1])
    tcs = tr.findall(qn("w:tc"))
    tc = copy.deepcopy(tcs[-1])
    for x in tcs:
        tr.remove(x)
    tcpr = tc.find(qn("w:tcPr"))
    tcw = tcpr.find(qn("w:tcW"))
    tcw.set(qn("w:w"), str(TEXT_W)); tcw.set(qn("w:type"), "dxa")
    ps = tc.findall(qn("w:p"))
    for extra in ps[1:]:
        tc.remove(extra)
    rpr = plain_rpr(ps[0])
    runs_into(ps[0], title, rpr, bold_all=True)
    pn = copy.deepcopy(ps[0]); runs_into(pn, text, rpr)
    jc = pn.find(qn("w:pPr")).find(qn("w:jc")) if pn.find(qn("w:pPr")) is not None else None
    if jc is not None:
        jc.set(qn("w:val"), "both")
    tc.append(pn)
    tr.append(tc)
    t.append(tr)
    body.insert(list(body).index(sect), t)


B, S, T = (lambda s: para("bullet", s)), (lambda s: para("sub", s)), (lambda s: para("text", s))

# ============================================================================ 본문
para("title", "Agentic Knowledge Base Construction for Technology Roadmapping: A Pilot System")
para("author", "Suin Lee, DDSI Lab, Seoul National University (November 2026)")
para("author", "Pilot system: https://agentic-trm-site.vercel.app")
box("Summary",
    "An agent reads a firm's documents and builds three kinds of firm-specific knowledge structures from them: a theme summary tree, "
    "a relation graph and a temporal knowledge graph. It then assembles the knowledge on each candidate opportunity into an opportunity card, "
    "selects the opportunities to pursue through a multi-AI-agent debate, and writes a technology roadmap whose every item traces back to the "
    "source documents. The pilot applies this pipeline to 180 documents on IonQ, a trapped-ion quantum computing company, and can be explored online.")

para("head", "1. Motivation")
B("A roadmapping workshop gathers a wide range of perspectives into a shared strategic landscape. Its knowledge base, however, is largely the "
  "participants' memory, and the connection between the source data and the content of the roadmap is easily lost. Phaal and Palmer (2010) note that "
  "keeping this connection is what makes a roadmap **maintainable and auditable**.")
B("What a firm or an industry needs is not a generic roadmap of a technology field but **a roadmap of its own**. Each organisation differs in "
  "business context, resources and technology types, so roadmapping has to be customised, down to the layers of the roadmap, to the particular "
  "organisation and problem; the same holds when a group of stakeholders roadmaps a technology or application area together (Phaal et al., 2004). "
  "A useful roadmap starts from the firm's or the industry's own products, capabilities, customers, partners and constraints, and from what its own "
  "documents say about them.")
B("Large language models can read an entire document corpus and can write a plausible roadmap of a technology field from general knowledge. Such a "
  "roadmap is generic: it does not know the firm's internal requirements, plans and constraints, and it cannot show where each item comes from.")
B("This research asks **what knowledge an agent should build from a firm's or an industry's own documents, and in what form, so that a firm- or "
  "industry-specific technology roadmap can be written from it and every item traced back to its source.** The system is general; the knowledge base "
  "it builds, and the roadmap written from it, are specific to the firm or industry whose documents it reads. The object of study is therefore the "
  "system that constructs the knowledge base, not one particular knowledge base.")

para("head", "2. From S-Plan to an agentic process")
B("Workshop roadmapping following S-Plan builds a strategic landscape (a), selects the opportunities to focus on (b), explores the linkages of each "
  "selected opportunity (c) and places the items in time (d). Table 1 sets these steps against the agentic process.")
table(["Step", "Workshop (S-Plan)", "Agentic process"], [
    ["a. Landscaping", "Participants place trends and drivers, stakeholder needs, current activities and milestones on a layered, time-based template "
                       "(Phaal et al., 2007; Trueman, 2014).", "The agent reads all documents in date order and accumulates the landscape in three knowledge structures."],
    ["b. Opportunity selection", "Opportunities are generated broadly (typically 30–80), clustered, and prioritised by vote against agreed criteria, "
                                 "usually to 10–15 (Phaal et al., 2007).", "Done last: a multi-AI-agent debate compares opportunity cards that already carry their linkages and timing."],
    ["c. Linkage", "Small groups write a topic roadmap for each selected opportunity; linkage grids are derived from these plans (Trueman, 2014).",
                   "Done for every candidate during landscaping (relation graph) and assembled per opportunity into a card."],
    ["d. Timing", "Items are placed from the current state through short, medium and long term to the vision, and integrated into one roadmap (Trueman, 2014).",
                  "Done for every candidate during landscaping (temporal knowledge graph)."],
], [3.0, 7.3, 6.7])
para("caption", "Table 1. Workshop roadmapping steps (S-Plan) and their counterparts in the agentic process")
B("In a workshop, linkage (c) and timing (d) follow selection (b) because participants cannot work them out for every candidate in the time available. "
  "An agent that has read every document can. In the Quantum Technology roadmap, the capability and enabler linkage charts were built from the "
  "per-opportunity plans (Trueman, 2014, p. 20); the agent derives the same information for all candidates first, so that **selection works on richer "
  "information**. The order becomes landscaping (a + c + d), opportunity cards, opportunity selection (b), and roadmap writing (Figure 1).")
picture(FIG1, 17.0)
para("caption", "Figure 1. Overall framework: landscaping, opportunity cards, opportunity selection by multi-AI-agent debate, and roadmap making")

para("head", "3. System")
para("text", "**3.1 Reading and routing**")
B("The **Reader** quotes, verbatim, every sentence in a document that a roadmap could use, and restates each one as a self-contained claim. "
  "It does not classify. A quote that cannot be found in the source text is discarded.")
B("The **Router** decides for each sentence whether to keep it, tags the roadmap layers it informs (why, what, how, resource), links it to shared "
  "subjects such as products, technologies and organisations, and chooses which knowledge structures it should feed. One sentence can feed several.")
para("text", "**3.2 Three firm-specific knowledge structures**")
B("Each structure serves a different roadmapping function and takes the form that function needs (Table 2).")
table(["Structure", "What it stores", "Roadmapping function", "Related approaches"], [
    ["Theme summary tree", "Sentences grouped into themes and themes into areas, with summaries per theme, per area and per year, and the number of documents "
                           "per year that touch each theme (no trend labels).", "Trend synthesis: where the firm, its market and its competitors are heading",
     "RAPTOR (Sarthi et al., 2024); GraphRAG community summaries (Edge et al., 2024)"],
    ["Relation graph", "(subject, relation, subject) statements made directly in a sentence, in 12 relation types such as requires, enables, supplies, "
                       "customer of and threatens.", "Linkage between drivers, offerings, capabilities and resources",
     "GraphRAG (Edge et al., 2024); linkage grids (Phaal et al., 2004; Trueman, 2014)"],
    ["Temporal knowledge graph", "(subject, attribute, value, valid time, stated time) facts in three families: metrics, lifecycle stages and milestones. "
                                 "Revisions are chained as updates or conflicts, never overwritten.", "Timing: when targets, launches and milestones fall, and how they were revised",
     "Zep bi-temporal model (Rasmussen et al., 2025)"],
], [3.0, 6.6, 3.9, 3.5])
para("caption", "Table 2. The three knowledge structures")
B("The three structures rest on two shared foundations. The **glossary** holds the firm's controlled vocabulary: canonical names, aliases, units and "
  "product generations, so that every structure names things the same way (Gruber, 1993). The **evidence store** keeps every stored sentence verbatim "
  "with its layer tags; every item in the structures, the cards and the roadmap cites sentence ids.")
B("After all documents are read, a consolidation step merges subjects and themes that were split under different names and writes the theme and area summaries.")
para("text", "**3.3 Opportunity cards**")
B("While reading, the Router sends sentences that name an application area or a product type for a market to an opportunity extractor, which writes "
  "candidate records. Generic names, organisations, technologies and concrete products are then removed from the candidates; products remain as offerings.")
B("Each remaining candidate becomes one card, modelled on the topic roadmap that a workshop group would write for it (Trueman, 2014). Every card has the "
  "same nine lines, filled from the knowledge structures (Table 3); a line reads “none stated” when the documents say nothing. Cards are not ranked "
  "at this stage, and platform offerings shared by many cards are named but not expanded, so that cards stay distinct.")
table(["Card line", "Content", "Filled from"], [
    ["head", "Opportunity name and kind (application area or product type), target markets and customers, maturity, number of documents (public / internal), period mentioned",
     "Opportunity records, relation graph, temporal knowledge graph"],
    ["now", "Latest lifecycle stage of the offering", "Temporal knowledge graph"],
    ["why", "The firm's need, driver and vision sentences, verbatim", "Evidence store"],
    ["trend", "Documents per year for the themes the card's sentences belong to", "Theme summary tree"],
    ["what", "Offerings and sub-products, with their latest facts", "Relation graph, temporal knowledge graph"],
    ["when", "Every dated statement on the card's subjects, with updates and conflicts", "Temporal knowledge graph"],
    ["how", "Capabilities and components linked by stated relations, with their latest metrics", "Relation graph, temporal knowledge graph"],
    ["resource", "Enablers: facilities, partners, funding, standards", "Relation graph"],
    ["actors", "Customers, partners and competitors", "Relation graph"],
    ["issue", "Risks, barriers, decisions and open questions", "Evidence store, relation graph"],
], [2.2, 9.6, 5.2])
para("caption", "Table 3. The nine lines of an opportunity card and the structures that fill them")
para("text", "**3.4 Opportunity selection by multi-AI-agent debate**")
B("Three AI agents, each running on a different language model (GPT-4.1, Claude Sonnet 4.6 and Gemini 2.5 Flash), assess every card on the three "
  "questions of roadmapping (Phaal et al., 2007; Phaal and Palmer, 2010), adapted to a single opportunity and answered only from the card:")
S("**Q1. Where do we want to go?** Who demands the opportunity, for what, under what conditions and by when, and whether the firm has stated this direction itself.")
S("**Q2. Where are we now?** The offering's lifecycle stage (exploring, pilot, contracted, revenue), its latest capability metrics, and the customers, partners and resources already secured.")
S("**Q3. How can we get there?** Whether the gap between the required specification and current capability is documented, together with a dated plan to close it.")
B("In the first round each agent scores the three questions from 0 to 10, citing the card lines that support each score. In the second round each agent reads "
  "the others' assessments, replies and gives final scores. Scores without valid evidence are dropped, and a card's profile is the mean of the grounded "
  "final scores. The agents run on different models on purpose: the panel is a crowd of different priors rather than one model playing personas.")
B("The user chooses which question should lead: all three equally, or Q1, Q2 or Q3 first. The top ten cards under that stance are selected. Because the "
  "full debate is kept, the selection step is **reproducible and auditable**.")
para("text", "**3.5 Roadmap writing**")
B("The generator reads the glossary, a summary of the landscape and the selected cards in full, together with the panel's reasons, and writes a roadmap "
  "with why, what, how and resource layers over 2025–2030. Why lines become why nodes; offerings and dated targets become what nodes placed by their latest "
  "statement, with revised targets flagged; how and resource lines become how and resource nodes; stated relations become edges. Demand without a "
  "documented path is kept and flagged rather than dropped.")
B("Every node cites the sentences and dated facts it rests on. The instructions, output format and model are the same as for a generator without a "
  "knowledge base, so that the contribution of the knowledge base can be isolated.")

para("head", "4. Pilot system")
B("The pilot builds a knowledge base for **IonQ**, a trapped-ion quantum computing company. The documents end on 31 December 2024, so that the roadmap "
  "for 2025–2030 can later be compared with what the firm actually published afterwards.")
B("The corpus has **180 documents**: 130 public documents collected from SEC filings, press releases, blog posts, investor presentations, industry reports "
  "and arXiv papers, and 50 synthetic internal documents such as meeting minutes, R&D reports and customer and supplier emails. The internal documents "
  "were generated from a ledger of 42 invented facts (requirements, plans, decisions, lead times) to supply the kind of knowledge that public documents "
  "rarely contain. All figures and names in them are fictional and unrelated to IonQ.")
B("The site walks through four screens: Documents, Knowledge structures, Opportunity cards and Roadmap (Figures 2–6).")
image("img_landing")
para("caption", "Figure 2. Entry screen")
image("img_docs")
para("caption", "Figure 3. Documents: the prepared corpus by document type")
B("**Knowledge structures.** The recorded construction is replayed document by document. The evidence store fills with quoted sentences and their layer "
  "tags, and the theme summary tree, relation graph and temporal knowledge graph grow as the Router dispatches each sentence. New glossary terms appear "
  "along the top. The side panel shows progress, the size of each structure, how the Router dispatches sentences by document type, and its decision log.")
image("img_build_a")
image("img_build_b")
para("caption", "Figure 4. Knowledge structures growing in real time (top: in progress; bottom: complete)")
B("**Opportunity cards.** The first step shows the candidates extracted while reading and those excluded, with the reason for each exclusion. The second "
  "step shows one card per candidate; a card opens to show every line with its source ids.")
image("img_cards")
para("caption", "Figure 5. From opportunity candidates to one card per opportunity")
B("**Roadmap.** The user chooses which question should lead, sees the ten selected cards with the panel's scores and reasons, and builds the roadmap. "
  "Clicking a node shows its description and the source sentences it cites. The same screen shows the roadmap written without a knowledge base for comparison.")
image("img_roadmap")
para("caption", "Figure 6. Opportunity selection and the roadmap written from the selected cards")

para("head", "5. Limitations and next steps")
B("The pilot covers one firm in one industry; how well the structures transfer to other firms and domains is untested.")
B("The internal documents are synthetic. Real internal material would differ in volume, noise and coverage.")
B("The knowledge base is built once from a fixed corpus. The temporal knowledge graph records revisions within the corpus, but updating, versioning and "
  "resolving contradictions across successive builds are outside the current scope.")
B("Evaluation against the roadmaps the firm published after the cut-off is under way. Milestone-based measures do not yet capture the market and application "
  "side that the opportunity cards emphasise, so measures for grounded linkages and for the stability of selection are being designed.")
B("Candidate opportunities are named somewhat differently from one build to the next; anchoring their names in the glossary is a next step, along with a "
  "second version of the corpus that spreads the internal documents over 2021–2024 so that internal knowledge also shows change over time.")

para("head", "References")
for ref in [
    "Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S. and Larson, J. (2024), “From Local to Global: A Graph RAG Approach to Query-Focused Summarization,” arXiv:2404.16130.",
    "Gruber, T. R. (1993), “A Translation Approach to Portable Ontology Specifications,” Knowledge Acquisition, 5(2), pp. 199–220.",
    "Phaal, R., Farrukh, C. J. P. and Probert, D. R. (2004), “Technology Roadmapping—A Planning Framework for Evolution and Revolution,” Technological Forecasting and Social Change, 71(1–2), pp. 5–26.",
    "Phaal, R., Farrukh, C. J. P. and Probert, D. R. (2007), “Strategic Roadmapping: A Workshop-Based Approach for Identifying and Exploring Strategic Issues and Opportunities,” Engineering Management Journal, 19(1), pp. 3–12.",
    "Phaal, R. and Palmer, P. J. (2010), “Technology Management—Structuring the Strategic Dialogue,” Engineering Management Journal, 22(1), pp. 64–74.",
    "Rasmussen, P., Paliychuk, P., Beauvais, T., Ryan, J. and Chalef, D. (2025), “Zep: A Temporal Knowledge Graph Architecture for Agent Memory,” arXiv:2501.13956.",
    "Sarthi, P., Abdullah, S., Tuli, A., Khanna, S., Goldie, A. and Manning, C. D. (2024), “RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval,” International Conference on Learning Representations.",
    "Trueman, J. (2014), Quantum Technology Roadmap Report: Consolidated from Workshops in London and Glasgow, IfM Education and Consultancy Services, University of Cambridge, for the Technology Strategy Board.",
]:
    T(ref)

# 글자 방향·언어: 영문 문서이므로 run 언어를 en-US 로 (맞춤법 검사)
for rp in body.iter(qn("w:rPr")):
    lang = rp.find(qn("w:lang"))
    if lang is None:
        lang = docx.oxml.OxmlElement("w:lang"); rp.append(lang)
    lang.set(qn("w:val"), "en-US")
d.core_properties.title = "Agentic Knowledge Base Construction for Technology Roadmapping: A Pilot System"
d.core_properties.author = "Suin Lee"
d.save(OUT)
sys.stdout.reconfigure(encoding="utf-8")
print("wrote", OUT)
