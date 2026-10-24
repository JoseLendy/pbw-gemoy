"""
Pipeline orchestrator (P5). Runs the WORKFLOW v4 stages 1 → 9 with dependency injection.

- Deps.real()  : the other workstreams' modules (imported lazily, so missing modules only fail here).
- Deps.fake()  : tests/fakes.py; no ima, no LLM.
- Deps.auto()  : real where the module imports, fake otherwise; Deps.fake_fields says which are fake
                 so the UI can show "开发模式：部分模块为模拟数据".

Rules enforced here: ima is never called from this file (only P1 modules do); the check loop runs at
most 2 rewrites; every edit path ends in the check loop; the ledger and bundle are reused on edits.
"""
from __future__ import annotations

import copy
import dataclasses
import importlib
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agent.schemas import (
    CardHook, CheckReport, Clarification, EditBlocked, FailingSentence, ImagePlan, Ledger, LockedResult, ModelBundle,
    NeedsHuman, NeedsReview,
    PLATFORM_LABELS, Post, RecommendationCard, RunResult, SCENARIO_LABELS, StaffContext, Strategy, Task,
)

log = logging.getLogger("agent.pipeline")

MAX_LOOPS = 2
Progress = Optional[Callable[[str, str], None]]
# Streaming hook for the UI: ("draft", post) once the first draft exists, ("revision", post) after each
# targeted rewrite. Purely for display; the result of the run never depends on it.
PostHook = Optional[Callable[[str, "Post"], None]]


def _emit_post(on_post: PostHook, kind: str, post: "Post") -> None:
    """Never let a display callback break a generation run."""
    if on_post is None:
        return
    try:
        on_post(kind, post)
    except Exception as e:  # noqa: BLE001 - streaming is display only
        log.warning("on_post(%s) failed: %s", kind, e)


# ---------------------------------------------------------------- Deps
@dataclass
class Deps:
    """Dependency injection: real modules by default, fakes in tests. Field names per CONTRACTS §3."""
    catalog: Any
    get_bundle: Callable[..., ModelBundle]
    build_ledger: Callable[..., Ledger]
    plan_images: Callable[..., ImagePlan]
    parse_task: Callable[..., Task | Clarification]
    analyze: Callable[..., Any]
    reconcile: Callable[..., Strategy | NeedsHuman]
    write_post: Callable[..., Post]
    rewrite: Callable[..., Post]
    run_checks: Callable[..., CheckReport]
    llm: Any = None
    status: Callable[[], dict] = field(default=lambda: {"kb_name": "", "connected": False,
                                                        "configured": False, "index_status": "stale",
                                                        "error": "status unavailable"})
    fetch_image_bytes: Optional[Callable[[str], bytes]] = None
    fake_fields: list[str] = field(default_factory=list)   # which fields come from tests/fakes.py

    @property
    def is_dev_mode(self) -> bool:
        return bool(self.fake_fields)

    # -- constructors ---------------------------------------------------------------------------
    @classmethod
    def fake(cls) -> "Deps":
        from tests import fakes as F
        return cls(
            catalog=F.FakeCatalog(), get_bundle=lambda model_id, catalog=None: F.fake_bundle(model_id),
            build_ledger=lambda bundle, llm=None, use_cache=True: F.fake_ledger(bundle.model.model_id),
            plan_images=F.fake_plan_images, parse_task=F.fake_parse_task, analyze=F.fake_analyze,
            reconcile=F.fake_reconcile, write_post=F.fake_write_post, rewrite=F.fake_rewrite,
            run_checks=F.fake_run_checks, llm=F.FakeLLM(), status=F.fake_status,
            fetch_image_bytes=None,
            fake_fields=["catalog", "get_bundle", "build_ledger", "plan_images", "parse_task", "analyze",
                         "reconcile", "write_post", "rewrite", "run_checks", "llm", "status"],
        )

    @classmethod
    def real(cls) -> "Deps":
        """Imports the other workstreams' modules lazily. Raises ImportError if one is missing."""
        catalog_mod = importlib.import_module("agent.catalog")
        retrieval = importlib.import_module("agent.retrieval")
        ledger = importlib.import_module("agent.ledger")
        platform_plan = importlib.import_module("agent.platform_plan")
        intake = importlib.import_module("agent.intake")
        scenario = importlib.import_module("agent.scenario")
        reconcile = importlib.import_module("agent.reconcile")
        writer = importlib.import_module("agent.writer")
        checks = importlib.import_module("agent.checks")
        llm_mod = importlib.import_module("agent.llm")
        wrapper = importlib.import_module("agent.ima_wrapper")
        client = wrapper.make_client()
        return cls(
            catalog=catalog_mod.load_catalog(client), get_bundle=retrieval.get_model_bundle,
            build_ledger=ledger.build_ledger, plan_images=platform_plan.plan_images,
            parse_task=intake.parse_task, analyze=scenario.analyze, reconcile=reconcile.reconcile,
            write_post=writer.write_post, rewrite=writer.rewrite, run_checks=checks.run_all,
            llm=llm_mod.LLM(), status=client.status, fetch_image_bytes=retrieval.fetch_image_bytes,
        )

    @classmethod
    def auto(cls) -> "Deps":
        """Real where the module imports and constructs, fake otherwise. Reports the fake fields."""
        d = cls.fake()
        fake_fields = list(d.fake_fields)

        def use(mod: str, attr: str, fld: str, wrap=None):
            try:
                obj = getattr(importlib.import_module(mod), attr)
                setattr(d, fld, wrap(obj) if wrap else obj)
                fake_fields.remove(fld)
            except Exception as e:  # ImportError, AttributeError, constructor errors
                log.info("Deps.auto: %s stays fake (%s)", fld, e)

        client = None
        try:
            wrapper = importlib.import_module("agent.ima_wrapper")
            client = wrapper.make_client()
            d.status = client.status
            fake_fields.remove("status")
        except Exception as e:
            log.info("Deps.auto: ima_wrapper unavailable (%s)", e)
            reason = getattr(e, "msg", None) or str(e)           # e.g. the mirror-missing message
            base_status = d.status
            d.status = lambda: {**base_status(), "error": reason}
        use("agent.catalog", "load_catalog", "catalog", wrap=lambda f: f(client) if client else f())
        use("agent.retrieval", "get_model_bundle", "get_bundle")
        try:
            d.fetch_image_bytes = importlib.import_module("agent.retrieval").fetch_image_bytes
        except Exception:
            d.fetch_image_bytes = None
        use("agent.ledger", "build_ledger", "build_ledger")
        use("agent.platform_plan", "plan_images", "plan_images")
        use("agent.intake", "parse_task", "parse_task")
        use("agent.scenario", "analyze", "analyze")
        use("agent.reconcile", "reconcile", "reconcile")
        use("agent.writer", "write_post", "write_post")
        use("agent.writer", "rewrite", "rewrite")
        use("agent.checks", "run_all", "run_checks")
        use("agent.llm", "LLM", "llm", wrap=lambda c: c())
        d.fake_fields = fake_fields
        return d


