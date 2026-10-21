#!/usr/bin/env python3
"""
Backend dry-run of every video scene, once, with real deps. Prints PASS/FAIL per scene with seconds.

    RUN_E2E=1 python scripts/demo_scenes.py --today 2026-10-23
    python scripts/demo_scenes.py --today 2026-10-23 --fake      # offline plumbing check (synthetic DemoBook)

--fake only checks the plumbing: the fake writer ignores the card brief (scene 3 similarity), the fake checker
has no 8A number check (scene 4) and the fake LLM returns no baseline text (scene 6), so those FAIL there.

Scenes (plan §9, §12):
  1 prepare_today for all stores (prepared posts)
  2 S01 default card, live 重新生成
  3 三店对比: S01 / S04 / S08 / S02 on one fixed product (COMPARE_MODEL)
  4 planted wrong spec value on the S01 post -> 8A must block it or the rewrite must remove it
  5 edit "加上立减500" -> EditBlocked (no writer call)
  6 baseline (对照组) vs ours for S01, 8D hits listed
  7 confusable model: a MODEL_F spec written under MODEL_A -> 8A fails
  8 MODEL_N: locked -> verified -> S01 default; reset_demo_state -> locked again

Real runs log themselves to runs/ (gitignored); the scene summary goes to runs/<date>/<ts>-demo_scenes.json.
Never prints keys, the Client ID or KB IDs.
"""
from __future__ import annotations

import argparse
import copy
import csv
import dataclasses
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.schemas import BaselineResult, EditBlocked, LockedResult, RunResult  # noqa: E402

COMPARE_STORES = ("S01", "S04", "S08", "S02")
# MODEL_F: the national best-seller, in the active campaign for all four stores, affinity >= 0.6 in every
# segment and in stock everywhere (MODEL_A is out of stock at S02).
COMPARE_MODEL = "matebook-14-2024"
MODEL_A, MODEL_F = "matebook-14-harmonyos", "matebook-14-2024"
PLANTED = "0.86 kg"
DEMO = "demobook-14"


@dataclasses.dataclass
class Scene:
    n: int
    name: str
    ok: bool = False
    seconds: float = 0.0
    detail: str = ""


def _demo(card):
    return dataclasses.replace(card, model_id=DEMO, display_name="DemoBook 14（演示版）")


def _errors(report, stage=None):
    return [i for i in report.issues if i.severity == "error" and (stage is None or i.stage == stage)]


