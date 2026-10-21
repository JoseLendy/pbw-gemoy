"""
ui.components (Phase 3 UI). Pure display-data helpers only - no Gradio rendering here. Fakes only;
no ima, no LLM, no network.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import pytest

from agent.pipeline import Deps, run_from_card
from agent.recommend.store_data import default_card, reload
from agent.schemas import (
    BaselineResult, CardReason, Clarification, EditBlocked, LockedResult, NeedsHuman, RecommendationCard,
    StaffContext,
)
from ui import components as C

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def _demo_card(store_id: str = "S01") -> RecommendationCard:
    card = default_card(store_id, TODAY)
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


# ---------------------------------------------------------------- stores / slots / role rule
def test_store_choices_are_label_value_pairs_with_store_name_first():
    stores = [{"store_id": "S01", "store_name": "紫金港店"}, {"store_id": "S04", "store_name": "钱江新城店"}]
    assert C.store_choices(stores) == [("紫金港店", "S01"), ("钱江新城店", "S04")]


def test_other_cards_excludes_the_default_and_keeps_slot_order():
    cards = [
        RecommendationCard(card_id="a", store_id="S01", store_name="x", date=TODAY, slot="customer_question",
                           slot_label="顾客问答", model_id="m", display_name="d", platform="朋友圈",
                           segment="student", segment_label="l", angle="a"),
        RecommendationCard(card_id="b", store_id="S01", store_name="x", date=TODAY, slot="potential",
                           slot_label="潜力款", model_id="m", display_name="d", platform="朋友圈",
                           segment="student", segment_label="l", angle="a", is_default=True),
        RecommendationCard(card_id="c", store_id="S01", store_name="x", date=TODAY, slot="promo",
                           slot_label="活动款", model_id="m", display_name="d", platform="朋友圈",
                           segment="student", segment_label="l", angle="a"),
    ]
    assert [c.card_id for c in C.other_cards(cards)] == ["c", "a"]   # promo before customer_question, default dropped
    assert C.default_card_of(cards).card_id == "b"


def test_reason_badges_preserves_order_and_is_demo_flag():
    card = _demo_card()
    card = dataclasses.replace(card, reasons=[CardReason("真实原因", "poi", False), CardReason("模拟原因", "sales", True)])
    assert C.reason_badges(card) == [("真实原因", False), ("模拟原因", True)]


@pytest.mark.parametrize("platform,role,expected", [
    ("朋友圈", "staff", True), ("朋友圈", None, True),
    ("小红书", "staff", False), ("公众号", "staff", False),
    ("小红书", "manager", True), ("公众号", None, True),
])
def test_can_act_follows_the_role_rule(platform, role, expected):
    card = dataclasses.replace(_demo_card(), platform=platform)
    staff = StaffContext(staff_id="x", display_name="x", role=role) if role else None
    assert C.can_act(card, staff) is expected


def test_role_notice_only_appears_when_not_actionable():
    card = dataclasses.replace(_demo_card(), platform="小红书")
    staff = StaffContext(staff_id="x", display_name="x", role="staff")
    assert C.role_notice(card, staff) == "由店长发布"
    assert C.role_notice(card, None) is None


def test_card_locked_label():
    locked = dataclasses.replace(_demo_card(), locked=True)
    assert C.card_locked_label(locked) == C.LOCKED_LABEL
    assert C.card_locked_label(_demo_card()) is None


# ---------------------------------------------------------------- session state (reset-friendly)
def test_fresh_session_has_the_expected_shape_and_a_unique_id():
    a, b = C.fresh_session(), C.fresh_session()
    assert a["id"] != b["id"]
    for s in (a, b):
        assert s["published"] == {} and s["chips"] == {} and s["results"] == {}


# ---------------------------------------------------------------- result classification
@dataclass
class NeedsReview:
    """Stand-in for the Phase 5 type (not merged into schemas.py yet): "carries the card, the best
    draft, failing sentences + reasons" per the Phase 3 task brief."""
    card: Any
    best_draft: str
    failing_sentences: list
    reasons: list


