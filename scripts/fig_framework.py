"""프레임워크 그림 (영문) — TFSC Fig2 양식(흰 바탕, 검은 테두리, Times 계열, 회색 입출력 상자, 파란 블록 화살표, 빨간 강조) 을 따름.
python scripts/fig_framework.py  →  연구계획/그림/Fig_Framework_TRM_KB_v1.svg (+ chrome headless 로 .png)
"""
import subprocess
from pathlib import Path

W, H = 1300, 960
FONT = "Liberation Serif, Times New Roman, serif"
BLUE, GREY, LIGHT, RED = "#4472C4", "#E7E6E6", "#F2F2F2", "#FF0000"
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
    if align == "middle":
        y0 = top + (h - (top - y)) / 2 - (n - 1) * lh / 2
    else:
        y0 = top + pad + lh / 2
    for i, ln in enumerate(lines):
        b = it = False
        if ln.startswith("**"):
            b, ln = True, ln[2:]
        if ln.startswith("__"):
            it, ln = True, ln[2:]
        tx = x + w / 2 if align == "middle" else x + pad
        text(tx, y0 + i * lh, ln, size=size, bold=b, italic=it, anchor="middle" if align == "middle" else "start")


def arrow_r(x, y, L=36, h=16, head=14):
    """오른쪽 블록 화살표 (x,y = 왼쪽 중앙)"""
    s = h / 2
    out.append(f'<path d="M{x},{y - s} L{x + L - head},{y - s} L{x + L - head},{y - s - 6} L{x + L},{y} L{x + L - head},{y + s + 6} '
               f'L{x + L - head},{y + s} L{x},{y + s} Z" fill="{BLUE}"/>')


def arrow_d(x, y, L=30, h=16, head=12):
    """아래 블록 화살표 (x,y = 위 중앙)"""
    s = h / 2
    out.append(f'<path d="M{x - s},{y} L{x - s},{y + L - head} L{x - s - 6},{y + L - head} L{x},{y + L} L{x + s + 6},{y + L - head} '
               f'L{x + s},{y + L - head} L{x + s},{y} Z" fill="{BLUE}"/>')


