"""8C conformance + image plan checks (agent/checks/conformance.py)."""
from __future__ import annotations

from agent.checks.conformance import check_conformance
from agent.schemas import PLATFORM_IMAGE_RANGE, PostImage
from tests.fakes import fake_plan, fake_post


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def test_fake_posts_conform():
    for p in ("xiaohongshu", "wechat_article", "moments"):
        r = check_conformance(fake_post(p), p, fake_plan(p))
        assert codes(r, "error") == set(), [(i.code, i.message) for i in r.issues]


def test_calls_platform_rules():
    p = fake_post()
    p.title = "这是一个非常长的小红书标题超过正常长度也需要被检查出来"
    p.body[0] = "赋能学习"
    assert {"ai_tell"} <= codes(check_conformance(p, "xiaohongshu", fake_plan()))


def test_image_not_in_plan():
    p = fake_post()
    p.images.append(PostImage("fake-img-demobook-14-se-01", "文末", "相近型号的图"))
    r = check_conformance(p, "xiaohongshu", fake_plan())
    assert "image_not_in_plan" in codes(r, "error")
    assert any(i.field == f"images[{len(p.images) - 1}]" for i in r.issues if i.code == "image_not_in_plan")


def test_image_count_above_max():
    p = fake_post("moments")
    plan = fake_plan("xiaohongshu")          # 6 images
    p.images = [PostImage(i.image.media_id, i.position, i.caption) for i in plan.items]
    assert "image_count" in codes(check_conformance(p, "moments", plan), "error")


def test_image_count_below_min_without_shortage():
    p = fake_post()
    p.images = p.images[:2]
    assert "image_count" in codes(check_conformance(p, "xiaohongshu", fake_plan()), "error")


def test_image_shortage_is_warn_only():
    plan = fake_plan()
    plan.items = plan.items[:2]
    plan.shortage = True
    p = fake_post()
    p.images = p.images[:2]
    r = check_conformance(p, "xiaohongshu", plan)
    assert "image_shortage" in codes(r, "warn")
    assert codes(r, "error") == set()


def test_shortage_does_not_excuse_too_many_images():
    plan = fake_plan()
    plan.shortage = True
    p = fake_post("douyin")
    assert len(p.images) <= PLATFORM_IMAGE_RANGE["douyin"][1]
    extra = fake_plan("douyin")
    p.images = [PostImage(i.image.media_id, i.position, "教室") for i in extra.items] * 2
    assert "image_count" in codes(check_conformance(p, "douyin", plan), "error")


def test_plan_platform_mismatch():
    assert "plan_platform" in codes(check_conformance(fake_post("moments"), "moments", fake_plan("xiaohongshu")))


def test_missing_plan():
    assert "plan_missing" in codes(check_conformance(fake_post(), "xiaohongshu", None))
