"""프레임워크 그림 v2 (영문) — Landscaping → Opportunity cards → Opportunity selection (LLM debate) → Roadmap making.
양식은 v1 과 같음 (흰 바탕, 검은 테두리, Times 계열, 회색 입출력 상자, 파란 블록 화살표, 빨간 강조).
python scripts/fig_framework_v2.py  →  연구계획/그림/Fig_Framework_TRM_KB_v2.svg (+ headless 브라우저로 .png)
"""
import subprocess
from pathlib import Path

W, H = 1500, 900
FONT = "Liberation Serif, Times New Roman, serif"
BLUE, GREY, LIGHT, RED, GREEN = "#4472C4", "#E7E6E6", "#F2F2F2", "#FF0000", "#548235"
out: list[str] = []


def text(x, y, s, size=11, bold=False, italic=False, anchor="middle", fill="#000000"):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{"bold" if bold else "normal"}" '
               f'font-style="{"italic" if italic else "normal"}" fill="{fill}" text-anchor="{anchor}" dominant-baseline="middle">{s}</text>')


def box(x, y, w, h, lines, fill="#FFFFFF", stroke="#000000", sw=1.2, size=11, title=None, title_fill=BLUE, lh=None, align="middle", pad=8):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    top = y
    if title:
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="22" fill="{title_fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        text(x + w / 2, y + 11, title, size=11, bold=True, fill="#FFFFFF")
        top = y + 22
    lh = lh or size + 3
    n = len(lines)
    y0 = top + (h - (top - y)) / 2 - (n - 1) * lh / 2 if align == "middle" else top + pad + lh / 2
    for i, ln in enumerate(lines):
        b = it = False
        if ln.startswith("**"):
            b, ln = True, ln[2:]
        if ln.startswith("__"):
            it, ln = True, ln[2:]
        tx = x + w / 2 if align == "middle" else x + pad
        text(tx, y0 + i * lh, ln, size=size, bold=b, italic=it, anchor="middle" if align == "middle" else "start")


def arrow_r(x, y, L=36, h=16, head=14, fill=BLUE):
    s = h / 2
    out.append(f'<path d="M{x},{y - s} L{x + L - head},{y - s} L{x + L - head},{y - s - 6} L{x + L},{y} L{x + L - head},{y + s + 6} '
               f'L{x + L - head},{y + s} L{x},{y + s} Z" fill="{fill}"/>')


def arrow_d(x, y, L=30, h=16, head=12, fill=BLUE):
    s = h / 2
    out.append(f'<path d="M{x - s},{y} L{x - s},{y + L - head} L{x - s - 6},{y + L - head} L{x},{y + L} L{x + s + 6},{y + L - head} '
               f'L{x + s},{y + L - head} L{x + s},{y} Z" fill="{fill}"/>')


def line(x1, y1, x2, y2, sw=1.2, dash=None, marker=False, color="#000000"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#arr)"' if marker else ""
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d}{m}/>')


# ------------------------------------------------------------------ 캔버스
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
out.append('<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse">'
           '<path d="M0,0 L10,5 L0,10 Z" fill="#000000"/></marker></defs>')
out.append('<rect width="100%" height="100%" fill="white"/>')
out.append(f'<rect x="20" y="20" width="{W - 40}" height="{H - 40}" fill="#FFFFFF" stroke="#000000" stroke-width="1.2"/>')

text(W / 2, 44, "Agentic technology roadmapping: Landscaping  →  Opportunity cards  →  Opportunity selection by LLM debate  →  Roadmap making", 16, bold=True)

# 워크숍 순서 대 에이전트 순서 (상단 띠)
box(45, 62, W - 90, 46, [
    "__Workshop (Cambridge S-Plan):  (a) landscape  →  (b) select opportunities by vote  →  (c) link the selected ones (topic roadmaps, linkage grids)  →  (d) place them in time",
    "__Agent:  (a)+(c)+(d) for every candidate (the agent has read all documents)  →  one card per opportunity  →  (b) select by debate  →  make the roadmap from the selected cards",
], fill=LIGHT, size=10.5, lh=16)

STAGE_Y, STAGE_H = 122, 590