_DEFAULT: Optional[Deps] = None


def default_deps() -> Deps:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Deps.auto()
    return _DEFAULT


# ---------------------------------------------------------------- helpers
class _Timer:
    def __init__(self):
        self.timings: dict[str, float] = {}
        self._t0 = time.perf_counter()
        self.start = self._t0

    def lap(self, stage: str):
        now = time.perf_counter()
        self.timings[stage] = round(now - self._t0, 3)
        self._t0 = now

    def total(self):
        self.timings["total"] = round(time.perf_counter() - self.start, 3)
        return self.timings


def _say(on_progress: Progress, stage: str, message: str):
    if on_progress:
        try:
            on_progress(stage, message)
        except Exception:  # a UI callback must never break a run
            log.exception("on_progress failed")


def _collect_pending(strategy: Strategy, plan: ImagePlan, report: CheckReport,
                     task: Task | None = None) -> list[str]:
    pending: list[str] = []
    pending.extend(getattr(task, "notes", None) or [])
    pending.extend(strategy.pending or [])
    if plan.shortage and plan.note:
        pending.append(plan.note)
    for i in report.issues:
        if i.severity == "error":
            pending.append(f"未通过核验：{i.message}" + (f"（{i.span}）" if i.span else ""))
        elif i.code == "pending_request" or ("待确认" in i.message and i.code != "boundary_violation"):
            pending.append(i.message)
    seen, out = set(), []
    for p in pending:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _sibling_ledgers(deps: Deps, model, on_progress: Progress, day: str) -> dict[str, Ledger]:
    from agent.fact_cache import get_facts
    out: dict[str, Ledger] = {}
    for sid in model.siblings or []:
        try:
            out[sid] = get_facts(deps, sid, day)[1]
        except Exception as e:  # a missing sibling must not stop the run
            log.warning("sibling ledger %s failed: %s", sid, e)
            _say(on_progress, "ledger", f"相近型号 {sid} 资料读取失败，8A 将只检查目标型号")
    return out


def _check_variant(task: Task, ledger: Ledger) -> Optional[str]:
    """Drop a variant the model's ledger does not know (agent.intake.check_variant); returns the 待确认 note."""
    from agent.intake import check_variant
    try:
        return check_variant(task, ledger)
    except Exception as e:  # a malformed ledger must not stop the run
        log.warning("variant check failed: %s", e)
        return None


def _auto_cite(post: Post, errors: list, ledger: Ledger) -> tuple[Post, list]:
    """Missing [F#] named by the 8A LLM layer: fixed in code (agent.checks.facts.auto_cite), no rewrite."""
    try:
        from agent.checks.facts import auto_cite
        return auto_cite(post, errors, ledger)
    except Exception as e:
        log.warning("auto-cite failed: %s", e)
        return post, []


# ---------------------------------------------------------------- the check loop (step 8)
def check_loop(post: Post, task: Task, strategy: Strategy, ledger: Ledger, sibling_ledgers: dict,
               plan: ImagePlan, deps: Deps, on_progress: Progress = None, on_post: PostHook = None
               ) -> tuple[Post, CheckReport, int]:
    """run_checks → if errors and loops < MAX_LOOPS: rewrite → run_checks again."""
    from agent.timing import stage
    loops = 0
    with stage("check.pass1"):
        report = deps.run_checks(post, ledger, sibling_ledgers, task, plan, deps.llm)
    n_facts = len(post.selling_points)
    while not report.passed and loops < MAX_LOOPS:
        errors = [i for i in report.issues if i.severity == "error"]
        post, fixed = _auto_cite(post, errors, ledger)
        if fixed:
            log.info("auto-cited %d sentence(s): %s", len(fixed), ", ".join(f"{i.field}+{i.fact_id}" for i in fixed))
            tags = list(dict.fromkeys(i.fact_id for i in fixed))   # several issues can name one missing tag
            _say(on_progress, "check", f"补上 {len(tags)} 处事实编号（{'、'.join(tags)}）")
            errors = [i for i in errors if i not in fixed]
        if errors:
            _say(on_progress, "check", f"发现 {len(errors)} 处问题，定向改写（第 {loops + 1} 轮）…")
            with stage(f"check.rewrite{loops + 1}"):
                post = deps.rewrite(post, errors, task, strategy, ledger, plan, deps.llm)
            _emit_post(on_post, "revision", post)
        loops += 1
        with stage(f"check.pass{loops + 1}"):
            report = deps.run_checks(post, ledger, sibling_ledgers, task, plan, deps.llm)
    if report.passed:
        _say(on_progress, "check", f"核验 {n_facts} 个事实点 ✓")
        _say(on_progress, "check", "合规检查 ✓")
    else:
        n = sum(1 for i in report.issues if i.severity == "error")
        _say(on_progress, "check", f"仍有 {n} 处未通过核验，已标红并列入待确认")
    return post, report, loops


# ---------------------------------------------------------------- the stages 6 → 9 (shared by run and edit)
def _from_plan(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
               strategy: Strategy, deps: Deps, on_progress: Progress, timer: _Timer,
               on_post: PostHook = None) -> RunResult:
    _say(on_progress, "plan", f"规划 {PLATFORM_LABELS.get(task.platform, task.platform)} 版式…")
    # The selling-point facts steer which images fit (agent.platform_plan: no unrelated filler images).
    focus = [f"{f.category} {f.attribute} {f.value}" for sp in strategy.selling_points if (f := ledger.get(sp.fact_id))]
    plan = deps.plan_images(bundle, task.platform, strategy, focus=focus)
    timer.lap("plan")
    _say(on_progress, "plan", f"匹配到 {len(plan.items)} 张图片" + ("（不足，已标记待确认）" if plan.shortage else ""))
    return _from_write(task, model, bundle, ledger, sibling_ledgers, strategy, plan, deps, on_progress, timer, on_post)