def _new_release_model() -> str:
    from agent.recommend.common import INPUTS
    rows = list(csv.DictReader((INPUTS / "models.csv").open(encoding="utf-8")))
    return next(r["model_id"] for r in rows if r["is_new_release"] == "true")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--today", default="2026-10-23")
    ap.add_argument("--fake", action="store_true", help="offline rehearsal on tests/fakes (synthetic facts)")
    args = ap.parse_args(argv)
    if not args.fake and os.environ.get("RUN_E2E") != "1":
        print("demo_scenes.py uses real deps (ima + LLM). Set RUN_E2E=1 to run it, or pass --fake.")
        return 2

    from agent.checks.facts import check_facts
    from agent.formatter import render_publishable
    from agent.pipeline import Deps, check_loop, edit, generate_baseline, generate_batch, prepare_today, run_from_card
    from agent.recommend.store_data import cards_for, default_card, product_card, reset_demo_state, set_fact_card_status
    from agent.runs import REHEARSAL_DIR, RUNS_DIR
    from agent.style.similarity import similarity_threshold

    try:
        deps = Deps.fake() if args.fake else Deps.real()
    except Exception as e:  # noqa: BLE001 - e.g. the KB mirror is missing: say why, no traceback
        print(f"真实依赖不可用：{getattr(e, 'msg', None) or e}")
        return 2
    card_map = _demo if args.fake else (lambda c: c)
    runs_dir = REHEARSAL_DIR if args.fake else None
    today = args.today
    reset_demo_state()
    scenes: list[Scene] = []
    ctx: dict = {}

    def scene(n, name):
        def deco(fn):
            s = Scene(n, name)
            t0 = time.perf_counter()
            try:
                s.ok, s.detail = fn()
            except Exception as e:  # noqa: BLE001 - one scene's failure must not stop the dry-run
                s.ok, s.detail = False, f"{type(e).__name__}: {str(e)[:200]}"
            s.seconds = round(time.perf_counter() - t0, 1)
            scenes.append(s)
            print(f"[{'PASS' if s.ok else 'FAIL'}] {n}. {name} ({s.seconds}s) — {s.detail}", flush=True)
            return fn
        return deco

    @scene(1, "prepare_today（全部门店）")
    def _():
        day = prepare_today(today, deps, runs_dir=runs_dir, card_map=card_map if args.fake else None)
        res = day.batch.results
        runs = {sid: r for sid, r in res.items() if isinstance(r, RunResult)}
        passed = sum(r.report.passed for r in runs.values())
        secs = sorted(day.batch.seconds.values())
        ok = len(day.paths) == len(res) and len(runs) == len(res)
        bad = {sid: type(r).__name__ for sid, r in res.items() if not isinstance(r, RunResult)}
        return ok, (f"整批 {day.batch.wall_seconds}s；{len(day.paths)} 条已存储；{passed}/{len(res)} 通过核验；锁定 {sorted(day.locked) or '无'}；"
                    f"8E 重生成 {day.batch.regenerated or '无'}；最慢 {secs[-1] if secs else 0:.1f}s"
                    + (f"；未生成 {bad}" if bad else ""))

    @scene(2, "S01 今日一条 · 重新生成（实时）")
    def _():
        card = card_map(default_card("S01", today))
        t0 = time.perf_counter()
        r = run_from_card(card, deps)
        secs = time.perf_counter() - t0
        ctx["s01"], ctx["s01_card"] = r, card
        if not isinstance(r, RunResult):
            return False, f"返回 {type(r).__name__}"
        return r.report.passed, (f"{card.slot} {card.model_id} → {card.platform}；{secs:.1f}s；改写 {r.loops} 轮；"
                                 f"未通过 {[(i.stage, i.code) for i in _errors(r.report)] or '无'}")

    @scene(3, f"三店对比（{'/'.join(COMPARE_STORES)} · {COMPARE_MODEL}）")
    def _():
        cards = [product_card(sid, COMPARE_MODEL, today) for sid in COMPARE_STORES]
        missing = [sid for sid, c in zip(COMPARE_STORES, cards) if c is None]
        if missing:
            return False, f"{missing} 没有包含该型号的有效活动"
        batch = generate_batch([card_map(c) for c in cards], deps)
        ok_runs = {sid: r for sid, r in batch.results.items() if isinstance(r, RunResult)}
        passed = [sid for sid, r in ok_runs.items() if r.report.passed]
        th = similarity_threshold()
        over = [f"{p.store_a}×{p.store_b} {p.after}" for p in batch.similarity if p.after > th]
        sims = "；".join(f"{p.store_a}×{p.store_b} {p.before}→{p.after}" for p in batch.similarity) or "—"
        ctx["compare"] = batch
        return (len(passed) == len(COMPARE_STORES) and not over,
                f"通过 {passed}；相似度 {sims}；超阈值 {over or '无'}；整批 {batch.wall_seconds}s；各店秒数 {batch.seconds}")

    def need_s01():
        r = ctx.get("s01")
        if not isinstance(r, RunResult):
            raise RuntimeError("依赖场景 2 的 RunResult")
        return r

    @scene(4, f"人为改错数字（{PLANTED}）→ 8A 拦截/改写")
    def _():
        r = need_s01()
        post = copy.deepcopy(r.post)
        weight = next((f.id for f in r.ledger.facts if f.attribute == "weight"), None)
        post.body = list(post.body)
        post.body[0] = post.body[0] + f"整机重量约 {PLANTED}" + (f" [{weight}]" if weight else "") + "。"
        sib = getattr(r, "_sibling_ledgers", {}) or {}
        first = deps.run_checks(post, r.ledger, sib, r.task, r.plan, deps.llm)
        hits = [i for i in _errors(first, "8A") if PLANTED.replace(" ", "") in (i.span or "").replace(" ", "")]
        final_post, final, loops = check_loop(post, r.task, r.strategy, r.ledger, sib, r.plan, deps)
        gone = PLANTED.replace(" ", "") not in render_publishable(final_post).replace(" ", "")
        still = [i for i in _errors(final, "8A") if PLANTED.replace(" ", "") in (i.span or "").replace(" ", "")]
        how = "改写后已删除" if gone else ("仍标红拦截（待确认）" if still else "仍在文中且未拦截")
        return bool(hits) and (gone or bool(still)), \
            f"8A 命中 {[(i.code, i.span) for i in hits] or '无'}；{how}；改写 {loops} 轮"

    @scene(5, "编辑「加上立减500」→ EditBlocked")
    def _():
        r = need_s01()
        before = len(getattr(deps.llm, "calls", []) or [])
        out = edit(r, "加上立减500", deps)
        after = len(getattr(deps.llm, "calls", []) or [])
        if isinstance(out, EditBlocked) and not args.fake:      # keep a real record (samples/, freeze check)
            from agent.runs import log_run
            log_run(ctx["s01_card"], out, kind="edit_blocked")
        return isinstance(out, EditBlocked) and after == before, \
            f"{type(out).__name__}：{getattr(out, 'message', '')[:80]}；写作调用 {after - before} 次"

    @scene(6, "对照组 vs 我们（S01）")
    def _():
        card = ctx.get("s01_card") or card_map(default_card("S01", today))
        b = generate_baseline(card, deps)
        if not isinstance(b, BaselineResult):
            return False, f"返回 {type(b).__name__}"
        ours = ctx.get("s01")
        ours_8d = [(i.code, i.span) for i in ours.report.issues if i.stage == "8D"] if isinstance(ours, RunResult) else "—"
        labelled = b.display_text.startswith("【对照组")
        return labelled and bool(b.text), (f"对照组标注 {'✓' if labelled else '✗'}；8D 命中 {len(b.hits)} 处："
                                           f"{[(i.code, i.span) for i in b.hits][:8]}；我们的终稿 8D：{ours_8d or '无'}")

    @scene(7, f"易混型号：在 {MODEL_A} 里写 {MODEL_F} 的参数 → 8A")
    def _():
        r = need_s01()
        sib = getattr(r, "_sibling_ledgers", {}) or {}
        target = DEMO + "-se" if args.fake else MODEL_F
        other = sib.get(target)
        if other is None:
            return False, f"S01 结果没有 {target} 的相近型号台账（siblings: {list(sib)}）"
        same_attr = {f.attribute: f.id for f in r.ledger.facts}
        for f in other.facts:
            if f.attribute not in same_attr or f.norm_value is None:
                continue
            post = copy.deepcopy(r.post)
            post.body = [f"{r.model.canonical_name} 这一项参数是 {f.value} [{same_attr[f.attribute]}]。"]
            post.title = post.intro = post.cta = ""
            rep = check_facts(post, r.ledger, sib, variant=r.task.variant, llm=None)
            errs = _errors(rep, "8A")
            if errs:
                return True, f"{target} 的 {f.attribute}「{f.value}」→ 8A {[(i.code, i.span) for i in errs][:3]}"
        return False, f"{target} 的参数写进 {r.model.model_id} 后 8A 没有报错"

    @scene(8, "新品：锁定 → 总部确认 → S01 默认 → 重置后再次锁定")
    def _():
        mid = _new_release_model()
        c0 = next((c for c in cards_for("S01", today) if c.slot == "new_release"), None)
        if c0 is None:
            return False, f"{today} 不在 {mid} 的新品窗口内"
        locked0 = c0.locked
        gate = run_from_card(card_map(c0), deps)              # LockedResult before any ima / LLM call (logged)
        locked0 = locked0 and isinstance(gate, LockedResult)
        set_fact_card_status(mid, "verified")
        d = default_card("S01", today)
        is_default = d is not None and d.slot == "new_release" and d.model_id == mid
        reason = next((x.text for x in d.reasons if x.source == "release"), "") if d else ""
        reset_demo_state()
        c1 = next(c for c in cards_for("S01", today) if c.slot == "new_release")
        ok = locked0 and is_default and c1.locked
        return ok, f"{mid}：初始锁定 {locked0}；确认后默认 {is_default}（理由「{reason}」）；重置后锁定 {c1.locked}"

    # ------------------------------------------------------------ summary
    calls_llm = len(getattr(deps.llm, "calls", []) or [])
    calls_ima = getattr(getattr(deps.catalog, "client", None), "live_calls", "n/a")
    print("\n| # | 场景 | 结果 | 秒 |\n|---|---|---|---|")
    for s in scenes:
        print(f"| {s.n} | {s.name} | {'PASS' if s.ok else 'FAIL'} | {s.seconds} |")
    print(f"\ncalls: LLM {calls_llm} · ima {calls_ima}")
    out_dir = (REHEARSAL_DIR if args.fake else RUNS_DIR) / today
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}-demo_scenes.json"
    path.write_text(json.dumps({"kind": "demo_scenes", "date": today, "fake": args.fake,
                                "scenes": [dataclasses.asdict(s) for s in scenes],
                                "calls": {"llm": calls_llm, "ima": calls_ima}}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"saved {path.relative_to(Path(__file__).resolve().parents[1])}")
    return 0 if all(s.ok for s in scenes) else 1


if __name__ == "__main__":
    sys.exit(main())
