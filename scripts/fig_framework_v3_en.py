"""프레임워크 그림 v3 (영문 소개본용) — 글자를 줄이고 모양으로 설명한다.

python scripts/fig_framework_v3_en.py  ->  연구계획/그림/Fig_Framework_TRM_KB_v3_en.svg / .png
  1 Landscaping      문서 더미 -> Reader/Router -> 세 지식 구조 (트리 · 네트워크 · 시간축 사슬) + 바탕 띠(용어집 · 근거 저장소)
  2 Opportunity cards 카드 묶음 (줄 색 = 층)
  3 Multi-AI-agent debate  원탁 가운데 카드, 둘레에 AI 에이전트 셋, 순환 화살표
  4 Roadmap          네 레인 × 2025-2030, 막대와 연결, 원문 문장으로 이어지는 점선
  아래 띠: 워크숍 순서 vs 에이전트 순서
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

W, H = 1200, 560
FONT = "Arial, Helvetica, sans-serif"
INK, BODY, MUTED, LINE, SOFT = "#1f2328", "#3d434b", "#7a818a", "#c9ced6", "#f3f5f8"
WHY, WHAT, HOW, RES = "#d9736a", "#5b93d1", "#5fae76", "#d2a447"
ACC = "#3b5bdb"
out: list[str] = []


def t(x, y, s, size=14, *, w="normal", c=INK, a="middle", it=False):
    out.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{w}" fill="{c}" text-anchor="{a}"'
               + (' font-style="italic"' if it else "") + f">{s}</text>")


def rect(x, y, w, h, *, f="none", s=LINE, sw=1.2, r=8, dash=None, op=1):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{f}" stroke="{s}" stroke-width="{sw}"'
               + (f' stroke-dasharray="{dash}"' if dash else "") + (f' fill-opacity="{op}"' if op != 1 else "") + "/>")


def line(x1, y1, x2, y2, *, s=MUTED, sw=1.4, dash=None, arrow=False):
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{s}" stroke-width="{sw}"'
               + (f' stroke-dasharray="{dash}"' if dash else "") + (' marker-end="url(#ah)"' if arrow else "") + "/>")


def circle(cx, cy, r, *, f="#fff", s=INK, sw=1.4):
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{f}" stroke="{s}" stroke-width="{sw}"/>')


def path(d, *, s=MUTED, sw=1.4, f="none", dash=None, arrow=False):
    out.append(f'<path d="{d}" fill="{f}" stroke="{s}" stroke-width="{sw}"' + (f' stroke-dasharray="{dash}"' if dash else "")
               + (' marker-end="url(#ah)"' if arrow else "") + "/>")


def chevron(x, y):
    out.append(f'<path d="M{x},{y - 16} L{x + 14},{y} L{x},{y + 16}" fill="none" stroke="{ACC}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')


def doc_icon(x, y, w=34, h=42, c=MUTED):
    out.append(f'<path d="M{x},{y} h{w - 10} l10,10 v{h - 10} h-{w} z" fill="#fff" stroke="{c}" stroke-width="1.3"/>')
    for k in range(3):
        line(x + 6, y + 16 + k * 8, x + w - 6, y + 16 + k * 8, s=LINE, sw=1.6)


out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
out.append(f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker></defs>')
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

COLS = [(12, 336), (372, 210), (618, 290), (944, 244)]   # (x, w)
TITLES = [("1", "Landscaping", "three firm-specific knowledge structures"),
          ("2", "Opportunity cards", "candidates from the documents"),
          ("3", "Multi-AI-agent debate", "select the opportunities to pursue"),
          ("4", "Roadmap", "written from the selected cards")]
TOP, BOT = 14, 440
for (x, w), (n, ti, sub) in zip(COLS, TITLES):
    rect(x, TOP, w, BOT - TOP, f=SOFT, s="none", r=14)
    circle(x + 24, TOP + 27, 13, f=ACC, s=ACC)
    t(x + 24, TOP + 32, n, 15, w="bold", c="#fff")
    t(x + 44, TOP + 33, ti, 18, w="bold", a="start")
    t(x + 44, TOP + 53, sub, 12.5, c=MUTED, a="start")
for (x, w) in COLS[1:-1]:
    chevron(x + w + 11, (TOP + BOT) / 2)

# ---------------------------------------------------------------- 1 Landscaping
x0 = COLS[0][0]
TREE_C, REL_C, TIME_C, EVID_C = "#495057", "#7048e8", "#0c8599", "#868e96"
cxl = x0 + 76
for k in range(3):
    doc_icon(x0 + 22 + k * 13, 84 + k * 5, c=MUTED if k < 2 else INK)
t(cxl, 160, "Firm's documents", 13, w="bold")
t(cxl, 176, "public + internal", 11.5, c=MUTED)
t(cxl, 191, "in date order", 11.5, c=MUTED)
line(cxl, 197, cxl, 207, s=INK, sw=1.4, arrow=True)
rect(x0 + 12, 209, 128, 28, f="#fff", s=INK, sw=1.3, r=14)
t(cxl, 228, "Reader  ›  Router", 13, w="bold")
TX, TW, TH = x0 + 164, 166, 74
TYS = [96, 180, 264]
for ty_, c_ in zip(TYS, (TREE_C, REL_C, TIME_C)):
    rect(TX, ty_, TW, TH, f="#fff", s=c_, sw=1.6, r=10)
    path(f"M{x0 + 140},{226} C{x0 + 152},{226} {TX - 14},{ty_ + 37} {TX - 2},{ty_ + 37}", s=MUTED, sw=1.1, arrow=True)
PX = TX + 34   # 그림 칸 가운데
LX = TX + 62   # 이름 시작
# (a) theme summary tree
ty = TYS[0]
root, mids = (PX, ty + 15), [(PX - 16, ty + 37), (PX + 16, ty + 37)]
leaves = [(PX - 25, ty + 59), (PX - 9, ty + 59), (PX + 9, ty + 59), (PX + 25, ty + 59)]
for m in mids: line(*root, *m, s=MUTED, sw=1.2)
for i, lf in enumerate(leaves): line(*mids[i // 2], *lf, s=MUTED, sw=1.2)
circle(*root, 6, f=INK, s=INK)
for m in mids: circle(*m, 5, f="#8a929c", s="#8a929c")
for lf in leaves: circle(*lf, 3.5, f="#fff", s=INK, sw=1.2)
t(LX, ty + 33, "Theme", 12, w="bold", c=TREE_C, a="start"); t(LX, ty + 49, "summary tree", 12, w="bold", c=TREE_C, a="start")
# (b) relation graph
ty = TYS[1]; gx, gy = PX, ty + 37
off = [(-19, -16, WHY), (3, -21, WHAT), (21, -5, HOW), (-23, 8, RES), (1, 4, WHAT), (17, 20, HOW), (-8, 23, RES)]
pts = [(gx + dx, gy + dy, c) for dx, dy, c in off]
for i, j in [(0, 1), (1, 4), (4, 2), (3, 4), (4, 5), (3, 6), (6, 5), (0, 4), (1, 2)]:
    line(pts[i][0], pts[i][1], pts[j][0], pts[j][1], s=MUTED, sw=1.1)
for k, (px, py, c) in enumerate(pts): circle(px, py, 6 if k == 4 else 4.5, f=c, s="#fff", sw=1.2)
t(LX, ty + 33, "Relation", 12, w="bold", c=REL_C, a="start"); t(LX, ty + 49, "graph", 12, w="bold", c=REL_C, a="start")
# (c) temporal knowledge graph
ty = TYS[2]; lx, rx = TX + 8, TX + 60
for yy in (ty + 16, ty + 36, ty + 56): line(lx, yy, rx, yy, s=LINE, sw=1.1)
line(lx, ty + 67, rx, ty + 67, s=MUTED, sw=1.1, arrow=True)
ch = [(lx + 5, ty + 16), (lx + 25, ty + 16), (lx + 46, ty + 16)]
path(f"M{ch[0][0]},{ch[0][1]} Q{(ch[0][0] + ch[1][0]) / 2},{ty + 6} {ch[1][0]},{ch[1][1]}", s=INK, sw=1.2)
path(f"M{ch[1][0]},{ch[1][1]} Q{(ch[1][0] + ch[2][0]) / 2},{ty + 6} {ch[2][0]},{ch[2][1]}", s=RES, sw=1.4, dash="3 2")
for (px, py) in ch: circle(px, py, 3.5, f=INK, s=INK)
out.append(f'<rect x="{lx + 13}" y="{ty + 31.5}" width="9" height="9" fill="{HOW}"/>')
out.append(f'<rect x="{lx + 35}" y="{ty + 31.5}" width="9" height="9" fill="#fff" stroke="{HOW}" stroke-width="1.4"/>')
out.append(f'<path d="M{lx + 26},{ty + 50} l6,6 l-6,6 l-6,-6 z" fill="{WHAT}"/>')
t(LX, ty + 33, "Temporal", 12, w="bold", c=TIME_C, a="start"); t(LX, ty + 49, "knowledge graph", 12, w="bold", c=TIME_C, a="start")
# foundation
rect(x0 + 12, 352, 318, 28, f="#e4e8ee", s="none", r=8)
t(x0 + 171, 371, "Glossary  ·  Evidence store (verbatim sentences)", 12.5, c=BODY)
t(x0 + 171, 420, "linkage and timing for every candidate", 12.5, c=MUTED, it=True)
SRC_PT = {"tree": (TX + TW, TYS[0] + 37, TREE_C, None), "rel": (TX + TW, TYS[1] + 37, REL_C, None),
          "time": (TX + TW, TYS[2] + 37, TIME_C, None), "evid": (x0 + 330, 366, EVID_C, "4 3")}

# ---------------------------------------------------------------- 2 Opportunity cards
x1, w1 = COLS[1]
cx1 = x1 + w1 / 2
# (i) Router 가 넘긴 기회 언급 -> (ii) 걸러내기 깔때기 -> (iii) 후보
t(cx1, 92, "opportunity mentions", 12, w="bold", c=BODY)
for k in range(6):
    rect(cx1 - 87 + k * 30, 100, 24, 11, f="#aeb6c0", s="none", r=5)
fy0, fy1, fw0, fw1 = 120, 176, 200, 116
path(f"M{cx1 - fw0 / 2},{fy0} L{cx1 + fw0 / 2},{fy0} L{cx1 + fw1 / 2},{fy1} L{cx1 - fw1 / 2},{fy1} Z", s=MUTED, sw=1.3, f="#fff")
t(cx1, fy0 + 20, "drop generic names, firms,", 11.5, c=BODY)
t(cx1, fy0 + 36, "technologies, products", 11.5, c=BODY)
line(cx1, fy1, cx1, fy1 + 10, s=MUTED, sw=1.3, arrow=True)
for k in range(3):
    rect(cx1 - 92 + k * 30, 190, 24, 11, f=ACC, s="none", r=5)
t(cx1 + 2, 200, "candidates", 12.5, w="bold", c=ACC, a="start")
line(cx1, 206, cx1, 216, s=MUTED, sw=1.3, arrow=True)
# (iv) 후보마다 카드 한 장
cy0, ch = 222, 160
for k in (2, 1):
    rect(cx1 - 70 + k * 8, cy0 - k * 8, 140, ch, f="#fff", s=LINE, r=10)
rect(cx1 - 70, cy0, 140, ch, f="#fff", s=INK, sw=1.4, r=10)
out.append(f'<rect x="{cx1 - 70}" y="{cy0}" width="140" height="26" rx="10" fill="{ACC}"/>'
           f'<rect x="{cx1 - 70}" y="{cy0 + 14}" width="140" height="12" fill="{ACC}"/>')
t(cx1, cy0 + 18, "Opportunity card", 13, w="bold", c="#fff")
rows = [("why", WHY), ("trend", MUTED), ("what", WHAT), ("when", WHAT), ("how", HOW), ("resource", RES), ("issue", MUTED)]
for i, (lab, c) in enumerate(rows):
    yy = cy0 + 43 + i * 17
    t(cx1 - 58, yy + 4, lab, 11, w="bold", c=c, a="start")
    rect(cx1 - 2, yy - 4, 60 - (i % 3) * 12, 7, f=LINE, s="none", r=3)
t(cx1, 404, "one card per candidate", 12.5, c=MUTED, it=True)
t(cx1, 421, "every line cites its source", 12.5, c=MUTED, it=True)
# Router 에서 기회 언급으로 (읽는 동안): 세 그래프 위로 돌아서
path(f"M{x0 + 140},{216} C{x0 + 156},{216} {x0 + 150},{86} {x0 + 172},{86} L{x1 - 6},{86} C{x1 + 4},{86} {x1 + 4},{105} {cx1 - 90},{105}", s=ACC, sw=1.5, dash="4 3", arrow=True)
# 세 그래프 (+ 근거 저장소) -> 카드 줄: 표 3 의 연결
ROWS_Y = {lab: cy0 + 43 + i * 17 for i, (lab, _) in enumerate(rows)}
LINKS = [("tree", "trend", 0), ("rel", "what", -3), ("time", "what", 3), ("time", "when", 0), ("rel", "how", -3), ("time", "how", 3),
         ("rel", "resource", 0), ("rel", "issue", -3), ("evid", "why", 0), ("evid", "issue", 3)]
ex = cx1 - 71
for src, row, dy in LINKS:
    sx, sy, c, dash = SRC_PT[src]
    ey = ROWS_Y[row] + dy
    path(f"M{sx},{sy} C{sx + 34},{sy} {ex - 34},{ey} {ex},{ey}", s=c, sw=1.5, dash=dash)
    circle(ex, ey, 2.6, f=c, s=c, sw=0.5)
for src in ("tree", "rel", "time"):
    sx, sy, c, _ = SRC_PT[src]
    circle(sx, sy, 3.2, f=c, s="#fff", sw=1)

# ---------------------------------------------------------------- 3 Multi-AI-agent debate
x2, w2 = COLS[2]
cx2, cy2, R = x2 + w2 / 2, 222, 92
out.append(f'<ellipse cx="{cx2}" cy="{cy2}" rx="58" ry="58" fill="#fff" stroke="{LINE}" stroke-width="1.4"/>')
rect(cx2 - 22, cy2 - 28, 44, 56, f="#fff", s=INK, sw=1.3, r=5)
out.append(f'<rect x="{cx2 - 22}" y="{cy2 - 28}" width="44" height="12" rx="5" fill="{ACC}"/>')
for k, c in enumerate((WHY, WHAT, HOW)):
    rect(cx2 - 14, cy2 - 8 + k * 11, 28, 5, f=c, s="none", r=2)
agents = [(-90, "GPT-4.1"), (30, "Claude"), (150, "Gemini")]
AC = ["#4c6ef5", "#e8590c", "#2b8a3e"]
pos = []
for (ang, name), c in zip(agents, AC):
    a = math.radians(ang)
    ax, ay = cx2 + R * math.cos(a), cy2 + R * math.sin(a)
    pos.append((ax, ay))
    # avatar: head + shoulders
    out.append(f'<path d="M{ax - 20},{ay + 22} q0,-18 20,-18 q20,0 20,18 z" fill="{c}"/>')
    circle(ax, ay - 8, 10, f=c, s="#fff", sw=2)
    ly = ay + 38 if ang != -90 else ay - 26
    t(ax, ly, name, 12.5, w="bold", c=c)
# circular debate arrows between agents (outer arc)
for i in range(3):
    a0, a1 = math.radians(agents[i][0] + 26), math.radians(agents[(i + 1) % 3][0] - 26)
    if a1 < a0:
        a1 += 2 * math.pi
    rr = R + 4
    p0 = (cx2 + rr * math.cos(a0), cy2 + rr * math.sin(a0)); p1 = (cx2 + rr * math.cos(a1), cy2 + rr * math.sin(a1))
    path(f"M{p0[0]:.1f},{p0[1]:.1f} A{rr},{rr} 0 0 1 {p1[0]:.1f},{p1[1]:.1f}", s=MUTED, sw=1.5, arrow=True)
# questions
qy = 348
for k, q in enumerate(("Q1  Where do we want to go?", "Q2  Where are we now?", "Q3  How can we get there?")):
    t(x2 + 26, qy + k * 19, q, 12.5, c=BODY, a="start")
rect(cx2 - 74, 404, 148, 26, f="#fff", s=INK, sw=1.3, r=13)
t(cx2, 422, "top-10 opportunities", 12.5, w="bold")

# ---------------------------------------------------------------- 4 Roadmap
x3, w3 = COLS[3]
lx0, lx1 = x3 + 64, x3 + w3 - 12
lanes = [("why", WHY), ("what", WHAT), ("how", HOW), ("resource", RES)]
ly0, lh = 100, 58
for i, (lab, c) in enumerate(lanes):
    yy = ly0 + i * lh
    rect(lx0, yy, lx1 - lx0, lh - 6, f=c, s="none", r=6, op=0.13)
    t(x3 + 58, yy + lh / 2 + 1, lab, 12, w="bold", c=c, a="end")
bars = {0: [(0.02, 0.50), (0.42, 0.95)], 1: [(0.12, 0.48), (0.55, 0.88)], 2: [(0.00, 0.38), (0.40, 0.75)], 3: [(0.20, 0.65)]}
span = lx1 - lx0 - 10
bar_xy = {}
for i, bs in bars.items():
    for j, (a, b) in enumerate(bs):
        bx = lx0 + 5 + a * span; bw = (b - a) * span
        by = ly0 + i * lh + 10 + j * 16
        rect(bx, by, bw, 12, f="#fff", s=lanes[i][1], sw=1.6, r=3)
        bar_xy[(i, j)] = (bx, by, bw)
# 연결: 두 막대가 시간으로 겹치는 구간의 가운데에서 곧게 (위 막대 아래 -> 아래 막대 위)
for (a, b) in [((0, 0), (1, 0)), ((0, 1), (1, 1)), ((2, 1), (1, 1)), ((3, 0), (2, 1))]:
    (ax, ay, aw), (bx, by, bw) = bar_xy[a], bar_xy[b]
    xm = (max(ax, bx) + min(ax + aw, bx + bw)) / 2
    if ay < by:
        line(xm, ay + 12, xm, by - 1, s=MUTED, sw=1.2, arrow=True)
    else:
        line(xm, ay - 1, xm, by + 13, s=MUTED, sw=1.2, arrow=True)
for k, yr in enumerate(("2025", "2030")):
    t(lx0 + 5 + k * span, ly0 + 4 * lh + 10, yr, 11.5, c=MUTED, a="start" if k == 0 else "end")
# 추적: 맨 아래 막대에서 원문 문장 문서로
bx, by, bw = bar_xy[(3, 0)]
dx, dy = bx + bw / 2 - 15, 366
line(bx + bw / 2, by + 13, bx + bw / 2, dy - 2, s=ACC, sw=1.5, dash="3 3", arrow=True)
doc_icon(dx, dy, 30, 36, c=INK)
t(dx - 8, dy + 24, "source sentence", 12.5, c=MUTED, a="end", it=True)
t(x3 + w3 / 2, 420, "every item traceable", 12.5, c=MUTED, it=True)

# ---------------------------------------------------------------- bottom band: order of steps
by0 = 462
rect(12, by0, W - 24, 84, f="#fff", s=LINE, r=12)


def pills(y, label, items):
    t(32, y + 5, label, 13.5, w="bold", a="start")
    x = 210
    for k, (s, hi) in enumerate(items):
        wv = 14 + len(s) * 7.6
        rect(x, y - 13, wv, 26, f=ACC if hi else "#fff", s=ACC if hi else LINE, sw=1.3, r=13)
        t(x + wv / 2, y + 5, s, 13, w="bold" if hi else "normal", c="#fff" if hi else BODY)
        x += wv
        if k < len(items) - 1:
            t(x + 14, y + 5, "→", 15, c=MUTED); x += 28


pills(by0 + 25, "Workshop (S-Plan)", [("a  landscape", False), ("b  select", False), ("c  link", False), ("d  place in time", False), ("roadmap", False)])
pills(by0 + 60, "Agent", [("a + c + d  for every candidate", True), ("opportunity cards", False), ("b  select by debate", False), ("roadmap", False)])
t(W - 30, by0 + 60 + 5, "selection works on richer information", 12.5, c=MUTED, a="end", it=True)

out.append("</svg>")
dst = Path(__file__).resolve().parents[2] / "연구계획" / "그림"
svg = dst / "Fig_Framework_TRM_KB_v3_en.svg"
svg.write_text("\n".join(out), encoding="utf-8")
png = dst / "Fig_Framework_TRM_KB_v3_en.png"
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png}", f"--window-size={W},{H}",
                "--force-device-scale-factor=2.5", svg.as_uri()], check=False, capture_output=True, timeout=120)
print("wrote", svg, png, png.exists())
