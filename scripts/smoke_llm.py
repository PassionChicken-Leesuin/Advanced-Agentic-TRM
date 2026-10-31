"""OpenRouter 연결 확인 + 구조화 출력 1회. 비용 몇 센트.
python scripts/smoke_llm.py [model]
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from pydantic import BaseModel
from trmkb.llm import LLM


class Probe(BaseModel):
    company: str
    year_founded: int
    one_line: str


model = sys.argv[1] if len(sys.argv) > 1 else "openai/gpt-4o-mini"
llm = LLM()
print(f"keys loaded: {len(llm.keys)}  model: {model}")
out = llm.structured(model, "You are a concise analyst.", "Describe IonQ in one line.", Probe, purpose="smoke")
print(out)
print(f"cost: ${llm.ledger.total_usd:.5f}  calls: {len(llm.ledger.records)}")
