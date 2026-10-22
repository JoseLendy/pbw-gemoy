"""
P4: thin OpenAI-compatible LLM client used by every LLM stage.

Env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (strong), LLM_MODEL_FAST (fast).
- chat_json: JSON mode where the endpoint supports it, else extract the first JSON object.
  2 retries on invalid JSON.
- chat_text: same, returns the raw text.
- Two-temperature design (plan §6.2): facts are locked at 0, only the writer is creative.
  FACT_TEMPERATURE (default 0)   ledger / extraction / intake / scenario / reconcile
  WRITER_TEMPERATURE (default 0.85) writer / rewrite / baseline
  CHECK_TEMPERATURE (default 0)  8A / 8B / 8C / 8D / 8E and any judge stage
- Per-stage timings are accumulated in self.timings (seconds, summed per stage name).
- Hard wall-clock deadline per HTTP attempt: LLM_CALL_DEADLINE seconds (default 120). The SDK/httpx
  timeout is per socket read, so an endpoint that keeps a response alive by trickling bytes never
  trips it (2026-10-23: four single calls ran ~3600 s). An attempt past the deadline is abandoned
  and raised as openai.APITimeoutError, so it is retried and then fails exactly like a timeout.
- Never logs or prints keys. Missing env raises LLMConfigError with a message the UI can show.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("agent.llm")

# Two-temperature design. Stage -> temperature bucket; anything unlisted is a fact stage.
WRITER_STAGES = {"writer", "rewrite", "baseline"}
CHECK_STAGES = {"check", "check_facts", "check_compliance", "check_conformance",
                "8a", "8b", "8c", "8d", "8e", "judge"}

DEFAULT_FACT_TEMPERATURE = 0.0
DEFAULT_WRITER_TEMPERATURE = 0.85
DEFAULT_CHECK_TEMPERATURE = 0.0
JSON_RETRIES = 2
RATE_RETRIES = 2            # 429 / timeout / 5xx: retried with backoff, each retry logged
RATE_BACKOFF = (2.0, 6.0)   # seconds before retry 1, 2
DEFAULT_CALL_DEADLINE = 120.0   # s, hard wall-clock cap on ONE HTTP attempt (healthy calls take < 40 s)


def call_deadline() -> float:
    """LLM_CALL_DEADLINE in seconds (> 0); a missing, bad or non-positive value gives the default."""
    raw = (os.environ.get("LLM_CALL_DEADLINE") or "").strip()
    if not raw:
        return DEFAULT_CALL_DEADLINE
    try:
        v = float(raw)
    except ValueError:
        v = -1.0
    if not v > 0:
        log.warning("LLM_CALL_DEADLINE=%r is not a positive number, using %s", raw, DEFAULT_CALL_DEADLINE)
        return DEFAULT_CALL_DEADLINE
    return v


def _env_temperature(name: str, default: float) -> float:
    """Read a temperature from the environment; a bad value falls back to the default (never crashes)."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        log.warning("%s=%r is not a number, using %s", name, raw, default)
        return default
    if not (0.0 <= v <= 2.0):
        log.warning("%s=%r is outside [0, 2], using %s", name, raw, default)
        return default
    return v


def temperatures() -> dict[str, float]:
    """The three configured temperatures (plan §6.2). Read on each call so tests and the UI can override."""
    return {
        "fact": _env_temperature("FACT_TEMPERATURE", DEFAULT_FACT_TEMPERATURE),
        "writer": _env_temperature("WRITER_TEMPERATURE", DEFAULT_WRITER_TEMPERATURE),
        "check": _env_temperature("CHECK_TEMPERATURE", DEFAULT_CHECK_TEMPERATURE),
    }


def temperature_for(stage: str, override: float | None = None) -> float:
    """Temperature for one stage. An explicit override wins; then writer / check / fact buckets."""
    if override is not None:
        return override
    key = (stage or "").split(":")[0].strip().lower()
    t = temperatures()
    if key in WRITER_STAGES:
        return t["writer"]
    if key in CHECK_STAGES:
        return t["check"]
    return t["fact"]


class LLMConfigError(RuntimeError):
    """Raised when the LLM env is incomplete. Message is safe to show in the UI (no secrets)."""


