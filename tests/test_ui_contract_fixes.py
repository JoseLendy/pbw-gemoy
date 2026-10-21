"""Regressions for the UI_SPEC audit findings (ErrorReport1792578570)."""
from __future__ import annotations

import dataclasses
import time

from unittest.mock import patch

from agent import ui_data
from agent.pipeline import BatchResult, Deps, SimilarityPair, run_from_card
from agent.schemas import FailingSentence, NeedsReview
from ui import baseline_tab, compare_tab, hq_tab, store_tab
from ui.components import prepared_post_html

import pytest


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    # Hermetic: never read this machine's real runs/ (after a real prepare_today, S01 has a prepared post
    # for 2026-10-23 and these "no result yet" tests would see it).
    import agent.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runs, "REHEARSAL_DIR", tmp_path / "runs" / "_rehearsal")
    ui_data.reset()
    yield
    ui_data.reset()


def _fake_result(card):
    return run_from_card(dataclasses.replace(card, model_id="demobook-14",
                                             display_name="DemoBook 14（演示版）"), Deps.fake())


def _session(store_id="S01"):
    s = store_tab.fresh_session()
    store_tab._load_store(s, store_id)
    return s


def test_publish_is_ignored_before_a_result_and_for_needs_review():
    s = _session()
    card, cid = store_tab._current_card(s)
    store_tab.on_publish(s)
    assert s["published"] == {}

    s["results"][cid] = NeedsReview(
        card=card, draft=_fake_result(card),
        failing=[FailingSentence(field="body[0]", sentence="x", stage="8A", code="c", reason="r")],
        attempts=[cid])
    out = store_tab._render(s)
    assert out[15]["visible"] is False and out[16]["visible"] is False and out[17]["visible"] is False
    store_tab.on_publish(s)
    assert s["published"] == {}

    s["results"][cid] = _fake_result(card)
    out = store_tab._render(s)
    assert out[15]["visible"] is True and out[16]["visible"] is True and out[17]["visible"] is True
    store_tab.on_publish(s)
    assert s["published"][cid] is True
    assert store_tab._render(s)[-1]["value"].startswith("已发布")


def test_next_card_uses_the_delivered_card_header():
    s = _session()
    requested, cid = store_tab._current_card(s)
    actual = next(c for c in s["cards"] if c.slot == "promo")
    r = _fake_result(requested)
    r = dataclasses.replace(r, fallback="next_card",
                            task=dataclasses.replace(r.task, card_id=actual.card_id, slot="promo"))
    s["results"][cid] = r
    out = store_tab._render(s)
    assert "活动款" in out[0] and "今日一条" not in out[0]
    assert "已换成下一条推荐" in out[11]


def test_failed_regeneration_is_visible_with_an_existing_result():
    s = _session()
    card, cid = store_tab._current_card(s)
    s["results"][cid] = _fake_result(card)
    with patch.object(store_tab.ui_data, "generate", side_effect=RuntimeError("402 Insufficient Balance")):
        out = store_tab.on_generate(s)
    assert out[8]["visible"] is True
    assert "402" not in out[9] and out[9]
    assert "hw-phone" in (out[13] or "")


def test_role_rule_marks_non_moments_as_manager_only():
    cards = ui_data.get_cards("S01", "2026-10-19")
    card = next(c for c in cards if c.platform != "朋友圈")
    s = store_tab.fresh_session()
    s.update({"store_id": "S01", "cards": cards, "active_card_id": card.card_id,
              "results": {}, "published": {}, "chips": {}})
    out = store_tab._render(s)
    assert "由店长发布" in out[0]
    assert out[1]["visible"] is False


def test_prepared_run_result_fills_the_phone_and_report_without_fetching_images():
    s = _session()
    card, cid = store_tab._current_card(s)
    r = _fake_result(card)
    payload = {"status": "RunResult", "result": dataclasses.asdict(r), "timestamp": "2026-10-23T08:00:00"}
    with patch.object(store_tab.ui_data, "prepared_post", return_value=payload), \
         patch.object(store_tab.ui_data, "DEPS") as deps:
        deps.fetch_image_bytes.side_effect = AssertionError("page load must not fetch images")
        s = _session()
        t0 = time.perf_counter()
        out = store_tab._render(s)
        elapsed = time.perf_counter() - t0
    assert "hw-phone" in out[13] and out[14]
    # A stored RunResult can be copied/published, downloaded and edited without regenerating.
    assert out[15]["visible"] is True and out[16]["visible"] is True and out[17]["visible"] is True
    assert elapsed < 0.5


def test_hq_reset_clears_both_messages():
    out = hq_tab.on_verify()
    assert len(out) == 5 and "已确认发布" in out[2] and out[3] == ""
    reset = hq_tab.on_reset()
    assert len(reset) == 8 and reset[4] == ""
    assert "待总部确认" in reset[1]


def test_new_release_refs_are_not_fake_fact_ids():
    refs = ui_data.new_release_drafts()[0]["refs"]
    assert refs and all(r["ref_id"].startswith("R") for r in refs)
    assert all("fact_id" not in r for r in refs)


def test_compare_uses_result_task_hook_angle_after_8e():
    cards = [ui_data.product_card(sid, "matebook-14-harmonyos")
             for sid, _ in compare_tab.COMPARE_STORES]
    card = next(c for c in cards if c.store_id == "S02")
    r = _fake_result(card)
    changed = dataclasses.replace(r, task=dataclasses.replace(
        r.task, hook="myth", angle="手机平板电脑多设备协同"))
    panel = compare_tab._result_panel("S02", card, changed, True)
    assert "多设备协同" in panel and card.angle not in panel
    assert "手机平板" in panel or "多设备" in panel


