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

import dataclasses
import datetime as dt
import importlib
import logging
import os
import re
from typing import Any, Callable, Optional

from agent.pipeline import BatchResult, Deps, edit as _pipeline_edit, generate_batch as _generate_batch
from agent.pipeline import generate_baseline as _generate_baseline
from agent.pipeline import run_from_card as _run_from_card
from agent.recommend.common import INPUTS, load_json, parse_date
from agent.recommend.store_data import (
    all_cards as _all_cards, cards_for as _cards_for, default_card as _default_card,
    fact_card_overrides as _fact_card_overrides, load_store_data,
    product_card as _product_card, reset_demo_state, set_fact_card_status,
    set_store_approval, store_approvals,
)
from agent.runs import latest_run
from agent.schemas import (
    CheckIssue, CheckReport, Conflict, Fact, ImagePlan, ImageRef, Ledger, Model, PlannedImage, Post,
    PostImage, RecommendationCard, RunResult, ScenarioAnalysis, SellingPoint, SourceRecord, StaffContext,
    Strategy, Task,
)

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


def default_card(store_id: str, date: Optional[str] = None) -> Optional[RecommendationCard]:
    return _default_card(store_id, date or today())


def product_card(store_id: str, model_id: str, date: Optional[str] = None) -> Optional[RecommendationCard]:
    """Stage 2: this store's 活动款 card, pointed at one fixed product (None if not in a campaign)."""
    return _product_card(store_id, model_id, date or today())


def fact_card_overrides() -> dict[str, str]:
    """HQ verifications made in this process (model_id -> draft/verified)."""
    return dict(_fact_card_overrides())


def question_pool() -> dict:
    """question_pool.json "chips": {chip_id: {text, segments}} - the UI's end-of-day chip list."""
    return dict(load_json(INPUTS / "question_pool.json")["chips"])


# ---------------------------------------------------------------- generate / edit / baseline / compare
def generate(card: RecommendationCard, staff: Optional[StaffContext] = None, deps: Optional[Deps] = None,
             on_progress=None, on_post=None):
    """on_progress(stage, message) streams progress lines; on_post(kind, post) streams the live draft
    ("draft" after the first write, "revision" after each rewrite) so the UI can type it in."""
    if on_progress is not None or on_post is not None:
        return _run_from_card(card, deps or DEPS, staff, on_progress=on_progress, on_post=on_post)
    return _run_from_card(card, deps or DEPS, staff)


def baseline(card: RecommendationCard, deps: Optional[Deps] = None):
    return _generate_baseline(card, deps=deps or DEPS)


def edit(result, instruction: str, deps: Optional[Deps] = None, on_progress=None, on_post=None):
    if on_progress is not None or on_post is not None:
        return _pipeline_edit(result, instruction, deps or DEPS, on_progress=on_progress, on_post=on_post)
    return _pipeline_edit(result, instruction, deps or DEPS)


def compare(cards, staff_map: Optional[dict] = None, deps: Optional[Deps] = None, on_progress=None) -> BatchResult:
    if on_progress is not None:
        return _generate_batch(cards, deps or DEPS, staff_map, on_progress=on_progress)
    return _generate_batch(cards, deps or DEPS, staff_map)


def verify_new_product(model_id: str) -> None:
    """HQ "确认发布" (plan §7), every store: drafts are never used for store posts until this runs."""
    set_fact_card_status(model_id, "verified")


def verify_new_product_for_store(model_id: str, store_id: str) -> None:
    """A manager confirms a new product for their own store: only that store's staff unlock it."""
    set_store_approval(model_id, store_id)


_RESET_TOKEN = 0


def reset() -> None:
    """重置演示 (plan §8/§9): backend only (fact-card overrides + data cache). The UI must separately
    clear its own session state (已发布 / chips / shown results) - see ui.components.fresh_session().
    reset_token() tells another tab/session that the backend state changed."""
    global _RESET_TOKEN
    reset_demo_state()
    from agent.recommend.weekly import clear_marks       # today's 已发布 marks are demo state; prepared posts are not
    clear_marks(today())
    _RESET_TOKEN += 1


def reset_token() -> int:
    """Bumped by reset(); the store tab clears its session when this differs from what it last saw."""
    return _RESET_TOKEN


def last_real_run(card_id: str) -> Optional[dict]:
    return latest_run(card_id)


