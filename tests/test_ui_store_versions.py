"""Store view state: platform versions (F), stored results first (D), inline edit + export gating (C).
Ported from the Gradio store tab tests to ui/state.py (dict views). Fakes only."""
from __future__ import annotations

import dataclasses

import pytest

from agent import ui_data
from agent.export import wechat_text
from agent.pipeline import Deps, run_from_card
from agent.schemas import Post, RunResult
from ui import state

NAME = "DemoBook 14（演示版）"


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(ui_data, "prepared_post", lambda *a, **k: None)
    monkeypatch.setattr(ui_data, "stored_version", lambda *a, **k: None)
    marks = []
    monkeypatch.setattr(ui_data, "mark_published", lambda *a, **k: marks.append(a))
    monkeypatch.setattr(ui_data, "log_human_edit", lambda *a, **k: marks.append(("edit",) + a))
    s = state.fresh_session()
    state.load_store(s, "S03")
    s["_marks"] = marks
    return s


def _with_result(s):
    card, key = state._current_card(s)
    demo = dataclasses.replace(card, model_id="demobook-14", display_name=NAME)
    r = run_from_card(demo, Deps.fake())
    assert isinstance(r, RunResult)
    r.post = Post("moments", "", "", [f"{NAME}重量约 1.25 kg [F1]，{r.task.landmark}的门店可以上手掂一掂。"],
                  "想上手试试，私信我或到店找我。", ["朋友圈"], ["F1"], r.post.images[:1])
    s["results"][key] = r
    return key, r


def test_opens_on_moments_with_the_weekly_progress_line(session):
    out = state.render(session)
    assert out["platform"] == "朋友圈"
    assert "本周：朋友圈" in out["progress_html"] and "今天建议发：" in out["progress_html"]


def test_other_platforms_are_manager_only_for_staff(session):
    out = state.on_platform("小红书", session)
    assert out["panel"]["notice"] == "由店长发布" and out["action"]["visible"] is False
    out = state.on_role("店长", session)
    assert not out["panel"]["notice"] and out["action"]["visible"] is True
    out = state.on_platform("公众号", session)
    assert out["action"]["label"] == "生成公众号文章"


def test_a_stored_version_is_shown_with_its_generation_time(session, monkeypatch):
    card, key = state._current_card(session)
    demo = dataclasses.replace(card, model_id="demobook-14", display_name=NAME)
    r = run_from_card(demo, Deps.fake())
    payload = {"status": "RunResult", "result": dataclasses.asdict(r), "timestamp": "2026-10-23T00:12:00+00:00"}
    monkeypatch.setattr(ui_data, "stored_version", lambda c, p=None: payload if c.platform == "小红书" else None)
    state.on_role("店长", session)
    out = state.on_platform("小红书", session)
    assert "生成于 10-23 08:12" in out["panel"]["head"] and out["action"]["label"] == "重新生成"


def test_edit_flow_blocks_export_until_checked_and_shows_failures(session):
    key, r = _with_result(session)
    original = state.render_publishable(r.post)
    out = state.on_text_input(original.replace("1.25 kg", "1.2 kg"), session)
    assert "未检查" in out["edit_status_html"] and out["can_copy"] is False and out["can_export"] is False
    out = state.on_check_save(original.replace("1.25 kg", "1.2 kg"), session)
    assert "未通过核验" in out["edit_status_html"] and "1.2 kg" in out["edit_status_html"]
    assert out["can_copy"] is False and out["can_export"] is False
    assert state.export_zip(session) is None


def test_a_passing_edit_is_saved_used_for_copy_and_logged(session):
    key, r = _with_result(session)
    edited = state.render_publishable(r.post).replace("掂一掂。", "掂一掂。周末店里人少一些。")
    out = state.on_check_save(edited, session)
    assert "已修改·已核验" in out["edit_status_html"] and out["can_copy"] is True
    assert "周末店里人少一些" in out["final_text"] and out["final_text"] == wechat_text(session["edited"][key]["post"])
    assert "周末店里人少一些" in out["phone_html"]                 # the phone preview shows the edit
    assert any(m[0] == "edit" for m in session["_marks"])
    out = state.on_revert(session)
    assert "周末店里人少一些" not in out["final_text"] and out["edit_status_html"] == ""


def test_published_is_recorded_per_platform(session):
    key, r = _with_result(session)
    out = state.on_publish(session)
    assert out["publish_label"].startswith("已发布 ✓（朋友圈") and out["published"] is True
    assert session["_marks"][-1][:2] == ("S03", "朋友圈")


def test_a_prepared_next_card_fallback_keeps_the_prepared_header():
    from agent.recommend.store_data import cards_for
    promo = next(c for c in cards_for("S10", "2026-10-23") if c.slot == "promo")
    head = state._card_panel(promo, True, prepared_slot="活动款", generated="生成于 10-23 08:12")["head"]
    assert "今日已为你准备好 · 活动款 · 生成于" in head and "已预先生成" not in head
    assert "已预先生成" in state._card_panel(promo, True, generated="生成于 10-23 08:12")["head"]


def test_zip_is_ready_once_images_are_cached_and_never_fetched_on_render(session, monkeypatch, tmp_path):
    import base64
    import io
    import zipfile
    from PIL import Image
    from ui import components
    monkeypatch.setattr(ui_data, "export_zip", lambda post, sid, text=None, date=None, fetch=None: (
        tmp_path.joinpath("z.zip").write_bytes(__import__("agent.export", fromlist=["x"]).publish_zip(
            post, sid, "2026-10-23", fetch, text)[1]) and str(tmp_path / "z.zip")))
    key, r = _with_result(session)
    for im in r.post.images:
        components._IMG_CACHE.pop(im.media_id, None)
    out = state.render(session)
    assert out["can_export"] is False and state.export_zip(session) is None   # nothing fetched on render
    b = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(b, "PNG")
    for im in r.post.images:
        components._IMG_CACHE[im.media_id] = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    out = state.render(session)
    assert out["can_export"] is True
    name, data = state.export_zip(session)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.read("文案.txt").decode("utf-8") == out["final_text"] and "1.jpg" in z.namelist()
    for im in r.post.images:
        components._IMG_CACHE.pop(im.media_id, None)
