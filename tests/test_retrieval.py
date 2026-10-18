"""Bundle + image rule on the synthetic DemoBook tree. No ima, no KB text."""
import dataclasses

import pytest

from agent import catalog as catalog_mod
from agent import retrieval
from agent.catalog import Catalog, build_index, set_current
from agent.retrieval import fetch_image_bytes, get_model_bundle, image_belongs_to, strip_banner
from agent.schemas import ImageRef
from tests.fixtures.p1.fake_ima import DEMO_ALIASES, FakeIma


@pytest.fixture
def cat(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval, "TEXT_CACHE", tmp_path / "text")
    monkeypatch.setattr(catalog_mod, "TEXT_CACHE", tmp_path / "csv")
    retrieval._images.clear()
    fake = FakeIma()
    c = Catalog(build_index(fake), aliases_cfg=DEMO_ALIASES, client=fake)
    set_current(c)
    yield c
    set_current(None)


def test_bundle_contents(cat):
    b = get_model_bundle("demobook-14", cat)
    assert b.model.model_id == "demobook-14" and b.index_status == "complete"
    assert "约 1.25 kg" in b.facts_text and "即将离开" not in b.facts_text and "继续访问" not in b.facts_text
    assert b.claims_text.startswith("# DemoBook 14（演示版） - 卖点与限制")
    assert len(b.images) == 6 and all(i.model_id == "demobook-14" for i in b.images)
    assert b.facts_source.title == "产品事实.md"
    assert b.facts_source.source_path == "P1-产品参数库/01-鸿蒙电脑/DemoBook 14/产品事实.md"
    assert {s.title for s in b.sources} == {"产品事实.md", "卖点与限制.md"}
    assert not any("价格" in s.source_path for s in b.sources)


def test_bundle_text_is_cached(cat):
    get_model_bundle("demobook-14", cat)
    n = len(cat.client.calls)
    get_model_bundle("demobook-14", cat)
    assert len(cat.client.calls) == n


def test_text_only_bundle(cat):
    b = get_model_bundle("txt-demo-商用台式机-pro", cat)
    assert b.images == [] and b.model.has_images is False and "演示用商用台式机" in b.facts_text
    assert b.facts_source.source_path.endswith("商用演示电脑/21-Demo 商用台式机 Pro.md")


def test_image_rule_rejects_sibling_image(cat):
    demo, se = cat.get("demobook-14"), cat.get("demobook-14-se")
    se_img = cat.images_for("demobook-14-se")[0]
    assert image_belongs_to(se_img, se) is True
    assert image_belongs_to(se_img, demo) is False          # slug demobook-14-se != demobook-14
    own = cat.images_for("demobook-14")[0]
    assert image_belongs_to(own, demo) is True and image_belongs_to(own, se) is False


def test_image_rule_rejects_joint_table_only_image(cat):
    demo = cat.get("demobook-14")
    ghost = ImageRef(media_id="img-joint-only-07", title="hwpc_demobook-14_演示_07.png",
                     source_path="P1-产品参数库/01-鸿蒙电脑/DemoBook 14/images", model_id="demobook-14")
    assert image_belongs_to(ghost, demo) is False


def test_image_rule_rejects_tampered_refs(cat):
    demo = cat.get("demobook-14")
    own = cat.images_for("demobook-14")[0]
    assert image_belongs_to(dataclasses.replace(own, source_path="P1-产品参数库/00-全库横向索引"), demo) is False
    assert image_belongs_to(dataclasses.replace(own, model_id="demobook-14-se"), demo) is False
    assert image_belongs_to(own, cat.get("txt-demo-商用台式机-pro")) is False


def test_image_rule_requires_index_row(cat):
    cat.entries["demobook-14"]["csv"]["P1-产品参数库/01-鸿蒙电脑/DemoBook 14/images"].pop(
        "hwpc_demobook-14_演示屏幕_04.jpg")
    ids = [i.media_id for i in cat.images_for("demobook-14")]
    assert "img-d14-04" not in ids and len(ids) == 5


def test_image_rule_rejects_wrong_model_in_index_row(cat):
    rows = cat.entries["demobook-14"]["csv"]["P1-产品参数库/01-鸿蒙电脑/DemoBook 14/images"]
    rows["hwpc_demobook-14_演示多彩配色_02.png"]["model"] = "DemoBook 14 SE（演示版）"
    assert "img-d14-02" not in [i.media_id for i in cat.images_for("demobook-14")]


def test_strip_banner_only_at_end():
    text = "## 规格\n\n重量\n\n约 1 kg\n\n即将离开demo.example.com\n\n演示提示\n\n继续访问\n\n取消\n"
    assert strip_banner(text) == "## 规格\n\n重量\n\n约 1 kg\n"
    plain = "## 规格\n\n即将离开这里不是域名\n"
    assert strip_banner(plain) == plain


def test_fetch_image_bytes_lru_and_guard(cat):
    assert fetch_image_bytes("img-d14-01") == b"bytes:img-d14-01"
    n = len(cat.client.calls)
    fetch_image_bytes("img-d14-01")
    assert len(cat.client.calls) == n                        # served from the in-memory LRU
    with pytest.raises(ValueError):
        fetch_image_bytes("md-d14-facts")                    # not a listed image: never fetched