def run_result_from_payload(payload: Optional[dict]) -> Optional[RunResult]:
    """Rehydrate a stored `RunResult` record (agent.runs payload) for the UI's read-only prepared /
    recovery screens. Returns None for any other status or a malformed record instead of raising."""
    if not isinstance(payload, dict) or payload.get("status") not in (None, "RunResult"):
        return None
    d = payload.get("result") or {}
    try:
        keep = lambda cls, value: {k: v for k, v in (value or {}).items()
                                   if k in {f.name for f in dataclasses.fields(cls)}}  # noqa: E731
        task = Task(**keep(Task, d.get("task")))
        model = Model(**keep(Model, d.get("model")))
        analysis = ScenarioAnalysis(**keep(ScenarioAnalysis, (d.get("strategy") or {}).get("analysis")))
        strategy_d = d.get("strategy") or {}
        strategy = Strategy(
            analysis=analysis, angle=strategy_d.get("angle") or "",
            selling_points=[SellingPoint(**keep(SellingPoint, x)) for x in strategy_d.get("selling_points") or []],
            dropped_categories=dict(strategy_d.get("dropped_categories") or {}),
            talk_card=list(strategy_d.get("talk_card") or []),
            cta_type=strategy_d.get("cta_type") or "",
            pending=list(strategy_d.get("pending") or []),
        )
        ledger_d = d.get("ledger") or {}
        ledger = Ledger(
            model_id=ledger_d.get("model_id") or model.model_id,
            facts=[Fact(**keep(Fact, x)) for x in ledger_d.get("facts") or []],
            conflicts=[Conflict(**keep(Conflict, x)) for x in ledger_d.get("conflicts") or []],
            dropped=list(ledger_d.get("dropped") or []),
            entities=list(ledger_d.get("entities") or []),
            boundaries=list(ledger_d.get("boundaries") or []),
        )
        plan_d = d.get("plan") or {}
        plan = ImagePlan(
            platform=plan_d.get("platform") or "",
            items=[PlannedImage(image=ImageRef(**keep(ImageRef, (x or {}).get("image"))),
                                position=(x or {}).get("position") or "",
                                caption=(x or {}).get("caption") or "")
                   for x in plan_d.get("items") or []],
            shortage=bool(plan_d.get("shortage")), note=plan_d.get("note") or "",
        )
        report_d = d.get("report") or {}
        report = CheckReport([CheckIssue(**keep(CheckIssue, x)) for x in report_d.get("issues") or []])
        post_d = d.get("post") or {}
        post = Post(platform=post_d.get("platform") or "", title=post_d.get("title") or "",
                    intro=post_d.get("intro") or "", body=list(post_d.get("body") or []),
                    cta=post_d.get("cta") or "", tags=list(post_d.get("tags") or []),
                    selling_points=list(post_d.get("selling_points") or []),
                    images=[PostImage(**keep(PostImage, x)) for x in post_d.get("images") or []])
        sources = [SourceRecord(**keep(SourceRecord, x)) for x in d.get("sources") or []]
        return RunResult(task=task, model=model, strategy=strategy, ledger=ledger, plan=plan, post=post,
                         report=report, pending=list(d.get("pending") or []), sources=sources,
                         timings=dict(d.get("timings") or {}), loops=int(d.get("loops") or 0),
                         fallback=d.get("fallback"))
    except Exception as e:  # noqa: BLE001 - a stored record must never crash a page
        log.warning("run_result_from_payload failed: %s", e)
        return None


_HOOK_LABELS: Optional[dict[str, str]] = None


def hook_label(hook_id: Optional[str]) -> Optional[str]:
    """Human label for angles.json's hook id (used after 8E changes a card's hook)."""
    global _HOOK_LABELS
    if not hook_id:
        return None
    if _HOOK_LABELS is None:
        try:
            _HOOK_LABELS = {h["id"]: h["label"] for h in load_json(INPUTS / "angles.json")["hooks"]}
        except Exception:  # noqa: BLE001
            _HOOK_LABELS = {}
    return _HOOK_LABELS.get(hook_id) or hook_id


def model_display_name(model_id: Optional[str]) -> Optional[str]:
    if not model_id:
        return None
    try:
        return load_store_data().model(model_id)["display_name"]
    except Exception:  # noqa: BLE001
        return None


def similarity_threshold() -> float:
    """8E threshold, exposed so the compare tab never hardcodes a stale value."""
    try:
        from agent.style.similarity import similarity_threshold as _threshold
        return _threshold()
    except Exception:  # noqa: BLE001
        return 0.55


