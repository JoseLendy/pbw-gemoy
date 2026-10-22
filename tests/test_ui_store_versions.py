"""Store tab: platform versions (F), stored results first (D), inline edit + export gating (C). Fakes only."""
from __future__ import annotations

import dataclasses

import pytest

from agent import ui_data
from agent.export import wechat_text
from agent.pipeline import Deps, run_from_card
from agent.schemas import Post, RunResult
from ui import store_tab

PROGRESS, PLATFORM, EDIT_ACTIONS, EDIT_STATUS, COPY, ZIP, FINAL = range(24, 31)
NAME = "DemoBook 14（演示版）"


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(ui_data, "prepared_post", lambda *a, **k: None)
    monkeypatch.setattr(ui_data, "stored_version", lambda *a, **k: None)
    marks = []
    monkeypatch.setattr(ui_data, "mark_published", lambda *a, **k: marks.append(a))
    monkeypatch.setattr(ui_data, "log_human_edit", lambda *a, **k: marks.append(("edit",) + a))
    s = store_tab.fresh_session()
    store_tab._load_store(s, "S03")
    s["_marks"] = marks
    return s


def _with_result(s):
    card, key = store_tab._current_card(s)
    demo = dataclasses.replace(card, model_id="demobook-14", display_name=NAME)
    r = run_from_card(demo, Deps.fake())
    assert isinstance(r, RunResult)
    r.post = Post("moments", "", "", [f"{NAME}重量约 1.25 kg [F1]，{r.task.landmark}的门店可以上手掂一掂。"],
                  "想上手试试，私信我或到店找我。", ["朋友圈"], ["F1"], r.post.images[:1])
    s["results"][key] = r
    return key, r


def test_opens_on_moments_with_the_weekly_progress_line(session):
    out = store_tab._render(session)
    assert out[PLATFORM]["value"] == "朋友圈"
    assert "本周：朋友圈" in out[PROGRESS] and "今天建议发：" in out[PROGRESS]


def test_other_platforms_are_manager_only_for_staff(session):
    out, *_ = (store_tab.on_platform("小红书", session),)
    assert "由店长发布" in out[0] and out[1]["visible"] is False
    out = store_tab.on_role("店长", session)
    assert "由店长发布" not in out[0] and out[1]["visible"] is True
    out = store_tab.on_platform("公众号", session)
    assert out[1]["value"] == "生成公众号文章"


def test_a_stored_version_is_shown_with_its_generation_time(session, monkeypatch):
    card, key = store_tab._current_card(session)
    demo = dataclasses.replace(card, model_id="demobook-14", display_name=NAME)
    r = run_from_card(demo, Deps.fake())
    payload = {"status": "RunResult", "result": dataclasses.asdict(r), "timestamp": "2026-10-23T00:12:00+00:00"}
    monkeypatch.setattr(ui_data, "stored_version", lambda c, p=None: payload if c.platform == "小红书" else None)
    store_tab.on_role("店长", session)
    out = store_tab.on_platform("小红书", session)
    assert "生成于 10-23 08:12" in out[0] and out[1]["value"] == "重新生成"


def test_edit_flow_blocks_export_until_checked_and_shows_failures(session):
    key, r = _with_result(session)
    original = store_tab.render_publishable(r.post)
    status, copy_u, zip_u, _ = store_tab.on_text_input(original.replace("1.25 kg", "1.2 kg"), session)
    assert "未检查" in status and copy_u["interactive"] is False and zip_u["interactive"] is False
    out = store_tab.on_check_save(original.replace("1.25 kg", "1.2 kg"), session)
    assert "未通过核验" in out[EDIT_STATUS] and "1.2 kg" in out[EDIT_STATUS]
    assert out[COPY]["interactive"] is False and out[ZIP]["interactive"] is False
    assert store_tab.on_export_zip(session) is None


def test_a_passing_edit_is_saved_used_for_copy_and_logged(session):
    key, r = _with_result(session)
    edited = store_tab.render_publishable(r.post).replace("掂一掂。", "掂一掂。周末店里人少一些。")
    out = store_tab.on_check_save(edited, session)
    assert "已修改·已核验" in out[EDIT_STATUS] and out[COPY]["interactive"] is True
    assert "周末店里人少一些" in out[FINAL] and out[FINAL] == wechat_text(session["edited"][key]["post"])
    assert "周末店里人少一些" in out[14]                         # the phone preview shows the edit
    assert any(m[0] == "edit" for m in session["_marks"])
    out = store_tab.on_revert(session)
    assert "周末店里人少一些" not in out[FINAL] and out[EDIT_STATUS] == ""


def test_published_is_recorded_per_platform(session):
    key, r = _with_result(session)
    out = store_tab.on_publish(session)
    assert out[PROGRESS - 1]["value"].startswith("已发布 ✓（朋友圈")
    assert session["_marks"][-1][:2] == ("S03", "朋友圈")


def test_mobile_view_shows_the_final_text_and_plain_images(session, monkeypatch, tmp_path):
    import io
    from PIL import Image
    monkeypatch.setattr(store_tab, "DOWNLOAD_DIR", tmp_path)

    def png(_mid):
        b = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(b, "PNG")
        return b.getvalue()
    monkeypatch.setattr(ui_data.DEPS, "fetch_image_bytes", png, raising=False)
    key, r = _with_result(session)
    edited = store_tab.render_publishable(r.post).replace("掂一掂。", "掂一掂。周末店里人少一些。")
    store_tab.on_check_save(edited, session)
    page, text = store_tab.mobile_view(session)
    assert text == wechat_text(session["edited"][key]["post"]) and "周末店里人少一些" in text
    assert page.count("<img ") == len(r.post.images) and "/gradio_api/file=" in page
    store_tab.on_text_input(edited + "未检查", session)
    assert store_tab.mobile_view(session)[1] == ""              # an unchecked change is never offered