def line(x1, y1, x2, y2, sw=1.2, dash=None, marker=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = ' marker-end="url(#arr)"' if marker else ""
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#000000" stroke-width="{sw}"{d}{m}/>')


# ------------------------------------------------------------------ 캔버스
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
out.append('<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse">'
           '<path d="M0,0 L10,5 L0,10 Z" fill="#000000"/></marker></defs>')
out.append(f'<rect width="100%" height="100%" fill="white"/>')
out.append(f'<rect x="20" y="20" width="{W - 40}" height="{H - 40}" fill="#FFFFFF" stroke="#000000" stroke-width="1.2"/>')

# ================================================================== Stage 1
text(W / 2, 46, "Stage 1: knowledge-base construction  →  the Router dispatches each source passage to the knowledge structure(s) whose roadmapping function it serves", 15, bold=True)

y1, h1 = 70, 78
box(45, y1, 185, h1, ["Company documents, in date order", "IonQ 2020–2024: SEC filings, blogs,", "press releases, papers, and", "internal memos (synthetic)"], fill=GREY, size=10.5)
arrow_r(233, y1 + h1 / 2)
box(272, y1, 200, h1, ["**Reader", "quotes every roadmap-usable sentence", "verbatim + a restated claim;", "no classification"], size=10.5)
arrow_r(475, y1 + h1 / 2)
box(514, y1, 230, h1, ["**K0 glossary (grows with each document)", "metrics · products · technologies · organizations ·",
                       "applications · lifecycle stages · programs", "aliases → one subject id; auto-confirmed at ≥ 2 docs"], size=10)
arrow_r(747, y1 + h1 / 2)
box(786, y1, 265, h1, ["**Router (per passage)", "store?  new | duplicate | irrelevant",
                       "layer tags why / what / how / resource · subjects (shared ids)", "significance test: admin & past financials stay in K1",
                       "routes to K2–K5 (0 or more), each with a stated reason"], size=10)
arrow_r(1054, y1 + h1 / 2)
box(1093, y1, 162, h1, ["**Structure-specific", "**extractors", "called in parallel per document;", "applied graph → grid → time → tree"], fill=GREY, size=10)

# 다섯 구조로 내려가는 레일
rail_y = 168
line(1174, y1 + h1, 1174, rail_y)
line(60, rail_y, 1174, rail_y)
ys, hs = 190, 150
cols = [(45, 215), (275, 240), (530, 265), (810, 205), (1030, 225)]
heads = ["K1  Evidence store", "K2  Theme summary tree", "K3  Opportunity linkage grid", "K4  Relation graph", "K5  Temporal knowledge graph"]
bodies = [
    ["__① grounding", "every stored passage, with tags", "(layers, kind, modality, subjects)", "flat list; cite by passage id", "", "≈ flat RAG"],
    ["__② trend synthesis", "passage → theme → area → root;", "yearly lines per theme", "trend = share of documents per year", "that touch the theme (code) → LLM text", "≈ RAPTOR + time axis"],
    ["__③ opportunity identification & comparison", "record = application area or product type", "+ stated market · offering · drivers · needs", "15 columns selected by market tier and", "document support; display order by links", "and strength (no vote-based priority)", "rows = drivers·needs / offerings / capabilities / enablers", "≈ Cambridge linkage grid (Trueman 2014)"],
    ["__④ relation representation & retrieval", "source-stated (subject, relation, subject)", "triples; 12 relation types", "generator retrieves one-hop neighbors;", "no multi-hop path inference", "≈ relation-centric graph retrieval"],
    ["__⑤ timing", "(subject, attribute, value, valid time,", "stated time, modality); families: metric /", "lifecycle stage / milestone", "chains with update · conflict, never overwritten", "≈ bi-temporal KG (Zep)"],
]
for (x, w), hd, bd in zip(cols, heads, bodies):
    arrow_d(x + w / 2, rail_y, L=22, h=12, head=10)
    box(x, ys, w, hs, bd, title=hd, size=9.5, lh=12.5, align="middle")
text(45 + 215 / 2, ys + hs + 12, "receives every stored passage", 9.5, italic=True)
text(1255, ys + hs + 12, "subjects from existing ids; attributes from K0 metrics / stages", 9.5, italic=True, anchor="end")

# 공통 골격
yc = 372
box(45, yc, 1210, 26, ["**Common skeleton shared by all five structures:   passage ids (K1)  ·  shared subject ids  ·  layer tags as metadata, not storage  ·  K0 vocabulary"], fill=GREY, size=10.5)

# 마무리
yf, hf = 410, 62
box(45, yf, 1210, hf, ["**Finish (once, after all documents)",
                       "LLM-judged merging of subjects and themes (embeddings only propose candidate pairs; each decision keeps its reason)  →  fact-chain relinking (update / duplicate / conflict)",
                       "→  K2 tree: document-share trend per year, summaries by LLM  →  K3 grid: tier-A opportunities first; cells from records and K4 relations (direct), co-mentions verified by LLM (derived)"],
    size=10, lh=14)
text(W / 2, yf + hf + 13, "Every decision is written as an event (passage.routed, glossary.term, grid.opportunity, graph.relation, time.fact, entity.merged, …) so the construction can be replayed on screen.", 10, italic=True)

# 구분선
line(45, 500, 1255, 500, sw=1.2, dash="8,6")

# ================================================================== Stage 2
text(W / 2, 522, "Stage 2: roadmap generation  →  opportunity cards assemble the five structures; one generator call per roadmap", 15, bold=True)

y2, h2 = 545, 150
# 카드 도식
cx, cw = 45, 440
box(cx, y2, cw, h2, [], title="Opportunity card  (up to 10 K3 anchors)")
rows = [("market / driver context  (why)", "← K3 driver/need labels  +  K2 trend"),
        ("offerings  (what)", "← K3 what rows  +  K5 timing chains (latest value, revised)"),
        ("capabilities & enablers  (how / resource)", "← K3 how·resource rows  +  K4 relations (1 hop)"),
        ("evidence", "← K1 passage ids cited on the card")]
ry = y2 + 22
rh = (h2 - 22) / 4
for i, (a, b) in enumerate(rows):
    fill = LIGHT if i % 2 == 0 else "#FFFFFF"
    out.append(f'<rect x="{cx}" y="{ry + i * rh}" width="{cw}" height="{rh}" fill="{fill}" stroke="#000000" stroke-width="0.6"/>')
    line(cx + 190, ry + i * rh, cx + 190, ry + (i + 1) * rh, sw=0.6)
    text(cx + 10, ry + i * rh + rh / 2, a, 10.5, bold=True, anchor="start")
    text(cx + 200, ry + i * rh + rh / 2, b, 10, anchor="start")
text(cx + cw / 2, y2 + h2 + 13, "ALL serialized 9 card sections: the K3-specific budget stopped the 10th header", 10, italic=True)

arrow_r(488, y2 + h2 / 2)
box(527, y2, 300, h2, ["**Generator  (single call, gpt-4.1, T = 0.2)", "same instructions, output schema and model as Initial (no KB)",
                       "+ cards  +  remaining worksheets (K2 root & areas,", "K4, K5, K1 passages)  +  one reading rule per structure present",
                       "a card becomes one vertical slice: why → what → how →", "resource; dates from K5 chains; evidence ids cited"], size=10, lh=14.5)
arrow_r(830, y2 + h2 / 2)
box(869, y2, 185, h2, ["**Technology roadmap", "**2025–2030", "nodes with layer, start / end year,", "evidence ids, revised / conflict flags;", "typed edges (drives, requires,", "enables, precedes)"], fill=GREY, size=10, lh=14.5)
arrow_r(1057, y2 + h2 / 2)
box(1096, y2, 159, h2, ["**Evaluation", "11 conditions ×", "3 generations × 3 judges", "recall vs official roadmaps", "(2020 and 2025 editions),", "year MAE, evidence rate,", "grounded edges, area coverage"], fill=GREY, stroke=RED, sw=2.5, size=10, lh=14)

# 조건 표
ty = 722
tx = 45
cw2 = [110, 370, 220]
hdr = ["Condition", "What is removed", "Expected drop"]
rows2 = [("Initial", "no knowledge base", "— (baseline)"),
         ("S0raw", "naive RAG over raw chunks", "—"),
         ("ALL", "nothing (K0 + K1–K5)", "— (best)"),
         ("ALL − K2", "theme tree (its card lines, worksheet, reading rule; budget → K1)", "area coverage, trend wording"),
         ("ALL − K3", "opportunity linkage matrix (cards also lose K3 rows)", "candidate coverage and linked elements"),
         ("ALL − K4", "relation graph (same removal)", "relation-level grounding (not captured by current proxy)"),
         ("ALL − K5", "temporal knowledge graph (same removal)", "year error, revision flags"),
         ("ALL − K0", "glossary at build time (KB rebuilt without K0)", "split names → broken chains and edges"),
         ("ALL (public only)", "synthetic internal documents", "internal citations 0; others slightly lower")]
th = 17.5
x0 = tx
for j, hname in enumerate(hdr):
    out.append(f'<rect x="{x0}" y="{ty}" width="{cw2[j]}" height="{th}" fill="{BLUE}" stroke="#FFFFFF" stroke-width="0.8"/>')
    text(x0 + cw2[j] / 2, ty + th / 2, hname, 10, bold=True, fill="#FFFFFF")
    x0 += cw2[j]
for i, r in enumerate(rows2):
    x0 = tx
    yy = ty + th + i * th
    for j, cell in enumerate(r):
        out.append(f'<rect x="{x0}" y="{yy}" width="{cw2[j]}" height="{th}" fill="{LIGHT if i % 2 == 0 else "#FFFFFF"}" stroke="#FFFFFF" stroke-width="0.8"/>')
        text(x0 + 6, yy + th / 2, cell, 9.5, anchor="start", bold=(j == 0))
        x0 += cw2[j]

# 가설 상자
hx, hw = 790, 465
box(hx, ty, hw, th * 10, ["**Hypothesis",
                          "Removing one structure lowers only the metrics of the",
                          "roadmapping function it serves, while the other metrics stay",
                          "at the level of the full knowledge base. The 2025-edition",
                          "comparison is an extrapolation task: documents end in 2024.",
                          "",
                          "__Industry transfer: the structures and the Router are generic; only the",
                          "__K0 vocabulary (metric names, stages, product families) is domain-specific."],
    fill="#FFFFFF", stroke=RED, sw=2.5, size=10.5, lh=15)

text(W / 2, 924, "Five functions (grounding, trend synthesis, opportunity identification/selection, relation representation/retrieval, timing) map to five structures; the Router decides per passage, cards assemble by opportunity.", 10.5, italic=True)

out.append("</svg>")

dst = Path(__file__).resolve().parents[2] / "연구계획" / "그림"
dst.mkdir(parents=True, exist_ok=True)
svg = dst / "Fig_Framework_TRM_KB_v1.svg"
svg.write_text("\n".join(out), encoding="utf-8")
print("wrote", svg)
chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
if chrome.exists():
    png = dst / "Fig_Framework_TRM_KB_v1.png"
    subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png}",
                    f"--window-size={W},{H}", "--force-device-scale-factor=3", svg.as_uri()], check=False, capture_output=True, timeout=120)
    print("wrote", png, png.exists())