# ================================================================== Stage 1  Landscaping
x1, w1 = 45, 330
out.append(f'<rect x="{x1}" y="{STAGE_Y}" width="{w1}" height="{STAGE_H}" fill="none" stroke="#000000" stroke-width="1" stroke-dasharray="4,3"/>')
text(x1 + w1 / 2, STAGE_Y + 14, "Stage 1  Landscaping", 13, bold=True)
box(x1 + 12, 150, 306, 56, ["**Company documents, in date order", "IonQ 2020–2024: SEC filings, blogs, press releases,", "papers, internal memos (synthetic)"], fill=GREY, size=10)
arrow_d(x1 + w1 / 2, 206, L=24)
box(x1 + 12, 230, 306, 50, ["**Reader", "quotes every roadmap-usable sentence verbatim;", "no classification"], size=10)
arrow_d(x1 + w1 / 2, 280, L=24)
box(x1 + 12, 304, 306, 74, ["**Router  (per passage)", "keep? · layer tag (why/what/how/resource) · kind",
                            "· modality · shared subject · which structures receive it", "+ opportunity record when a passage names an opportunity"], size=10, stroke=RED, sw=2)
arrow_d(x1 + w1 / 2, 378, L=24)
# 구조들
box(x1 + 12, 402, 306, 22, ["**Glossary  (canonical names, aliases, units, product generations)"], fill=LIGHT, size=9.5)
box(x1 + 12, 428, 306, 22, ["**Evidence store  (verbatim passages + layer tags; every item cites it)"], fill=LIGHT, size=9.5)
gy = 460
box(x1 + 12, gy, 96, 118, ["**Theme", "**summary tree", "passage → theme", "→ area;", "documents per", "year (no labels)"], size=9.5, lh=13)
box(x1 + 117, gy, 96, 118, ["**Relation", "**graph", "(subject, relation,", "subject) stated", "in documents;", "12 relation types"], size=9.5, lh=13)
box(x1 + 222, gy, 96, 118, ["**Temporal", "**knowledge graph", "(subject, attribute,", "value, valid time,", "stated time); update/", "conflict chains"], size=9.5, lh=13)
box(x1 + 12, 590, 306, 44, ["Consolidation after all documents: merge split subjects/themes;", "build theme and area summaries"], fill=LIGHT, size=9.5)
text(x1 + w1 / 2, 660, "= workshop steps (a), (c), (d) for every subject", 10, italic=True)
text(x1 + w1 / 2, 678, "(nothing is selected yet)", 10, italic=True)

# ================================================================== Stage 2  Opportunity cards
x2, w2 = 395, 330
arrow_r(x1 + w1 + 2, STAGE_Y + STAGE_H / 2, L=18, h=14, head=10)
out.append(f'<rect x="{x2}" y="{STAGE_Y}" width="{w2}" height="{STAGE_H}" fill="none" stroke="#000000" stroke-width="1" stroke-dasharray="4,3"/>')
text(x2 + w2 / 2, STAGE_Y + 14, "Stage 2  Opportunity cards", 13, bold=True)
box(x2 + 12, 150, 306, 70, ["**Candidates  (opportunity records written while reading)", "opportunity = application area or product type + market;",
                            "fields: customer, offering, drivers, needs, maturity.", "Generic names, organizations, technologies, concrete products removed."], size=9.5, lh=13)
arrow_d(x2 + w2 / 2, 220, L=24)
# 카드
cx, cy, cw, ch = x2 + 12, 248, 306, 352
out.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" fill="#FFFFFF" stroke="#000000" stroke-width="1.6"/>')
out.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="24" fill="{BLUE}"/>')
text(cx + cw / 2, cy + 12, "One card per candidate  =  a topic roadmap page", 11, bold=True, fill="#FFFFFF")
rows = [("head", "name · kind · markets · stage · docs (public / internal)", "records · relation graph · temporal graph"),
        ("now", "current lifecycle stage of the offering", "temporal graph"),
        ("why", "the company's need / driver / vision sentences, verbatim", "evidence store"),
        ("trend", "documents per year for the card's themes (no label)", "theme tree"),
        ("what", "offerings and their latest facts", "relation graph + temporal graph"),
        ("when", "every dated statement, chained; UPDATE / CONFLICT", "temporal graph"),
        ("how", "capabilities linked by stated relations, latest metrics", "relation graph + temporal graph"),
        ("resource", "enablers: facilities, partners, funding, standards", "relation graph"),
        ("actors", "customers, partners, competitors", "relation graph"),
        ("issue", "risks, barriers, decisions, open questions", "evidence store + relation graph")]
ry = cy + 30
for k, (lab, desc, src) in enumerate(rows):
    y = ry + k * 32
    out.append(f'<rect x="{cx + 6}" y="{y}" width="{cw - 12}" height="28" fill="{LIGHT if k % 2 else "#FFFFFF"}" stroke="#BBBBBB" stroke-width="0.8"/>')
    text(cx + 12, y + 9, lab, 9.5, bold=True, anchor="start")
    text(cx + 12, y + 21, desc, 8.6, anchor="start")
    text(cx + cw - 10, y + 9, "← " + src, 7.8, italic=True, anchor="end", fill="#555555")
