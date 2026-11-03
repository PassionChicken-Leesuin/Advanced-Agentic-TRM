"""생성 로드맵(rm_<i>.json)을 층별 스윔레인 그림(PNG)으로 그린다.

python scripts/render_roadmap.py runs/struct5/eval/ALL/rm_1.json --out "경로/그림.png" [--title "..."]
층(why/what/how/resource) 별 레인, 가로축 연도, 막대 = start–end, 점선 테두리 = 근거 없는(llm_prior) 항목,
막대 오른쪽 숫자 = 근거 문장 수, 선 = 관계(drives 회색, requires 파랑, enables 초록, precedes 주황 화살표).
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

LANES = ["why", "what", "how", "resource"]
LANE_TITLE = {"why": "WHY  market · drivers · needs", "what": "WHAT  products · applications · milestones",
              "how": "HOW  technologies · capabilities", "resource": "RESOURCE  funding · facilities · partners · standards"}
LANE_COLOR = {"why": "#f2d5d0", "what": "#d4e3f5", "how": "#d9ecd6", "resource": "#efe6c8"}
LANE_EDGE = {"why": "#b9574a", "what": "#2f66a8", "how": "#3f8a3a", "resource": "#a58a2b"}
EDGE_STYLE = {"drives": ("#888888", "-", 0.9), "requires": ("#2f66a8", "-", 0.9), "enables": ("#3f8a3a", "-", 0.9), "precedes": ("#d9822b", "-", 1.4)}
X0, X1 = 2024.9, 2030.6


def layout(nodes: list[dict]) -> dict[str, tuple[str, int]]:
    """노드마다 (레인, 레인 안의 행) 배정. 겹치지 않게 탐욕 배치."""
    pos = {}
    for lane in LANES:
        ns = sorted([n for n in nodes if n["layer"] == lane], key=lambda n: ((n.get("start") or 2025), -(n.get("end") or 2030)))
        rows: list[float] = []   # 각 행의 현재 끝 x
        for n in ns:
            s, e = n.get("start") or 2025.0, n.get("end") or 2030.0
            need = max(e, s + 0.9) + 0.15
            for r, end in enumerate(rows):
                if s >= end:
                    rows[r] = need; pos[n["id"]] = (lane, r); break
            else:
                rows.append(need); pos[n["id"]] = (lane, len(rows) - 1)
    return pos


def render(rm: dict, out: Path, title: str | None = None) -> None:
    nodes = [n for n in rm["nodes"] if n["layer"] in LANES]
    pos = layout(nodes)
    lane_rows = {lane: max([r for (l, r) in pos.values() if l == lane], default=-1) + 1 for lane in LANES}
    row_h = 0.62
    # 레인 y 범위 (위에서 아래로 why → resource)
    y_top = 0.0
    lane_y = {}
    for lane in LANES:
        h = max(lane_rows[lane], 1) * row_h + 0.35
        lane_y[lane] = (y_top - h, y_top)
        y_top -= h
    H = -y_top
    fig_h = max(7.0, H * 0.95)
    fig, ax = plt.subplots(figsize=(16, fig_h), dpi=150)
    ax.set_xlim(X0, X1); ax.set_ylim(y_top - 0.1, 0.1)
    ax.set_yticks([]); ax.set_xticks(range(2025, 2031)); ax.tick_params(axis="x", labelsize=10, labeltop=True, top=True)
    for yr in range(2025, 2031):
        ax.axvline(yr, color="#dddddd", lw=0.6, zorder=0)
    for lane in LANES:
        lo, hi = lane_y[lane]
        ax.add_patch(FancyBboxPatch((X0, lo), X1 - X0, hi - lo, boxstyle="square,pad=0", fc=LANE_COLOR[lane], ec="none", alpha=0.35, zorder=0))
        ax.axhline(lo, color="#bbbbbb", lw=0.6, zorder=0)
        ax.text(X0 + 0.03, hi - 0.12, LANE_TITLE[lane], fontsize=9.5, fontweight="bold", color=LANE_EDGE[lane], va="top", zorder=3)
    centers = {}
    for n in nodes:
        lane, r = pos[n["id"]]
        s, e = n.get("start") or 2025.0, n.get("end") or 2030.0
        e = max(e, s + 0.9)
        lo, hi = lane_y[lane]
        y = hi - 0.35 - r * row_h - row_h / 2
        prior = "llm_prior" in (n.get("produced_by") or []) and not n.get("evidence_ids")
        box = FancyBboxPatch((s, y - 0.22), e - s, 0.44, boxstyle="round,pad=0.01,rounding_size=0.06",
                             fc="white", ec=LANE_EDGE[lane], lw=1.1, ls="--" if prior else "-", zorder=2)
        ax.add_patch(box)
        label = n["label"]
        maxc = int((e - s) * 13)
        if len(label) > maxc:
            label = label[:max(maxc - 1, 6)] + "…"
        ax.text(s + 0.06, y, label, fontsize=7.6, va="center", ha="left", zorder=3, color="#222")
        ev = len(n.get("evidence_ids") or [])
        ax.text(e - 0.05, y, f"{ev}", fontsize=6.5, va="center", ha="right", color="#666" if ev else "#c33", zorder=3)
        centers[n["id"]] = (s, e, y)
    for ed in rm.get("edges", []):
        a, b = centers.get(ed["src"]), centers.get(ed["dst"])
        if not a or not b:
            continue
        col, ls, lw = EDGE_STYLE.get(ed["type"], ("#999", "-", 0.8))
        x1, y1 = a[0] + 0.12, a[2]
        x2, y2 = b[0] + 0.12, b[2]
        if ed["type"] == "precedes":
            x1, x2 = a[1], b[0]
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=col, lw=lw, alpha=0.8, connectionstyle="arc3,rad=0.15"), zorder=1)
        else:
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="-", color=col, lw=lw, alpha=0.22, connectionstyle="arc3,rad=0.25"), zorder=1)
    ev_rate = sum(1 for n in nodes if n.get("evidence_ids")) / max(len(nodes), 1)
    et = {}
    for ed in rm.get("edges", []):
        et[ed["type"]] = et.get(ed["type"], 0) + 1
    t = title or f"{rm.get('condition')} · {rm.get('model')}"
    ax.set_title(f"{t}\n{len(nodes)} items, {len(rm.get('edges', []))} links ({', '.join(f'{k} {v}' for k, v in sorted(et.items()))}), "
                 f"items with evidence {ev_rate:.0%}; dashed = no evidence (model prior); number at right = evidence passages",
                 fontsize=10, loc="left")
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rm")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default=None)
    a = ap.parse_args()
    rm = json.loads(Path(a.rm).read_text(encoding="utf-8"))
    render(rm, Path(a.out), a.title)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
