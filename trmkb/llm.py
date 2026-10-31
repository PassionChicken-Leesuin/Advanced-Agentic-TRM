"""
trmkb.llm — OpenRouter 클라이언트. 키 로테이션, 재시도, 구조화 출력, 비용 집계.

.env 의 Open_Router_key1..N 을 읽는다. 429/401/402 가 오면 다음 키로 넘어간다.
비용은 OpenRouter 응답의 usage.cost 를 그대로 집계한다 (extra_body usage.include=True).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from dotenv import dotenv_values
from openai import APIStatusError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def load_keys(env_path: str | Path | None = None) -> list[str]:
    env_path = Path(env_path) if env_path else Path(__file__).resolve().parent.parent / ".env"
    vals = dotenv_values(env_path) if env_path.exists() else {}
    keys = []
    for k, v in sorted(vals.items(), key=lambda kv: _key_index(kv[0])):
        if re.match(r"(?i)open_?router_?key\d*$", k) and v:
            keys.append(v.strip())
    env_single = os.environ.get("OPENROUTER_API_KEY")
    if env_single:
        keys.insert(0, env_single)
    if not keys:
        raise RuntimeError(f"No OpenRouter keys found in {env_path}")
    return keys


def _key_index(name: str) -> int:
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else 0


@dataclass
class CallRecord:
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_s: float
    key_idx: int


@dataclass
class CostLedger:
    records: list[CallRecord] = field(default_factory=list)

    def add(self, r: CallRecord) -> None:
        self.records.append(r)

    @property
    def total_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def by(self, attr: str) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for r in self.records:
            k = getattr(r, attr)
            d = out.setdefault(k, {"calls": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0})
            d["calls"] += 1; d["cost_usd"] += r.cost_usd
            d["prompt_tokens"] += r.prompt_tokens; d["completion_tokens"] += r.completion_tokens
        return out

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "total_usd": self.total_usd,
            "by_model": self.by("model"),
            "by_purpose": self.by("purpose"),
            "n_calls": len(self.records),
        }, indent=2, ensure_ascii=False), encoding="utf-8")


class LLM:
    def __init__(self, keys: list[str] | None = None, *, max_retries: int = 4,
                 ledger: CostLedger | None = None, app_title: str = "trmkb"):
        self.keys = keys or load_keys()
        self.key_idx = 0
        self.max_retries = max_retries
        self.ledger = ledger or CostLedger()
        self._headers = {"HTTP-Referer": "https://github.com/local/trmkb", "X-Title": app_title}
        self._client = self._make_client()

    def _make_client(self) -> OpenAI:
        return OpenAI(base_url=OPENROUTER_BASE, api_key=self.keys[self.key_idx],
                      default_headers=self._headers, max_retries=0)

    def _rotate(self) -> None:
        self.key_idx = (self.key_idx + 1) % len(self.keys)
        self._client = self._make_client()

    # ------------------------------------------------------------------
    def complete(self, model: str, system: str, user: str, *, purpose: str = "generic",
                 temperature: float = 0.0, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        last_err: Exception | None = None
        for attempt in range(self.max_retries * len(self.keys)):
            t0 = time.time()
            try:
                kwargs: dict[str, Any] = dict(
                    model=model, temperature=temperature, max_tokens=max_tokens,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    extra_body={"usage": {"include": True}},
                )
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = self._client.chat.completions.create(**kwargs)
                usage = resp.usage
                cost = float(getattr(usage, "cost", None) or
                             (usage.model_extra or {}).get("cost", 0.0) if usage else 0.0)
                self.ledger.add(CallRecord(
                    model=model, purpose=purpose,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    cost_usd=cost, latency_s=time.time() - t0, key_idx=self.key_idx))
                return resp.choices[0].message.content or ""
            except RateLimitError as e:
                last_err = e; self._rotate(); time.sleep(1.0)
            except APIStatusError as e:
                last_err = e
                if e.status_code in (401, 402, 403, 429):
                    self._rotate(); time.sleep(1.0)
                elif e.status_code >= 500:
                    time.sleep(2.0 * (attempt + 1))
                else:
                    raise
            except Exception as e:  # 네트워크 등
                last_err = e; time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after retries: {last_err}")

    def structured(self, model: str, system: str, user: str, schema: type[T], *,
                   purpose: str = "generic", temperature: float = 0.0,
                   max_tokens: int = 4096, repair_attempts: int = 2) -> T:
        """pydantic 스키마로 파싱되는 JSON 출력. 실패 시 오류를 돌려주며 수정 요청."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys_prompt = (f"{system}\n\nReturn ONLY a JSON object that conforms to this JSON Schema:\n"
                      f"{schema_json}")
        prompt = user
        for i in range(repair_attempts + 1):
            raw = self.complete(model, sys_prompt, prompt, purpose=purpose,
                                temperature=temperature, max_tokens=max_tokens, json_mode=True)
            try:
                return schema.model_validate(_extract_json(raw))
            except (ValidationError, ValueError) as e:
                if i == repair_attempts:
                    _log_failure(model, purpose, raw, str(e))
                    raise
                prompt = (f"{user}\n\nYour previous output failed validation:\n{e}\n"
                          f"Previous output:\n{raw}\nFix it and return valid JSON only.")
        raise AssertionError("unreachable")


FAILURE_LOG = Path(__file__).resolve().parent.parent / "runs" / "_llm_failures.log"


def _log_failure(model: str, purpose: str, raw: str, err: str) -> None:
    try:
        FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FAILURE_LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} model={model} purpose={purpose} err={err[:200]}\n{raw[:1500]}\n")
    except OSError:
        pass


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    salvaged = _salvage_truncated(text)
    if salvaged is not None:
        return salvaged
    raise ValueError("no JSON object in response")


def _salvage_truncated(text: str) -> Any | None:
    """잘린 JSON 복구: 마지막으로 완결된 배열 원소까지 자르고 괄호를 닫는다."""
    start = text.find("{")
    if start < 0:
        return None
    body = text[start:]
    # 마지막 완결 객체 경계 찾기: '}' 뒤에 ',' 또는 ']' 가 올 수 있는 위치를 뒤에서부터 시도
    for cut in [m.end() for m in re.finditer(r"\}", body)][::-1][:60]:
        cand = body[:cut]
        opens = cand.count("[") - cand.count("]")
        braces = cand.count("{") - cand.count("}")
        if opens < 0 or braces < 0:
            continue
        fixed = cand + "]" * opens + "}" * braces
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            continue
    return None
