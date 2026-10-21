"""Task 3: fact-ID tagging in 8A + traceability in the 4-section output. Fakes only."""
from __future__ import annotations

import re

from agent.checks.facts import auto_cite, check_facts, excluded_fact_ids
from agent.formatter import render_publishable, render_report
from agent.pipeline import Deps, run
from agent.schemas import Conflict
from tests.fakes import fake_ledger, fake_post

TEXT = "一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书"


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def with_body(*paragraphs):
    p = fake_post("xiaohongshu")
    p.body = list(paragraphs)
    return p


def conflicted_ledger():
    led = fake_ledger()
    led.conflicts = [Conflict("brightness", "all", ["F5"], "两份资料亮度不一致")]
    return led


# ------------------------------------------------------------------ untagged
def test_untagged_spec_sentence_fails():
    r = check_facts(with_body("重量约 1.25 kg，放进双肩包不占地方。"), fake_ledger(), {})
    assert "untagged_claim" in codes(r, "error")
    i = next(i for i in r.issues if i.code == "untagged_claim")
    assert i.field == "body[0]" and "1.25 kg" in i.span and "[F#]" in i.message


def test_untagged_entity_sentence_fails():
    r = check_facts(with_body("多屏协同让课件直接拖到电脑上。"), fake_ledger(), {})
    assert "untagged_claim" in codes(r, "error")


def test_scene_sentence_without_spec_passes():
    r = check_facts(with_body("宿舍、教室、图书馆来回跑，电脑的重量每天都在你肩上。", "重量约 1.25 kg [F1]。"),
                    fake_ledger(), {})
    assert "untagged_claim" not in codes(r)


def test_whitelisted_numbers_are_not_claims():
    r = check_facts(with_body("2026 开学季，先看 3 个理由。", "重量约 1.25 kg [F1]。"), fake_ledger(), {})
    assert "untagged_claim" not in codes(r)


def test_fake_posts_still_pass():
    for p in ("xiaohongshu", "wechat_article", "moments"):
        assert codes(check_facts(fake_post(p), fake_ledger(), {}), "error") == set(), p


# ------------------------------------------------------------------ tag agreement
def test_tag_pointing_at_the_wrong_fact_fails_and_names_the_right_one():
    r = check_facts(with_body("续航可达约 14 小时 [F1]。"), fake_ledger(), {})
    i = next(i for i in r.issues if i.code == "tag_mismatch")
    assert i.fact_id == "F7" and "14 小时" in i.message


def test_tag_mismatch_is_fixed_in_code_by_auto_cite():
    post = with_body("重量约 1.25 kg [F1]，续航可达约 14 小时。")
    led = fake_ledger()
    issues = [i for i in check_facts(post, led, {}).issues if i.code == "tag_mismatch"]
    new, fixed = auto_cite(post, issues, led)
    assert fixed and "[F7]" in new.body[0]
    assert "tag_mismatch" not in codes(check_facts(new, led, {}))


def test_auto_cite_never_fixes_an_unsupported_number():
    """An LLM issue may name a fact, but auto-cite must not bless a number that no ledger fact supports."""
    from agent.schemas import CheckIssue
    post = with_body("续航可达约 15 小时。")
    led = fake_ledger()
    issue = CheckIssue("8A", "error", "uncited_claim", "x", field="body[0]",
                       span="续航可达约 15 小时", fact_id="F7")
    new, fixed = auto_cite(post, [issue], led)
    assert fixed == [] and "[F7]" not in new.body[0]
    report = check_facts(post, led, {})
    assert "unsupported_number" in codes(report, "error") or "untagged_claim" in codes(report, "error")


# ------------------------------------------------------------------ conflict gate
def test_tag_to_an_excluded_fact_fails():
    led = conflicted_ledger()
    assert excluded_fact_ids(led) == {"F5"}
    r = check_facts(with_body("亮度 500 nits [F5]。"), led, {})
    assert "excluded_fact" in codes(r, "error")


def test_auto_cite_never_adds_an_excluded_fact():
    from agent.schemas import CheckIssue
    led = conflicted_ledger()
    post = with_body("屏幕很亮。")
    issue = CheckIssue("8A", "error", "uncited_claim", "x", field="body[0]", span="屏幕很亮", fact_id="F5")
    new, fixed = auto_cite(post, [issue], led)
    assert fixed == [] and "[F5]" not in new.body[0]


def test_writer_never_offers_excluded_facts():
    from agent.writer import _usable
    from tests.fakes import fake_strategy
    led = conflicted_ledger()
    chosen, others = _usable(led, fake_strategy())
    assert "F5" not in {f.id for f in chosen + others}


# ------------------------------------------------------------------ formatter
def test_publishable_has_no_tags_and_section_4_lists_them():
    r = run(TEXT, deps=Deps.fake())
    pub = render_publishable(r.post)
    assert not re.search(r"\[F\d+\]", pub)
    md = render_report(r)
    sec4 = md.split("## 四、核验结果", 1)[1]
    assert "事实编号追溯" in sec4
    for fid in r.post.selling_points:
        f = r.ledger.get(fid)
        assert f"- {fid} → {f.value} → {f.source_title}" in sec4
    assert "文风（去模板化）" in sec4