text(x2 + w2 / 2, 618, "Same nine lines on every card; a line reads \"none stated\" when", 9.5, italic=True)
text(x2 + w2 / 2, 634, "the documents say nothing. Every item cites passage / fact ids.", 9.5, italic=True)
text(x2 + w2 / 2, 660, "No ranking here — the platform offerings shared by many cards", 9.5, italic=True)
text(x2 + w2 / 2, 676, "are named but not expanded, so cards stay distinct.", 9.5, italic=True)

# ================================================================== Stage 3  Selection by debate
x3, w3 = 745, 350
arrow_r(x2 + w2 + 2, STAGE_Y + STAGE_H / 2, L=18, h=14, head=10)
out.append(f'<rect x="{x3}" y="{STAGE_Y}" width="{w3}" height="{STAGE_H}" fill="none" stroke="#000000" stroke-width="1" stroke-dasharray="4,3"/>')
text(x3 + w3 / 2, STAGE_Y + 14, "Stage 3  Opportunity selection by LLM debate", 13, bold=True)
box(x3 + 12, 150, 326, 92, ["**Three questions  (the workshop's where-to / where-now / how-to, for the company)",
                            "Q1  Why go?  who demands it, for what, by when; stated company intent",
                            "Q2  Where are we?  offerings' stage, latest metrics, customers, resources",
                            "Q3  Can we get there?  documented gap + a dated plan to close it",
                            "answered only from the card; every score cites card line ids"], size=9.2, lh=13.5, align="start", pad=6)
arrow_d(x3 + w3 / 2, 242, L=22)
# 세 모델
my = 268
for i, (name, note) in enumerate([("GPT-4.1", ""), ("Claude Sonnet 4.6", ""), ("Gemini 2.5 Flash", "")]):
    bx = x3 + 12 + i * 110
    box(bx, my, 104, 40, ["**" + name, "analyst"], size=9.5, lh=12)
text(x3 + w3 / 2, my + 56, "Round 1: each scores Q1·Q2·Q3 (0–10) + evidence ids + contested points", 9.5)
text(x3 + w3 / 2, my + 72, "Round 2: replies to the others, revises, final scores", 9.5)
# 토론 화살표
for i in range(3):
    bx = x3 + 12 + i * 110 + 52
    line(bx, my + 40, bx, my + 46, sw=1)
line(x3 + 64, my + 46, x3 + 284, my + 46, sw=1)
arrow_d(x3 + w3 / 2, my + 82, L=22)
box(x3 + 12, 372, 326, 50, ["**Profile per card  (q1, q2, q3) = mean of grounded final scores", "ungrounded scores are dropped; model spread before/after round 2 recorded"], size=9.5, lh=13)
arrow_d(x3 + w3 / 2, 422, L=22)
box(x3 + 12, 446, 326, 74, ["**Stance  (chosen by a person; default = balanced)", "balanced: z-scores of the three questions summed",
                            "or top-10 by Q1 (why go) / by Q2 (where we are) / by Q3 (can we get there)"], size=9.5, lh=13.5, stroke=GREEN, sw=2)
arrow_d(x3 + w3 / 2, 520, L=22)
box(x3 + 12, 544, 326, 56, ["**Selected opportunity cards  (top 10)  +  debate record", "= workshop step (b), reproducible and auditable"], fill=LIGHT, size=10, lh=14, stroke=RED, sw=2.5)
text(x3 + w3 / 2, 618, "Output of the knowledge construction system:", 10, italic=True)
text(x3 + w3 / 2, 634, "the selected cards, with every score traceable to a card line", 10, italic=True)
text(x3 + w3 / 2, 660, "Models differ on purpose: a crowd of different priors,", 9.5, italic=True)
text(x3 + w3 / 2, 676, "not one model playing personas", 9.5, italic=True)

# ================================================================== Stage 4  Roadmap making
x4, w4 = 1115, 340
arrow_r(x3 + w3 + 2, STAGE_Y + STAGE_H / 2, L=18, h=14, head=10)
out.append(f'<rect x="{x4}" y="{STAGE_Y}" width="{w4}" height="{STAGE_H}" fill="none" stroke="#000000" stroke-width="1" stroke-dasharray="4,3"/>')
text(x4 + w4 / 2, STAGE_Y + 14, "Stage 4  Roadmap making", 13, bold=True)
box(x4 + 12, 150, 316, 80, ["**Generator input", "glossary legend  +  landscape summary (areas, documents per year)",
                            "+  the selected cards in full (profile and panel reasons attached)", "same instructions, output schema, model and temperature", "as the generator without a knowledge base"], size=9.5, lh=13)
