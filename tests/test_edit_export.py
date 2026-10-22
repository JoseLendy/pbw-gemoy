"""C: inline edit check (deterministic, no LLM) and the export (copy text, publish zip). Synthetic DemoBook."""
from __future__ import annotations

import dataclasses
import io
import json
import time
import zipfile

import pytest
from PIL import Image

from agent.edit_check import check_edit
from agent.export import article_md, publish_zip, wechat_text
from agent.formatter import render_publishable
from agent.pipeline import Deps, run_from_card
from agent.recommend.store_data import default_card, reload
from agent.runs import log_human_edit
from agent.schemas import Post, PostImage, RunResult

DAY = "2026-10-23"
NAME = "DemoBook 14（演示版）"


@pytest.fixture
def result():
    reload()
    card = dataclasses.replace(default_card("S03", DAY), model_id="demobook-14", display_name=NAME)
    r = run_from_card(card, Deps.fake())
    assert isinstance(r, RunResult)
    imgs = [PostImage(p.image.media_id, p.position, p.caption) for p in r.plan.items[:2]]
    r.post = Post("moments", "", "", [f"{NAME}重量约 1.25 kg [F1]，{r.task.landmark}的门店可以上手掂一掂。"],
                  "想上手试试，私信我或到店找我。", ["朋友圈"], ["F1"], imgs)
    return r


def _text(r):
    return render_publishable(r.post)


def test_the_unedited_post_passes(result):
    chk = check_edit(_text(result), result)
    assert chk.passed, [(i.code, i.message) for i in chk.issues]


def test_a_harmless_personal_sentence_passes(result):
    chk = check_edit(_text(result).replace("掂一掂。", "掂一掂。周末店里人少一些，可以慢慢试。"), result)
    assert chk.passed, [(i.code, i.message) for i in chk.issues]


def test_adding_a_discount_fails(result):
    chk = check_edit(_text(result).replace("掂一掂。", "掂一掂，现在立减500。"), result)
    assert not chk.passed and any(f.sentence and "立减500" in f.sentence for f in chk.failing)


def test_changing_a_spec_value_fails(result):
    chk = check_edit(_text(result).replace("1.25 kg", "1.2 kg"), result)
    assert not chk.passed and any(i.code == "unsupported_number" for i in chk.issues)
    assert any("1.2 kg" in f.sentence for f in chk.failing)


def test_deleting_the_product_name_fails(result):
    chk = check_edit(_text(result).replace(NAME, "这台"), result)
    assert not chk.passed and any(i.code == "product_unnamed" for i in chk.issues)


def test_adding_a_name_or_too_many_paragraphs_fails(result):
    assert not check_edit(_text(result) + "\n\n小王", result).passed
    many = "\n\n".join([f"{NAME}重量约 1.25 kg。", "第二段。", "第三段。", "第四段。", "到店找我。"])
    chk = check_edit(many, result)
    assert any(i.code == "paragraph_count" and i.severity == "error" for i in chk.issues)


def test_check_is_fast_and_takes_no_llm(result):
    import inspect
    assert "llm" not in inspect.signature(check_edit).parameters
    t0 = time.perf_counter()
    check_edit(_text(result), result)
    assert time.perf_counter() - t0 < 2.0


def test_human_edit_is_logged_with_both_texts(result, tmp_path):
    card = default_card("S03", DAY)
    p = log_human_edit(card, "朋友圈", "原文", "改后", runs_dir=tmp_path)
    rec = json.loads(p.read_text("utf-8"))
    assert rec["kind"] == "human_edit" and rec["edited_by_human"] is True
    assert (rec["original_text"], rec["edited_text"]) == ("原文", "改后")


# ---------------------------------------------------------------- export
def _png(color):
    b = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(b, "PNG")
    return b.getvalue()


def test_copy_text_merges_the_title_and_drops_tags():
    p = Post("xiaohongshu", "演示标题", "导语一句。", ["正文 1.25 kg [F1]。"], "到店找我。", ["演示", "笔记本"], ["F1"], [])
    t = wechat_text(p)
    assert t.startswith("演示标题｜导语一句。") and "[F" not in t and t.endswith("#演示 #笔记本")


def test_zip_holds_the_copied_text_and_images_in_posting_order(result):
    colors = {im.media_id: c for im, c in zip(result.post.images, ("red", "blue"))}
    name, data = publish_zip(result.post, "S03", DAY, lambda mid: _png(colors[mid]))
    assert name == f"S03-{DAY}-朋友圈.zip"
    z = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(z.namelist()) == ["1.jpg", "2.jpg", "文案.txt"]
    assert z.read("文案.txt").decode("utf-8") == wechat_text(result.post)
    first = Image.open(io.BytesIO(z.read("1.jpg"))).convert("RGB").getpixel((5, 5))
    second = Image.open(io.BytesIO(z.read("2.jpg"))).convert("RGB").getpixel((5, 5))
    assert first[0] > 200 and second[2] > 200                    # red first, blue second: posting order


def test_edited_text_is_what_gets_exported(result):
    edited = _text(result).replace("掂一掂。", "掂一掂。周末店里人少一些，可以慢慢试。")
    chk = check_edit(edited, result)
    assert chk.passed
    _, data = publish_zip(chk.post, "S03", DAY, lambda mid: _png("red"), text=wechat_text(chk.post))
    txt = zipfile.ZipFile(io.BytesIO(data)).read("文案.txt").decode("utf-8")
    assert "周末店里人少一些" in txt and "[F" not in txt and txt == wechat_text(chk.post)


def test_wechat_article_zip_has_a_markdown_article_with_headings():
    p = Post("wechat_article", "演示标题", "导语。", ["续航：演示正文。", "第二段。"], "到店找我。", ["演示"], [],
             [PostImage("m1", "标题下方", "图"), PostImage("m2", "第1段后", "图")])
    _, data = publish_zip(p, "S03", DAY, lambda mid: _png("red"))
    z = zipfile.ZipFile(io.BytesIO(data))
    md = z.read("文章.md").decode("utf-8")
    assert md.startswith("# 演示标题") and "## 续航" in md and md.index("![](1.jpg)") < md.index("## 续航")
    assert md == article_md(p)