def test_result_kind_classifies_every_known_type():
    card = _demo_card()
    run_result = run_from_card(card, Deps.fake())
    locked = run_from_card(dataclasses.replace(card, locked=True, locked_reason="fact_card_draft"), Deps.fake())
    cases = [
        (run_result, "run_result"),
        (locked, "locked"),
        (NeedsHuman(conflicts=[], message="冲突"), "needs_human"),
        (EditBlocked(instruction="加上立减500", message="未找到匹配的活动记录"), "edit_blocked"),
        (BaselineResult(card_id="c", model_id="m", platform="朋友圈", prompt="p", text="t", display_text="【x】t"),
         "baseline"),
        (Clarification(questions=[]), "clarification"),
        (NeedsReview(card=card, best_draft="草稿", failing_sentences=["这句话"], reasons=["未命中事实"]),
         "needs_review"),
        (object(), "unknown"),
    ]
    for result, expected in cases:
        assert C.result_kind(result) == expected, expected


def test_fallback_note_only_fires_for_next_card():
    class _R:
        pass
    r = _R()
    assert C.fallback_note(r) is None
    r.fallback = "trimmed"
    assert C.fallback_note(r) is None
    r.fallback = "next_card"
    assert C.fallback_note(r) == "今日主推暂不可用，已为你准备下一条"


def test_needs_review_view_extracts_best_effort_fields():
    card = _demo_card()
    stub = NeedsReview(card=card, best_draft="草稿文本", failing_sentences=["问题句子"], reasons=["未命中事实台账"])
    v = C.needs_review_view(stub)
    assert v["card"] is card and v["draft"] == "草稿文本"
    assert v["failing"] == ["问题句子"] and v["reasons"] == ["未命中事实台账"]


# ---------------------------------------------------------------- HTML render panels
def test_phone_html_and_banner_html_render_a_fake_run_result():
    result = run_from_card(_demo_card(), Deps.fake())
    phone = C.phone_html(result)
    assert 'class="hw-phone' in phone
    banner = C.banner_html(result)
    assert banner  # at least one banner (ok / err / warn / note)


def test_stop_html_escapes_the_message():
    out = C.stop_html("<script>alert(1)</script>", "标题")
    assert "<script>" not in out and "&lt;script&gt;" in out


def test_needs_review_html_highlights_the_failing_sentence():
    stub = NeedsReview(card=_demo_card(), best_draft="开头。问题句子。结尾。",
                       failing_sentences=["问题句子。"], reasons=["未命中事实台账"])
    out = C.needs_review_html(stub)
    assert '<span class="flag">问题句子。</span>' in out
    assert "未命中事实台账" in out


def test_last_real_run_html_shows_the_timestamp_and_strips_fact_tags():
    payload = {"timestamp": "2026-10-21T10:00:00+08:00",
              "result": {"post": {"title": "标题[F1]", "intro": "导语", "body": ["正文[F2]"], "cta": "到店"}}}
    out = C.last_real_run_html(payload)
    assert "2026-10-21T10:00:00+08:00" in out
    assert "[F1]" not in out and "[F2]" not in out
    assert "非本次生成" in out


# ---------------------------------------------------------------- never leak model_id / "MODEL_"
def test_card_panel_html_never_leaks_model_id():
    from ui.store_tab import _card_panel_html
    card = _demo_card()
    out = _card_panel_html(card, prepared=False)
    assert card.model_id not in out
    assert "MODEL_" not in out
    assert card.display_name in out


def test_reason_badges_and_store_choices_never_mention_model_id_or_model_placeholder():
    card = _demo_card()
    rendered = " ".join(text for text, _ in C.reason_badges(card))
    assert card.model_id not in rendered and "MODEL_" not in rendered
    choices = C.store_choices([{"store_id": "S01", "store_name": "紫金港店"}])
    assert "MODEL_" not in str(choices)
