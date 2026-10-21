#!/usr/bin/env python3
"""
Eval: run every store's default card through the real pipeline and write eval/report.md.

    RUN_E2E=1 python scripts/eval_cards.py --today 2026-10-23     # real deps (ima + LLM)
    python scripts/eval_cards.py --fake                            # offline rehearsal on tests/fakes

Per store: pass/fail per checker (8A / 8B / 8C / 8D), number of rewrites, 8D hits seen during the loop,
fact tags used. Then a character-3-gram Jaccard similarity matrix between stores in the same peer group
(same dominant segment). Report only: regenerate-on-similarity (8E) is Phase 4.

Never prints keys, the Client ID or KB text beyond what the 4-section output already shows. eval/ is
gitignored because a real run's report contains KB-derived copy.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.formatter import render_publishable  # noqa: E402
from agent.recommend.store_data import default_card, load_store_data  # noqa: E402
from agent.schemas import LockedResult, NeedsHuman, NeedsReview, RunResult  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "report.md"
STAGES = ("8A", "8B", "8C", "8D")
SIMILARITY_FLAG = 0.55          # plan §6.4 starting threshold (report only)


# ---------------------------------------------------------------- similarity
def char_ngrams(text: str, n: int = 3) -> set[str]:
    s = "".join((text or "").split())
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else ({s} if s else set())


def jaccard(a: str, b: str, n: int = 3) -> float:
    x, y = char_ngrams(a, n), char_ngrams(b, n)
    if not x and not y:
        return 0.0
    return len(x & y) / len(x | y)


# ---------------------------------------------------------------- one store
@dataclasses.dataclass
class StoreEval:
    store_id: str
    store_name: str
    segment: str
    card_id: str = ""
    slot: str = ""
    model_id: str = ""
    status: str = "ok"                    # ok | locked | needs_human | no_card | error
    message: str = ""
    stage_pass: dict = dataclasses.field(default_factory=dict)   # stage -> bool (final report)
    rewrites: int = 0
    hits_8d: list = dataclasses.field(default_factory=list)       # codes+spans seen in ANY pass
    tags: list = dataclasses.field(default_factory=list)
    text: str = ""                        # publishable text (our article), for similarity only
    seconds: float = 0.0                  # wall-clock for this store's post, incl. 8E reruns
    errors: list = dataclasses.field(default_factory=list)       # (stage, code, span) left in the final report
    sim_flags: list = dataclasses.field(default_factory=list)    # "S01×S02 0.61→0.42" pairs over the threshold
    regenerated: bool = False
    fallback: str = ""                    # "" | trimmed | next_card | needs_review (T4 policy)
    timings: dict = dataclasses.field(default_factory=dict)      # RunResult.timings (+ "8E" regen seconds)

    @property
    def passed(self) -> bool:
        """Passed within the 2 rewrites, with no fallback (the writer's own quality)."""
        return self.status == "ok" and all(self.stage_pass.values()) and not self.fallback


def _recording(run_checks, sink: list):
    def wrapped(*a, **k):
        report = run_checks(*a, **k)
        sink.append(report)
        return report
    return wrapped


def eval_store(store: dict, today, deps, data, fake: bool = False) -> StoreEval:
    from agent.pipeline import run_from_card
    sid = store["store_id"]
    ev = StoreEval(store_id=sid, store_name=store["store_name"], segment=data.signals[sid]["dominant"])
    card = default_card(sid, today, data)
    if card is None:
        ev.status, ev.message = "no_card", "今日无可生成的卡片"
        return ev
    ev.card_id, ev.slot, ev.model_id = card.card_id, card.slot, card.model_id or ""
    if fake:   # tests/fakes only know the synthetic DemoBook; facts stay synthetic
        card = dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")
    reports: list = []
    base = deps.run_checks
    deps.run_checks = _recording(base, reports)
    try:
        r = run_from_card(card, deps)
    except Exception as e:  # noqa: BLE001 - one store's failure must not stop the eval
        ev.status, ev.message = "error", f"{type(e).__name__}: {str(e)[:160]}"
        return ev
    finally:
        deps.run_checks = base
    if isinstance(r, LockedResult):
        ev.status, ev.message = "locked", r.message
        return ev
    if isinstance(r, NeedsHuman):
        ev.status, ev.message = "needs_human", r.message
        return ev
    assert isinstance(r, RunResult)
    final = r.report
    ev.stage_pass = {s: not any(i.stage == s and i.severity == "error" for i in final.issues) for s in STAGES}
    ev.rewrites = r.loops
    seen = []
    for rep in reports:
        for i in rep.issues:
            if i.stage == "8D" and (i.code, i.span) not in seen:
                seen.append((i.code, i.span))
    ev.hits_8d = seen
    ev.tags = list(dict.fromkeys(r.post.selling_points))
    ev.text = render_publishable(r.post)
    return ev


# ---------------------------------------------------------------- report
def similarity_groups(evals: list[StoreEval]) -> dict[str, list[tuple[str, str, float]]]:
    groups: dict[str, list[StoreEval]] = {}
    for e in evals:
        if e.status == "ok" and e.text:
            groups.setdefault(e.segment, []).append(e)
    out = {}
    for seg, members in groups.items():
        pairs = []
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                pairs.append((a.store_id, b.store_id, round(jaccard(a.text, b.text), 3)))
        out[seg] = pairs
    return out


def summary(evals: list[StoreEval]) -> dict:
    """Pass rate within the rewrite budget (MAX_LOOPS = 2) and seconds per generated post."""
    ok = [e for e in evals if e.status == "ok"]
    secs = sorted(e.seconds for e in ok)
    failures: dict[str, list[str]] = {}
    for e in ok:
        for stage, code, span in e.errors:
            failures.setdefault(stage, []).append(f"{e.store_id} {code}" + (f"「{span}」" if span else ""))
    fb = {k: sum(e.fallback == k for e in evals) for k in ("trimmed", "next_card", "needs_review")}
    return {"stores": len(evals), "generated": len(ok), "passed": sum(e.passed for e in evals), "fallback": fb,
            "median_s": statistics.median(secs) if secs else 0.0, "max_s": max(secs) if secs else 0.0,
            "rewrites": sum(e.rewrites for e in ok), "failures": failures}


# Stage columns of the timing table (RunResult.timings keys; nested check.* keys are parts of "check").
TIMING_COLS = ("retrieval", "ledger", "analyze", "reconcile", "write", "check", "check.pass1", "check.rewrite1",
               "check.pass2", "check.rewrite2", "check.pass3", "check.8A", "check.8B", "check.8C", "check.8D",
               "llm.8D", "8E", "total")


def stage_medians(evals: list[StoreEval]) -> dict[str, float]:
    keys = sorted({k for e in evals if e.status == "ok" for k in e.timings})
    out = {}
    for k in keys:
        vals = [e.timings[k] for e in evals if e.status == "ok" and k in e.timings]
        out[k] = round(statistics.median(vals), 1)
    return out


def llm_stage_table(calls: list[dict]) -> list[str]:
    by: dict[tuple, list[float]] = {}
    for c in calls or []:
        by.setdefault((c.get("stage") or "?", c.get("model") or "?"), []).append(c.get("seconds") or 0.0)
    lines = ["| LLM 阶段 | 模型 | 次数 | 合计秒 | 中位秒 | 最大秒 |", "|---|---|---|---|---|---|"]
    for (stage, model), v in sorted(by.items(), key=lambda kv: -sum(kv[1])):
        lines.append(f"| {stage} | {model} | {len(v)} | {sum(v):.1f} | {statistics.median(v):.1f} | {max(v):.1f} |")
    return lines


def build_report(evals: list[StoreEval], today, mode: str, pairs=None, wall: float | None = None,
                 llm_calls: list | None = None) -> str:
    mark = {True: "✅", False: "❌"}
    from agent.llm import temperatures
    lines = [f"# 卡片评测报告 · {today} · {mode}", "",
             "每家店的今日一条走完整流程（台账 → 写作 → 8A/8B/8C/8D 核验循环，最多 2 轮改写）。数值仅供内部调参。",
             f"温度：{temperatures()}", "",
             "| 门店 | 客群 | 卡片 | 型号 | 状态 | 8A | 8B | 8C | 8D | 改写轮数 | 秒 | 8E | 8D 命中（最终） | 事实编号 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in evals:
        sp = [mark[e.stage_pass[s]] if e.status == "ok" else "—" for s in STAGES]
        hits = "、".join(f"{c}「{s}」" if s else c for c, s in e.hits_8d) or "—"
        status = e.status if e.status == "ok" else f"{e.status}：{e.message}"
        sim = "; ".join(e.sim_flags) + (" (已重生成)" if e.regenerated else "") if e.sim_flags else "—"
        lines.append(f"| {e.store_id} {e.store_name} | {e.segment} | {e.slot or '—'} | {e.model_id or '—'} | "
                     f"{status} | {' | '.join(sp)} | {e.rewrites if e.status == 'ok' else '—'} | "
                     f"{e.seconds:.1f} | {sim} | {hits} | {', '.join(e.tags) or '—'} |")
    sm = summary(evals)
    if wall is not None:
        lines += ["", f"- 12 店整批耗时（含 8E 重生成）：**{wall:.1f} 秒**"]
    lines += ["", f"- 生成成功：{sm['generated']} / {sm['stores']} 家；≤2 轮改写内四项核验全部通过："
                  f"**{sm['passed']} / {sm['stores']}**（目标 ≥10）",
              f"- 兜底（T4）：删句后通过 {sm['fallback']['trimmed']} · 换下一条卡片 {sm['fallback']['next_card']} · "
              f"需人工确认 {sm['fallback']['needs_review']}",
              f"- 每条耗时：中位数 {sm['median_s']:.1f} 秒，最大 {sm['max_s']:.1f} 秒",
              f"- 平均改写轮数：{(sm['rewrites'] / sm['generated']) if sm['generated'] else 0:.2f}", ""]
    ok = [e for e in evals if e.status == "ok"]
    if ok:
        lines += ["## 分阶段耗时（秒，墙钟）", "",
                  "check.* 是 check 的组成部分；8A/8B/8D 在每轮核验内并行，所以它们之和可大于 check.passN。", "",
                  "| 门店 | " + " | ".join(TIMING_COLS) + " |", "|---" * (len(TIMING_COLS) + 1) + "|"]
        for e in ok:
            lines.append(f"| {e.store_id} | " + " | ".join(
                f"{e.timings[c]:.1f}" if c in e.timings else "—" for c in TIMING_COLS) + " |")
        med = stage_medians(evals)
        lines.append("| **中位数** | " + " | ".join(f"{med[c]:.1f}" if c in med else "—" for c in TIMING_COLS) + " |")
        lines.append("")
    if llm_calls:
        lines += ["## LLM 调用耗时（按阶段与模型）", ""] + llm_stage_table(llm_calls) + [""]
    if sm["failures"]:
        lines += ["## 未通过项（按核验器分组）", ""]
        for stage in STAGES:
            for item in sm["failures"].get(stage, []):
                lines.append(f"- {stage} · {item}")
        lines.append("")
    if pairs:
        lines += ["## 8E 跨店去重（before → after）", "",
                  "| 门店 A | 门店 B | before | after | 处理 |", "|---|---|---|---|---|"]
        for p in pairs:
            before, after = getattr(p, "before", None), getattr(p, "after", None)
            if before is None and isinstance(p, dict):
                before, after = p.get("before"), p.get("after")
            seg = getattr(p, "segment", "") or (p.get("segment") if isinstance(p, dict) else "")
            a = getattr(p, "store_a", "") or (p.get("store_a") if isinstance(p, dict) else "")
            b = getattr(p, "store_b", "") or (p.get("store_b") if isinstance(p, dict) else "")
            regen = getattr(p, "regenerated", False) or (p.get("regenerated") if isinstance(p, dict) else False)
            lines.append(f"| {a} | {b} | {before} | {after} | {'已换 hook/angle' if regen else '保持'} |")
        lines.append("")
    lines += ["## 同客群门店相似度（字符 3-gram Jaccard）", "",
              f"超过 {SIMILARITY_FLAG} 标 ⚠️；8E 已对超阈值门店换 hook/angle 后重算。", ""]
    groups = similarity_groups(evals)
    if not groups:
        lines.append("（没有可比较的文案）")
    for seg, seg_pairs in sorted(groups.items()):
        lines += [f"**{seg}**", ""]
        if not seg_pairs:
            lines += ["- 该客群只有一家成功生成，无需比较", ""]
            continue
        lines += ["| 门店 A | 门店 B | 相似度 |", "|---|---|---|"]
        lines += [f"| {a} | {b} | {s}{' ⚠️' if s > SIMILARITY_FLAG else ''} |" for a, b, s in seg_pairs]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--today", default="2026-10-21")
    ap.add_argument("--fake", action="store_true", help="offline rehearsal on tests/fakes (synthetic facts)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    if not args.fake and os.environ.get("RUN_E2E") != "1":
        print("eval_cards.py uses real deps (ima + LLM). Set RUN_E2E=1 to run it, or pass --fake.")
        return 2
    from agent.pipeline import Deps, generate_batch
    deps = Deps.fake() if args.fake else Deps.real()
    if args.fake:
        base_write = deps.write_post

        def write(task, strategy, ledger, plan, llm=None):
            p = base_write(task, strategy, ledger, plan, llm)
            # The real writer follows the card brief. Make the fake rehearsal do the same so 8E's
            # before/after is not artificially flat.
            p.body = [f"【{task.store_name or ''}·{task.hook or ''}·{task.angle or ''}】"] + list(p.body)
            return p

        deps.write_post = write
    today = dt.date.fromisoformat(args.today)
    data = load_store_data()
    cards = []
    for st in data.stores:
        card = default_card(st["store_id"], today, data)
        if card is not None and args.fake:
            card = dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")
        cards.append((st, card))
    batch = generate_batch([c for _, c in cards if c is not None], deps)
    evals: list[StoreEval] = []
    for st, card in cards:
        sid = st["store_id"]
        ev = StoreEval(store_id=sid, store_name=st["store_name"], segment=data.signals[sid]["dominant"])
        if card is None:
            ev.status, ev.message = "no_card", "今日无可生成的卡片"
            evals.append(ev)
            continue
        ev.card_id, ev.slot, ev.model_id = card.card_id, card.slot, card.model_id or ""
        r = batch.results.get(sid)
        if isinstance(r, LockedResult):
            ev.status, ev.message = "locked", r.message
        elif isinstance(r, NeedsHuman):
            ev.status, ev.message = "needs_human", r.message
        elif isinstance(r, Exception):
            ev.status, ev.message = "error", f"{type(r).__name__}: {str(r)[:160]}"
        elif isinstance(r, NeedsReview):
            ev.status, ev.message, ev.fallback = "needs_review", r.message, "needs_review"
            final = r.draft.report
            ev.stage_pass = {s: not any(i.stage == s and i.severity == "error" for i in final.issues) for s in STAGES}
            ev.rewrites = r.draft.loops
            ev.errors = [(i.stage, i.code, i.span) for i in final.issues if i.severity == "error"]
        elif isinstance(r, RunResult):
            ev.fallback = r.fallback or ""
            final = r.report
            ev.stage_pass = {s: not any(i.stage == s and i.severity == "error" for i in final.issues) for s in STAGES}
            ev.rewrites = r.loops
            ev.hits_8d = [(i.code, i.span) for i in final.issues if i.stage == "8D"]
            ev.errors = [(i.stage, i.code, i.span) for i in final.issues if i.severity == "error"]
            ev.tags = list(dict.fromkeys(r.post.selling_points))
            ev.text = render_publishable(r.post)
            ev.timings = dict(r.timings or {})
        else:
            ev.status, ev.message = "no_result", "没有返回结果"
        ev.seconds = batch.seconds.get(sid, 0.0)
        ev.regenerated = sid in batch.regenerated
        if sid in batch.regen_seconds:
            ev.timings["8E"] = batch.regen_seconds[sid]
        ev.sim_flags = [f"{p.store_a}×{p.store_b} {p.before}→{p.after}" for p in batch.similarity
                        if sid in (p.store_a, p.store_b) and max(p.before, p.after) > SIMILARITY_FLAG]
        evals.append(ev)
    report = build_report(evals, today, "fakes（合成数据）" if args.fake else "真实依赖", batch.similarity,
                          wall=batch.wall_seconds, llm_calls=getattr(deps.llm, "calls", None))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    sm = summary(evals)
    for e in evals:
        print(f"{e.store_id} {e.status:12} " + " ".join(f"{s}{'✓' if e.stage_pass.get(s) else '✗'}" for s in STAGES)
              + f" rewrites={e.rewrites} {e.seconds:.1f}s" + (f" fallback={e.fallback}" if e.fallback else "") + (f" 8E[{'; '.join(e.sim_flags)}]" if e.sim_flags else ""))
    print(f"wrote {out} · {sm['generated']}/{sm['stores']} generated · {sm['passed']}/{sm['stores']} passed "
          f"within 2 rewrites · fallback {sm['fallback']} · median {sm['median_s']:.1f}s · max {sm['max_s']:.1f}s")
    med = stage_medians(evals)
    print("stage medians (s): " + " · ".join(f"{k} {med[k]}" for k in TIMING_COLS if k in med))
    print(f"batch wall time: {batch.wall_seconds:.1f}s (BATCH_MAX_WORKERS={os.getenv('BATCH_MAX_WORKERS', '4')})")
    print(f"calls: LLM {len(getattr(deps.llm, 'calls', []) or [])} · "
          f"ima {getattr(getattr(deps.catalog, 'client', None), 'live_calls', 'n/a')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
