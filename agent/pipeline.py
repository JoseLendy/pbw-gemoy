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
import importlib
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agent.schemas import (
    CardHook, CheckReport, Clarification, EditBlocked, ImagePlan, Ledger, LockedResult, ModelBundle, NeedsHuman,
    PLATFORM_LABELS, Post, RecommendationCard, RunResult, SCENARIO_LABELS, StaffContext, Strategy, Task,
)

log = logging.getLogger("agent.pipeline")

MAX_LOOPS = 2
Progress = Optional[Callable[[str, str], None]]


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
               plan: ImagePlan, deps: Deps, on_progress: Progress = None) -> tuple[Post, CheckReport, int]:
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
               strategy: Strategy, deps: Deps, on_progress: Progress, timer: _Timer) -> RunResult:
    _say(on_progress, "plan", f"规划 {PLATFORM_LABELS.get(task.platform, task.platform)} 版式…")
    plan = deps.plan_images(bundle, task.platform, strategy)
    timer.lap("plan")
    _say(on_progress, "plan", f"匹配到 {len(plan.items)} 张图片" + ("（不足，已标记待确认）" if plan.shortage else ""))
    return _from_write(task, model, bundle, ledger, sibling_ledgers, strategy, plan, deps, on_progress, timer)


def _from_write(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
                strategy: Strategy, plan: ImagePlan, deps: Deps, on_progress: Progress,
                timer: _Timer) -> RunResult:
    _say(on_progress, "write", "撰写软文…")
    post = deps.write_post(task, strategy, ledger, plan, deps.llm)
    timer.lap("write")
    _say(on_progress, "check", f"核验 {len(post.selling_points)} 个事实点…")
    post, report, loops = check_loop(post, task, strategy, ledger, sibling_ledgers, plan, deps, on_progress)
    from agent.checks.prices import mark_demo_prices
    post = mark_demo_prices(post, task)      # a DEMO campaign price always shows [演示活动] (added in code)
    timer.lap("check")
    pending = _collect_pending(strategy, plan, report, task)
    result = RunResult(task=task, model=model, strategy=strategy, ledger=ledger, plan=plan, post=post,
                       report=report, pending=pending, sources=list(bundle.sources), timings=timer.total(),
                       loops=loops)
    return attach_context(result, bundle, sibling_ledgers)


def _from_reconcile(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
                    analysis, deps: Deps, on_progress: Progress, timer: _Timer):
    _say(on_progress, "reconcile", "对照知识库事实确定卖点…")
    strategy = deps.reconcile(task, analysis, ledger, model, deps.llm)
    timer.lap("reconcile")
    if isinstance(strategy, NeedsHuman):
        _say(on_progress, "reconcile", "资料冲突，已停止输出，需人工确认")
        return strategy
    _say(on_progress, "reconcile", f"卖点：{'、'.join(sp.fact_id for sp in strategy.selling_points)}")
    return _from_plan(task, model, bundle, ledger, sibling_ledgers, strategy, deps, on_progress, timer)


def _from_analyze(task: Task, model, bundle: ModelBundle, ledger: Ledger, sibling_ledgers: dict,
                  deps: Deps, on_progress: Progress, timer: _Timer):
    _say(on_progress, "analyze", f"分析{SCENARIO_LABELS.get(task.scenario, task.scenario or '')}场景…")
    analysis = deps.analyze(task, deps.llm)
    timer.lap("analyze")
    return _from_reconcile(task, model, bundle, ledger, sibling_ledgers, analysis, deps, on_progress, timer)


# ---------------------------------------------------------------- run
def run(text: str, form: dict | None = None, deps: Deps | None = None,
        on_progress: Progress = None) -> RunResult | Clarification | NeedsHuman:
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
        return _from_retrieval(parsed, deps, on_progress, timer)


# ---------------------------------------------------------------- run from a recommendation card
LOCKED_MESSAGES = {"fact_card_draft": "新品资料待总部确认，暂不可生成"}


