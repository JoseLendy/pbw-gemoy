"""Writer brief + 8D rules from the 2026-10-23 review (synthetic text only):
the calendar theme is an idea (never copied verbatim), the myth hook has no fixed opener, the CTA does not
read like legal text, and the writer is told the product name. (Sign-offs are gone: tests/test_personal_names.py.)"""
from __future__ import annotations

import dataclasses

from agent.schemas import Post, Task
from agent.style.antiai import check_style
from agent.style.profile import HOOK_OPENING, brief
from agent.writer import _context
from tests.fakes import fake_ledger, fake_plan, fake_post, fake_strategy


def _task(**kw) -> Task:
    base = dict(raw_text="", product_query="DemoBook 14（演示版）", model_id="demobook-14", platform="moments",
                source="card", hook="scene", voice="techie", landmark="演示广场附近",
                angle="送礼怎么选", calendar_theme="购物节前做功课", scenario="holiday")
    base.update(kw)
    return Task(**base)


def _post(body, cta="想上手试试，到店找我。") -> Post:
    p = fake_post("moments")
    p.body, p.cta = list(body), cta
    return p


def _codes(report):
    return {i.code for i in report.issues if i.severity == "error"}


# ---------------------------------------------------------------- calendar theme
def test_calendar_theme_copied_verbatim_is_flagged():
    p = _post(["演示广场附近的门店，购物节前做功课，重量约 1.25 kg [F1]。"])
    assert "ai_theme_copied" in _codes(check_style(p, _task()))


def test_calendar_theme_copied_with_a_filler_word_is_flagged():
    p = _post(["购物节前先来做做功课，重量约 1.25 kg [F1]，演示广场附近的门店。"])
    assert "ai_theme_copied" in _codes(check_style(p, _task()))


def test_calendar_theme_as_an_idea_passes():
    p = _post(["双十一前想换电脑，演示广场附近的门店可以先摸摸实物，重量约 1.25 kg [F1]。"])
    assert "ai_theme_copied" not in _codes(check_style(p, _task()))


def test_brief_gives_the_theme_as_an_idea_not_a_phrase():
    b = brief(_task())
    assert "不要照抄" in b and "购物节前做功课" in b


# ---------------------------------------------------------------- stock openers
def test_myth_hook_prescribes_no_fixed_opener():
    assert "开头用“你可能以为" not in HOOK_OPENING["myth"]
    assert "不要用「你可能以为」" in HOOK_OPENING["myth"]
    b = brief(_task(hook="myth"))
    assert "「你可能以为」" in b and "不要用" in b


def test_brief_lists_phrases_other_stores_already_used():
    b = brief(_task(avoid_phrases=["下班顺路进店聊聊天"]))
    assert "下班顺路进店聊聊天" in b


def test_brief_names_selling_points_other_stores_already_use():
    b = brief(_task(avoid_facts=["F1"]))
    assert "F1" in b


# ---------------------------------------------------------------- CTA
def test_cta_that_reads_like_legal_text_is_flagged():
    p = _post(["演示广场附近的门店，重量约 1.25 kg [F1]。"], cta="欢迎到店上手试试，具体配置按门店演示版本确认。")
    issues = [i for i in check_style(p, _task()).issues if i.code == "ai_cta_legal"]
    assert issues and issues[0].field == "cta"


def test_cta_qualifier_shapes_are_flagged():
    for cta in ("到店试试，以门店实际为准。", "欢迎来店里，具体以官网为准。", "到店看看，请以实物为准。"):
        p = _post(["演示广场附近的门店，重量约 1.25 kg [F1]。"], cta=cta)
        assert "ai_cta_legal" in _codes(check_style(p, _task())), cta


def test_plain_cta_passes_and_a_qualifier_in_the_body_is_not_a_cta_issue():
    p = _post(["演示广场附近的门店，Windows 版支持该功能，以官网为准，重量约 1.25 kg [F1]。"],
              cta="想上手试试，到店或私信我都行。")
    assert "ai_cta_legal" not in _codes(check_style(p, _task()))


# ---------------------------------------------------------------- product name in the writer prompt
def test_writer_prompt_carries_the_display_name_and_the_naming_rule():
    ctx = _context(_task(), fake_strategy(), fake_ledger(), fake_plan("moments"))
    assert "DemoBook 14（演示版）" in ctx
    assert "这台" in ctx                     # the rule says 「这台/这款」 alone is not enough


def test_manual_prompt_still_names_the_product():
    t = dataclasses.replace(_task(), source="manual")
    assert "DemoBook 14（演示版）" in _context(t, fake_strategy(), fake_ledger(), fake_plan("moments"))
