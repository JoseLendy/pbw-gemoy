"""Image plan per platform, using the shared fakes (synthetic DemoBook)."""
import dataclasses

import pytest

from agent.platform_plan import (POSTER_NO_IMAGE_NOTE, SHORTAGE_NOTE, TEXT_ONLY_NOTE, image_role,
                                 plan_images)
from agent.schemas import PLATFORM_IMAGE_RANGE
from tests.fakes import fake_bundle, fake_strategy


@pytest.mark.parametrize("platform,n_images,expected", [
    ("wechat_article", 6, 3), ("xiaohongshu", 6, 6), ("xiaohongshu", 4, 4), ("moments", 6, 2),
    ("poster", 6, 1), ("douyin", 6, 6),
])
def test_counts_per_platform(platform, n_images, expected):
    plan = plan_images(fake_bundle(n_images=n_images), platform, fake_strategy())
    assert len(plan.items) == expected and plan.shortage is False
    lo, hi = PLATFORM_IMAGE_RANGE[platform]
    assert lo <= len(plan.items) <= hi
    assert len({p.image.media_id for p in plan.items}) == len(plan.items)


def test_shortage_uses_what_exists_never_pads():
    b = fake_bundle(n_images=2)
    plan = plan_images(b, "xiaohongshu", fake_strategy())
    assert len(plan.items) == 2 and plan.shortage is True and plan.note == SHORTAGE_NOTE
    assert {p.image.model_id for p in plan.items} == {"demobook-14"}


def test_text_only_model_gets_empty_plan():
    plan = plan_images(fake_bundle("demo-desk-pro"), "wechat_article", fake_strategy())
    assert plan.items == [] and plan.shortage is True and plan.note == TEXT_ONLY_NOTE


def test_poster_without_image_is_refused():
    plan = plan_images(fake_bundle("demo-desk-pro"), "poster", fake_strategy())
    assert plan.items == [] and plan.shortage is True and plan.note == POSTER_NO_IMAGE_NOTE


def test_poster_uses_main_visual():
    b = fake_bundle()
    b.images = list(reversed(b.images))
    plan = plan_images(b, "poster", fake_strategy())
    assert plan.items[0].image.role == "main" and plan.items[0].position == "海报主视觉"


def test_moments_main_first_then_scene():
    b = fake_bundle()
    b.images = [i for i in b.images if i.role != "main"] + [i for i in b.images if i.role == "main"]
    plan = plan_images(b, "moments", fake_strategy())
    assert [p.image.role for p in plan.items] == ["main", "scene"]
    assert [p.position for p in plan.items] == ["配图第1张", "配图第2张"]


def test_positions_are_chinese_and_lead_image_first():
    plan = plan_images(fake_bundle(), "wechat_article", fake_strategy())
    assert plan.items[0].position == "标题下方" and plan.items[0].image.role == "main"
    for p in plan.items:
        assert p.position == "标题下方" or p.position == "文末" or p.position.startswith("第")


def test_captions_come_from_kb_only():
    b = fake_bundle()
    b.images = [dataclasses.replace(b.images[0], caption="")] + b.images[1:]
    plan = plan_images(b, "wechat_article", fake_strategy())
    caps = {p.image.media_id: p.caption for p in plan.items}
    assert caps[b.images[0].media_id] == "示例图"            # scene words from the KB file name
    assert all(caps[i.media_id] == i.caption for i in b.images[1:] if i.media_id in caps)


def test_no_image_next_to_performance_paragraph():
    s = fake_strategy()
    s.analysis.categories = ["performance", "design", "display"]
    plan = plan_images(fake_bundle(), "xiaohongshu", s)
    assert "第1段后" not in [p.position for p in plan.items]


@pytest.mark.parametrize("title,caption,role", [
    ("hwpc_x_高质感主视觉_01.png", "", "main"),
    ("hwpc_x_办公场景_02.png", "", "scene"),
    ("hwpc_x_精致产品细节_03.png", "", "detail"),
    ("hwpc_x_多彩配色外观_04.png", "", "color"),
    ("hwpc_x_高清护眼屏幕_05.png", "", "unknown"),
    ("hwpc_x_图_06.png", "使用场景示意", "scene"),
])
def test_image_role(title, caption, role):
    assert image_role(title, caption) == role