def _from_write(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
                strategy: Strategy, plan: ImagePlan, deps: Deps, on_progress: Progress,
                timer: _Timer, on_post: PostHook = None) -> RunResult:
    _say(on_progress, "write", "撰写软文…")
    post = deps.write_post(task, strategy, ledger, plan, deps.llm)
    timer.lap("write")
    _emit_post(on_post, "draft", post)      # the UI types the first draft in while checks run
    _say(on_progress, "check", f"核验 {len(post.selling_points)} 个事实点…")
    post, report, loops = check_loop(post, task, strategy, ledger, sibling_ledgers, plan, deps, on_progress, on_post)
    from agent.checks.prices import mark_demo_prices
    post = mark_demo_prices(post, task)      # a DEMO campaign price always shows [演示活动] (added in code)
    _emit_post(on_post, "revision", post)    # the demo-price tag is added in code, after the last rewrite
    timer.lap("check")
    pending = _collect_pending(strategy, plan, report, task)
    result = RunResult(task=task, model=model, strategy=strategy, ledger=ledger, plan=plan, post=post,
                       report=report, pending=pending, sources=list(bundle.sources), timings=timer.total(),
                       loops=loops)
    return attach_context(result, bundle, sibling_ledgers)


def _from_reconcile(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
                    analysis, deps: Deps, on_progress: Progress, timer: _Timer, on_post: PostHook = None):
    _say(on_progress, "reconcile", "对照知识库事实确定卖点…")
    strategy = deps.reconcile(task, analysis, ledger, model, deps.llm)
    timer.lap("reconcile")
    if isinstance(strategy, NeedsHuman):
        _say(on_progress, "reconcile", "资料冲突，已停止输出，需人工确认")
        return strategy
    _say(on_progress, "reconcile", f"卖点：{'、'.join(sp.fact_id for sp in strategy.selling_points)}")
    return _from_plan(task, model, bundle, ledger, sibling_ledgers, strategy, deps, on_progress, timer, on_post)


def _from_analyze(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
                  deps: Deps, on_progress: Progress, timer: _Timer, on_post: PostHook = None):
    _say(on_progress, "analyze", f"分析{SCENARIO_LABELS.get(task.scenario, task.scenario or '')}场景…")
    analysis = deps.analyze(task, deps.llm)
    timer.lap("analyze")
    return _from_reconcile(task, model, bundle, ledger, sibling_ledgers, analysis, deps, on_progress, timer, on_post)


# ---------------------------------------------------------------- run
def run(text: str, form: dict | None = None, deps: Deps | None = None,
        on_progress: Progress = None, on_post: PostHook = None) -> RunResult | Clarification | NeedsHuman:
    from agent.timing import collect
    deps = deps or default_deps()
    timer = _Timer()
    with collect(timer.timings):
        _say(on_progress, "intake", "理解需求、匹配型号…")
        parsed = deps.parse_task(text, deps.catalog, form, deps.llm)
        timer.lap("intake")
        if isinstance(parsed, Clarification):
            _say(on_progress, "intake", "还缺少信息，请补充")
            return parsed
        result = _from_retrieval(parsed, deps, on_progress, timer, on_post)
        # Same step 1 as the card path's fallback: a post still failing after 2 rewrites first loses its
        # failing sentences and is re-checked; only if that fails too does it reach the user marked red.
        return trim_if_failed(result, deps, on_progress)


# ---------------------------------------------------------------- run from a recommendation card
LOCKED_MESSAGES = {"fact_card_draft": "新品资料待总部确认，暂不可生成"}


def _from_retrieval(task: Task, deps: Deps, on_progress: Progress, timer: _Timer, on_post: PostHook = None):
    """Stages 3 → 9 for a task whose model_id is already exact (shared by run and run_from_card)."""
    import datetime as dt
    from agent.fact_cache import get_facts
    model = deps.catalog.get(task.model_id)
    day = task.card_date or dt.date.today().isoformat()
    _say(on_progress, "retrieval", f"读取产品资料：{model.canonical_name}…")
    bundle, ledger = get_facts(deps, task.model_id, day)     # per (model, date): stores share it (plan §7)
    timer.lap("retrieval")      # retrieval + ledger for the target model (cached after the first store)
    if bundle.index_status != "complete":
        _say(on_progress, "retrieval", "知识库索引可能不完整（" + bundle.index_status + "）")
    _say(on_progress, "ledger", f"台账 {len(ledger.facts)} 条事实" +
         (f"，{len(ledger.conflicts)} 处冲突" if ledger.conflicts else ""))
    note = _check_variant(task, ledger)
    if note:
        task.notes = [*task.notes, note]
        _say(on_progress, "ledger", note)
    sibling_ledgers = _sibling_ledgers(deps, model, on_progress, day)
    timer.lap("ledger")         # variant check + sibling ledgers
    return _from_analyze(task, model, bundle, ledger, sibling_ledgers, deps, on_progress, timer, on_post)


def _log_real(card, result, staff, deps, kind: str = "run_from_card") -> None:
    """Append a full run record only for real deps (fake/demo runs are never logged)."""
    if deps is None or getattr(deps, "is_dev_mode", True):
        return
    try:
        from agent.runs import log_run
        log_run(card, result, staff, kind=kind)
    except Exception as e:  # noqa: BLE001 - logging must never break a run
        log.warning("run log failed: %s", e)


def run_from_card(card: RecommendationCard, deps: Deps | None = None, staff: StaffContext | None = None,
                  on_progress: Progress = None, fallback: bool = True, avoid: dict | None = None,
                  on_post: PostHook = None
                  ) -> RunResult | LockedResult | NeedsHuman | NeedsReview:
    """Proactive entry (PROACTIVE_AGENT_PLAN §3): the card replaces the user sentence, so intake and model
    disambiguation are skipped (the card carries an exact model_id). A locked card returns LockedResult
    before any LLM or ima call. Otherwise continues from retrieval / scenario exactly like run().

    A draft that still fails after 2 rewrites goes through the fallback policy (fallback=True): trim the
    failing sentences → the store's next unlocked card → NeedsReview. An unchecked post is never returned.
    avoid ({"facts": [...], "phrases": [...]}) is set by 8E in generate_batch: what other stores use today."""
    result = _run_card(card, deps, staff, on_progress, avoid, on_post)
    if fallback and isinstance(result, RunResult) and not result.report.passed:
        deps = deps or default_deps()
        result = apply_fallback(card, result, deps, staff, on_progress, on_post)
        if not (isinstance(result, RunResult) and result.fallback == "next_card"):   # next card logged itself
            _log_real(card, result, staff, deps, kind="fallback")
    return result


def _run_card(card: RecommendationCard, deps: Deps | None, staff: StaffContext | None, on_progress: Progress,
              avoid: dict | None = None, on_post: PostHook = None):
    if card.locked:
        reason = card.locked_reason or "locked"
        msg = LOCKED_MESSAGES.get(reason, "该推荐暂不可生成，请等待总部确认")
        _say(on_progress, "card", msg)
        result = LockedResult(card=card, reason=reason, message=msg)
        _log_real(card, result, staff, deps)
        return result
    from agent.recommend.to_task import card_to_task
    deps = deps or default_deps()
    from agent.timing import collect
    timer = _Timer()
    with collect(timer.timings):
        _say(on_progress, "card", f"今日推荐：{card.slot_label} {card.display_name or card.model_id} → {card.platform}")
        task = card_to_task(card, staff)       # raises ValueError on a staff voice the segment does not allow
        if avoid:
            task.avoid_facts = list(avoid.get("facts") or [])
            task.avoid_phrases = list(avoid.get("phrases") or [])
        timer.lap("intake")
        result = _from_retrieval(task, deps, on_progress, timer, on_post)
    _log_real(card, result, staff, deps)
    return result


