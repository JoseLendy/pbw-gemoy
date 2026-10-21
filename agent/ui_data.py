"""
UI adapter (Phase 3). The ONLY file outside ui/ the UI workstream may create or edit (plan "Code
structure"). Every ui/*.py module calls through here, never agent.pipeline / agent.recommend /
agent.runs directly, so the UI doesn't care which backend paths are real vs fake, and so a single
shared Deps (one catalog, one ima client) is built for the whole app - never two.

    get_cards(store_id, date=None)        -> list[RecommendationCard]           agent.recommend.store_data.cards_for
    generate(card, staff=None)            -> RunResult | LockedResult | ...     agent.pipeline.run_from_card
    baseline(card)                        -> BaselineResult | LockedResult      agent.pipeline.generate_baseline
    edit(result, instruction)             -> RunResult | ... | EditBlocked      agent.pipeline.edit
    compare(cards, staff_map=None)        -> BatchResult                        agent.pipeline.generate_batch
    verify_new_product(model_id)          -> None                               agent.recommend.store_data.set_fact_card_status
    reset()                               -> None                               agent.recommend.store_data.reset_demo_state
    last_real_run(card_id)                -> dict | None                        agent.runs.latest_run
    prepared_post(store_id, date)         -> dict | None                        agent.runs.prepared_post
    clear_prepared(date)                  -> int                                agent.runs.clear_prepared

prepared_post/clear_prepared landed in Phase 5 (PR #4, merged); detected once at import like every
other optional path, so a future rename/removal degrades to None/0 instead of crashing the UI.
`ACTIVE_PATHS` is logged at startup so the UI can show real-vs-fallback status without touching the
network itself. prepared_post/last_real_run return the RAW logged dict (agent.runs._payload shape),
not a live RunResult - see ui.components.prepared_post_html for why and how it's rendered.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
from typing import Any, Callable, Optional

from agent.pipeline import BatchResult, Deps, edit as _pipeline_edit, generate_batch as _generate_batch
from agent.pipeline import generate_baseline as _generate_baseline
from agent.pipeline import run_from_card as _run_from_card
from agent.recommend.common import INPUTS, load_json
from agent.recommend.store_data import (
    cards_for as _cards_for, load_store_data, reset_demo_state, set_fact_card_status,
)
from agent.runs import latest_run
from agent.schemas import RecommendationCard, StaffContext

log = logging.getLogger("agent.ui_data")

# ---------------------------------------------------------------- demo date (plan: never the system clock)
_DEFAULT_TODAY = "2026-10-23"


def today() -> str:
    return os.getenv("DEMO_TODAY", _DEFAULT_TODAY)


# ---------------------------------------------------------------- shared Deps (one instance for the whole app)
DEPS: Deps = Deps.auto()


# ---------------------------------------------------------------- optional Phase 5 hooks, detected once
def _optional(mod_name: str, attr: str) -> Optional[Callable]:
    try:
        fn = getattr(importlib.import_module(mod_name), attr)
    except Exception as e:  # ImportError / AttributeError: not merged yet
        log.info("ui_data: %s.%s not available, falling back (%s)", mod_name, attr, e)
        return None
    log.info("ui_data: %s.%s is wired (real)", mod_name, attr)
    return fn


_prepared_post_fn = _optional("agent.runs", "prepared_post")
_clear_prepared_fn = _optional("agent.runs", "clear_prepared")

ACTIVE_PATHS: dict[str, bool] = {
    "prepared_post": _prepared_post_fn is not None,
    "clear_prepared": _clear_prepared_fn is not None,
}
log.info("ui_data: active adapter paths = %s; dev_mode=%s fake_fields=%s",
         ACTIVE_PATHS, DEPS.is_dev_mode, DEPS.fake_fields)


def prepared_post(store_id: str, date: Optional[str] = None) -> Optional[dict]:
    """The raw logged record (agent.runs._payload shape: {"status", "result", "timestamp", ...}), or
    None if nothing was prepared for that store/date yet, or on any failure - the UI falls back to the
    normal card flow either way. Render it with ui.components.prepared_post_html, never as a live post."""
    if _prepared_post_fn is None:
        return None
    try:
        return _prepared_post_fn(store_id, date or today())
    except Exception as e:  # noqa: BLE001 - a missing/half-built optional path must never break the UI
        log.warning("prepared_post failed: %s", e)
        return None


def clear_prepared(date: Optional[str] = None) -> int:
    """重置演示 (plan §8) must NOT call this - prepared posts survive reset. Returns how many were
    deleted, or 0 if the path isn't wired or the call failed."""
    if _clear_prepared_fn is None:
        return 0
    try:
        return _clear_prepared_fn(date or today())
    except Exception as e:  # noqa: BLE001
        log.warning("clear_prepared failed: %s", e)
        return 0


