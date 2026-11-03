"""카드 v2 선정: 카드마다 모델 셋이 Q1~Q3 를 토론 → 프로파일 → z-합 순위 → 상위 N.

python scripts/select_cards.py --run runs/struct5 [--limit 5] [--top 10] [--models ...] [--rounds 2] [--force]
산출: runs/<run>/cards_v2/selection/{debate_<eid>.json, profiles.json, ranking.md}
"""
import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.llm import LLM
from trmkb.sources.cards_v2 import Card
from trmkb.sources.select import debate_card, rank, write_outputs

MODELS = ["openai/gpt-4.1", "anthropic/claude-sonnet-4.6", "google/gemini-2.5-flash"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/struct5")
    ap.add_argument("--limit", type=int, default=0, help="앞 n장만 (시범)")
    ap.add_argument("--only", nargs="*", default=None, help="이름에 이 문자열이 든 카드만")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--models", nargs="*", default=MODELS)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--stances", nargs="*", default=["balanced", "q1", "q2", "q3"])
    ap.add_argument("--quota-product", type=int, default=-1, help="상위 N 중 제품형 정원 (나머지는 응용형); -1 이면 종류 구분 없음")
    a = ap.parse_args()
    root = Path(a.run) / "cards_v2"
    cards = json.loads((root / "cards.json").read_text(encoding="utf-8"))
    texts = {}
    for c in cards:
        cc = Card(**{k: (set(v) if k in ("pids", "elements") else v) for k, v in c.items()})
        texts[c["eid"]] = cc.text()
    sel = cards
    if a.only:
        sel = [c for c in cards if any(k.lower() in c["name"].lower() for k in a.only)]
    if a.limit:
        sel = sel[:a.limit]
    out = root / "selection"; out.mkdir(parents=True, exist_ok=True)
    llm = LLM()

    def job(c):
        p = out / f"debate_{c['eid']}.json"
        if p.exists() and not a.force:
            return json.loads(p.read_text(encoding="utf-8"))
        rec = debate_card(llm, c, texts[c["eid"]], a.models, rounds=a.rounds)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        pr = rec["profile"]
        print(f"  {c['name'][:45]:45s} q1 {pr['q1']:4.1f} q2 {pr['q2']:4.1f} q3 {pr['q3']:4.1f} | sd final {pr['q1_sd_final']}/{pr['q2_sd_final']}/{pr['q3_sd_final']}", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        records = list(ex.map(job, sel))
    support = sorted(cards, key=lambda c: -(c["docs_public"] + c["docs_internal"]))
    support_rank = {c["eid"]: i for i, c in enumerate(support, 1)}
    kinds = {c["eid"]: c["kind"] for c in cards}
    quota = {"product_type": a.quota_product, "application": a.top - a.quota_product} if a.quota_product >= 0 else None
    for stance in a.stances:
        recs = rank([dict(r, profile=dict(r["profile"])) for r in records], top=a.top, stance=stance, kinds=kinds, quota=quota)
        write_outputs(recs, out, a.top, support_rank)
        sel = [f"{r['name'][:34]} ({r['profile']['kind'][0]})" for r in recs if r["profile"]["selected"]]
        print(f"[{stance}] " + " | ".join(sel))
    print(f"cost ${llm.ledger.total_usd:.3f}")


if __name__ == "__main__":
    main()