@dataclass
class SimilarityPair:
    segment: str
    store_a: str
    store_b: str
    before: float
    after: float
    regenerated: bool = False


@dataclass
class BatchResult:
    results: dict[str, Any]                 # store_id -> RunResult | LockedResult | NeedsHuman | Exception
    similarity: list[SimilarityPair]
    regenerated: list[str] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)   # store_id -> wall-clock incl. 8E reruns
    regen_seconds: dict[str, float] = field(default_factory=dict)   # store_id -> part of that spent on 8E reruns
    wall_seconds: float = 0.0               # the whole batch (stores run concurrently)
    variety: dict[str, dict] = field(default_factory=dict)   # store_id -> 8E breach: reasons, avoided, kept?


def batch_max_workers() -> int:
    """BATCH_MAX_WORKERS (default 4): stores generated at the same time. 1 = sequential."""
    try:
        return max(1, int(os.getenv("BATCH_MAX_WORKERS", "4")))
    except ValueError:
        return 4


def _batch_text(result) -> str:
    if not isinstance(result, RunResult):
        return ""
    from agent.formatter import render_publishable
    return render_publishable(result.post)


def _variety_entry(card: RecommendationCard, result) -> Optional[dict]:
    """What 8E compares for one store: the final text plus the wording it may repeat (fact values and
    qualifiers, product names, store details): copying a fact's wording is required, never a style repeat."""
    if not isinstance(result, RunResult):
        return None
    task = result.task
    keep = [f.value for f in result.ledger.facts] + [f.qualifier for f in result.ledger.facts if f.qualifier]
    keep += [task.product_query, task.landmark, task.store_name, card.display_name]
    try:
        from agent.writer import product_names
        keep += product_names(task)
    except Exception:  # noqa: BLE001
        pass
    return {"store_id": card.store_id, "segment": card.segment, "model_id": task.model_id,
            "selling_points": list(result.post.selling_points), "text": _batch_text(result),
            "keep": [k for k in keep if k], "customer": card.slot == "customer_question"}


def generate_batch(cards, deps: Deps | None = None, staff_map: dict | None = None,
                   on_progress: Progress = None, keep_angle: bool = False,
                   max_workers: int | None = None) -> BatchResult:
    """Run several recommendation cards and enforce 8E cross-store variety.

    8E compares every post with every other post of the day (agent.style.similarity.variety_breaches): too
    similar, a phrase in more than 3 posts, a repeated stock opener / filler, or one product's selling point in
    more than 2 stores (or twice in a peer group). The later store id is regenerated once: the next hook unused
    by its peers, told what to avoid (selling points: reconcile drops them; wording: the writer brief lists it),
    and, if still too similar, the next unused angle. The rerun replaces the post only if it passes all checks;
    model and platform never change; customer-question cards are never regenerated. Returns final results,
    before/after similarity pairs for every pair of the day, and the per-store breach record (`variety`).

    The first pass runs stores concurrently (BATCH_MAX_WORKERS, default 4); results keep the input order and
    a store's exception becomes that store's result. The 8E reruns also run concurrently, after that pass.
    Same-model stores share one retrieval + ledger (agent.fact_cache). keep_angle=True (prepare_today: every
    platform version of a card shares its angle) limits a rerun to the hook and the avoid lists.
    """
    from agent.formatter import render_publishable   # noqa: F401  (used by _batch_text)
    from agent.recommend.common import INPUTS, load_json
    from agent.style.similarity import jaccard, similarity_threshold, variety_breaches

    t_batch = time.perf_counter()
    deps = deps or default_deps()
    staff_map = staff_map or {}
    raw = list(cards.values()) if isinstance(cards, dict) else list(cards)
    items = [c if isinstance(c, RecommendationCard) else RecommendationCard.from_dict(c) for c in raw]
    by_store = {c.store_id: c for c in items}
    results: dict[str, Any] = {}
    seconds: dict[str, float] = defaultdict(float)
    regen_seconds: dict[str, float] = defaultdict(float)

    def timed_run(card, regen: bool = False, avoid: dict | None = None):
        t0 = time.perf_counter()
        try:
            if regen:     # an 8E rerun stands on its own: no trim / next-card fallback
                return run_from_card(card, deps, staff_map.get(card.store_id), on_progress, fallback=False,
                                     avoid=avoid)
            return run_from_card(card, deps, staff_map.get(card.store_id), on_progress)
        finally:
            dt_ = time.perf_counter() - t0
            seconds[card.store_id] += dt_
            if regen:
                regen_seconds[card.store_id] += dt_

    def safe_run(card):
        try:
            return timed_run(card)
        except Exception as e:  # noqa: BLE001 - one store must not abort the batch
            log.warning("batch: store %s failed: %s: %s", card.store_id, type(e).__name__, e)
            return e

    # Stores run concurrently; the caller may pass max_workers to match the selected store count
    # (the compare view does), else BATCH_MAX_WORKERS (default 4) applies.
    cap = max_workers if max_workers is not None else batch_max_workers()
    workers = max(1, min(cap, len(items) or 1))
    if workers == 1:
        outs = [safe_run(card) for card in items]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(safe_run, items))
    for card, out in zip(items, outs):
        results[card.store_id] = out

    initial = {sid: _batch_text(r) for sid, r in results.items()}
    angles_cfg = load_json(INPUTS / "angles.json")
    breaches = variety_breaches([e for card in items if (e := _variety_entry(card, results[card.store_id]))])
    regenerated: list[str] = []
    variety: dict[str, dict] = {}

    def rerun(sid: str, breach: dict):
        """One 8E regeneration: the next unused hook (peer group), the avoid lists, and, if the post is still too
        similar, the next unused angle too. Returns (card, result) or None; never falls back to another card."""
        card = by_store[sid]
        peers = [by_store[s] for s in by_store if s != sid and by_store[s].segment == card.segment]
        used_hooks = {c.hook.id for c in peers if c.hook}
        used_angles = {c.angle for c in peers if c.angle}
        current_hook = card.hook.id if card.hook else None
        hooks = [h for h in angles_cfg["hooks"] if not h.get("requires_logged_question")]
        next_hook = next((h for h in hooks if h["id"] not in used_hooks and h["id"] != current_hook), None) \
            or next((h for h in hooks if h["id"] != current_hook), None)
        next_angle = None if keep_angle else next((x for x in angles_cfg["segment_angles"].get(card.segment, [])
                                                   if x not in used_angles and x != card.angle), None)
        avoid = {"facts": breach["avoid_facts"], "phrases": breach["avoid_phrases"]}
        new_card = copy.deepcopy(card)
        if next_hook is not None:
            new_card.hook = CardHook(next_hook["id"], next_hook["label"])
        elif next_angle is not None:
            new_card.angle, next_angle = next_angle, None
        best = None
        for attempt in range(2):
            try:
                out = timed_run(new_card, regen=True, avoid=avoid)
            except Exception as e:  # noqa: BLE001 - keep the original result if the rerun fails
                log.warning("8E rerun failed for %s: %s", sid, e)
                break
            if isinstance(out, RunResult) and out.report.passed:
                best = (new_card, out)
            if attempt or "similar" not in breach["reasons"] or next_angle is None or best is None:
                break
            ref = initial.get(breach["similar_to"] or "", "")
            if jaccard(_batch_text(best[1]), ref) <= similarity_threshold():
                break
            new_card = copy.deepcopy(new_card)          # still too similar: also the next unused angle
            new_card.angle = next_angle
        return best

    targets = [sid for sid in sorted(breaches) if sid in by_store]
    if targets:
        _say(on_progress, "8E", f"跨门店去重：{len(targets)} 家门店需要换一种写法")
    if workers == 1 or len(targets) <= 1:
        reruns = [rerun(sid, breaches[sid]) for sid in targets]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            reruns = list(ex.map(lambda sid: rerun(sid, breaches[sid]), targets))
    for sid, got in zip(targets, reruns):
        variety[sid] = {**breaches[sid], "replaced": got is not None}
        if got is None:                # a failing rerun never replaces a passing post
            continue
        by_store[sid], results[sid] = got
        regenerated.append(sid)

    pairs: list[SimilarityPair] = []
    sids = sorted(results)
    for i, a in enumerate(sids):
        for b in sids[i + 1:]:
            before_a, before_b = initial.get(a, ""), initial.get(b, "")
            if not before_a and not before_b:
                continue
            seg_a, seg_b = by_store[a].segment, by_store[b].segment
            pairs.append(SimilarityPair(seg_a if seg_a == seg_b else f"{seg_a}/{seg_b}", a, b,
                                        round(jaccard(before_a, before_b), 3),
                                        round(jaccard(_batch_text(results[a]), _batch_text(results[b])), 3),
                                        b in regenerated or a in regenerated))
    batch = BatchResult(results=results, similarity=pairs, regenerated=regenerated, variety=variety,
                        seconds={sid: round(v, 2) for sid, v in seconds.items()},
                        regen_seconds={sid: round(v, 2) for sid, v in regen_seconds.items()},
                        wall_seconds=round(time.perf_counter() - t_batch, 2))
    if deps is not None and not getattr(deps, "is_dev_mode", True):
        try:
            from agent.runs import log_batch
            log_batch(items, batch)
        except Exception as e:  # noqa: BLE001 - logging must never break a batch
            log.warning("batch log failed: %s", e)
    return batch


