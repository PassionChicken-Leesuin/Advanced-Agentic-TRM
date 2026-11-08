"""로드맵 항목의 근거 사슬: 로드맵 항목 ← 기회 카드(어느 줄) ← 지식 구조(어떤 사실·관계·문장) ← 원문.

생성기는 선정된 카드 전문을 읽고 항목마다 근거 id(ps_ = 문장, tf_ = 시간 사실)를 인용한다. 그 id 가 어느 카드의 어느 줄에 있었는지,
그 줄 조각이 어느 구조에서 왔는지를 카드 텍스트에서 되짚는다. 카드 줄의 꼴 (cards_v2.Card):
  why / issue     "[kind, modality, date, type] 문장 [ps_..]"                       → 근거 저장소 (원문 문장 그대로)
  how / resource  "A --requires--> B [ps_..] | latest: 지표 "값" @2024 (...) [tf_.., ps_..]"  → 관계 그래프 / 시간 지식그래프
  what / state    "대상 (e_..): lifecycle stage "GA" @2023 (...) [tf_.., ps_..]"     → 시간 지식그래프 (제공물 연결은 관계 그래프)
  when            "대상: 속성 (family): "값" @연도 (...) [tf_.., ps_..] -> ..."       → 시간 지식그래프 (갱신·충돌 사슬)
  trend           주제의 연도별 문서 수                                               → 주제 요약 트리
"""
from __future__ import annotations

import re

from .store import SourceStore

LINE_ORDER = ("why", "what", "state", "when", "how", "resource", "actors", "issue", "trend")
LINE_NAME = {"why": "why (needs, drivers, vision)", "what": "what (offerings)", "state": "now (current stage)", "when": "when (dated statements)",
             "how": "how (capabilities)", "resource": "resources (enablers)", "actors": "actors", "issue": "issues (risks, barriers)",
             "trend": "trend (documents per year)"}
REL_RE = re.compile(r"(?P<a>[^|\[\]]+?)\s+--(?P<rel>[a-z_]+)-->\s+(?P<b>[^\[\]|]+?)\s*$")


def _segment(text: str, idx: int) -> str:
    """id 가 든 대괄호 바로 앞의 조각 (앞선 ']' 또는 '|' 또는 '->' 뒤부터)."""
    lb = text.rfind("[", 0, idx)
    head = text[:lb] if lb >= 0 else text[:idx]
    # 사슬 구분자는 앞뒤 빈칸이 있는 " -> " 뿐 (관계 표기 "--part_of-->" 안의 "->" 와 구별)
    arrow = head.rfind(" -> ")
    cut = max(head.rfind("]"), head.rfind("|"), arrow + 3 if arrow >= 0 else -1)
    seg = head[cut + 1:] if cut >= 0 else head
    return seg.strip(" ;,:")


def _structure(line: str, seg: str, rid: str) -> tuple[str, str]:
    if line == "trend":
        return "theme summary tree", seg
    m = REL_RE.search(seg)
    if m:
        return "relation graph", f"{m.group('a').strip()} —{m.group('rel').replace('_', ' ')}→ {m.group('b').strip()}"
    if rid.startswith("tf_") or re.search(r"@\d{4}", seg) or "lifecycle stage" in seg:
        return "temporal knowledge graph", re.sub(r"^latest:\s*", "", seg)
    return "evidence store", re.sub(r"^\[[^\]]*\]\s*", "", seg)


def _source(st: SourceStore, rid: str) -> dict | None:
    p = st.passages.get(rid)
    if p is None:
        f = st.facts.get(rid)
        p = st.passages.get(f.pid) if f else None
    if p is None:
        return None
    return {"text": p.text, "date": p.doc_date.isoformat(), "type": p.source_type, "synthetic": p.is_synthetic, "doc_id": p.doc_id}


def _fact_detail(st: SourceStore, rid: str) -> str | None:
    f = st.facts.get(rid)
    if not f:
        return None
    e = st.entities.get(f.eid)
    when = f" @{f.valid_start:g}" if f.valid_start is not None else ""
    status = f", {f.status}" if f.status in ("update", "conflict") else ""
    return f"{e.name if e else f.eid} · {f.attribute} = {f.value}{when} ({f.modality or '-'}{status})"


def chains(st: SourceStore, cards: list[dict], rm: dict, selected: list[str] | None = None, max_cards: int = 2) -> dict:
    """{node_id: [{id, card: {eid, name, selected} | None, line, line_name, structure, detail, source}]}"""
    sel = set(selected or [])
    order = sorted(cards, key=lambda c: (c["eid"] not in sel, (selected or []).index(c["eid"]) if c["eid"] in sel else 0))
    out = {}
    for n in rm.get("nodes", []):
        steps = []
        for rid in n.get("evidence_ids", []):
            hits = []
            for c in order:
                for line in LINE_ORDER:
                    for txt in c.get(line, []) or []:
                        i = txt.find(rid)
                        if i < 0:
                            continue
                        seg = _segment(txt, i)
                        struct, detail = _structure(line, seg, rid)
                        if struct == "temporal knowledge graph":
                            detail = _fact_detail(st, rid) or detail
                        hits.append({"card": {"eid": c["eid"], "name": c["name"], "selected": c["eid"] in sel}, "line": line,
                                     "line_name": LINE_NAME.get(line, line), "structure": struct, "detail": detail[:300]})
                        break
                    if hits and hits[-1]["card"]["eid"] == c["eid"]:
                        break
                if len(hits) >= max_cards:
                    break
            src = _source(st, rid)
            if not hits:
                struct = "temporal knowledge graph" if rid.startswith("tf_") else "evidence store"
                hits = [{"card": None, "line": None, "line_name": None, "structure": struct, "detail": _fact_detail(st, rid) or ""}]
            for h in hits:
                steps.append({"id": rid, **h, "source": src})
        out[n["id"]] = steps
    return out