# ---------------------------------------------------------------- HQ panels (offline, local files only)
def publish_stats(days: int = 14) -> dict:
    """Posting rate per store over the last `days` dates in publish_log.csv (local fixture)."""
    data = load_store_data()
    dates = sorted({r["date"] for r in data.publish})[-days:]
    stats = []
    for s in data.stores:
        rows = [r for r in data.publish if r["store_id"] == s["store_id"] and r["date"] in dates]
        posted = sum(str(r.get("posted", "")).lower() == "true" for r in rows)
        stats.append({"store_id": s["store_id"], "store_name": s["store_name"],
                      "posted": posted, "days": len(dates) or 1,
                      "rate": posted / (len(dates) or 1), "low": False})
    ordered = sorted(stats, key=lambda x: (x["rate"], x["store_id"]))
    for row in ordered[:3]:
        row["low"] = True
    return {"window": [dates[0], dates[-1]] if dates else ["", ""], "days": len(dates), "stats": stats}


def question_stats(limit: int = 8, store_id: Optional[str] = None) -> list[dict]:
    """Aggregated customer questions (chip text), most frequent first. `store_id` scopes it to one store
    (the manager's 总部端); the default aggregates every store."""
    data = load_store_data()
    agg: dict[str, dict] = {}
    for q in data.questions:
        if store_id and q.get("store_id") != store_id:
            continue
        key = q.get("chip_id") or q.get("text") or "?"
        row = agg.setdefault(key, {"chip_id": key, "text": q.get("text") or key,
                                   "count": 0, "stores": set()})
        row["count"] += 1
        if q.get("store_id"):
            row["stores"].add(q["store_id"])
    out = [{"chip_id": r["chip_id"], "text": r["text"], "count": r["count"],
            "stores": len(r["stores"])} for r in agg.values()]
    return sorted(out, key=lambda x: (-x["count"], x["chip_id"]))[:limit]


def weekly_progress(store_id: str, date: Optional[str] = None) -> dict:
    """{"progress": {platform: {done, minimum}}, "suggestion": platform, "line": 「本周：…」} for one store."""
    from agent.recommend.weekly import progress_line, suggest_platform, weekly_progress as _wp
    prog = _wp(store_id, date or today())
    sug = suggest_platform(prog)
    return {"progress": prog, "suggestion": sug, "line": progress_line(prog, sug)}


def weekly_progress_all(date: Optional[str] = None) -> list[dict]:
    """总部端 本周计划: every store's weekly progress against the minimums; `behind` lists platforms short."""
    from agent.recommend.weekly import behind
    out = []
    for st in load_store_data().stores:
        w = weekly_progress(st["store_id"], date)
        gap = behind(w["progress"])
        out.append({"store_id": st["store_id"], "store_name": st["store_name"], **w,
                    "behind": [p for p, n in gap.items() if n > 0]})
    return out


def mark_published(store_id: str, platform: str, card_id: str = "", date: Optional[str] = None) -> None:
    from agent.recommend.weekly import mark_published as _mark
    _mark(store_id, date or today(), platform, card_id)


def stored_version(card: RecommendationCard, platform: Optional[str] = None) -> Optional[dict]:
    """A precomputed version of this card on `platform` (prepare_today / prepare_demo), or None."""
    try:
        from agent.runs import stored_version as _sv
        return _sv(card, platform)
    except Exception as e:  # noqa: BLE001 - a missing/half-built record must never break the UI
        log.warning("stored_version failed: %s", e)
        return None


def stored_compare(model_id: str, platform: str = "朋友圈", date: Optional[str] = None) -> Optional[dict]:
    from agent.recommend.to_task import platform_key
    from agent.runs import stored
    try:
        return stored(date or today(), "compare", f"{model_id}__{platform_key(platform)}")
    except Exception as e:  # noqa: BLE001
        log.warning("stored_compare failed: %s", e)
        return None


def stored_baseline(card_id: str, date: Optional[str] = None) -> Optional[dict]:
    from agent.runs import stored
    try:
        return stored(date or today(), "baseline", card_id)
    except Exception as e:  # noqa: BLE001
        log.warning("stored_baseline failed: %s", e)
        return None


def baseline_from_payload(payload: Optional[dict]):
    """Rehydrate a stored BaselineResult (its 8D hits included), or None."""
    from agent.schemas import BaselineResult
    try:
        d = dict((payload or {})["baseline"])
        d["hits"] = [CheckIssue(**h) for h in d.get("hits") or []]
        return BaselineResult(**d)
    except Exception:  # noqa: BLE001
        return None


def check_edit(text: str, result: RunResult):
    """「检查并保存」: deterministic checks only (agent.edit_check), no LLM call."""
    from agent.edit_check import check_edit as _check
    return _check(text, result)


def log_human_edit(card: RecommendationCard, platform: str, original_text: str, edited_text: str) -> None:
    from agent.runs import log_human_edit as _log
    try:
        _log(card, platform, original_text, edited_text)
    except Exception as e:  # noqa: BLE001 - logging never blocks the save
        log.warning("human edit log failed: %s", e)