# ---------------------------------------------------------------- fallback policy (Phase 5, T4)
_SENT_PIECE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;\n]*")
_TAG = re.compile(r"\s*\[F\d+\]")
_NORM = re.compile(r"[\s，,。！？!?；;：:、“”\"「」（）()]+")
NEXT_CARD_ORDER = ("potential", "promo", "customer_question", "new_release")


def _norm_text(text: str) -> str:
    return _NORM.sub("", _TAG.sub("", text or ""))


def _text_fields(post: Post) -> list[tuple[str, str]]:
    return [("title", post.title), ("intro", post.intro), *[(f"body[{i}]", b) for i, b in enumerate(post.body)],
            ("cta", post.cta)]


def failing_sentences(post: Post, report: CheckReport) -> list[FailingSentence]:
    """Each error mapped to the post sentence that carries its span (publishable text, no tags). Errors with
    no locatable span (e.g. a missing store detail) are listed with an empty sentence."""
    out: list[FailingSentence] = []
    fields = _text_fields(post)
    for i in report.issues:
        if i.severity != "error":
            continue
        span = _norm_text(i.span)
        hit = None
        for name, text in fields:
            if i.field and i.field in dict(fields) and name != i.field:
                continue
            for piece in _SENT_PIECE.findall(text or ""):
                n = _norm_text(piece)
                if span and n and (span in n or (len(n) >= 4 and n in span)):
                    hit = (name, _TAG.sub("", piece).strip())
                    break
            if hit:
                break
        out.append(FailingSentence(field=hit[0] if hit else (i.field or ""), sentence=hit[1] if hit else "",
                                   stage=i.stage, code=i.code, reason=i.message))
    return out


def _trim(post: Post, failing: list[FailingSentence]) -> Optional[Post]:
    """The post without the failing sentences, or None if some error had no sentence to remove."""
    if not failing or any(not f.sentence for f in failing):
        return None
    drop: dict[str, set[str]] = defaultdict(set)
    for f in failing:
        drop[f.field].add(_norm_text(f.sentence))
    new = copy.deepcopy(post)

    def cut(name: str, text: str) -> str:
        keep = [piece for piece in _SENT_PIECE.findall(text or "") if _norm_text(piece) not in drop.get(name, ())]
        return "".join(keep).strip()

    new.title, new.intro, new.cta = cut("title", post.title), cut("intro", post.intro), cut("cta", post.cta)
    new.body = [b for b in (cut(f"body[{i}]", b) for i, b in enumerate(post.body)) if b]
    cited = set(re.findall(r"\[(F\d+)\]", new.all_text()))
    new.selling_points = [i for i in post.selling_points if i in cited]
    return new


def _deliverable(post: Post) -> bool:
    """Still a post: a title if the platform has one, at least one fact-backed point, and a CTA."""
    from agent.platform_rules import PLATFORM_RULES
    blocks = {b[0] for b in (PLATFORM_RULES.get(post.platform) or {}).get("blocks", [])}
    return (bool(post.title) or "title" not in blocks) and bool(post.selling_points) and bool(post.cta)


def _next_card(card: RecommendationCard) -> Optional[RecommendationCard]:
    """The store's next unlocked card after this one (潜力款 → 活动款 → 顾客问答 → 新品款 if verified), on the
    same platform: a 小红书 / 公众号 version must not fall back to the next card's default 朋友圈."""
    from agent.recommend.store_data import cards_for
    if not card.date:
        return None
    try:
        cards = cards_for(card.store_id, card.date)
    except Exception:  # noqa: BLE001
        return None
    rank = {slot: i for i, slot in enumerate(NEXT_CARD_ORDER)}
    later = [c for c in cards if not c.locked and c.slot != card.slot]
    nxt = min(later, key=lambda c: rank.get(c.slot, 99), default=None)
    return dataclasses.replace(nxt, platform=card.platform) if nxt is not None else None


