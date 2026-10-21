"""8C platform + writing conformance (agent/platform_rules.py)."""
from __future__ import annotations

import pytest

from agent.platform_rules import (AI_TELL_PHRASES, PLATFORM_RULES, WRITING_RULES, build_prompt_rules,
                                  check_post, count_chars)
from agent.schemas import PLATFORM_IMAGE_RANGE, PLATFORMS
from tests.fakes import fake_post


def codes(issues):
    return {i.code for i in issues}


# ------------------------------------------------------------------ rules table
def test_five_platforms_and_image_ranges_come_from_schemas():
    assert set(PLATFORM_RULES) == set(PLATFORMS)
    for p, rule in PLATFORM_RULES.items():
        assert rule["images"] == PLATFORM_IMAGE_RANGE[p]


def test_rules_table_shape():
    for p, r in PLATFORM_RULES.items():
        lo, hi = r["body_chars"]
        assert lo < hi
        assert r["blocks"] and r["cta_types"]
        assert r["title_max"] is None or r["title_max"] > 0
        assert r["caption_max"] is None or r["caption_max"] > 0
    assert PLATFORM_RULES["poster"]["title_max"] == 10
    assert PLATFORM_RULES["douyin"]["caption_max"] == 12
    assert PLATFORM_RULES["moments"]["selling_points_max"] == 1
    assert PLATFORM_RULES["poster"]["selling_points_max"] == 3
    assert PLATFORM_RULES["xiaohongshu"]["hashtags"] and PLATFORM_RULES["wechat_article"]["hashtags"] == 0


def test_absolutes_are_not_ai_tell_phrases():
    for w in ("最", "第一", "唯一", "顶级", "全网", "首选"):
        assert not any(w in p for p in AI_TELL_PHRASES)
    assert any("最、第一" in w for w in WRITING_RULES)   # only in the rules text, not the phrase list


def test_prompt_rules_have_no_real_looking_weight():
    """WORKFLOW fix 1: the example must be a placeholder, never a number a writer could copy."""
    from pathlib import Path
    prompts = Path(__file__).resolve().parents[1] / "prompts"
    # The tag example lives once, in the system prompt (Phase 5 prompt-bloat guard); it must stay a placeholder.
    assert "约 X kg [F1]" in (prompts / "system_prompt.md").read_text(encoding="utf-8")
    texts = [build_prompt_rules(p) for p in PLATFORMS] + [(prompts / n).read_text(encoding="utf-8")
                                                          for n in ("system_prompt.md", "writer.md")]
    for text in texts:
        assert "1.3kg" not in text and "1.3 kg" not in text and "1.25" not in text


def test_prompt_rules_state_platform_specific_limits():
    xhs = build_prompt_rules("xiaohongshu")
    assert "300–600" in xhs and "3–8" in xhs and "6" in xhs
    assert "12 个字" in build_prompt_rules("douyin")
    assert "10 个字" in build_prompt_rules("poster")
    assert "一个核心卖点" in build_prompt_rules("moments")


# ------------------------------------------------------------------ happy paths
@pytest.mark.parametrize("platform", ["xiaohongshu", "wechat_article", "moments"])
def test_fake_post_has_no_conformance_errors(platform):
    issues = check_post(fake_post(platform), platform)
    assert not [i for i in issues if i.severity == "error"], [(i.code, i.message) for i in issues]
    assert not any(i.stage != "8C" for i in issues)


# ------------------------------------------------------------------ blocks / CTA / tags
def test_missing_blocks_and_cta():
    p = fake_post()
    p.intro, p.cta, p.body = "", "", []
    cs = codes(check_post(p, "xiaohongshu"))
    assert {"missing_block", "missing_cta"} & cs


def test_cta_type_warning():
    p = fake_post()
    p.cta = "就这样吧"
    issues = [i for i in check_post(p, "xiaohongshu") if i.code == "cta_type"]
    assert issues and issues[0].severity == "warn"


