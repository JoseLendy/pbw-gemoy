"""
RecommendationCard (+ optional StaffContext) → schemas.Task (plan §3 "the card is the task").

Fills exactly what intake.parse_task fills (model_id, platform, audience, scenario, raw_text) plus the
writer brief fields that Task now carries as optional extras. The manual flow is untouched.
"""
from __future__ import annotations

from typing import Optional

from agent.recommend.common import INPUTS, load_json
from agent.recommend.profiles import check_voice, voices_by_id
from agent.schemas import RecommendationCard, SCENARIO_LABELS, StaffContext, Task

# Chinese label from the weekly rotation → pipeline platform key (schemas.PLATFORM_LABELS inverse + aliases).
PLATFORM_KEYS = {"朋友圈": "moments", "门店朋友圈": "moments", "小红书": "xiaohongshu", "公众号": "wechat_article",
                 "海报": "poster", "门店海报": "poster", "抖音": "douyin", "抖音图文": "douyin",
                 "moments": "moments", "xiaohongshu": "xiaohongshu", "wechat_article": "wechat_article",
                 "poster": "poster", "douyin": "douyin"}

# Segment → audience phrasing ("audience" is free text for the scenario stage).
SEGMENT_AUDIENCE = {"student": "周边高校的学生", "office": "附近写字楼的上班族", "family": "周边社区的家庭用户",
                    "shopper": "逛街与送礼的顾客"}


def platform_key(label: str) -> str:
    try:
        return PLATFORM_KEYS[label]
    except KeyError:
        raise ValueError(f"unknown platform label {label!r}") from None


def _raw_text(card: RecommendationCard) -> str:
    """A one-line description of the brief: what a staff member would have typed in the manual flow."""
    bits = [f"{card.store_name}今日推荐（{card.slot_label}）", f"面向{card.segment_label}", f"角度：{card.angle}"]
    if card.calendar_theme:
        bits.append(f"主题：{card.calendar_theme}")
    if card.question:
        bits.append(f"顾客常问：{card.question.text}")
    return "，".join(bits) + f"，发{card.platform}"


def card_to_task(card: RecommendationCard, staff: Optional[StaffContext] = None,
                 angles: Optional[dict] = None) -> Task:
    """Build the Task the pipeline runs on. Raises ValueError if the card has no model, or a staff voice
    override is not allowed for the card's segment (validated against data/demo/inputs/angles.json)."""
    if not card.model_id:
        raise ValueError(f"card {card.card_id} has no model_id")
    if card.scenario not in SCENARIO_LABELS:
        raise ValueError(f"card {card.card_id}: scenario {card.scenario!r} is not a known Scenario key")
    angles = angles or load_json(INPUTS / "angles.json")
    voice_id = card.voice.id if card.voice else None
    nickname = card.nickname
    if staff is not None:
        if staff.voice:
            check_voice(staff.voice, card.segment, angles, who=f"staff {staff.staff_id}")
            voice_id = staff.voice
        if staff.nickname:
            nickname = staff.nickname
    if voice_id is not None and voice_id not in voices_by_id(angles):
        raise ValueError(f"card {card.card_id}: unknown voice {voice_id!r}")
    return Task(
        raw_text=_raw_text(card),
        product_query=card.display_name,
        model_id=card.model_id,
        audience=SEGMENT_AUDIENCE[card.segment],
        scenario=card.scenario,
        platform=platform_key(card.platform),
        source="card", card_id=card.card_id, store_id=card.store_id, store_name=card.store_name,
        slot=card.slot, segment=card.segment, hook=card.hook.id if card.hook else None,
        voice=voice_id, landmark=card.landmark or None, nickname=nickname or None,
        angle=card.angle, calendar_theme=card.calendar_theme,
        promo=card.promo.to_dict() if card.promo else None,
        question=card.question.to_dict() if card.question else None,
        staff=staff.to_dict() if staff else None,
        card_date=card.date,
    )
