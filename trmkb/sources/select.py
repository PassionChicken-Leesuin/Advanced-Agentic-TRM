"""기회 카드 선정 — 카드마다 여러 LLM 이 Phaal 의 세 질문(왜 가야 하는가 / 지금 어디인가 / 갈 수 있는가)을 토론해
프로파일(q1, q2, q3)을 세우고, 차원별로 표준화한 합으로 상위 N 을 고른다 (2026-11-03 사용자와 확정).

  1라운드: 모델마다 카드만 보고 Q1~Q3 를 0~10 으로 평가 + 근거 줄 id + 쟁점.
  2라운드: 서로의 1라운드 평가를 보고 반박·수정해 최종 점수.
  프로파일 = 모델별 최종 점수의 평균. 근거 id 가 하나도 없는 점수는 뺀다.
  순위 = 차원별 z-점수의 합 (원점수도 보존). Q1 만 높고 Q2·Q3 가 낮은 카드는 '경로를 만들어야 할 기회' 로 따로 표시.
"""
from __future__ import annotations

import json
import re
import statistics as S
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from ..llm import LLM

QUESTIONS = """Three questions, asked from the company's own point of view, answered ONLY from what this card (the company's documents) says:
Q1. Why should the company pursue this opportunity? Who demands it, for what, under what conditions and by when (named customers/markets,
    numbers, deadlines score high); and has the company itself stated this direction in strategy/vision statements?
Q2. Where is the company now on it? What it already has: the offering's lifecycle stage (exploring -> pilot -> contracted -> revenue),
    the latest capability metrics, secured customers/partners/resources.
Q3. Can the company get there? Is the gap between the required specification (why lines) and current capability (how lines, latest values)
    visible in the documents, and is there a plan with dates to close it (dated planned facts, preceding milestones, acquisitions, facilities, hiring)?
Scores are 0-10 per question. Every score must cite the card line ids (ps_..., tf_...) it rests on. Knowledge from outside the card
(what you know about the industry) must not raise a score; if a line is missing, say so and score low."""

SYS = "You are one of several analysts debating how a company should prioritise an opportunity for its technology roadmap. JSON only."

R1_USER = """{questions}

Opportunity card (assembled from the company's documents; 'internal' marks internal documents):
{card}

Give your round-1 assessment. Return JSON:
{{"q1": int, "q2": int, "q3": int, "evidence": {{"q1": [ids], "q2": [ids], "q3": [ids]}},
  "reasons": {{"q1": str, "q2": str, "q3": str}}, "contested": [str]}}
reasons: one sentence each (<=40 words). contested: up to 3 points another analyst might reasonably score differently."""

R2_USER = """{questions}

Opportunity card:
{card}

Round-1 assessments (yours is marked *):
{others}

Round 2: reply to the other assessments. Where they cite a line you missed, or you cited a line they missed, adjust. Where you disagree,
say why in one sentence. Then give your FINAL scores. Return JSON:
{{"q1": int, "q2": int, "q3": int, "evidence": {{"q1": [ids], "q2": [ids], "q3": [ids]}},
  "reasons": {{"q1": str, "q2": str, "q3": str}}, "replies": [str], "changed": bool}}"""


class Assess(BaseModel):
    q1: int = Field(ge=0, le=10)
    q2: int = Field(ge=0, le=10)
    q3: int = Field(ge=0, le=10)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    contested: list[str] = Field(default_factory=list)
    replies: list[str] = Field(default_factory=list)
    changed: bool = False


ID_RE = re.compile(r"\b(?:ps|tf|ev|chunk)_[0-9a-f]+\b")


def _valid_ids(ev: list[str], card_text: str) -> list[str]:
    return [i for i in ev if ID_RE.fullmatch(i) and i in card_text]


def debate_card(llm: LLM, card: dict, card_text: str, models: list[str], *, rounds: int = 2) -> dict:
    tag = {m: m.split("/")[1] for m in models}
    r1: dict[str, Assess] = {}

    def ask(model, user, purpose):
        return llm.structured(model, SYS, user, Assess, purpose=purpose, max_tokens=3000, temperature=0.2)

    with ThreadPoolExecutor(max_workers=len(models)) as ex:
        for m, a in zip(models, ex.map(lambda m: ask(m, R1_USER.format(questions=QUESTIONS, card=card_text), "select_r1"), models)):
            r1[m] = a
    final = dict(r1)
    if rounds >= 2:
        def r2(m):
            others = "\n".join(f"{'*' if mm == m else ' '} {tag[mm]}: q1={a.q1} q2={a.q2} q3={a.q3} | {json.dumps(a.reasons, ensure_ascii=False)} | evidence {json.dumps(a.evidence)} | contested {a.contested}"
                               for mm, a in r1.items())
            return ask(m, R2_USER.format(questions=QUESTIONS, card=card_text, others=others), "select_r2")
        with ThreadPoolExecutor(max_workers=len(models)) as ex:
            for m, a in zip(models, ex.map(r2, models)):
                final[m] = a
    rec = {"eid": card["eid"], "name": card["name"], "models": {}}
    for m in models:
        a1, a2 = r1[m], final[m]
        ev = {q: _valid_ids(a2.evidence.get(q, []), card_text) for q in ("q1", "q2", "q3")}
        rec["models"][tag[m]] = {"r1": {"q1": a1.q1, "q2": a1.q2, "q3": a1.q3, "reasons": a1.reasons, "contested": a1.contested},
                                "final": {"q1": a2.q1, "q2": a2.q2, "q3": a2.q3, "reasons": a2.reasons, "replies": a2.replies, "changed": a2.changed},
                                "evidence_valid": ev}
    # 프로파일: 근거 id 가 있는 점수만 평균
    prof = {}
    for q in ("q1", "q2", "q3"):
        vals = [v["final"][q] for v in rec["models"].values() if v["evidence_valid"][q]]
        allv = [v["final"][q] for v in rec["models"].values()]
        r1v = [v["r1"][q] for v in rec["models"].values()]
        prof[q] = round(S.mean(vals), 2) if vals else 0.0
        prof[q + "_n_grounded"] = len(vals)
        prof[q + "_sd_r1"] = round(S.pstdev(r1v), 2) if len(r1v) > 1 else 0.0
        prof[q + "_sd_final"] = round(S.pstdev(allv), 2) if len(allv) > 1 else 0.0
    rec["profile"] = prof
    return rec


