"""
"为什么推这条" (plan §5.5): templates filled with computed values, never the LLM.
Order of reasons on a card: where (POI) → why this product (sales / promo / release / question) → when (calendar).
Each reason carries is_demo, which drives the 模拟 badge.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from agent.recommend.common import parse_date
from agent.recommend.scoring import CALENDAR_LOOKAHEAD_DAYS

# Events where "how many days left" counts down to the END (the sale window), not the start.
_COUNTDOWN_TO_END = ("双十一", "双十二")


def reason(text: Optional[str], source: str, is_demo: bool) -> dict:
    return {"text": text, "source": source, "is_demo": is_demo}


def poi_reason(sig: dict, seg_cfg: dict) -> Optional[str]:
    """门店1.5km内有2所高校（浙江大学紫金港校区等）→ 学生客群为主"""
    cat = sig["top_category"]
    if not cat:
        return None
    label = seg_cfg["categories"][cat]["label"]
    unit = "所" if cat in ("university", "middle_school", "primary_school") else "个"
    return (f"门店{seg_cfg['radius_m'] / 1000:g}km内有{sig['top_category_count']}{unit}{label}"
            f"（{sig['top_category_example']}等）→ {seg_cfg['segment_labels'][sig['dominant']]}为主")


def calendar_reason(calendar: list[dict], segment: str, today: dt.date) -> Optional[dict]:
    """{event, theme, text} for the nearest relevant event within CALENDAR_LOOKAHEAD_DAYS, else None."""
    best = None
    for ev in calendar:
        if segment not in ev["segments"]:
            continue
        start, end = parse_date(ev["start"]), parse_date(ev["end"])
        if start <= today <= end:
            return {"event": ev["event"], "theme": ev["theme"], "text": f"正值{ev['event']}（{ev['theme']}）"}
        days = (end - today).days if ev["event"] in _COUNTDOWN_TO_END else (start - today).days
        if 0 < days <= CALENDAR_LOOKAHEAD_DAYS and (best is None or days < best[0]):
            best = (days, ev)
    if best:
        d, ev = best
        return {"event": ev["event"], "theme": ev["theme"], "text": f"距{ev['event']}还有 {d} 天"}
    return None


def sales_reason(stats: dict) -> str:
    peer_word = "同类商圈门店" if stats["peer_basis"] == "same_segment" else "其他门店"
    return f"该型号本店销量占比低于{peer_word} {round((1 - stats['index']) * 100)}%"


def promo_reason(promo: dict) -> str:
    return f"全国活动「{promo['name']}」进行中（{promo['start']} 至 {promo['end']}）"


DEMO_RELEASE_REASON = "总部新品推送（演示流程）"


def release_reason(launch: dt.date, verified: bool, kb_launch: Optional[dt.date] = None) -> str:
    """models.csv launch_date only schedules the card (demo). The date is shown only when the KB states
    the same date (optional models.csv column kb_launch_date); otherwise the line says it is a demo push."""
    if not verified:
        return "新品资料待总部确认，暂不可生成"
    return f"新品 {launch.isoformat()} 上市" if kb_launch == launch else DEMO_RELEASE_REASON


def question_reason(text: str, count: int) -> str:
    return f"本店近7天顾客问「{text}」{count} 次"


def order_reasons(poi: list[dict], why: list[dict], when: list[dict]) -> list[dict]:
    """where → why → when, dropping empty lines."""
    return [r for r in poi + why + when if r["text"]]
