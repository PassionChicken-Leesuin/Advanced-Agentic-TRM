"""구축 결과 점검: K0 용어집 표, K5 체인(가족별), K3 기회 등급 개수, 기회 카드 한 장, 작업지 글자 통계.

python scripts/inspect_v2.py --run runs/pilot3 [--card 1] [--write]
  --write: runs/<run>/inspect.md 로 저장
"""
import argparse
import io
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.sources.store import SourceStore
from trmkb.sources.worksheets import STRUCTS, build_worksheets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/pilot3")
    ap.add_argument("--card", type=int, default=1)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    st = SourceStore(a.run)
    out = []
    P = out.append
    s = st.stats()
    P(f"# 점검 — {a.run}\n")
    P(f"문장 {s['passages']}, 대상 {s['entities']}, 용어 {s['glossary_terms']} {s['glossary_by_type']}, 관계 {s['graph_relations']}, "
      f"시간 사실 {s['time_facts']} {s['time_fact_family']} 상태 {s['time_fact_status']}, 기회 기록 {s['grid_opportunities']}, 주제 {s['tree_themes']}, 영역 {s['tree_areas']}\n")

    # K0
    P("## K0 용어집\n")
    P("| 종류 | 이름 | 별칭 | 단위·방향 | 세대 | 범위 | 문서 수 | 정의 |\n|---|---|---|---|---|---|---|---|")
    for t in sorted(st.terms.values(), key=lambda t: (t.type, -t.count)):
        P(f"| {t.type} | {t.name} | {', '.join(t.aliases[:4])} | {(t.unit or '') + (', ' + t.direction if t.direction and t.direction != 'none' else '')} | "
          f"{t.order if t.order is not None else ''} | {t.scope} | {t.count} | {t.definition[:100].replace('|', '/')} |")

    # K5
    P("\n## K5 시간 사실 (대상 → 속성 → 체인)\n")
    by = defaultdict(lambda: defaultdict(list))
    for f in st.facts.values():
        by[f.eid][f.attribute].append(f)
    for e in sorted(by, key=lambda e: -len(by[e])):
        P(f"- **{st.entities[e].name}**")
        for attr, fs in by[e].items():
            fs.sort(key=lambda f: f.stated_on)
            chain = " → ".join(f"\"{f.value}\"{' ' + f.unit if f.unit and f.unit not in f.value else ''} @{f.valid_start} ({f.stated_on}, {f.modality}"
                               + (f", {f.status.upper()}" if f.status != 'new' else "") + ")" for f in fs)
            P(f"  - {attr} ({fs[0].family}): {chain}")
    ev = sum(1 for e in by if any(w in st.entities[e].name.lower() for w in ("target", "achievement", "availability", "demo", "update", "wind-down")))
    P(f"\n사건형 대상 이름: {ev} / {len(by)}")

    # K3
    P("\n## K3 기회 등급\n")
    recs = defaultdict(list)
    for o in st.opps.values():
        recs[o.eid].append(o)
    tier = {e: ("A" if any(o.customer for o in rs) else "B") for e, rs in recs.items()}
    P(f"기회 대상 {len(recs)}개: A급 {sum(1 for v in tier.values() if v == 'A')}, B급 {sum(1 for v in tier.values() if v == 'B')} (제외는 추출 단계에서 걸러져 기록 없음)\n")
    P("| 등급 | 기회 | 종류 | 기록 | 시장·고객 | 제공물 | 성숙도 |\n|---|---|---|---|---|---|---|")
    for e, rs in sorted(recs.items(), key=lambda x: (tier[x[0]], -len(x[1]))):
        kinds = Counter(o.kind for o in rs).most_common(1)[0][0]
        cust = sorted({o.customer for o in rs if o.customer})[:3]
        offs = sorted({st.entities[o.offering].name for o in rs if o.offering and o.offering in st.entities})[:3]
        mat = Counter(o.maturity for o in rs).most_common(1)[0][0]
        P(f"| {tier[e]} | {st.entities[e].name} | {kinds} | {len(rs)} | {', '.join(cust)} | {', '.join(offs)} | {mat} |")
    if st.grid:
        P(f"\n그리드: 열 {len(st.grid['columns'])} {st.grid['meta'].get('columns_by_tier')}, 칸 {len(st.grid['cells'])}")

    # K2
    if st.tree:
        P("\n## K2 영역 추세 (계산 추세 → LLM 추세, 연도별 문서 비율)\n")
        for ar in st.tree["areas"]:
            sh = ", ".join(f"{r['year']} {r['docs']}/{r['total']}" for r in ar.get("shares", []))
            P(f"- {ar['name']}: computed {ar.get('computed_trend')} → {ar['trend']} ({sh}; emphasis {ar.get('emphasis')}) {('— ' + ar['trend_reason']) if ar.get('trend_reason') else ''}")

    # 카드
    ctx = build_worksheets(st, set(STRUCTS), label="ALL")
    P(f"\n## 작업지 통계 (ALL)\n\n{ctx.stats}\n")
    cards = ctx.text.split("### Card ")
    if len(cards) > a.card:
        P(f"## 기회 카드 {a.card}\n\n```\n### Card " + cards[a.card].split("\n## ")[0].strip() + "\n```")
    txt = "\n".join(out)
    print(txt)
    if a.write:
        (Path(a.run) / "inspect.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