def test_moments_needs_no_title_but_needs_tags():
    p = fake_post("moments")
    p.tags = []
    assert "tags_missing" in codes(check_post(p, "moments"))


# ------------------------------------------------------------------ length / emoji / hashtags
def test_body_length_both_bounds():
    short = fake_post("wechat_article")
    assert "body_too_short" in codes(check_post(short, "wechat_article"))
    long = fake_post("moments")
    long.body = ["重量约 1.25 kg [F1]，" + "很轻" * 100]
    assert "body_too_long" in codes(check_post(long, "moments"))


def test_f_tags_do_not_count_toward_length():
    p = fake_post()
    before = count_chars(" ".join(p.body))
    assert count_chars(" ".join(p.body) + " [F1]") == before


def test_emoji_limit():
    p = fake_post("wechat_article")
    p.body.append("🎉🎉🎉")
    assert "emoji_count" in codes(check_post(p, "wechat_article"))
    allowed = fake_post("xiaohongshu")
    allowed.body[0] += " 😊"
    assert "emoji_count" not in codes(check_post(allowed, "xiaohongshu"))


def test_hashtags_visible_only_where_allowed():
    p = fake_post("wechat_article")
    p.body[0] += " #开学季 #轻薄本"
    assert "hashtag_not_allowed" in codes(check_post(p, "wechat_article"))
    x = fake_post("xiaohongshu")
    x.tags = ["开学季"]
    assert "hashtag_count" in codes(check_post(x, "xiaohongshu"))


# ------------------------------------------------------------------ moments / poster
def test_moments_with_three_selling_points_fails():
    p = fake_post("moments")
    p.selling_points = ["F1", "F6", "F7"]
    p.body = ["重量约 1.25 kg [F1]，电池 65 Wh [F6]，续航约 14 小时 [F7]。"]
    assert "moments_focus" in codes(check_post(p, "moments"))


def test_poster_title_and_selling_point_limits():
    p = fake_post("poster")
    p.title = "开学装备清单一台背着不累的笔记本"
    p.selling_points = ["F1", "F6", "F7", "F11"]
    cs = codes(check_post(p, "poster"))
    assert "title_too_long" in cs and "too_many_selling_points" in cs


def test_douyin_caption_limit():
    p = fake_post("douyin")
    p.images[0].caption = "这是第一张图片的说明文字，超过十二个字"
    assert "caption_too_long" in codes(check_post(p, "douyin"))


# ------------------------------------------------------------------ fake experience
def test_xhs_fake_personal_experience():
    for text in ("亲测重量约 1.25 kg [F1]", "我用了三天 [F1]", "入手两个月，说点真话", "自用体验分享"):
        p = fake_post()
        p.body[0] = text
        assert "fake_experience" in codes(check_post(p, "xiaohongshu")), text


def test_fake_experience_not_flagged_on_wechat():
    p = fake_post("wechat_article")
    p.body[0] = "很多家长会问，重量约 1.25 kg [F1] 够不够轻。"
    assert "fake_experience" not in codes(check_post(p, "wechat_article"))


# ------------------------------------------------------------------ AI tells
def test_ai_tell_phrases_and_patterns():
    for bad in ("赋能学习场景", "综上所述，值得买", "不仅仅是轻薄，更是便携", "在当今快节奏的时代"):
        p = fake_post()
        p.body[0] = bad + " 重量约 1.25 kg [F1]"
        assert "ai_tell" in codes(check_post(p, "xiaohongshu")), bad
    d = fake_post()
    d.body[0] = "重量约 1.25 kg [F1] —— 很轻"
    assert "ai_tell" in codes(check_post(d, "xiaohongshu"))


def test_exclamation_and_repeated_openings():
    p = fake_post()
    p.body = ["重量很轻 [F1]！", "重量很轻 [F1]！", "重量很轻 [F1]！", "重量很轻 [F1]！"]
    cs = codes(check_post(p, "xiaohongshu"))
    assert "ai_tell" in cs


def test_unknown_platform():
    assert check_post(fake_post(), "微博")[0].code == "unknown_platform"
