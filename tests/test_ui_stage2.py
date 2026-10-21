"""Stage 2/3 UI: 三店对比, 总部端 and 对照组. Local fixtures + fakes only; no network."""
from __future__ import annotations

import dataclasses

import pytest

from agent import ui_data
from agent.pipeline import BatchResult, Deps, SimilarityPair, run_from_card
from agent.schemas import BASELINE_LABEL, BaselineResult, CheckIssue
from ui import baseline_tab, compare_tab, hq_tab

MODEL = "matebook-14-harmonyos"
STORES = ["S01", "S04", "S08", "S02"]


@pytest.fixture(autouse=True)
def _clean():
    ui_data.reset()
    yield
    ui_data.reset()


def _fakeable(card):
    """Fakes only know DemoBook, so keep the store expression but swap the product for the fake one."""
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


def _fake_result(card):
    return run_from_card(_fakeable(card), Deps.fake())


# ---------------------------------------------------------------- adapter data
def test_compare_products_and_store_cards_keep_store_expression():
    products = ui_data.compare_products()
    assert products and all(p["model_id"] and p["display_name"] for p in products)
    cards = [ui_data.product_card(sid, MODEL) for sid in STORES]
    assert all(c is not None for c in cards)
    assert {c.model_id for c in cards} == {MODEL}
    assert len({c.store_name for c in cards}) == 4
    assert len({(c.angle, getattr(c.voice, "id", None)) for c in cards}) >= 3


def test_publish_stats_window_and_lowest_three():
    data = ui_data.publish_stats()
    assert data["days"] == 14 and len(data["stats"]) == 12
    assert sum(1 for s in data["stats"] if s["low"]) == 3
    assert all(0 <= s["rate"] <= 1 for s in data["stats"])


def test_weekly_plan_marks_friday_and_platform_rotation():
    plan = ui_data.weekly_plan()
    today = [d for d in plan["days"] if d["is_today"]]
    assert len(today) == 1
    assert today[0]["label"] == "周五" and today[0]["platform"] == "朋友圈"
    assert plan["minimum"]["朋友圈"] >= 1


def test_question_stats_are_sorted_and_aggregated():
    rows = ui_data.question_stats(5)
    assert len(rows) <= 5
    assert rows == sorted(rows, key=lambda r: (-r["count"], r["chip_id"]))
    assert rows[0]["count"] > 0 and rows[0]["stores"] > 0


def test_recommendation_distribution_covers_every_store():
    rows = ui_data.recommendation_distribution()
    assert len(rows) == 12
    assert all(r["display_name"] and r["slot_label"] and r["platform"] for r in rows)


# ---------------------------------------------------------------- HQ verify / reset
def test_new_release_verify_unlocks_stores_and_reset_reverts():
    draft = ui_data.new_release_drafts()[0]
    assert draft["status"] == "draft" and draft["refs"]
    assert all(r["fact_id"].startswith("F") and r["source_title"] for r in draft["refs"])
    before = hq_tab.release_html()
    assert "待总部确认" in before and draft["display_name"] in before
    assert "产品事实.md" in before or "卖点与限制.md" in before

    _, _, msg, distribution = hq_tab.on_verify()
    assert "已确认发布" in msg
    assert "已确认发布" in hq_tab.release_html()
    assert draft["model_id"] not in hq_tab.release_html()   # never show an internal model id
    assert draft["display_name"] in distribution

    hq_tab.on_reset()
    assert "待总部确认" in hq_tab.release_html()
    assert ui_data.new_release_drafts()[0]["status"] == "draft"


def test_store_tab_clears_its_session_after_hq_reset():
    from ui import store_tab

    session = store_tab.fresh_session()
    store_tab._load_store(session, "S01")
    session["results"]["stale"] = object()
    session["published"]["stale"] = True
    session["chips"]["S01"] = {"Q01"}

    ui_data.reset()
    store_tab.on_tab_select(session)
    assert "stale" not in session["results"]
    assert session["published"] == {} and session["chips"] == {}
    assert session["store_id"] == "S01" and session["cards"]


def test_hq_panels_never_show_internal_model_ids():
    for panel in (hq_tab.posting_html(), hq_tab.release_html(), hq_tab.questions_html(),
                  hq_tab.plan_html(), hq_tab.distribution_html()):
        assert "matebook-" not in panel
        assert "MODEL_" not in panel


# ---------------------------------------------------------------- 三店对比 rendering
def test_compare_renders_four_phones_and_similarity(monkeypatch):
    cards = [ui_data.product_card(sid, MODEL) for sid in STORES]
    results = {c.store_id: _fake_result(c) for c in cards}
    batch = BatchResult(results=results,
                        similarity=[SimilarityPair("学生", "S01", "S02", 0.85, 0.42, True)],
                        regenerated=["S02"], wall_seconds=1.2)
    by_store = {c.store_id: c for c in cards}
    monkeypatch.setattr(compare_tab, "COMPARE_STORES", [(sid, sid) for sid in STORES])
    monkeypatch.setattr(compare_tab.ui_data, "product_card", lambda sid, mid: by_store[sid])
    monkeypatch.setattr(compare_tab.ui_data, "compare", lambda cards: batch)
    monkeypatch.setattr(compare_tab.ui_data, "DEPS", Deps.fake())

    body, summary = compare_tab.on_compare(MODEL, "小红书")
    assert body.count('class="hw-phone') == 4
    assert "0.850 → 0.420" in body and "8E 已重写" in body
    assert "4 店完成" in summary and "1 店" in summary
    assert MODEL not in body and "matebook-" not in body


def test_compare_missing_campaign_is_a_plain_message(monkeypatch):
    monkeypatch.setattr(compare_tab.ui_data, "product_card", lambda sid, mid: None)
    body, summary = compare_tab.on_compare(MODEL, "朋友圈")
    assert "无法对比" in body and summary == ""


# ---------------------------------------------------------------- 对照组 rendering
def test_baseline_is_always_labelled_and_hits_are_highlighted():
    card = ui_data.default_card("S01")
    result = BaselineResult(card_id=card.card_id, model_id=card.model_id, platform=card.platform,
                            prompt="p", text="这台电脑能用到 48 小时。", display_text="",
                            hits=[CheckIssue(stage="8D", severity="error", code="unsupported_number",
                                             message="无法核验的数字", span="48 小时")])
    result.display_text = f"【{BASELINE_LABEL}】{result.text}"
    out = baseline_tab.baseline_html(result)
    assert f">{BASELINE_LABEL}</h3>" in out
    assert "<mark" in out and "48 小时" in out
    assert "无法核验的数字" in out


def test_ours_html_contains_the_verified_result_and_report():
    card = ui_data.default_card("S01")
    result = _fake_result(card)
    out = baseline_tab.ours_html(result)
    assert "我们的结果（知识库核验）" in out
    assert 'class="hw-phone' in out
    assert "四、核验结果" in out
    assert card.model_id not in out


def test_baseline_highlight_escapes_html():
    assert "<script>" not in baseline_tab._highlight("<script>x</script>", [])