class LLMResponseError(RuntimeError):
    """Raised when the model never returned valid JSON after the retries."""


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Read prompts/<name>.md at runtime, so the repo shows the real prompt design."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def _load_env() -> None:
    """Load the repo-root .env if python-dotenv is available. Never reads or prints the values itself.

    The path is explicit (as in ima_wrapper): a bare load_dotenv() walks up from this file and, in a
    git worktree under <repo>/.claude/worktrees/, picks up the MAIN checkout's .env."""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
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
        # max_retries=0: rate-limit / timeout retries happen in _create, with backoff and a log line.
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        self.timings: dict[str, float] = {}
        self.calls: list[dict] = []          # {"stage", "model", "seconds", "ok", "json_retries"}; never content
        self._json_mode_ok: dict[str, bool] = {}   # per model: does response_format work?
        self._temperature_ignored = False    # set once if the model rejects the temperature parameter
        self.rate_retries = 0                # 429 / timeout / 5xx retries taken (logged; never content)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _temperature(stage: str, override: float | None) -> float:
        return temperature_for(stage, override)

    def _record(self, stage: str, model: str, t0: float, ok: bool, retries: int = 0) -> None:
        dt = time.perf_counter() - t0
        self.timings[stage or "unnamed"] = self.timings.get(stage or "unnamed", 0.0) + dt
        self.calls.append({"stage": stage, "model": model, "seconds": round(dt, 3), "ok": ok,
                           "json_retries": retries})
        from agent.timing import add
        add(f"llm.{stage or 'unnamed'}", dt)     # per-run attribution (no-op outside a pipeline run)

    def _call(self, params: dict[str, Any]) -> str:
        """One completion; 429 / timeout / 5xx are retried RATE_RETRIES times with backoff and logged."""
        for attempt in range(RATE_RETRIES + 1):
            try:
                r = self._bounded_create(params)
                return r.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                if attempt >= RATE_RETRIES or not _is_transient(e):
                    raise
                wait = RATE_BACKOFF[min(attempt, len(RATE_BACKOFF) - 1)]
                log.warning("LLM %s (model %s): retry %d/%d in %.0fs", type(e).__name__, params.get("model", ""),
                            attempt + 1, RATE_RETRIES, wait)
                self.rate_retries += 1
                time.sleep(wait)
        raise AssertionError("unreachable")

    def _bounded_create(self, params: dict[str, Any]) -> Any:
        """chat.completions.create with a hard wall-clock deadline (LLM_CALL_DEADLINE).

        The request runs on a daemon thread; if it is still running at the deadline it is abandoned
        (its socket read timeout or the server ends it later) and APITimeoutError is raised here.
        """
        deadline = call_deadline()
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["r"] = self._client.chat.completions.create(**params)
            except BaseException as e:  # noqa: BLE001  (re-raised on the caller's thread)
                box["e"] = e

        t = threading.Thread(target=run, name="llm-call", daemon=True)
        t.start()
        t.join(deadline)
        if t.is_alive():
            log.warning("LLM call (model %s) still running after the %.0fs deadline (LLM_CALL_DEADLINE); "
                        "abandoning it", params.get("model", ""), deadline)
            import httpx
            from openai import APITimeoutError
            url = str(getattr(self._client, "base_url", "") or "http://llm.invalid/")
            raise APITimeoutError(request=httpx.Request("POST", url))
        if "e" in box:
            raise box["e"]
        return box["r"]

    def _create(self, params: dict[str, Any]) -> str:
        """One API call. A model that rejects `temperature` is retried without it, once per model."""
        model = params.get("model", "")
        try:
            return self._call(params)
        except Exception as e:  # noqa: BLE001
            if "temperature" not in params or not _looks_like_unsupported_temperature(e):
                raise
            if not self._temperature_ignored:
                log.warning("model %s rejects temperature; sending it without one from now on", model)
                self._temperature_ignored = True
            params = {k: v for k, v in params.items() if k != "temperature"}
            return self._call(params)

    def _complete(self, messages: list[dict], model: str, temperature: float,
                  json_mode: bool, **kw: Any) -> str:
        params: dict[str, Any] = dict(model=model, messages=messages)
        if not self._temperature_ignored:
            params["temperature"] = temperature
        params.update(kw)
        if json_mode and self._json_mode_ok.get(model, True):
            try:
                r = self._create({**params, "response_format": {"type": "json_object"}})
                return r
            except Exception as e:  # endpoint/model doesn't support JSON mode -> plain text + extraction
                if _looks_like_unsupported_param(e):
                    self._json_mode_ok[model] = False
                else:
                    raise
        return self._create(params)

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


def _is_transient(e: Exception) -> bool:
    """Rate limit (429), timeout / connection error or a 5xx: worth retrying after a pause."""
    status = getattr(e, "status_code", None)
    if isinstance(status, int):                 # an HTTP answer: only 429 and 5xx are worth retrying
        return status == 429 or status >= 500   # (402 balance / 4xx are final; "429" may sit in a request id)
    name = type(e).__name__.lower()
    return any(k in name for k in ("ratelimit", "timeout", "connection"))


def _looks_like_unsupported_param(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("response_format", "json_object", "unsupported", "invalid_request",
                                  "not support", "unknown parameter", "400"))


def _looks_like_unsupported_temperature(e: Exception) -> bool:
    """True when the failure is specifically about the temperature parameter, not some other 400."""
    msg = str(e).lower()
    return "temperature" in msg and any(k in msg for k in ("invalid", "unsupported", "not support", "range",
                                                           "out of", "expected", "unknown parameter", "400"))