def _errors_n(r) -> int:
    return sum(1 for i in r.report.issues if i.severity == "error") if isinstance(r, RunResult) else 10 ** 6


def _note(result: RunResult, on_progress: Progress, message: str) -> None:
    """Why the trim step did not deliver: streamed as progress and kept on the result for the UI."""
    _say(on_progress, "check", message)
    try:
        result._trim_note = message
    except AttributeError:   # a frozen / slotted result: the progress line is enough
        pass


def _try_trim(result: RunResult, deps: Deps, on_progress: Progress = None) -> tuple[RunResult | None, bool]:
    """Fallback step 1, shared by the card path and the 生成 path: delete the failing sentences and run every
    check again. Returns (a passing, still-deliverable RunResult with fallback="trimmed" or None, whether a
    trimmed post could be built at all). No LLM writer call; only the checks run again."""
    failing = failing_sentences(result.post, result.report)
    trimmed_post = _trim(result.post, failing)
    if trimmed_post is None:
        whole = sum(1 for f in failing if not f.sentence)
        _note(result, on_progress, f"自动删句未执行：{whole} 处问题针对整篇（如缺少到店引导、卖点数量、段落结构），"
                                   "删句无法解决" if whole else "自动删句未执行：没有可删的句子")
        return None, False
    if not _deliverable(trimmed_post):
        _note(result, on_progress, f"自动删句未采用：删去 {len(failing)} 句后缺少标题、卖点或到店引导，内容不完整")
        return None, True
    report = deps.run_checks(trimmed_post, result.ledger, getattr(result, "_sibling_ledgers", {}) or {},
                             result.task, result.plan, deps.llm)
    if not report.passed:
        left = sum(1 for i in report.issues if i.severity == "error")
        _note(result, on_progress, f"自动删句未通过：删去 {len(failing)} 句后重新核验，仍有 {left} 处未通过")
        return None, True
    from agent.checks.prices import mark_demo_prices
    out = copy.copy(result)
    out.post, out.report, out.fallback = mark_demo_prices(trimmed_post, result.task), report, "trimmed"
    out.pending = _collect_pending(result.strategy, result.plan, report, result.task)
    _say(on_progress, "check", f"删去 {len(failing)} 处未通过的句子后核验通过")
    return out, True


def trim_if_failed(result, deps: Deps, on_progress: Progress = None):
    """The 生成 path's safety net (run / edit): a RunResult that failed after its rewrites gets fallback step 1
    (delete the failing sentences, re-check). Anything else, or a trim that does not pass, is returned as is."""
    if not isinstance(result, RunResult) or result.report.passed:
        return result
    trimmed, _ = _try_trim(result, deps, on_progress)
    return trimmed if trimmed is not None else result


def apply_fallback(card: RecommendationCard, result: RunResult, deps: Deps, staff=None,
                   on_progress: Progress = None, on_post: PostHook = None):
    """T4 policy for a card run that failed after 2 rewrites. Returns a passing RunResult (fallback set)
    or NeedsReview. Every delivered post has passed all checks."""
    attempts = [card.card_id]
    best = result
    trimmed, tried = _try_trim(result, deps, on_progress)
    if tried:
        attempts.append("trimmed")
    if trimmed is not None:
        return trimmed
    nxt = _next_card(card)
    if nxt is not None:
        attempts.append(nxt.card_id)
        _say(on_progress, "card", f"改用下一条推荐：{nxt.slot_label}")
        try:
            other = run_from_card(nxt, deps, staff, on_progress, fallback=False, on_post=on_post)
        except Exception as e:  # noqa: BLE001 - the fallback must not crash the batch
            log.warning("next-card fallback failed for %s: %s", card.store_id, e)
            other = None
        if isinstance(other, RunResult) and other.report.passed:
            other.fallback = "next_card"
            return other
        if isinstance(other, RunResult) and _errors_n(other) < _errors_n(best):
            best = other
    _say(on_progress, "check", "仍未通过核验：需人工确认")
    return NeedsReview(card=card, draft=best, failing=failing_sentences(best.post, best.report), attempts=attempts)


# ---------------------------------------------------------------- prepared posts (the push model)
@dataclass
class PreparedDay:
    date: str
    batch: BatchResult                      # the 朋友圈 batch (every staff member posts there)
    paths: dict[str, Any]                   # store_id -> prepared record path (朋友圈 default card)
    locked: dict[str, str]                  # store_id -> why nothing was generated (locked / no card)
    errors: dict[str, str] = field(default_factory=dict)   # store_id -> crash; nothing stored, old post kept
    batches: dict[str, BatchResult] = field(default_factory=dict)       # platform label -> its batch
    versions: dict[str, dict] = field(default_factory=dict)             # platform label -> {store_id: path}
    wechat_skipped: list[str] = field(default_factory=list)            # weekly 公众号 already done


STAFF_PLATFORMS = ("朋友圈", "小红书")
WECHAT = "公众号"


def _store_versions(cards: list, batch: BatchResult, deps: Deps, runs_dir, errors: dict) -> dict[str, Any]:
    from agent.runs import log_version
    by_store = {c.store_id: c for c in cards}
    out = {}
    for sid, result in batch.results.items():
        if isinstance(result, Exception):     # never overwrite a stored post with a crash (e.g. LLM 402)
            errors[f"{sid}/{by_store[sid].platform}"] = f"{type(result).__name__}: {str(result)[:160]}"
            continue
        sims = [dict(p.__dict__) for p in batch.similarity if sid in (p.store_a, p.store_b)]
        out[sid] = log_version(by_store[sid], result, seconds=batch.seconds.get(sid), similarity=sims,
                               regenerated=sid in batch.regenerated, dev_mode=deps.is_dev_mode, runs_dir=runs_dir)
    return out


