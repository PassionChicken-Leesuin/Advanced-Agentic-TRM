# -*- coding: utf-8 -*-
"""영역 묶기 수정 뒤 트리(K2)만 다시 생성: tree.json(스토어) + tree_real.json. python scripts/redo_tree.py --run runs/xxx"""
import argparse, io, json, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trmkb.llm import LLM
from trmkb.sources.store import SourceStore
from trmkb.sources.tree import build_tree

ap = argparse.ArgumentParser(); ap.add_argument("--run", required=True); a = ap.parse_args()
st, llm = SourceStore(a.run), LLM()
t = build_tree(st, llm); st.save()
print("tree:", {"areas": len(t["areas"]), "themes": len(t["themes"])}, [(x["name"], len(x["theme_ids"])) for x in t["areas"]])
tr = build_tree(st, llm, real_only=True, emit=False)
(Path(a.run) / "tree_real.json").write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
print("tree_real:", {"areas": len(tr["areas"]), "themes": len(tr["themes"])}, [(x["name"], len(x["theme_ids"])) for x in tr["areas"]])
llm.ledger.dump(Path(a.run) / "cost_redo_tree.json"); print(f"cost ${llm.ledger.total_usd:.3f}")
