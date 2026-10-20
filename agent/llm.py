"""
P4: thin OpenAI-compatible LLM client used by every LLM stage.

Env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (strong), LLM_MODEL_FAST (fast).
- chat_json: JSON mode where the endpoint supports it, else extract the first JSON object.
  2 retries on invalid JSON. Temperature 0.2 for intake/extraction stages, 0.7 for writing.
- chat_text: same, returns the raw text.
- Per-stage timings are accumulated in self.timings (seconds, summed per stage name).
- Never logs or prints keys. Missing env raises LLMConfigError with a message the UI can show.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

# Stages that extract/classify (low temperature). Everything else is writing (0.7).
EXTRACTION_STAGES = {"intake", "scenario", "reconcile", "ledger", "extract", "check", "check_facts",
                     "check_compliance"}
TEMP_EXTRACT = 0.2
TEMP_WRITE = 0.7
JSON_RETRIES = 2


class LLMConfigError(RuntimeError):
    """Raised when the LLM env is incomplete. Message is safe to show in the UI (no secrets)."""


class LLMResponseError(RuntimeError):
    """Raised when the model never returned valid JSON after the retries."""


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Read prompts/<name>.md at runtime, so the repo shows the real prompt design."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def _load_env() -> None:
    """Load .env if python-dotenv is available. Never reads or prints the values itself."""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass


def extract_json(text: str) -> Optional[dict]:
    """Return the first JSON object in `text`, or None. Tolerates ```json fences and prose around it."""
    if not text:
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Scan for the first balanced {...} that parses.
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = s.find("{", start + 1)
    return None


class LLM:
    """OpenAI-compatible chat client. Same interface as tests.fakes.FakeLLM."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, model_fast: str | None = None, timeout: float = 90.0):
        _load_env()
        base_url = base_url or os.environ.get("LLM_BASE_URL", "").strip()
        api_key = api_key or os.environ.get("LLM_API_KEY", "").strip()
        self.model = (model or os.environ.get("LLM_MODEL", "")).strip()
        self.model_fast = (model_fast or os.environ.get("LLM_MODEL_FAST", "")).strip() or self.model
        missing = [n for n, v in (("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key),
                                  ("LLM_MODEL", self.model)) if not v]
        if missing:
            raise LLMConfigError("LLM 未配置：缺少环境变量 " + "、".join(missing)
                                 + "。请在 .env 或部署平台的密钥设置中填写（不要把密钥写进代码或聊天）。")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise LLMConfigError("缺少依赖 openai，请执行 pip install -r requirements.txt") from e
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.timings: dict[str, float] = {}
        self._lock = threading.Lock()        # 8A and 8B record timings from two threads
        self.calls: list[dict] = []          # {"stage", "model", "seconds", "ok", "json_retries"}; never content
        self._json_mode_ok: dict[str, bool] = {}   # per model: does response_format work?

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _temperature(stage: str, override: float | None) -> float:
        if override is not None:
            return override
        key = (stage or "").split(":")[0].lower()
        return TEMP_EXTRACT if key in EXTRACTION_STAGES else TEMP_WRITE

    def _record(self, stage: str, model: str, t0: float, ok: bool, retries: int = 0) -> None:
        dt = time.perf_counter() - t0
        with self._lock:
            self.timings[stage or "unnamed"] = self.timings.get(stage or "unnamed", 0.0) + dt
            self.calls.append({"stage": stage, "model": model, "seconds": round(dt, 3), "ok": ok,
                               "json_retries": retries})

    def _complete(self, messages: list[dict], model: str, temperature: float,
                  json_mode: bool, **kw: Any) -> str:
        params: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature)
        params.update(kw)
        if json_mode and self._json_mode_ok.get(model, True):
            try:
                r = self._client.chat.completions.create(response_format={"type": "json_object"}, **params)
                return r.choices[0].message.content or ""
            except Exception as e:  # endpoint/model doesn't support JSON mode -> plain text + extraction
                if _looks_like_unsupported_param(e):
                    self._json_mode_ok[model] = False
                else:
                    raise
        r = self._client.chat.completions.create(**params)
        return r.choices[0].message.content or ""

    # ------------------------------------------------------------------ public API
    def chat_json(self, system: str, user: str, stage: str = "", fast: bool = False, **kw: Any) -> dict:
        model = self.model_fast if fast else self.model
        temperature = self._temperature(stage, kw.pop("temperature", None))
        t0 = time.perf_counter()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_text = ""
        for attempt in range(JSON_RETRIES + 1):
            try:
                text = self._complete(messages, model, temperature, json_mode=True, **kw)
            except Exception:
                self._record(stage, model, t0, ok=False, retries=attempt)
                raise
            obj = extract_json(text)
            if obj is not None:
                self._record(stage, model, t0, ok=True, retries=attempt)
                return obj
            last_text = text
            # Ask again, showing the model what it produced, and insist on bare JSON.
            messages = messages[:2] + [
                {"role": "assistant", "content": text[:4000]},
                {"role": "user", "content": "上面的输出不是合法 JSON。请只输出一个 JSON 对象，不要任何解释或 Markdown 代码块。"},
            ]
        self._record(stage, model, t0, ok=False, retries=JSON_RETRIES)
        raise LLMResponseError(f"模型在 {JSON_RETRIES + 1} 次尝试后仍未返回合法 JSON（阶段 {stage or '未命名'}）。"
                               f" 返回开头：{last_text[:120]!r}")

    def chat_text(self, system: str, user: str, stage: str = "", fast: bool = False, **kw: Any) -> str:
        model = self.model_fast if fast else self.model
        temperature = self._temperature(stage, kw.pop("temperature", None))
        t0 = time.perf_counter()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            text = self._complete(messages, model, temperature, json_mode=False, **kw)
        except Exception:
            self._record(stage, model, t0, ok=False)
            raise
        self._record(stage, model, t0, ok=True)
        return text.strip()

    def status(self) -> dict:
        """Safe for the UI: no key characters."""
        return {"configured": True, "model": self.model, "model_fast": self.model_fast,
                "api_key": "已配置"}


def _looks_like_unsupported_param(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("response_format", "json_object", "unsupported", "invalid_request",
                                  "not support", "unknown parameter", "400"))
