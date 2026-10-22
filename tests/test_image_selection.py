"""Step 6 image choice: no picture twice in a post (same picture saved as two files), denylisted images never
planned, and images that fit the post's selling point preferred. Synthetic images only (drawn here)."""
from __future__ import annotations

import dataclasses

import pytest
from PIL import Image, ImageDraw

from agent import image_filter
from agent.platform_plan import plan_images
from tests.fakes import fake_bundle, fake_strategy

SRC = "P1-产品参数库/01-鸿蒙电脑/DemoBook 14/images"


def _draw(path, shape: str, fmt: str, size=(320, 240)):
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    if shape == "laptop":
        d.rectangle([60, 40, 260, 170], fill="black")
        d.polygon([(40, 180), (280, 180), (300, 210), (20, 210)], fill="gray")
    elif shape == "circle":
        d.ellipse([100, 60, 220, 180], fill="green")
    else:
        d.rectangle([10, 10, 150, 230], fill="orange")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, fmt)


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr(image_filter, "_denied_hashes", lambda: frozenset())
    image_filter.clear_cache()
    yield tmp_path
    image_filter.clear_cache()


def _bundle(mirror, specs):
    """specs: [(title, caption, role, shape, fmt)] -> a DemoBook bundle whose images exist in the mirror."""
    b = fake_bundle()
    imgs = []
    for i, (title, caption, role, shape, fmt) in enumerate(specs, start=1):
        _draw(mirror / SRC / title, shape, fmt)
        imgs.append(dataclasses.replace(b.images[0], media_id=f"fake-img-sel-{i:02d}", title=title,
                                        caption=caption, role=role, source_path=SRC))
    b.images = imgs
    return b


def test_same_picture_saved_twice_is_planned_once(mirror):
    b = _bundle(mirror, [("hwpc_demobook-14_主视觉_01.png", "DemoBook KV", "main", "laptop", "PNG"),
                         ("hwpc_demobook-14_主视觉_02.jpg", "DemoBook KV", "main", "laptop", "JPEG"),
                         ("hwpc_demobook-14_接口细节_03.png", "接口细节", "detail", "circle", "PNG")])
    plan = plan_images(b, "moments", fake_strategy())
    ids = [p.image.media_id for p in plan.items]
    assert not {"fake-img-sel-01", "fake-img-sel-02"} <= set(ids), ids
    assert len(ids) == len(set(ids))


def test_dedupe_applies_to_every_platform(mirror):
    b = _bundle(mirror, [("hwpc_demobook-14_主视觉_01.png", "KV", "main", "laptop", "PNG"),
                         ("hwpc_demobook-14_主视觉_02.jpg", "KV", "main", "laptop", "JPEG"),
                         ("hwpc_demobook-14_接口细节_03.png", "接口细节", "detail", "circle", "PNG"),
                         ("hwpc_demobook-14_场景_04.png", "场景", "scene", "bar", "PNG")])
    plan = plan_images(b, "xiaohongshu", fake_strategy())
    ids = [p.image.media_id for p in plan.items]
    assert not {"fake-img-sel-01", "fake-img-sel-02"} <= set(ids), ids


def test_denylisted_image_is_never_planned(mirror, monkeypatch):
    b = _bundle(mirror, [("hwpc_demobook-14_主视觉_01.png", "KV", "main", "laptop", "PNG"),
                         ("hwpc_demobook-14_接口细节_02.png", "接口细节", "detail", "circle", "PNG")])
    monkeypatch.setattr(image_filter, "_denied_hashes",
                        lambda: frozenset({image_filter.media_hash("fake-img-sel-01")}))
    for platform in ("moments", "xiaohongshu", "poster"):
        plan = plan_images(b, platform, fake_strategy())
        assert "fake-img-sel-01" not in [p.image.media_id for p in plan.items], platform


def test_denylist_config_holds_hashes_only():
    """The committed denylist never contains a raw media id, a file name or a caption."""
    import yaml
    from agent.checks import CONFIG_DIR
    data = yaml.safe_load((CONFIG_DIR / "image_denylist.yaml").read_text("utf-8")) or {}
    rows = data.get("images") or []
    assert rows, "the denylist must list the known bad images"
    for row in rows:
        assert set(row) <= {"id_sha256", "reason"}
        assert len(row["id_sha256"]) == 64 and int(row["id_sha256"], 16) >= 0
        assert not any(s in row.get("reason", "") for s in ("img_", "hwpc_", "vmall_", ".jpg", ".png"))


def test_moments_prefers_the_image_that_fits_the_selling_point(mirror):
    b = _bundle(mirror, [("hwpc_demobook-14_多彩配色外观_01.png", "DemoBook 颜色", "color", "laptop", "PNG"),
                         ("hwpc_demobook-14_舒适键盘细节_02.png", "键盘细节", "detail", "circle", "PNG"),
                         ("hwpc_demobook-14_多彩配色外观_03.png", "DemoBook 颜色", "color", "bar", "PNG")])
    plan = plan_images(b, "moments", fake_strategy(), focus=["design keyboard 演示款键盘"])
    assert [p.image.media_id for p in plan.items] == ["fake-img-sel-02"]


def test_no_fitting_image_gives_one_neutral_product_image(mirror):
    """A fingerprint-button post must not get two colour/fashion photos: one neutral image instead."""
    b = _bundle(mirror, [("hwpc_demobook-14_多彩配色外观_01.png", "DemoBook 颜色", "color", "laptop", "PNG"),
                         ("hwpc_demobook-14_多彩配色外观_02.png", "DemoBook 颜色", "color", "circle", "PNG"),
                         ("hwpc_demobook-14_轻薄机身细节_03.png", "轻薄机身细节", "detail", "bar", "PNG")])
    plan = plan_images(b, "moments", fake_strategy(), focus=["security power_button 演示款电源键识别"])
    assert [p.image.media_id for p in plan.items] == ["fake-img-sel-03"]


def test_without_focus_moments_planning_is_unchanged(mirror):
    b = _bundle(mirror, [("hwpc_demobook-14_主视觉_01.png", "KV", "main", "laptop", "PNG"),
                         ("hwpc_demobook-14_场景_02.png", "场景", "scene", "circle", "PNG"),
                         ("hwpc_demobook-14_接口细节_03.png", "接口细节", "detail", "bar", "PNG")])
    plan = plan_images(b, "moments", fake_strategy())
    assert [p.image.media_id for p in plan.items] == ["fake-img-sel-01", "fake-img-sel-02"]


def test_missing_mirror_file_never_breaks_planning(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_LOCAL_DIR", str(tmp_path / "nowhere"))
    image_filter.clear_cache()
    plan = plan_images(fake_bundle(), "moments", fake_strategy())
    assert plan.items


def test_a_large_trackpad_is_not_a_body_size_fact(mirror):
    """A trackpad fact that mentions 尺寸 must not pull in a thin-body photo."""
    b = _bundle(mirror, [("hwpc_demobook-14_主视觉_01.png", "KV", "main", "laptop", "PNG"),
                         ("hwpc_demobook-14_轻薄机身细节_02.png", "轻薄机身细节", "detail", "circle", "PNG")])
    plan = plan_images(b, "moments", fake_strategy(), focus=["design spec_1 演示触控板尺寸加大"])
    assert [p.image.media_id for p in plan.items] == ["fake-img-sel-01"]
