"""Formatter tests on fakes only."""
from __future__ import annotations

import re

from agent.formatter import render_download, render_publishable, render_report, strip_fact_tags
from agent.pipeline import Deps, run
from agent.schemas import CheckIssue, CheckReport, SECTION_HEADINGS


TEXT = "一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书"


def _result(platform_text="发小红书", **kw):
    return run(TEXT.replace("发小红书", platform_text), deps=Deps.fake(), **kw)


def test_headings_verbatim_and_ordered():
    md = render_report(_result())
    pos = [md.index(f"## {h}") for h in SECTION_HEADINGS]
    assert pos == sorted(pos)
    assert "## 四、核验结果" in md
    for f in ("目标人群", "使用场景", "用户问题", "内容目标", "平台", "产品型号", "事实点", "资料标题", "图片来源",
              "标题", "导语", "正文", "行动引导", "平台标签", "图片名称", "来源", "插入位置", "图片说明",
              "产品事实", "图片型号", "合规", "待确认信息"):
        assert f in md, f


def test_no_fact_tags_in_publishable():
    for pt in ("发小红书", "发朋友圈", "发公众号"):
        r = _result(pt)
        assert "[F" in r.post.all_text()           # tags kept on the Post
        assert not re.search(r"\[F\d+\]", render_publishable(r.post))


def test_hashtags_only_on_xiaohongshu_and_douyin():
    for pt, expect in (("发小红书", True), ("发抖音", True), ("发朋友圈", False), ("发公众号", False)):
        r = _result(pt)
        assert r.post.tags, pt
        assert ("#" in render_publishable(r.post)) is expect, pt
        assert "平台标签" in render_report(r)     # always listed in section 三


def test_no_media_ids_or_secrets_anywhere():
    r = _result()
    ids = {it.image.media_id for it in r.plan.items} | {s.media_id for s in r.sources}
    for text in (render_report(r), render_publishable(r.post), render_download(r)):
        for mid in ids:
            assert mid not in text
        assert "fake-img" not in text and "fake-demobook" not in text
        assert "IMA_OPENAPI" not in text


def test_sources_shown_by_title_and_path():
    md = render_report(_result())
    assert "产品事实.md" in md and "P1-产品参数库/01-鸿蒙电脑/DemoBook 14" in md


def test_issues_rendered_with_marks():
    r = _result()
    r.report = CheckReport([CheckIssue("8B", "error", "banned_word", "含绝对化用语", field="body[0]", span="最轻"),
                            CheckIssue("8C", "warn", "length", "篇幅偏短")])
    r.pending = ["未通过核验：含绝对化用语"]
    md = render_report(r)
    assert "❌ [8B] 含绝对化用语" in md and "⚠️ [8C] 篇幅偏短" in md and "⚠️ 未通过核验" in md
    assert "✅" in md   # 8A still passes


def test_strip_fact_tags_local_fallback():
    assert strip_fact_tags("重量约 1.25 kg [F1]，好带。") == "重量约 1.25 kg，好带。"


def test_download_has_article_and_sources_no_quotes_outside_table():
    r = _result()
    md = render_download(r)
    assert md.startswith("# ")
    assert "资料来源" in md and "配图" in md
    assert "hwpc_demobook-14_示例图_01.png" in md
    assert "fake-img" not in md