def prepare_today(date, deps: Deps | None = None, runs_dir=None, on_progress: Progress = None,
                  card_map: Optional[Callable[[RecommendationCard], RecommendationCard]] = None,
                  platforms: tuple = STAFF_PLATFORMS, wechat: str = "auto") -> PreparedDay:
    """Morning run: every store's default card for `date`, one version per platform, each platform through
    generate_batch (8E across that platform's posts). The 朋友圈 version is also the store's prepared post
    (agent.runs.log_prepared); every version is stored with log_version. Same card = same model, angle and
    fact card on every platform; only format and length follow the platform rules.

    wechat: "auto" adds a 公众号 version only for stores whose weekly 公众号 minimum is not met yet
    (agent.recommend.weekly); "all" for every store; "none" never. Locked cards (and stores without an
    unlocked card) are skipped and listed. card_map is for the --fake rehearsal only (maps each card onto the
    synthetic DemoBook)."""
    from agent.recommend.store_data import default_card, load_store_data
    from agent.recommend.weekly import behind, weekly_progress
    from agent.runs import log_prepared
    deps = deps or default_deps()
    data = load_store_data()
    cards, locked = [], {}
    for st in data.stores:
        card = default_card(st["store_id"], date, data)
        if card is None:
            locked[st["store_id"]] = "今日无可生成的卡片"
        elif card.locked:
            locked[st["store_id"]] = LOCKED_MESSAGES.get(card.locked_reason or "", "该推荐暂不可生成，请等待总部确认")
        else:
            cards.append(card_map(card) if card_map else card)
    plan: dict[str, list] = {p: [dataclasses.replace(c, platform=p) for c in cards] for p in platforms}
    skipped: list[str] = []
    if wechat != "none" and WECHAT not in plan:
        due = [c for c in cards if wechat == "all"
               or behind(weekly_progress(c.store_id, date, data)).get(WECHAT, 0) > 0]
        skipped = sorted({c.store_id for c in cards} - {c.store_id for c in due})
        if due:
            plan[WECHAT] = [dataclasses.replace(c, platform=WECHAT) for c in due]
    paths, errors, batches, versions = {}, {}, {}, {}
    for platform, pcards in plan.items():
        _say(on_progress, "card", f"{platform}：{len(pcards)} 家门店")
        batch = generate_batch(pcards, deps, on_progress=on_progress, keep_angle=True)
        batches[platform] = batch
        versions[platform] = _store_versions(pcards, batch, deps, runs_dir, errors)
        if platform == "朋友圈":
            by_store = {c.store_id: c for c in pcards}
            for sid, result in batch.results.items():
                if isinstance(result, Exception):
                    continue
                sims = [dict(p.__dict__) for p in batch.similarity if sid in (p.store_a, p.store_b)]
                paths[sid] = log_prepared(by_store[sid], result, seconds=batch.seconds.get(sid), similarity=sims,
                                          regenerated=sid in batch.regenerated, dev_mode=deps.is_dev_mode,
                                          runs_dir=runs_dir)
    for key in list(errors):                  # keep the old "store_id -> crash" shape for the 朋友圈 batch
        sid, _, platform = key.partition("/")
        if platform == "朋友圈":
            errors[sid] = errors.pop(key)
    main = batches.get("朋友圈") or next(iter(batches.values()), BatchResult(results={}, similarity=[]))
    return PreparedDay(date=str(date), batch=main, paths=paths, locked=locked, errors=errors, batches=batches,
                       versions=versions, wechat_skipped=skipped)


COMPARE_STORES = ("S01", "S04", "S08", "S02")


@dataclass
class DemoPrecompute:
    day: PreparedDay
    others: BatchResult                      # every other unlocked slot per store, 朋友圈
    compare_model: Optional[str]
    compare: Optional[BatchResult]
    baseline_card: Optional[str]
    seconds: dict[str, float] = field(default_factory=dict)      # step -> wall seconds
    llm_calls: dict[str, int] = field(default_factory=dict)      # step -> LLM calls


def prepare_demo(date, deps: Deps | None = None, runs_dir=None, on_progress: Progress = None,
                 card_map: Optional[Callable[[RecommendationCard], RecommendationCard]] = None) -> DemoPrecompute:
    """Everything the UI can show for `date`, stored like prepared posts so the demo reads instead of
    generating: prepare_today (朋友圈 + 小红书 + 公众号 where due), every other unlocked slot of every store
    (换一条), the 三店对比 set (S01/S04/S08/S02, first product in an active campaign, 朋友圈, with similarity)
    and the 对照组 pair for S01 (baseline + our prepared post). Live generation stays for 重新生成."""
    from agent.recommend.store_data import cards_for, load_store_data, product_card
    from agent.runs import _payload, log_stored, log_version
    deps = deps or default_deps()
    data = load_store_data()
    seconds: dict[str, float] = {}
    calls: dict[str, int] = {}

    def n_calls() -> int:
        return len(getattr(deps.llm, "calls", []) or [])

    def step(name):
        class _S:
            def __enter__(self):
                self.t, self.c = time.perf_counter(), n_calls()

            def __exit__(self, *exc):
                seconds[name] = round(time.perf_counter() - self.t, 1)
                calls[name] = n_calls() - self.c
        return _S()

    with step("prepare_today"):
        day = prepare_today(date, deps, runs_dir=runs_dir, on_progress=on_progress, card_map=card_map)
    with step("other_slots"):
        others = [c for st in data.stores for c in cards_for(st["store_id"], date, data)
                  if not c.is_default and not c.locked]
        others = [card_map(c) if card_map else c for c in others]
        # One batch per slot: 8E compares posts that would be shown side by side (and store ids stay unique).
        merged = BatchResult(results={}, similarity=[])
        for slot in dict.fromkeys(c.slot for c in others):
            group = [c for c in others if c.slot == slot]
            b = generate_batch(group, deps, on_progress=on_progress)
            for c in group:
                r = b.results.get(c.store_id)
                if r is not None and not isinstance(r, Exception):
                    log_version(c, r, seconds=b.seconds.get(c.store_id), dev_mode=deps.is_dev_mode,
                                runs_dir=runs_dir)
                merged.results[c.card_id] = r
    compare_model, compare = None, None
    with step("compare"):
        from agent.recommend.common import parse_date
        d = parse_date(date)
        model = next((m for p in data.promos if parse_date(p["start"]) <= d <= parse_date(p["end"])
                      for m in p.get("models") or []), None)
        ccards = [c for sid in COMPARE_STORES if (c := product_card(sid, model, date, data))] if model else []
        ccards = [dataclasses.replace(card_map(c) if card_map else c, platform="朋友圈", is_default=False)
                  for c in ccards]
        if ccards:
            compare_model = model
            compare = generate_batch(ccards, deps, on_progress=on_progress)
            log_stored(date, "compare", f"{model}__moments", {
                "model": model, "platform": "朋友圈", "stores": [c.store_id for c in ccards],
                "cards": [c.to_dict() for c in ccards],
                "results": {sid: (_payload(r) if not isinstance(r, Exception) else {"error": repr(r)})
                            for sid, r in compare.results.items()},
                "status": {sid: type(r).__name__ for sid, r in compare.results.items()},
                "similarity": [dict(p.__dict__) for p in compare.similarity],
                "regenerated": list(compare.regenerated), "wall_seconds": compare.wall_seconds,
                "dev_mode": deps.is_dev_mode}, runs_dir)
    baseline_card = None
    with step("baseline"):
        from agent.recommend.store_data import default_card
        card = default_card("S01", date, data)
        if card is not None and not card.locked:
            card = card_map(card) if card_map else card
            base = generate_baseline(card, deps)
            log_stored(date, "baseline", card.card_id, {"card_id": card.card_id, "model": card.model_id,
                                                        "baseline": base.to_dict(), "dev_mode": deps.is_dev_mode},
                       runs_dir)
            baseline_card = card.card_id
    return DemoPrecompute(day=day, others=merged, compare_model=compare_model, compare=compare,
                          baseline_card=baseline_card, seconds=seconds, llm_calls=calls)


