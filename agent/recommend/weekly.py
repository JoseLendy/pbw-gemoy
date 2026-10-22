"""
Weekly platform progress (replaces the fixed day→platform rotation as a LOCK; it is now a suggestion).

    progress = weekly_progress("S03", "2026-10-23")      # {"朋友圈": {"done": 1, "minimum": 3}, ...}
    suggest_platform(progress)                           # the platform most behind its weekly minimum
    mark_published("S03", "2026-10-23", "小红书")         # 已发布 ✓, per platform; progress updates at once

The week runs Monday..today. Counts come from generated/publish_log.csv (posted == true) plus the
已发布 marks staff made in the app, stored per date in runs/published/<date>.json (local, gitignored).
reset_demo_state() does not touch these marks; agent.ui_data's 重置演示 clears them explicitly.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

from agent.recommend.common import parse_date

PLATFORM_ORDER = ("朋友圈", "小红书", "公众号")


def _marks_path(day, runs_dir: Optional[Path] = None) -> Path:
    from agent.runs import RUNS_DIR
    return (Path(runs_dir) if runs_dir else RUNS_DIR) / "published" / f"{parse_date(day).isoformat()}.json"


def published_marks(day, runs_dir: Optional[Path] = None) -> list[dict]:
    """[{"store_id", "platform", "card_id"}] marked 已发布 in the app on that date."""
    p = _marks_path(day, runs_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except (OSError, ValueError):
        return []


def mark_published(store_id: str, day, platform: str, card_id: str = "", runs_dir: Optional[Path] = None) -> None:
    marks = published_marks(day, runs_dir)
    row = {"store_id": store_id, "platform": platform, "card_id": card_id}
    if row not in marks:
        marks.append(row)
        p = _marks_path(day, runs_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(marks, ensure_ascii=False, indent=1), encoding="utf-8")


def clear_marks(day, runs_dir: Optional[Path] = None) -> None:
    p = _marks_path(day, runs_dir)
    if p.exists():
        p.unlink()


def weekly_progress(store_id: str, day, data=None, runs_dir: Optional[Path] = None) -> dict[str, dict]:
    """{platform: {"done", "minimum"}} for the store's week (Monday..day), log + today's app marks."""
    from agent.recommend.store_data import load_store_data
    data = data or load_store_data()
    today = parse_date(day)
    monday = today - dt.timedelta(days=today.weekday())
    minimum = dict(data.quota["weekly_minimum"])
    done = {p: 0 for p in minimum}
    for r in data.publish:
        if r["store_id"] == store_id and r["posted"] == "true" and r["platform"] in done \
                and monday <= parse_date(r["date"]) < today:
            done[r["platform"]] += 1
    for m in published_marks(today, runs_dir):
        if m["store_id"] == store_id and m["platform"] in done:
            done[m["platform"]] += 1
    order = [p for p in PLATFORM_ORDER if p in minimum] + [p for p in minimum if p not in PLATFORM_ORDER]
    return {p: {"done": done[p], "minimum": minimum[p]} for p in order}


def behind(progress: dict[str, dict]) -> dict[str, int]:
    """Posts still missing this week, per platform (0 when the minimum is met)."""
    return {p: max(0, v["minimum"] - v["done"]) for p, v in progress.items()}


def suggest_platform(progress: dict[str, dict]) -> str:
    """The platform most behind: the largest missing share of its weekly minimum, then the most posts
    missing, then 朋友圈 → 小红书 → 公众号. With every minimum met: 朋友圈 (every staff member posts there)."""
    gap = behind(progress)
    if not any(gap.values()):
        return "朋友圈" if "朋友圈" in progress else next(iter(progress))
    order = list(progress)
    return max(order, key=lambda p: (gap[p] / max(1, progress[p]["minimum"]), gap[p], -order.index(p)))


def progress_line(progress: dict[str, dict], suggestion: Optional[str] = None) -> str:
    """「本周：朋友圈 x/3 · 小红书 x/3 · 公众号 x/1 · 今天建议发：<platform>」"""
    parts = " · ".join(f"{p} {v['done']}/{v['minimum']}" for p, v in progress.items())
    return f"本周：{parts} · 今天建议发：{suggestion or suggest_platform(progress)}"


__all__ = ["weekly_progress", "suggest_platform", "behind", "progress_line", "mark_published",
           "published_marks", "clear_marks", "PLATFORM_ORDER"]
