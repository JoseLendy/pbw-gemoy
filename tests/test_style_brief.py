"""Task 1: the writer brief built from a recommendation card (agent/style/profile.py).

The manual flow must be byte-identical to before Phase 2, so every card-only assertion is paired with a
manual assertion that the same text does NOT appear.
"""
from __future__ import annotations

import pytest

from agent.recommend.store_data import cards_for, reload
from agent.recommend.to_task import card_to_task
from agent.style.profile import CUSTOMER_HOOK, brief, hook_label, voice_label
from agent.writer import _context
from tests.fakes import fake_ledger, fake_plan, fake_strategy, fake_task

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def clean_cache():
    reload()
    yield
    reload()


def _card(store="S01", slot="potential"):
    reload()
    card = next((c for c in cards_for(store, TODAY) if c.slot == slot), None)
    assert card is not None, f"{store}/{slot} card missing"
    return card


def _ctx(task) -> str:
    return _context(task, fake_strategy(task.scenario if task.scenario == "office" else "back_to_school"),
                    fake_ledger(), fake_plan(task.platform or "moments"))


# ------------------------------------------------------------------ manual flow is untouched
def test_manual_brief_is_empty():
    assert brief(fake_task()) == ""


def test_manual_prompt_has_no_card_section():
    task = fake_task(platform="moments")
    ctx = _ctx(task)
    assert "门店推荐卡" not in ctx
    for field in ("误区澄清", "学长学姐", "紫金港", "购物节前做功课"):
        assert field not in ctx


def test_manual_prompt_keeps_its_original_sections():
    ctx = _ctx(fake_task(platform="moments"))
    for section in ("## 任务", "## 策略", "## 已选事实", "## 背景事实", "## 表达边界", "## 图片方案"):
        assert section in ctx, section


# ------------------------------------------------------------------ card brief carries the fields
def test_card_brief_has_hook_voice_landmark_angle_and_calendar():
    card = _card("S01")
    task = card_to_task(card)
    block = brief(task)
    assert block, "card brief must not be empty"
    assert hook_label(task.hook) in block
    assert voice_label(task.voice) in block
    assert task.landmark in block
    assert task.angle in block
    assert task.calendar_theme in block


def test_card_prompt_contains_the_brief_and_manual_does_not():
    task = card_to_task(_card("S01"))
    ctx = _ctx(task)
    assert "门店推荐卡要求" in ctx
    assert task.landmark in ctx
    assert "门店推荐卡要求" not in _ctx(fake_task(platform=task.platform))


def test_staff_voice_and_nickname_override_the_card():
    from agent.schemas import StaffContext

    card = _card("S01")
    base = card_to_task(card)
    staff = StaffContext(staff_id="u1", display_name="小李", voice="techie", nickname="小张")
    over = card_to_task(card, staff)
    assert over.voice == "techie" and over.nickname == "小张"
    assert base.voice == "senior"
    block = brief(over)
    assert "懂技术的店员" in block and "小李" in block


# ------------------------------------------------------------------ customer hook
def test_customer_hook_quotes_the_logged_question_only():
    card = _card("S01", "customer_question")
    card.hook.id = CUSTOMER_HOOK           # force the customer hook for this assertion
    task = card_to_task(card)
    assert task.question and task.question["text"]
    block = brief(task)
    assert task.question["text"] in block
    assert "不得添加其他顾客问题" in block


def test_customer_hook_without_a_logged_question_refuses_and_bans_inventing():
    card = _card("S01")
    task = card_to_task(card)
    task.hook = CUSTOMER_HOOK
    task.question = None
    block = brief(task)
    assert "不得使用" in block and "没有该问题的记录" in block
    assert "不得虚构顾客提问" in block


# ------------------------------------------------------------------ nickname / platform
def test_nickname_sign_off_only_on_moments():
    card = _card("S01")
    task = card_to_task(card)
    task.platform = "moments"
    assert "署名" in brief(task) and task.nickname in brief(task)
    task.platform = "xiaohongshu"
    assert "署名" in brief(task) and f"「{task.nickname}」署名" not in brief(task)


# ------------------------------------------------------------------ calendar / sales / price
def test_calendar_theme_never_implies_a_discount():
    assert "不得暗示折扣" in brief(card_to_task(_card("S01")))


def test_sales_data_is_banned_from_the_copy():
    block = brief(card_to_task(_card("S01")))
    assert "不得提销量" in block
    for word in ("热销", "爆款", "销量第一", "卖断货"):
        assert word in block                # named in the ban, not as an option


def test_no_promo_record_bans_every_price_wording():
    task = card_to_task(_card("S01"))
    assert task.promo is None
    block = brief(task)
    assert "没有任何价格记录" in block
    assert "不得写价格" in block


def test_demo_promo_quotes_value_conditions_and_marks_the_tag():
    card = next((c for c in cards_for("S01", TODAY) if c.slot == "promo"), None)
    assert card is not None and card.promo, "S01 promo card missing"
    task = card_to_task(card)
    block = brief(task)
    if task.promo.get("price_info"):
        assert str(task.promo["price_info"]["value"]) in block
        assert task.promo["price_info"]["conditions"] in block
        assert "[演示活动]" in block