arrow_d(x4 + w4 / 2, 230, L=22)
box(x4 + 12, 254, 316, 78, ["**Reading rules", "why lines → why nodes;  offerings + dated targets → what nodes",
                            "(start/end from the latest statement; UPDATE → \"revised\")", "how / resource lines → how / resource nodes;  stated relations → edges",
                            "every node cites the card's passage / fact ids"], size=9.2, lh=13)
arrow_d(x4 + w4 / 2, 332, L=22)
# 로드맵 스윔레인
rx, ry, rw, rh = x4 + 12, 356, 316, 220
out.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" fill="#FFFFFF" stroke="#000000" stroke-width="1.6"/>')
out.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="22" fill="{BLUE}"/>')
text(rx + rw / 2, ry + 11, "Technology roadmap 2025–2030", 11, bold=True, fill="#FFFFFF")
lanes = [("why", "#F2D5D0"), ("what", "#D4E3F5"), ("how", "#D9ECD6"), ("resource", "#EFE6C8")]
lh_ = (rh - 22 - 18) / 4
for k, (lab, col) in enumerate(lanes):
    y = ry + 22 + k * lh_
    out.append(f'<rect x="{rx}" y="{y}" width="{rw}" height="{lh_}" fill="{col}" opacity="0.6"/>')
    text(rx + 6, y + lh_ / 2, lab, 9.5, bold=True, anchor="start")
    bars = [(0.22, 0.45), (0.3, 0.3), (0.5, 0.42)] if k != 1 else [(0.22, 0.3), (0.4, 0.25), (0.62, 0.3)]
    for j, (s, L) in enumerate(bars):
        bx = rx + 60 + s * (rw - 70); bw = L * (rw - 70) * 0.9
        by = y + 4 + j * (lh_ - 8) / 3
        out.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{(lh_ - 8) / 3 - 2}" fill="#FFFFFF" stroke="#333333" stroke-width="0.8"/>')
        text(bx + bw - 3, by + ((lh_ - 8) / 3 - 2) / 2, "[ps_…]", 7, anchor="end", fill="#555555")
for k, yr in enumerate(range(2025, 2031)):
    tx = rx + 60 + k * (rw - 70) / 5.5
    text(tx, ry + rh - 8, str(yr), 8.5)
text(x4 + w4 / 2, 592, "Nodes placed by the latest dated statement; revised targets flagged;", 9.5, italic=True)
text(x4 + w4 / 2, 608, "items without a documented path marked infeasible.", 9.5, italic=True)
text(x4 + w4 / 2, 636, "Evaluation: against the company's official roadmaps (technology", 9.5, italic=True)
text(x4 + w4 / 2, 652, "milestones and application opportunities), year-by-metric chart", 9.5, italic=True)
text(x4 + w4 / 2, 668, "scoring, grounding and selection stability — to be designed.", 9.5, italic=True)

# ------------------------------------------------------------------ 하단: 인간 역할·감사 가능성
box(45, 730, W - 90, 118, [
    "**Where people stay in the loop",
    "Stance choice in Stage 3 (which question should lead) · review of the debate record (every score cites a card line) · glossary confirmation",
    "**What the documents cannot say is left visible",
    "A card line reads \"none stated\" when the company's documents are silent; a candidate with demand but no documented path is kept and flagged, not dropped",
    "**Why the order is reversed",
    "In the workshop, linkage grids are derived from the per-opportunity plans (Trueman 2014, p. 20); an agent that has read everything can derive them for all candidates first, so selection sees richer information",
], size=10, lh=16, align="start", pad=10)

text(W / 2, 868, "The knowledge base = glossary + evidence store (foundation) and theme summary tree + relation graph + temporal knowledge graph (landscape). Cards are assembled from them; the debate selects; the generator makes.", 10.5, italic=True)

out.append("</svg>")

dst = Path(__file__).resolve().parents[2] / "연구계획" / "그림"
dst.mkdir(parents=True, exist_ok=True)
svg = dst / "Fig_Framework_TRM_KB_v2.svg"
svg.write_text("\n".join(out), encoding="utf-8")
print("wrote", svg)
browsers = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"), Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]
for b in browsers:
    if b.exists():
        png = dst / "Fig_Framework_TRM_KB_v2.png"
        subprocess.run([str(b), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png}",
                        f"--window-size={W},{H}", "--force-device-scale-factor=2", svg.as_uri()], check=False, capture_output=True, timeout=120)
        print("wrote", png, png.exists())
        break