# ---------------------------------------------------------------- edit
_PLATFORM_WORDS = {"小红书": "xiaohongshu", "朋友圈": "moments", "公众号": "wechat_article",
                   "海报": "poster", "抖音": "douyin"}
_SCENARIO_WORDS = {v: k for k, v in SCENARIO_LABELS.items()}


def classify_edit(instruction: str, llm=None) -> tuple[str, dict]:
    """Code-first classifier per the quick-edits table. Returns (stage, params)."""
    s = instruction.strip()
    for word, key in _PLATFORM_WORDS.items():
        if word in s and (re.search(r"换成|改成|换到|发到|改为|换平台|平台", s) or len(s) <= 6):
            return "platform", {"platform": key}
    if re.search(r"短一点|长一点|精简|压缩|再长|语气|口语|正式|亲切|活泼", s):
        return "writer", {"requirement": s}
    if re.search(r"换卖点|突出|主打|换个角度|换角度|另一个角度|强调", s):
        return "reconcile", {"requirement": s}
    for label, key in _SCENARIO_WORDS.items():
        if label in s:
            return "analyze", {"scenario": key, "requirement": s}
    if re.search(r"换人群|换场景|面向|人群|场景", s):
        return "analyze", {"requirement": s}
    if llm is not None and hasattr(llm, "chat_json"):
        try:
            r = llm.chat_json(
                "你是编辑指令分类器。把指令归为 writer（长度、语气）、reconcile（卖点、角度）、analyze（人群、场景）、"
                "platform（切换平台）之一，输出 JSON {\"stage\": ..., \"platform\": 可选平台 key}",
                s, stage="classify_edit", fast=True)
            stage = r.get("stage")
            if stage in ("writer", "reconcile", "analyze", "platform"):
                return stage, {"requirement": s, **({"platform": r["platform"]} if r.get("platform") else {})}
        except Exception as e:
            log.info("LLM edit classifier failed: %s", e)
    return "writer", {"requirement": s}


def edit(prev: RunResult, instruction: str, deps: Deps | None = None,
         on_progress: Progress = None, on_post: PostHook = None) -> RunResult | Clarification | NeedsHuman | EditBlocked:
    """Quick edit. Ledger and bundle are reused; never refetched. Every path ends in the check loop.
    A price / discount / subsidy / installment / stock ask with no matching active promotion record is
    blocked here, before any classifier or writer call (price traceability, plan §4.3)."""
    from agent.checks.prices import price_request_block
    blocked = price_request_block(instruction, prev.task)
    if blocked:
        _say(on_progress, "edit", blocked)
        return EditBlocked(instruction=instruction, message=blocked, prev=prev)
    from agent.timing import collect
    deps = deps or default_deps()
    timer = _Timer()
    with collect(timer.timings):
        result = _edit_stages(prev, instruction, deps, on_progress, timer, on_post)
        return trim_if_failed(result, deps, on_progress)     # same trim step as a fresh run


def _edit_stages(prev: RunResult, instruction: str, deps: Deps, on_progress: Progress, timer: _Timer,
                 on_post: PostHook = None):
    stage, params = classify_edit(instruction, deps.llm)
    task = copy.deepcopy(prev.task)
    model = prev.model
    ledger = prev.ledger
    sibling_ledgers = getattr(prev, "_sibling_ledgers", {}) or {}
    bundle = _bundle_from_result(prev)
    stage_label = {"platform": "平台规划", "writer": "撰写", "reconcile": "卖点匹配", "analyze": "场景分析"}[stage]
    _say(on_progress, "edit", f"编辑：{instruction}（从{stage_label}重跑）")
    if stage == "platform":
        task.platform = params["platform"]
        return _from_plan(task, model, bundle, ledger, sibling_ledgers, prev.strategy, deps, on_progress, timer,
                          on_post)
    task.extra_requirements = [*task.extra_requirements, params["requirement"]]
    if stage == "writer":
        return _from_write(task, model, bundle, ledger, sibling_ledgers, prev.strategy, prev.plan, deps,
                           on_progress, timer, on_post)
    if stage == "reconcile":
        return _from_reconcile(task, model, bundle, ledger, sibling_ledgers, prev.strategy.analysis, deps,
                               on_progress, timer, on_post)
    if params.get("scenario"):
        task.scenario = params["scenario"]
    return _from_analyze(task, model, bundle, ledger, sibling_ledgers, deps, on_progress, timer, on_post)


def _bundle_from_result(prev: RunResult) -> ModelBundle:
    """Rebuild the parts of the bundle later stages need (images + sources) without refetching."""
    cached = getattr(prev, "_bundle", None)
    if cached is not None:
        return cached
    images = [it.image for it in prev.plan.items]
    return ModelBundle(model=prev.model, facts_text="", claims_text="", images=images,
                       sources=list(prev.sources))


def attach_context(result: RunResult, bundle: ModelBundle, sibling_ledgers: dict) -> RunResult:
    """Keep the bundle and sibling ledgers on the result (not serialized) so edits reuse them."""
    result._bundle = bundle                      # type: ignore[attr-defined]
    result._sibling_ledgers = sibling_ledgers    # type: ignore[attr-defined]
    return result


def run_all_platforms(prev: RunResult, platforms=("wechat_article", "xiaohongshu", "moments"),
                      deps: Deps | None = None, on_progress: Progress = None) -> dict[str, Any]:
    """全平台: step 6 in parallel for each platform, then 7 → 8 → 9 each."""
    from concurrent.futures import ThreadPoolExecutor
    deps = deps or default_deps()
    with ThreadPoolExecutor(max_workers=len(platforms)) as ex:
        futs = {p: ex.submit(edit, prev, f"换成{PLATFORM_LABELS[p]}", deps, on_progress) for p in platforms}
        return {p: f.result() for p, f in futs.items()}


# ---------------------------------------------------------------- baseline (video before/after; never our result)
def generate_baseline(card: RecommendationCard, deps: Deps | None = None, llm=None):
    """Re-export of agent.baseline.generate_baseline so the UI imports every entry point from here."""
    from agent.baseline import generate_baseline as _gen
    return _gen(card, deps=deps, llm=llm)
