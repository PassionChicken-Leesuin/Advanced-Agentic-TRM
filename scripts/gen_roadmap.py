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
    ap.add_argument("cmd", choices=["initial", "show", "prompt"])
    ap.add_argument("--run", default="runs/demo")
    ap.add_argument("--model", default=G.DEFAULT_MODEL)
    ap.add_argument("--temperature", type=float, default=0.2)
    args = ap.parse_args()

    if args.cmd == "prompt":
        print(G.SYSTEM, "\n---\n", G.build_user_prompt(None), "\n--- hash:", G.prompt_hash())
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