# 선정 관점(stance): 세 질문의 가중치. 사용자가 "어떤 기회를 위에 두고 싶은가"를 고른다 (2026-11-03). 기본은 동일 가중.
STANCES = {
    "balanced": {"w": (1.0, 1.0, 1.0), "label": "Balanced", "desc": "the three questions count equally"},
    "demand":   {"w": (1.6, 0.7, 0.7), "label": "Demand-led", "desc": "opportunities that customers and the company's own strategy call for most, even if the company is early on them"},
    "position": {"w": (0.7, 1.6, 0.7), "label": "Build on what we have", "desc": "opportunities where the company already has offerings, customers and capability in place"},
    "path":     {"w": (0.7, 0.7, 1.6), "label": "Where a path exists", "desc": "opportunities whose gap to the requirement is documented together with a dated plan to close it"},
}


def rank(records: list[dict], top: int = 10, *, stance: str = "balanced", kinds: dict[str, str] | None = None,
         quota: dict[str, int] | None = None) -> list[dict]:
    """차원별 z-점수의 가중합으로 정렬. kinds(eid→application|product_type)와 quota({'product_type': 3, 'application': 7})가 있으면
    종류별로 나눠 뽑는다 (워크숍의 기회 군집이 응용 범주별이었던 것에 대응). Q1 높고 Q2·Q3 낮은 카드는 path_needed 표시."""
    w = STANCES[stance]["w"]
    for q in ("q1", "q2", "q3"):
        xs = [r["profile"][q] for r in records]
        mu, sd = S.mean(xs), (S.pstdev(xs) or 1.0)
        for r in records:
            r["profile"][q + "_z"] = round((r["profile"][q] - mu) / sd, 3)
    for r in records:
        p = r["profile"]
        p["score"] = round(w[0] * p["q1_z"] + w[1] * p["q2_z"] + w[2] * p["q3_z"], 3)
        p["stance"] = stance
        p["path_needed"] = p["q1"] >= 7 and p["q2"] <= 3 and p["q3"] <= 3
        p["kind"] = (kinds or {}).get(r["eid"], "application")
    records.sort(key=lambda r: -r["profile"]["score"])
    for i, r in enumerate(records, 1):
        r["profile"]["rank"] = i
    if quota and kinds:
        chosen, taken = set(), {k: 0 for k in quota}
        for r in records:
            k = r["profile"]["kind"]
            if k in taken and taken[k] < quota[k]:
                chosen.add(r["eid"]); taken[k] += 1
        for r in records:                      # 어느 종류의 카드가 정원보다 적으면 전체 순위로 채움
            if len(chosen) >= sum(quota.values()):
                break
            chosen.add(r["eid"])
        for r in records:
            r["profile"]["selected"] = r["eid"] in chosen
    else:
        for i, r in enumerate(records, 1):
            r["profile"]["selected"] = i <= top
    return records


def write_outputs(records: list[dict], out_dir: Path, top: int, support_rank: dict[str, int] | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    st = records[0]["profile"].get("stance", "balanced") if records else "balanced"
    (out_dir / ("profiles.json" if st == "balanced" else f"profiles_{st}.json")).write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    st = records[0]["profile"].get("stance", "balanced") if records else "balanced"
    md = [f"# 기회 카드 선정 (토론 프로파일, 상위 {top}, 관점 {st} w={STANCES[st]['w']})", "",
          "| 순위 | 기회 | 종류 | q1 | q2 | q3 | 가중합(z) | 모델 편차 r1→final (q1/q2/q3) | 근거 있는 모델 수 | 문서지지 순위 | 비고 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        p = r["profile"]
        sd = "/".join(f"{p[q + '_sd_r1']:.1f}→{p[q + '_sd_final']:.1f}" for q in ("q1", "q2", "q3"))
        ng = "/".join(str(p[q + "_n_grounded"]) for q in ("q1", "q2", "q3"))
        note = ("선정" if p["selected"] else "") + (" 경로 필요" if p["path_needed"] else "")
        md.append(f"| {p['rank']} | {r['name'][:50]} | {p.get('kind', '')} | {p['q1']} | {p['q2']} | {p['q3']} | {p['score']} | {sd} | {ng} | {support_rank.get(r['eid'], '-') if support_rank else '-'} | {note} |")
    (out_dir / ("ranking.md" if st == "balanced" else f"ranking_{st}.md")).write_text("\n".join(md) + "\n", encoding="utf-8")
