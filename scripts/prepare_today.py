#!/usr/bin/env python3
"""
Morning run (push model): prepare every store's default post for a date and store it as a real run.

    python scripts/prepare_today.py --today 2026-10-23          # real deps (ima + LLM)
    python scripts/prepare_today.py --today 2026-10-23 --fake   # rehearsal on tests/fakes -> runs/_rehearsal/

Prints per store: status, rewrites, seconds taken, its closest post of the day (8E compares every pair, not
only peers) and any 8E breach (similar / phrase / stock / selling_point) with whether the rerun replaced it. Refuses to run when any dependency
would fall back to a fake, unless --fake is passed. Never prints keys, the Client ID or KB IDs.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.schemas import LockedResult, NeedsHuman, NeedsReview, RunResult  # noqa: E402


def _status(result) -> str:
    if isinstance(result, RunResult):
        tag = f" ({result.fallback})" if result.fallback else ""
        return ("PASS" if result.report.passed else "FAIL（未通过核验）") + tag
    if isinstance(result, NeedsReview):
        return "NEEDS_REVIEW（需人工确认）"
    if isinstance(result, NeedsHuman):
        return "NEEDS_HUMAN"
    if isinstance(result, LockedResult):
        return "LOCKED"
    if isinstance(result, Exception):
        return f"ERROR {type(result).__name__}"
    return type(result).__name__


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--fake", action="store_true", help="rehearsal on tests/fakes (synthetic facts)")
    args = ap.parse_args(argv)
    from agent.pipeline import Deps, prepare_today
    from agent.runs import REHEARSAL_DIR
    from agent.style.similarity import similarity_threshold

    if args.fake:
        deps, runs_dir = Deps.fake(), REHEARSAL_DIR

        def card_map(card):
            return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")
    else:
        deps, runs_dir, card_map = Deps.auto(), None, None
        if deps.is_dev_mode:
            print("prepare_today.py needs real deps, but these would be fakes: " + ", ".join(deps.fake_fields))
            reason = (deps.status() or {}).get("error")
            if reason:
                print(f"原因：{reason}")
            print("Fix the configuration, or pass --fake for a rehearsal.")
            return 2

    day = prepare_today(args.today, deps, runs_dir=runs_dir, card_map=card_map)
    threshold = similarity_threshold()
    print(f"prepare_today {day.date} · {'rehearsal (fakes)' if args.fake else 'real deps'}")
    print(f"{'store':6} {'status':22} {'rewrites':>8} {'seconds':>8}  closest post today (before→after)  8E")
    for sid in sorted(day.batch.results):
        r = day.batch.results[sid]
        mine = [p for p in day.batch.similarity if sid in (p.store_a, p.store_b)]
        top = max(mine, key=lambda p: p.after, default=None)
        closest = (f"{top.store_b if top.store_a == sid else top.store_a} {top.before}→{top.after}"
                   + (" ⚠️" if top.after > threshold else "")) if top else "-"
        v = day.batch.variety.get(sid)
        flag = (",".join(v["reasons"]) + (" → regenerated" if v.get("replaced") else " → kept (rerun did not pass)")
                if v else "-")
        print(f"{sid:6} {_status(r):22} {getattr(r, 'loops', '-')!s:>8} {day.batch.seconds.get(sid, 0):>8.1f}  "
              f"{closest:32}  {flag}")
    for sid, why in sorted(day.locked.items()):
        print(f"{sid:6} {'SKIPPED':22} {'-':>8} {'-':>8}  {why}")
    if day.errors:
        print(f"NOT stored (crashed; any earlier prepared post is kept): {sorted(day.errors)}")
    print(f"stored: {len(day.paths)} prepared post(s) under {runs_dir or 'runs/'}{day.date}/prepared/")
    print(f"batch wall time: {day.batch.wall_seconds:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