# ---------------------------------------------------------------- stores / cards
def list_stores() -> list[dict]:
    """Raw store rows (stores.csv), for building the store selector. Read-only demo data."""
    return list(load_store_data().stores)


def get_cards(store_id: str, date: Optional[str] = None) -> list[RecommendationCard]:
    return _cards_for(store_id, date or today())


def question_pool() -> dict:
    """question_pool.json "chips": {chip_id: {text, segments}} - the UI's end-of-day chip list."""
    return dict(load_json(INPUTS / "question_pool.json")["chips"])


# ---------------------------------------------------------------- generate / edit / baseline / compare
def generate(card: RecommendationCard, staff: Optional[StaffContext] = None, deps: Optional[Deps] = None):
    return _run_from_card(card, deps or DEPS, staff)


def baseline(card: RecommendationCard, deps: Optional[Deps] = None):
    return _generate_baseline(card, deps=deps or DEPS)


def edit(result, instruction: str, deps: Optional[Deps] = None):
    return _pipeline_edit(result, instruction, deps or DEPS)


def compare(cards, staff_map: Optional[dict] = None, deps: Optional[Deps] = None) -> BatchResult:
    return _generate_batch(cards, deps or DEPS, staff_map)


def verify_new_product(model_id: str) -> None:
    """HQ "确认发布" (plan §7): drafts are never used for store posts until this runs."""
    set_fact_card_status(model_id, "verified")


def reset() -> None:
    """重置演示 (plan §8/§9): backend only (fact-card overrides + data cache). The UI must separately
    clear its own session state (已发布 / chips / shown results) - see ui.components.fresh_session()."""
    reset_demo_state()


def last_real_run(card_id: str) -> Optional[dict]:
    return latest_run(card_id)


# ---------------------------------------------------------------- plain-language errors (never leak keys/ids)
_SECRET_RE = re.compile(r"(IMA_OPENAPI_\w+|LLM_API_KEY|sk-[A-Za-z0-9]{8,}|[A-Za-z0-9]{32,})")


def plain_error(e: Exception) -> str:
    code = getattr(e, "code", None)
    msg = str(e)
    if code == 220021 or "220021" in msg or "次数已达上限" in msg:
        return "知识库今日调用次数已达上限，已使用缓存/请稍后再试。"
    if code == 403 or "403" in msg or "无权限" in msg:
        return "该资料目录没有访问权限，已跳过。"
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "知识库或模型响应超时，请稍后重试。"
    if (code == 402 or "402" in msg or "insufficient balance" in msg.lower() or "余额不足" in msg
            or "quota" in msg.lower()):
        return "模型账户额度不足，请联系管理员充值后重试。"
    if "LLM" in msg or "openai" in msg.lower() or "api key" in msg.lower():
        return "模型服务暂时不可用，请稍后重试。"
    if "node" in msg.lower() and "not found" in msg.lower():
        return "运行环境缺少 Node.js，无法调用知识库。"
    return "生成失败：" + _SECRET_RE.sub("［已隐藏］", msg)[:200]


__all__ = [
    "DEPS", "ACTIVE_PATHS", "today", "prepared_post", "clear_prepared", "list_stores", "get_cards",
    "question_pool", "generate", "baseline", "edit", "compare", "verify_new_product", "reset",
    "last_real_run", "plain_error",
]
