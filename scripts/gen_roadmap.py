"""로드맵 생성 CLI (1막 initial).

python scripts/gen_roadmap.py initial --run runs/demo            # KB 없음
python scripts/gen_roadmap.py initial --run runs/demo --model anthropic/claude-sonnet-4.6
python scripts/gen_roadmap.py show --run runs/demo
"""
import argparse
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from trmkb.llm import LLM
from trmkb.roadmap import generate as G


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["initial", "advanced", "diff", "context", "show", "prompt"])
    ap.add_argument("--run", default="runs/demo")
    ap.add_argument("--model", default=G.DEFAULT_MODEL)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--initial-from", default=None, help="advanced/diff: initial roadmap 을 다른 run 에서 복사해 올 경로")
    args = ap.parse_args()

    if args.cmd == "prompt":
        print(G.SYSTEM, "\n---\n", G.build_user_prompt(None), "\n--- hash:", G.prompt_hash())
        return
    if args.cmd in ("context", "advanced", "diff"):
        from trmkb.roadmap import retrieve as R
        from trmkb.store import KBStore
        kb = KBStore(args.run)
        if args.cmd == "context":
            ctx = R.build_context(kb)
            print(ctx.text[:6000]); print("\n...stats:", ctx.stats)
            return
        if args.initial_from and not G.load(args.run, "initial"):
            import shutil
            shutil.copy(args.initial_from, f"{args.run}/roadmap_initial.json")
        llm = LLM()
        if args.cmd == "advanced":
            ctx = R.build_context(kb)
            print("context stats:", ctx.stats)
            rm = G.generate(llm, condition="advanced", context=ctx.text, model=args.model, temperature=args.temperature,
                            ops_by_evidence=ctx.ops_by_ref)
            p = G.save(rm, args.run)
            print(json.dumps(G.summary(rm), indent=1, ensure_ascii=False)); print("saved", p)
            return
        from trmkb.roadmap import diff as D
        ini, adv = G.load(args.run, "initial"), G.load(args.run, "advanced")
        assert ini and adv, "both roadmap_initial.json and roadmap_advanced.json are required"
        d = D.compute_diff(ini, adv, llm)
        p = D.save(d, args.run)
        print(json.dumps({k: v for k, v in d.items() if k != "pairs"}, indent=1, ensure_ascii=False)); print("saved", p)
        return
    if args.cmd == "show":
        for cond in ("initial", "advanced"):
            rm = G.load(args.run, cond)
            if rm:
                print(json.dumps(G.summary(rm), indent=1, ensure_ascii=False))
                for layer in ("why", "what", "how", "resource"):
                    print(f"\n[{layer}]")
                    for n in sorted((x for x in rm.nodes if x.layer.value == layer), key=lambda x: x.start or 0):
                        print(f"  {n.start:.1f}-{n.end:.1f}  {n.label}  ({n.category})  {n.flags or ''}")
        return
    llm = LLM()
    rm = G.generate(llm, condition="initial", model=args.model, temperature=args.temperature)
    p = G.save(rm, args.run)
    print(json.dumps(G.summary(rm), indent=1, ensure_ascii=False))
    print("saved", p)


if __name__ == "__main__":
    main()
