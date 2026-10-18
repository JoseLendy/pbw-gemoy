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


# ---------------------------------------------------------------------- local KB mirror (KB_BACKEND)
import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

from agent import ima_wrapper, kb_local  # noqa: E402
from agent.ima_wrapper import KB_NAME, ImaError, make_client  # noqa: E402
from agent.kb_local import HybridKB, LocalKB, build_id_map  # noqa: E402
from agent.retrieval import source_origin  # noqa: E402

MIRROR = Path(__file__).parent / "fixtures" / "p1" / "mirror"
D14 = "P1-产品参数库/01-鸿蒙电脑/DemoBook 14"
SE = "P1-产品参数库/02-MateBook-Windows/DemoBook 14 SE 版"
P4 = "P4-价格政策库（机密）"
PNG = b"\x89PNG\r\n\x1a\n"
IDS = {f"{D14}/产品事实.md": "ima-d14-facts", f"{D14}/卖点与限制.md": "ima-d14-claims",
       f"{D14}/images/hwpc_demobook-14_演示主视觉_01.png": "ima-d14-img01", f"{D14}/images": "folder_d14img"}


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    """A copy of the synthetic mirror plus a P4 folder and a statistics json that must stay hidden."""
    root = tmp_path / "kb"
    shutil.copytree(MIRROR, root)
    (root / P4).mkdir()
    (root / P4 / "演示政策.md").write_text("# 合成的机密目录（不得读取）\n", "utf-8")
    (root / "全库统计.json").write_text("{}", "utf-8")
    monkeypatch.setattr(kb_local, "IDS_PATH", tmp_path / "ima_ids.json")
    monkeypatch.setattr(kb_local, "TREE_PATH", tmp_path / "no_tree.json")
    monkeypatch.setattr(retrieval, "TEXT_CACHE", tmp_path / "text")
    monkeypatch.setattr(catalog_mod, "TEXT_CACHE", tmp_path / "csv")
    monkeypatch.setattr(catalog_mod, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(catalog_mod, "LOCAL_INDEX_PATH", tmp_path / "index_local.json")
    monkeypatch.setattr(catalog_mod, "_load_aliases", lambda: DEMO_ALIASES)
    monkeypatch.setattr(ima_wrapper, "_DEFAULT", None)
    retrieval._images.clear()
    set_current(None)
    yield root
    set_current(None)


def mirror_catalog(kb):
    c = Catalog(build_index(kb), aliases_cfg=DEMO_ALIASES, client=kb)
    set_current(c)
    return c


def test_local_lists_and_reads_by_kb_path(mirror):
    kb = LocalKB(mirror, ids=IDS)
    top = kb.list_path("")
    assert [i["title"] for i in top] == ["P1-产品参数库", "P6-营销素材库", "README.md"]
    assert top[0]["media_type"] == 99 and top[2]["media_type"] == 7
    items = {i["title"]: i for i in kb.list_path(D14)}
    assert items["images"]["media_type"] == 99 and items["images"]["media_id"] == "folder_d14img"
    assert items["产品事实.md"]["media_id"] == "ima-d14-facts"                     # known to ima
    assert items["图片索引.csv"]["media_type"] == 5
    assert items["来源清单.csv"]["media_id"] == f"local:{D14}/来源清单.csv"        # mirror-only
    imgs = kb.list_folder("local", "folder_d14img")
    assert [i["media_type"] for i in imgs] == [9, 9]
    assert "约 1.25 kg" in kb.read_text(f"{D14}/产品事实.md")
    assert kb.read_bytes(f"{D14}/images/hwpc_demobook-14_演示屏幕_02.png").startswith(PNG)
    assert kb.fetch_text("ima-d14-claims").startswith("# DemoBook 14（演示版）")
    assert kb.fetch_media(f"local:{D14}/images/hwpc_demobook-14_演示屏幕_02.png")[0] == 9
    assert kb.status()["mode"] == "本地镜像" and kb.status()["connected"] is False


def test_p4_and_excluded_paths_never_returned(mirror, tmp_path):
    tree = [{"type": "folder", "path": f"/{KB_NAME}/{P4}", "id": "folder_p4", "raw": {}},
            {"type": "file", "path": f"/{KB_NAME}/{P4}/演示政策.md", "id": "ima-p4", "raw": {}},
            {"type": "file", "path": f"/{KB_NAME}/{D14}/产品事实.md", "id": "ima-d14-facts", "raw": {}}]
    (tmp_path / "tree.json").write_text(json.dumps(tree, ensure_ascii=False), "utf-8")
    ids = build_id_map(tmp_path / "tree.json", tmp_path / "ids.json")
    assert ids == {f"{D14}/产品事实.md": "ima-d14-facts"}
    kb = LocalKB(mirror, ids={**ids, P4: "folder_p4", f"{P4}/演示政策.md": "ima-p4"})
    assert all(not i["title"].startswith("P4") and not i["title"].endswith(".json") for i in kb.list_path(""))
    assert kb.list_path(P4) == [] and kb.read_text(f"{P4}/演示政策.md") is None
    assert kb.fetch_text("ima-p4") is None and kb.fetch_text(f"local:{P4}/演示政策.md") is None
    assert kb.fetch_text("local:../kb/README.md") is None and kb.read_text("全库统计.json") is None
    with pytest.raises(ImaError):
        kb.list_folder("local", "folder_p4")
    assert kb.list_path("P6-营销素材库/04-图片/02-华为商城电脑专区素材") == []
    assert all("02-华为商城电脑专区素材" not in str(h) and P4 not in str(h) for h in kb.search("local", "演示"))


def test_local_bundle_has_the_right_images(mirror):
    kb = LocalKB(mirror, ids=IDS)
    cat = mirror_catalog(kb)
    assert cat.status == "complete" and set(cat.models) >= {"demobook-14", "demobook-14-se"}
    b = get_model_bundle("demobook-14", cat)
    assert [i.title for i in b.images] == ["hwpc_demobook-14_演示主视觉_01.png", "hwpc_demobook-14_演示屏幕_02.png"]
    assert all(i.model_id == "demobook-14" for i in b.images)
    assert "约 1.25 kg" in b.facts_text and "继续访问" not in b.facts_text
    assert b.facts_source.source_path == f"{D14}/产品事实.md" and b.facts_source.media_id == "ima-d14-facts"
    assert fetch_image_bytes(b.images[1].media_id).startswith(PNG)
    assert fetch_image_bytes("ima-d14-img01").startswith(PNG)
    assert source_origin(b.facts_source.source_path) == "本地镜像"
    se = get_model_bundle("demobook-14-se", cat)
    assert [i.model_id for i in se.images] == ["demobook-14-se"]


def test_local_three_signal_rule_rejects_sibling_image(mirror):
    cat = mirror_catalog(LocalKB(mirror, ids=IDS))
    demo, se = cat.get("demobook-14"), cat.get("demobook-14-se")
    se_img = cat.images_for("demobook-14-se")[0]
    assert image_belongs_to(se_img, se) is True
    assert image_belongs_to(se_img, demo) is False                 # slug prefix trap
    assert image_belongs_to(dataclasses.replace(se_img, model_id="demobook-14"), demo) is False


def test_local_mode_makes_zero_ima_calls(mirror, monkeypatch):
    monkeypatch.setenv("KB_BACKEND", "local")
    monkeypatch.setenv("KB_LOCAL_DIR", str(mirror))
    run = mock.Mock(side_effect=AssertionError("ima called"))
    monkeypatch.setattr(ima_wrapper.subprocess, "run", run)
    with mock.patch.object(ima_wrapper.ImaClient, "call", side_effect=AssertionError("ima called")) as call:
        cat = catalog_mod.load_catalog(refresh=True)
        b = get_model_bundle("demobook-14")
        fetch_image_bytes(b.images[0].media_id)
        assert isinstance(cat.client, LocalKB) and not isinstance(cat.client, HybridKB)
        assert cat.client.status()["mode"] == "本地镜像" and cat.client.status()["kb_name"] == KB_NAME
        assert call.call_count == 0
    assert run.call_count == 0 and cat.client.live_calls == 0


def quota_error(*a, **k):
    raise ImaError(220021, "资料获取次数已达上限", "openapi/wiki/v1/x")


def test_hybrid_falls_back_to_mirror_on_220021(mirror, tmp_path):
    ima = mock.Mock(live_calls=0)
    ima.find_kb.side_effect = ima.search.side_effect = ima.media_info.side_effect = quota_error
    kb = HybridKB(mirror, ima=ima, ids=IDS, confirm_path=tmp_path / "confirm.json")
    cat = mirror_catalog(kb)
    b = get_model_bundle("demobook-14", cat)
    assert len(b.images) == 2 and "约 1.25 kg" in b.facts_text
    fetch_image_bytes("ima-d14-img01")
    assert source_origin(b.facts_source.source_path) == "本地镜像"
    assert source_origin(f"{D14}/images/hwpc_demobook-14_演示主视觉_01.png") == "本地镜像"
    st = kb.status()
    assert st["mode"] == "ima + 本地镜像" and st["connected"] is False and "上限" in st["error"]
    assert ima.find_kb.call_count == 1                                    # startup only, not per status()
    assert all(e["origin"] == "本地镜像" for e in kb.call_log) and not any(e["ok"] for e in kb.call_log)
    assert not (tmp_path / "confirm.json").exists()                       # errors are never cached as "no"


def test_hybrid_confirms_live_and_caches_yes_no_only(mirror, tmp_path):
    ima = mock.Mock(live_calls=0)
    ima.find_kb.return_value = {"id": "kb-demo", "name": KB_NAME}
    ima.search.return_value = [{"title": "产品事实.md", "media_id": "ima-d14-facts"}]
    ima.media_info.return_value = {"media_type": 7, "url_info": {"url": "https://example.com/x?sign=s&t=1"}}
    kb = HybridKB(mirror, ima=ima, ids=IDS, confirm_path=tmp_path / "confirm.json")
    cat = mirror_catalog(kb)
    b = get_model_bundle("demobook-14", cat)
    fetch_image_bytes("ima-d14-img01")
    fetch_image_bytes(f"local:{D14}/images/hwpc_demobook-14_演示屏幕_02.png")   # not in ima: no call
    assert ima.search.call_args.args[1] == "DemoBook 14（演示版）"
    assert source_origin(b.facts_source.source_path) == "ima" and source_origin(b.claims_source.source_path) == "ima"
    assert source_origin(f"{D14}/images/hwpc_demobook-14_演示主视觉_01.png") == "ima"
    assert source_origin(f"{D14}/images/hwpc_demobook-14_演示屏幕_02.png") == "本地镜像"
    assert ima.media_info.call_count == 3 and kb.live_hits[0]["origin"] == "ima"
    assert kb.status() == {"kb_name": KB_NAME, "connected": True, "configured": kb.status()["configured"],
                           "index_status": "unknown", "error": "", "mode": "ima + 本地镜像"}
    saved = (tmp_path / "confirm.json").read_text("utf-8")
    assert "sign=" not in saved and "https" not in saved and "ima-d14" not in saved
    log = json.dumps(kb.call_log, ensure_ascii=False)
    assert "ima-d14" not in log and "kb-demo" not in log
    kb2 = HybridKB(mirror, ima=ima, ids=IDS, confirm_path=tmp_path / "confirm.json")
    kb2.confirm("ima-d14-facts")
    assert ima.media_info.call_count == 3 and kb2.origin(f"{D14}/产品事实.md") == "ima"


def test_make_client_reads_kb_backend(mirror, monkeypatch):
    monkeypatch.setenv("KB_LOCAL_DIR", str(mirror))
    monkeypatch.delenv("KB_BACKEND", raising=False)
    assert type(make_client()) is LocalKB
    assert type(make_client("ima")) is ima_wrapper.ImaClient
    assert isinstance(make_client("hybrid"), HybridKB)
    monkeypatch.setenv("KB_BACKEND", "cloud")
    with pytest.raises(ValueError):
        make_client()