def test_compare_summary_counts_failures(monkeypatch):
    cards = [ui_data.product_card(sid, "matebook-14-harmonyos")
             for sid, _ in compare_tab.COMPARE_STORES]
    by_store = {c.store_id: c for c in cards}
    results = {c.store_id: (RuntimeError("boom") if c.store_id == "S04" else _fake_result(c))
               for c in cards}
    batch = BatchResult(results=results,
                        similarity=[SimilarityPair("student", "S01", "S02", 0.8, 0.4, True)],
                        regenerated=["S02"], wall_seconds=1.0)
    monkeypatch.setattr(compare_tab.ui_data, "product_card", lambda sid, mid: by_store[sid])
    monkeypatch.setattr(compare_tab.ui_data, "compare", lambda cs: batch)
    body, summary = compare_tab.on_compare("matebook-14-harmonyos", "朋友圈")
    assert "3/4 店完成" in summary and "1 店失败" in summary
    assert "0.550" in body


def test_baseline_renders_fallback_note():
    card = ui_data.default_card("S01")
    r = dataclasses.replace(_fake_result(card), fallback="next_card")
    out = baseline_tab.ours_html(r, "今日一条未通过核验，已换成下一条推荐")
    assert "已换成下一条推荐" in out


def test_prepared_needs_human_shows_message_not_an_empty_phone():
    out = prepared_post_html({"status": "NeedsHuman",
                              "result": {"message": "资料冲突，请人工确认", "conflicts": ["重量冲突"]}})
    assert "资料冲突" in out and "重量冲突" in out and "hw-phone" not in out


def test_prepared_next_card_uses_the_delivered_card():
    s = _session()
    requested, cid = store_tab._current_card(s)
    actual = next(c for c in s["cards"] if c.slot == "promo")
    r = _fake_result(requested)
    r = dataclasses.replace(r, fallback="next_card",
                            task=dataclasses.replace(r.task, card_id=actual.card_id, slot="promo"))
    s["results"][cid] = store_tab._PreparedDisplay(
        {"status": "RunResult", "result": dataclasses.asdict(r), "timestamp": "x"})
    out = store_tab._render(s)
    assert "活动款" in out[0] and "今日一条" not in out[0]


def test_prefetch_images_warms_the_cache_without_rendering():
    from ui.components import images_ready, prefetch_images
    from agent.schemas import PostImage

    card = ui_data.default_card("S01")
    r = _fake_result(card)
    r = dataclasses.replace(r, post=dataclasses.replace(
        r.post, images=[PostImage(media_id="media-async-check", position="p1", caption="图")]))

    class D:
        def fetch_image_bytes(self, media_id):
            return b"\x89PNG\r\n\x1a\nasync"

    assert not images_ready(r)
    prefetch_images(r, D())
    assert images_ready(r)


def test_image_placeholder_is_not_cached_as_a_real_image():
    from ui.components import image_data_uri

    class D:
        def fetch_image_bytes(self, media_id):
            return b"\x89PNG\r\n\x1a\nreal"

    first = image_data_uri("media-cache-check", "商品图", None, allow_fetch=False)
    second = image_data_uri("media-cache-check", "商品图", D(), allow_fetch=True)
    assert "image/svg+xml" in first
    assert "image/svg+xml" not in second and "image/png" in second


def test_reset_updates_the_store_dropdown():
    from ui import store_tab as st
    s = st.fresh_session()
    st._load_store(s, "S04")
    ui_data.reset()
    out = st.on_tab_select(s)
    values = [x.get("value") for x in out if isinstance(x, dict) and "value" in x]
    assert "S01" in values and s["store_id"] == "S01"


def test_recovery_rejects_non_store_run_records():
    from ui import store_tab as st
    s = _session()
    card, cid = st._current_card(s)
    baseline = {"kind": "generate_baseline", "status": None,
                "result": {"display_text": "对照组文本"}, "timestamp": "x"}
    with patch.object(st.ui_data, "last_real_run", return_value=baseline):
        st.on_show_recovery(s)
    assert cid not in s["results"] and "不是门店生成结果" in s["recovery"]["error"]


def test_local_store_switch_does_not_fetch_live_result_images():
    s = _session()
    card, cid = store_tab._current_card(s)
    r = _fake_result(card)
    s["results"][cid] = r
    calls = []
    with patch.object(store_tab.ui_data.DEPS, "fetch_image_bytes", lambda m: calls.append(m)):
        store_tab.on_store_change("S01", s)
    assert calls == []


def test_published_label_is_hidden_when_not_publishable():
    from ui import store_tab as st
    s = _session()
    out = st._render(s)
    assert out[19] == ""
    card, cid = st._current_card(s)
    s["results"][cid] = NeedsReview(
        card=card, draft=_fake_result(card),
        failing=[FailingSentence(field="body[0]", sentence="x", stage="8A", code="c", reason="r")],
        attempts=[cid])
    assert st._render(s)[19] == ""


def test_manual_tab_clears_its_session_after_hq_reset():
    import app
    from agent import ui_data as ud

    session = {"id": "old-session", "result": object()}
    token = ud.reset_token()
    ud.reset()
    out = app.on_manual_tab(session, token, "old all-platform output")
    assert out[0] == "" and out[10]["id"] != "old-session" and out[11] == ""
    assert out[12] == ud.reset_token()


def test_baseline_needs_review_shows_read_only_draft():
    card = ui_data.default_card("S01")
    nr = NeedsReview(card=card, draft=_fake_result(card),
                     failing=[FailingSentence(field="body[0]", sentence="x", stage="8A",
                                              code="c", reason="r")], attempts=[card.card_id])
    out = baseline_tab.ours_html(nr)
    assert "hw-phone" in out and "草稿" in out