def export_zip(post: Post, store_id: str, text: Optional[str] = None, date: Optional[str] = None,
               fetch: Optional[Callable[[str], bytes]] = None) -> str:
    """「下载发布包」: write <store>-<date>-<platform>.zip to the download folder; returns its path.
    fetch overrides where image bytes come from (the store tab passes its in-process cache)."""
    from agent.export import publish_zip
    import tempfile
    from pathlib import Path
    name, data = publish_zip(post, store_id, date or today(), fetch or getattr(DEPS, "fetch_image_bytes", None), text)
    folder = Path(tempfile.gettempdir()) / "hwpc_downloads"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return str(path)


def weekly_plan(date: Optional[str] = None) -> dict:
    """platform_quota.json's weekly rotation, anchored to the demo date."""
    data = load_store_data()
    day = parse_date(date or today())
    start = day - dt.timedelta(days=day.weekday())
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    days = [{"label": labels[i], "date": (start + dt.timedelta(days=i)).isoformat(),
             "platform": data.quota["rotation"][i], "is_today": i == day.weekday()} for i in range(7)]
    return {"days": days, "minimum": dict(data.quota.get("weekly_minimum") or {}),
            "today": day.isoformat()}


def recommendation_distribution(date: Optional[str] = None) -> list[dict]:
    """Each store's 今日一条: model / slot / platform / segment / angle."""
    data = load_store_data()
    day = date or today()
    all_today = _all_cards(data, day)
    out = []
    for s in data.stores:
        cards = all_today.get(s["store_id"], [])
        card = next((c for c in cards if c.get("is_default")), cards[0] if cards else None)
        if not card:
            continue
        out.append({"store_id": s["store_id"], "store_name": s["store_name"],
                    "display_name": card.get("display_name") or "",
                    "slot_label": card.get("slot_label") or "",
                    "platform": card.get("platform") or "",
                    "segment_label": card.get("segment_label") or "",
                    "angle": card.get("angle") or ""})
    return out


def new_release_drafts(store_id: Optional[str] = None) -> list[dict]:
    """Draft new-release fact cards (models.csv): field groups + source titles, never KB values.
    Values are pending HQ review; only the field names and the source documents are shown.

    `store_id` scopes the approval state to one store (a manager's view); without it a product counts as
    verified when HQ verified it process-wide. `approved_stores` is always the full per-store list."""
    data = load_store_data()
    approved = store_approvals()
    out = []
    for m in data.models:
        if str(m.get("is_new_release", "")).lower() != "true":
            continue
        refs, seen = [], set()
        for key in ("why_student", "why_office", "why_family", "why_shopper"):
            raw = (m.get(key) or "").strip()
            if "—" not in raw:
                continue
            fields, source = (part.strip() for part in raw.split("—", 1))
            if not fields or not source or (fields, source) in seen:
                continue
            seen.add((fields, source))
            refs.append({"ref_id": f"R{len(refs) + 1}", "fields": fields,
                         "source_title": source.rsplit("/", 1)[-1], "source_path": source})
        status = m.get("fact_card_status") or "draft"
        stores = approved.get(m["model_id"], [])
        approved_here = bool(store_id) and store_id in stores
        verified = status == "verified" or approved_here
        out.append({"model_id": m["model_id"], "display_name": m["display_name"],
                    "launch_date": m.get("launch_date") or "",
                    "status": "verified" if verified else status,
                    "verified": verified, "approved_here": approved_here,
                    "approved_stores": stores, "refs": refs})
    return out


def compare_products(date: Optional[str] = None) -> list[dict]:
    """Products in an active campaign on the demo date - the fixed product options for 三店对比."""
    data = load_store_data()
    day = parse_date(date or today())
    out, seen = [], set()
    for p in data.promos:
        if not (parse_date(p["start"]) <= day <= parse_date(p["end"])):
            continue
        for model_id in p.get("models") or []:
            if model_id in seen:
                continue
            seen.add(model_id)
            out.append({"model_id": model_id, "display_name": data.model(model_id)["display_name"],
                        "campaign": p.get("name") or ""})
    return out


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
    "default_card", "product_card", "fact_card_overrides", "question_pool", "generate", "baseline",
    "edit", "compare", "verify_new_product", "reset", "reset_token", "last_real_run",
    "run_result_from_payload", "hook_label", "model_display_name", "similarity_threshold",
    "publish_stats", "question_stats", "weekly_plan", "recommendation_distribution",
    "new_release_drafts", "compare_products", "plain_error", "weekly_progress", "weekly_progress_all",
    "mark_published", "stored_version", "stored_compare", "stored_baseline", "baseline_from_payload",
    "check_edit", "log_human_edit", "export_zip",
]
