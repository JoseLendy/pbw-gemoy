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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agent.schemas import (
    CheckReport, Clarification, ImagePlan, Ledger, ModelBundle, NeedsHuman, PLATFORM_LABELS,
    Post, RunResult, SCENARIO_LABELS, Strategy, Task,
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
        client = wrapper.ImaClient()
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
            client = wrapper.ImaClient()
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


def _collect_pending(strategy: Strategy, plan: ImagePlan, report: CheckReport) -> list[str]:
    pending: list[str] = []
    pending.extend(strategy.pending or [])
    if plan.shortage and plan.note:
        pending.append(plan.note)
    for i in report.issues:
        if i.severity == "error":
            pending.append(f"未通过核验：{i.message}" + (f"（{i.span}）" if i.span else ""))
        elif i.code == "pending_request" or "待确认" in i.message:
            pending.append(i.message)
    seen, out = set(), []
    for p in pending:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _sibling_ledgers(deps: Deps, model, on_progress: Progress) -> dict[str, Ledger]:
    out: dict[str, Ledger] = {}
    for sid in model.siblings or []:
        try:
            sb = deps.get_bundle(sid, deps.catalog)
            out[sid] = deps.build_ledger(sb, deps.llm)
        except Exception as e:  # a missing sibling must not stop the run
            log.warning("sibling ledger %s failed: %s", sid, e)
            _say(on_progress, "ledger", f"相近型号 {sid} 资料读取失败，8A 将只检查目标型号")
    return out


# ---------------------------------------------------------------- the check loop (step 8)
def check_loop(post: Post, task: Task, strategy: Strategy, ledger: Ledger, sibling_ledgers: dict,
               plan: ImagePlan, deps: Deps, on_progress: Progress = None) -> tuple[Post, CheckReport, int]:
    """run_checks → if errors and loops < MAX_LOOPS: rewrite → run_checks again."""
    loops = 0
    report = deps.run_checks(post, ledger, sibling_ledgers, task, plan, deps.llm)
    n_facts = len(post.selling_points)
    while not report.passed and loops < MAX_LOOPS:
        errors = [i for i in report.issues if i.severity == "error"]
        _say(on_progress, "check", f"发现 {len(errors)} 处问题，定向改写（第 {loops + 1} 轮）…")
        post = deps.rewrite(post, errors, task, strategy, ledger, plan, deps.llm)
        loops += 1
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
    timer.lap("check")
    pending = _collect_pending(strategy, plan, report)
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
    deps = deps or default_deps()
    timer = _Timer()
    _say(on_progress, "intake", "理解需求、匹配型号…")
    parsed = deps.parse_task(text, deps.catalog, form, deps.llm)
    timer.lap("intake")
    if isinstance(parsed, Clarification):
        _say(on_progress, "intake", "还缺少信息，请补充")
        return parsed
    task: Task = parsed
    model = deps.catalog.get(task.model_id)
    _say(on_progress, "retrieval", f"读取产品资料：{model.canonical_name}…")
    bundle = deps.get_bundle(task.model_id, deps.catalog)
    timer.lap("retrieval")
    if bundle.index_status != "complete":
        _say(on_progress, "retrieval", "知识库索引可能不完整（" + bundle.index_status + "）")
    _say(on_progress, "ledger", "建立事实台账…")
    ledger = deps.build_ledger(bundle, deps.llm)
    _say(on_progress, "ledger", f"台账 {len(ledger.facts)} 条事实" +
         (f"，{len(ledger.conflicts)} 处冲突" if ledger.conflicts else ""))
    sibling_ledgers = _sibling_ledgers(deps, model, on_progress)
    timer.lap("ledger")
    return _from_analyze(task, model, bundle, ledger, sibling_ledgers, deps, on_progress, timer)


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
         on_progress: Progress = None) -> RunResult | Clarification | NeedsHuman:
    """Quick edit. Ledger and bundle are reused; never refetched. Every path ends in the check loop."""
    deps = deps or default_deps()
    timer = _Timer()
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
