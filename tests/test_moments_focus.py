"""8C moments_focus (朋友圈只讲一个核心卖点): what is counted, and whether the issue can be fixed.

Proof tests for the 2026-10-23 card runs (synthetic DemoBook data only):
  * the focus is judged on the facts the post actually cites, not on stale ids left in post.selling_points
  * a post that really cites two facts is still flagged, on the field that carries the extra tag, with the
    sentence as the span (so the rewrite gets that field and the T4 trim can locate the sentence)
  * a rewrite that removes a tag also removes that id from post.selling_points
"""
from __future__ import annotations

from agent.pipeline import _trim, failing_sentences
from agent.platform_rules import build_prompt_rules, check_post
from agent.schemas import CheckIssue, CheckReport
from agent.writer import rewrite
from tests.fakes import FakeLLM, fake_ledger, fake_plan, fake_post, fake_strategy, fake_task


def focus(post):
    return [i for i in check_post(post, "moments") if i.code == "moments_focus"]


# ------------------------------------------------------------------ (b) over-flag: stale selling_points id
def test_uncited_selling_point_id_is_not_a_second_point():
    """The live shape: the text cites one fact; selling_points still lists a second id that no sentence
    cites (left over after a rewrite dropped its tag). The post says one thing, so 8C must not flag it."""
    p = fake_post("moments")
    p.selling_points = ["F1", "F2"]
    assert "[F2]" not in p.all_text()
    assert focus(p) == []


def test_good_moments_post_passes():
    assert focus(fake_post("moments")) == []


# ------------------------------------------------------------------ guards: real focus breaks stay flagged
def test_two_cited_facts_are_still_flagged():
    p = fake_post("moments")
    p.body = ["重量约 1.25 kg [F1]，放进双肩包不占地方。", "电池 65 Wh [F6]，一天的课够用。"]
    p.selling_points = ["F1", "F6"]
    assert focus(p)


def test_two_facts_in_one_sentence_are_still_flagged():
    p = fake_post("moments")
    p.body = ["重量约 1.25 kg [F1]，电池 65 Wh [F6]。"]
    p.selling_points = ["F1"]
    assert focus(p)


def test_no_cited_fact_and_no_or_many_selling_points_still_flagged():
    p = fake_post("moments")
    p.body = ["周末路过可以进来看看。"]
    p.selling_points = []
    assert focus(p)
    p.selling_points = ["F1", "F6"]
    assert focus(p)


# ------------------------------------------------------------------ (a) the issue must be actionable
def test_issue_names_the_field_with_the_extra_tag_and_the_fact_to_keep():
    """Live S09 shape: the extra tag sits in the intro too. An issue on field="body" only sends the body to
    the rewrite, so the intro's extra tag can never be removed."""
    p = fake_post("moments")
    p.intro = "宿舍到教室来回跑，重量约 1.25 kg [F1][F12]。"
    p.body = ["放进双肩包不占地方 [F1]。"]
    p.selling_points = ["F1", "F12"]
    issues = focus(p)
    assert {i.field for i in issues} == {"intro"}
    assert all("[F1]" in i.message and "[F12]" in i.message for i in issues)
    assert issues[0].span and "[F12]" in issues[0].span


def test_trim_can_locate_a_sentence_that_only_carries_the_extra_fact():
    """T4 trim: before, the span was only tags ("[F1][F6]"), so no sentence was found ("trim not
    possible"). With the sentence as span the extra-fact sentence is removed and the post passes 8C."""
    p = fake_post("moments")
    p.body = ["背着跑一天也不累，重量约 1.25 kg [F1]，放进双肩包不占地方。", "电池 65 Wh [F6]，一天的课够用。"]
    p.selling_points = ["F1", "F6"]
    report = CheckReport([i for i in check_post(p, "moments") if i.severity == "error"])
    failing = failing_sentences(p, report)
    assert failing and all(f.sentence for f in failing)
    trimmed = _trim(p, failing)
    assert trimmed is not None and "[F6]" not in trimmed.all_text() and trimmed.selling_points == ["F1"]
    assert focus(trimmed) == []


# ------------------------------------------------------------------ rewrite keeps selling_points in sync
def test_rewrite_that_drops_a_tag_drops_the_id_from_selling_points():
    before = fake_post("moments")
    before.body = ["重量约 1.25 kg [F1]，电池 65 Wh [F6]。"]
    before.selling_points = ["F1", "F6"]
    issues = [CheckIssue("8C", "error", "moments_focus", "只能围绕一个核心卖点", field="body[0]")]
    llm = FakeLLM({"rewrite": {"body": ["重量约 1.25 kg [F1]，放进双肩包不占地方。"]}})
    new = rewrite(before, issues, fake_task("moments"), fake_strategy(), fake_ledger(), fake_plan("moments"), llm)
    assert "[F6]" not in new.all_text()
    assert new.selling_points == ["F1"]


def test_rewrite_keeps_a_declared_id_it_did_not_touch():
    """Only ids the rewrite removed are dropped; a declared id that was never a tag is left as before."""
    before = fake_post("xiaohongshu")
    before.selling_points = before.selling_points + ["F3"]
    issues = [CheckIssue("8D", "error", "ai_tell", "套话", field="cta")]
    llm = FakeLLM({"rewrite": {"cta": "想试试重量，可以来店里上手看看。"}})
    new = rewrite(before, issues, fake_task(), fake_strategy(), fake_ledger(), fake_plan(), llm)
    assert new.selling_points == before.selling_points


# ------------------------------------------------------------------ writer prompt states the counted rule
def test_moments_prompt_says_the_text_tags_only_one_fact():
    rules = build_prompt_rules("moments")
    assert "selling_points 只放一个事实编号" in rules
    assert "正文只标注这一个事实编号" in rules