def _from_retrieval(task: Task, deps: Deps, on_progress: Progress, timer: _Timer):
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
    return _from_analyze(task, model, bundle, ledger, sibling_ledgers, deps, on_progress, timer)


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
                  on_progress: Progress = None) -> RunResult | LockedResult | NeedsHuman:
    """Proactive entry (PROACTIVE_AGENT_PLAN §3): the card replaces the user sentence, so intake and model
    disambiguation are skipped (the card carries an exact model_id). A locked card returns LockedResult
    before any LLM or ima call. Otherwise continues from retrieval / scenario exactly like run()."""
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
        timer.lap("intake")
        result = _from_retrieval(task, deps, on_progress, timer)
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


def generate_batch(cards, deps: Deps | None = None, staff_map: dict | None = None,
                   on_progress: Progress = None) -> BatchResult:
    """Run several recommendation cards and enforce 8E cross-store variety.

    Same-peer stores whose publishable text exceeds SIMILARITY_THRESHOLD are regenerated once (the later
    store id): first with the next hook unused by peers today; if still above the threshold, also with
    the next unused angle. Model, platform and facts never change; customer-question cards keep the
    reserved customer hook. Returns final results plus before/after similarity pairs for the UI / eval report.

    The first pass runs stores concurrently (BATCH_MAX_WORKERS, default 4); results keep the input order and
    a store's exception becomes that store's result. 8E comparison and regeneration run after that pass,
    sequentially, exactly as before. Same-model stores share one retrieval + ledger (agent.fact_cache).
    """
    from agent.formatter import render_publishable   # noqa: F401  (used by _batch_text)
    from agent.recommend.common import INPUTS, load_json
    from agent.style.similarity import jaccard, similarity_threshold

    t_batch = time.perf_counter()
    deps = deps or default_deps()
    staff_map = staff_map or {}
    raw = list(cards.values()) if isinstance(cards, dict) else list(cards)
    items = [c if isinstance(c, RecommendationCard) else RecommendationCard.from_dict(c) for c in raw]
    by_store = {c.store_id: c for c in items}
    results: dict[str, Any] = {}
    seconds: dict[str, float] = defaultdict(float)
    regen_seconds: dict[str, float] = defaultdict(float)

    def timed_run(card, regen: bool = False):
        t0 = time.perf_counter()
        try:
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

    # Stores run concurrently (BATCH_MAX_WORKERS, default 4); results keep the input order.
    workers = max(1, min(batch_max_workers(), len(items) or 1))
    if workers == 1:
        outs = [safe_run(card) for card in items]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(safe_run, items))
    for card, out in zip(items, outs):
        results[card.store_id] = out

    groups: dict[str, list[str]] = defaultdict(list)
    for card in items:
        groups[card.segment].append(card.store_id)
    for group in groups.values():
        group.sort()
    initial = {sid: _batch_text(r) for sid, r in results.items()}
    threshold = similarity_threshold()
    angles_cfg = load_json(INPUTS / "angles.json")
    regenerated: list[str] = []

    def peer_text(sid: str) -> str:
        return _batch_text(results.get(sid))

    changed = True
    while changed:
        changed = False
        for seg, sids in groups.items():
            for i, a in enumerate(sids):
                for b in sids[i + 1:]:
                    ta, tb = peer_text(a), peer_text(b)
                    if not ta or not tb or jaccard(ta, tb) <= threshold:
                        continue
                    later = b                         # sids are sorted, so b is the later store
                    if later in regenerated:
                        continue
                    card = by_store[later]
                    if card.slot == "customer_question":   # customer hook is reserved for the logged question
                        continue
                    peer_cards = [by_store[s] for s in sids if s != later]
                    used_hooks = {c.hook.id for c in peer_cards if c.hook}
                    used_angles = {c.angle for c in peer_cards if c.angle}
                    current_hook = card.hook.id if card.hook else None
                    hooks = [h for h in angles_cfg["hooks"] if not h.get("requires_logged_question")]
                    next_hook = next((h for h in hooks
                                      if h["id"] not in used_hooks and h["id"] != current_hook), None)
                    seg_angles = angles_cfg["segment_angles"][seg]
                    next_angle = next((x for x in seg_angles
                                       if x not in used_angles and x != card.angle), None)
                    if next_hook is None and next_angle is None:
                        continue
                    def max_peer_sim(text: str) -> float:
                        vals = [jaccard(text, peer_text(s)) for s in sids if s != later and peer_text(s)]
                        return max(vals, default=0.0)

                    new_card = copy.deepcopy(card)
                    hook_changed = next_hook is not None
                    if hook_changed:
                        new_card.hook = CardHook(next_hook["id"], next_hook["label"])
                    if not hook_changed and next_angle is not None:
                        new_card.angle = next_angle
                    try:
                        new_result = timed_run(new_card, regen=True)
                    except Exception:  # noqa: BLE001 - keep the original result if the rerun fails
                        continue
                    if not isinstance(new_result, RunResult):
                        continue
                    by_store[later] = new_card
                    results[later] = new_result
                    # Phase 4 wording: hook first; only if still above the threshold, also change angle.
                    if hook_changed and next_angle is not None and max_peer_sim(_batch_text(new_result)) > threshold:
                        angle_card = copy.deepcopy(new_card)
                        angle_card.angle = next_angle
                        try:
                            angle_result = timed_run(angle_card, regen=True)
                        except Exception:  # noqa: BLE001
                            angle_result = None
                        if isinstance(angle_result, RunResult):
                            by_store[later] = angle_card
                            results[later] = angle_result
                    regenerated.append(later)
                    changed = True
                    break
                if changed:
                    break
            if changed:
                break

    pairs: list[SimilarityPair] = []
    for seg, sids in groups.items():
        for i, a in enumerate(sids):
            for b in sids[i + 1:]:
                before, after = initial.get(a, ""), initial.get(b, "")
                if not before and not after:
                    continue
                pairs.append(SimilarityPair(seg, a, b, round(jaccard(before, after), 3),
                                            round(jaccard(peer_text(a), peer_text(b)), 3), b in regenerated))
    batch = BatchResult(results=results, similarity=pairs, regenerated=regenerated,
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


# ---------------------------------------------------------------- prepared posts (the push model)
@dataclass
class PreparedDay:
    date: str
    batch: BatchResult
    paths: dict[str, Any]                   # store_id -> prepared record path
    locked: dict[str, str]                  # store_id -> why nothing was generated (locked / no card)


def prepare_today(date, deps: Deps | None = None, runs_dir=None, on_progress: Progress = None,
                  card_map: Optional[Callable[[RecommendationCard], RecommendationCard]] = None) -> PreparedDay:
    """Morning run: every store's default card for `date` through generate_batch (8E included). Each final
    result is stored as that store's prepared post (agent.runs.log_prepared); staff open the app to it and
    重新生成 runs live. Locked cards (and stores without an unlocked card) are skipped and listed.
    card_map is for the --fake rehearsal only (maps each card onto the synthetic DemoBook)."""
    from agent.recommend.store_data import default_card, load_store_data
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
    batch = generate_batch(cards, deps, on_progress=on_progress)
    by_store = {c.store_id: c for c in cards}
    paths = {}
    for sid, result in batch.results.items():
        # The morning card is stored; if 8E changed hook / angle, result.task records what actually ran.
        sims = [dict(p.__dict__) for p in batch.similarity if sid in (p.store_a, p.store_b)]
        paths[sid] = log_prepared(by_store[sid], result, seconds=batch.seconds.get(sid), similarity=sims,
                                  regenerated=sid in batch.regenerated, dev_mode=deps.is_dev_mode,
                                  runs_dir=runs_dir)
    return PreparedDay(date=str(date), batch=batch, paths=paths, locked=locked)


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
         on_progress: Progress = None) -> RunResult | Clarification | NeedsHuman | EditBlocked:
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
        return _edit_stages(prev, instruction, deps, on_progress, timer)


def _edit_stages(prev: RunResult, instruction: str, deps: Deps, on_progress: Progress, timer: _Timer):
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
        return _from_plan(task, model, bundle, ledger, sibling_ledgers, prev.strategy, deps, on_progress, timer)
    task.extra_requirements = [*task.extra_requirements, params["requirement"]]
    if stage == "writer":
        return _from_write(task, model, bundle, ledger, sibling_ledgers, prev.strategy, prev.plan, deps,
                           on_progress, timer)
    if stage == "reconcile":
        return _from_reconcile(task, model, bundle, ledger, sibling_ledgers, prev.strategy.analysis, deps,
                               on_progress, timer)
    if params.get("scenario"):
        task.scenario = params["scenario"]
    return _from_analyze(task, model, bundle, ledger, sibling_ledgers, deps, on_progress, timer)


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
