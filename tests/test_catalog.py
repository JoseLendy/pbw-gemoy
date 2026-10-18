"""Catalog build + resolver on the synthetic DemoBook tree (tests/fixtures/p1). No ima, no KB text."""
import copy

import pytest

from agent import catalog as catalog_mod
from agent.catalog import Catalog, build_index, load_catalog, set_current, tokens
from tests.fixtures.p1.fake_ima import DEMO_ALIASES, TREE, FakeIma


@pytest.fixture(autouse=True)
def _tmp_text_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "TEXT_CACHE", tmp_path / "text")


def make(tree=None, fail=None, fail_media=None, previous=None):
    fake = FakeIma(tree, fail, fail_media)
    return Catalog(build_index(fake, previous), aliases_cfg=DEMO_ALIASES, client=fake), fake


@pytest.fixture
def cat():
    return make()[0]


def test_index_built_from_targeted_listings_only(cat):
    _, fake = make()
    listed = {fid for api, fid in fake.calls if api == "get_knowledge_list"}
    assert "folder_08" not in listed and "folder_00" not in listed and "folder_p4" not in listed
    assert cat.status == "complete" and cat.unlisted == []


def test_canonical_name_comes_from_index_csv_not_folder(cat):
    m = cat.get("demobook-14")
    assert m.canonical_name == "DemoBook 14（演示版）"
    assert m.folder_name == "DemoBook 14" and "DemoBook 14" in m.aliases
    se = cat.get("demobook-14-se")
    assert se.canonical_name == "DemoBook 14 SE（演示版）" and se.folder_name == "DemoBook 14 SE 版"
    assert m.route == "harmonyos" and se.route == "windows"


def test_model_fields_from_config(cat):
    assert cat.get("demobook-14").siblings == ["demobook-14-se"]
    assert cat.get("demobook-14-se").needs_human == ["cpu"]
    assert [s.model_id for s in cat.siblings("demobook-14")] == ["demobook-14-se"]


def test_images_counted_per_model_incl_mall_folder(cat):
    ids = [i.media_id for i in cat.images_for("demobook-14")]
    assert ids == ["img-d14-01", "img-d14-02", "img-d14-03", "img-d14-04", "img-d14-v05", "img-d14-v06"]
    assert [i.media_id for i in cat.images_for("demobook-14-se")] == ["img-se-01", "img-se-02"]
    first = cat.images_for("demobook-14")[0]
    assert first.caption == "演示主视觉图" and first.role == "main" and first.model_id == "demobook-14"


@pytest.mark.parametrize("q,status,expect", [
    ("DemoBook 14（演示版）", "resolved", "demobook-14"),
    ("演示本 14", "resolved", "demobook-14"),
    ("DemoBook 14 SE", "resolved", "demobook-14-se"),
    ("demobook14se", "resolved", "demobook-14-se"),
    ("ＤｅｍｏＢｏｏｋ　１４　ＳＥ", "resolved", "demobook-14-se"),
    ("HUAWEI DemoBook 14 SE 版", "resolved", "demobook-14-se"),
    ("Demo 商用台式机 Pro", "text_only", "txt-demo-商用台式机-pro"),
])
def test_resolve_single(cat, q, status, expect):
    r = cat.resolve(q)
    assert r.status == status and r.model.model_id == expect


def test_resolve_ambiguous_prefix_trap(cat):
    r = cat.resolve("DemoBook 14")       # tokens are a subset of both models: never pick one
    assert r.status == "ambiguous" and r.model is None
    assert {c.model_id for c in r.candidates} == {"demobook-14", "demobook-14-se"}
    assert r.candidates[0].model_id == "demobook-14"     # exact folder-name match ranks first


def test_resolve_ambiguous_text_only_group(cat):
    r = cat.resolve("商用台式机")
    assert r.status == "ambiguous" and len(r.candidates) == 2
    assert all(c.route == "text_only" for c in r.candidates)


def test_resolve_not_found_gives_three_nearest(cat):
    r = cat.resolve("ThinkPad X1 Carbon")
    assert r.status == "not_found" and r.model is None and len(r.candidates) == 3
    r2 = cat.resolve("DemoBook 16")
    assert r2.status == "not_found" and r2.candidates[0].model_id.startswith("demobook-14")


def test_resolve_never_substring(cat):
    # "Demo" is a substring of every name but is not a token of the image models' names
    assert cat.resolve("Demo").status in ("ambiguous", "not_found")
    assert cat.resolve("Book 14").status == "not_found"


def test_tokens_normalise():
    assert tokens("HUAWEI MateBook 14（鸿蒙版）") == {"matebook", "14", "鸿蒙"}
    assert tokens("MateBook 14 HarmonyOS") == tokens("华为MateBook 14 鸿蒙版")
    assert tokens("MateBook 14 32GB") == {"matebook", "14"}


def test_folder_with_two_slugs_fails_closed():
    tree = copy.deepcopy(TREE)
    tree["folders"]["folder_d14_img"].append(
        {"media_id": "img-trap", "title": "hwpc_demobook-14-se_误放_09.png", "media_type": 9})
    cat, _ = make(tree)
    assert cat.images_for("demobook-14") == []
    assert cat.get("demobook-14").has_images is False
    assert len(cat.images_for("demobook-14-se")) == 2
    assert any("多个" in i["issue"] for i in cat.index["issues"])


def test_unlistable_folder_marks_partial():
    cat, _ = make(fail={"folder_d14_mall": 220021})
    assert cat.status == "partial" and any("商城款式图片" in p for p in cat.unlisted)
    assert len(cat.images_for("demobook-14")) == 4


def test_load_catalog_persists_and_reads_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_mod, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(catalog_mod, "_load_aliases", lambda: DEMO_ALIASES)
    set_current(None)
    fake = FakeIma()
    c1 = load_catalog(fake, refresh=True)
    assert (tmp_path / "index.json").exists() and fake.index_status == "complete"
    set_current(None)
    fake2 = FakeIma()
    c2 = load_catalog(fake2)
    assert fake2.calls == [] and set(c2.models) == set(c1.models)
    set_current(None)


def test_unreadable_image_index_marks_partial_and_drops_model():
    cat, _ = make(fail_media={"csv-se": 220021})
    assert cat.status == "partial"
    assert any(p.endswith("DemoBook 14 SE 版/images/图片索引.csv") for p in cat.unlisted)
    assert "demobook-14-se" not in cat.models                # canonical name unknown: never guessed
    assert len(cat.images_for("demobook-14")) == 6


def test_unreadable_image_index_uses_previous_index_rows(tmp_path, monkeypatch):
    good, _ = make()
    monkeypatch.setattr(catalog_mod, "TEXT_CACHE", tmp_path / "empty")   # text cache gone too
    cat, fake = make(fail_media={"csv-se": 220021}, previous=good.index)
    assert cat.status == "stale" and cat.unlisted == []
    assert cat.get("demobook-14-se").canonical_name == "DemoBook 14 SE（演示版）"
    assert len(cat.images_for("demobook-14-se")) == 2


def test_image_index_text_is_disk_cached():
    _, fake = make()
    _, fake2 = make()
    assert any(api == "get_media_info" for api, _ in fake.calls)
    assert not any(api == "get_media_info" for api, _ in fake2.calls)
