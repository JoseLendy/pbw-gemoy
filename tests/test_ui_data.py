"""
agent.ui_data (Phase 3 UI adapter). Fakes only; no ima, no LLM, no network. Covers: the adapter works
with and without the optional Phase 5 functions, DEMO_TODAY is used instead of the system clock, and
reset() never touches prepared posts.
"""
from __future__ import annotations

import dataclasses
import importlib

import pytest

import agent.ui_data as ui_data
from agent.pipeline import Deps
from agent.recommend.store_data import default_card, fact_card_overrides, reload
from agent.schemas import BaselineResult, EditBlocked, LockedResult, RecommendationCard, RunResult

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def _demo_card(store_id: str = "S01") -> RecommendationCard:
    """A real demo card, patched to a model id the shared fakes catalog knows (tests/fakes.py only
    has demobook-14/-se), same pattern as tests/test_batch.py and tests/test_runs.py."""
    card = default_card(store_id, TODAY)
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


# ---------------------------------------------------------------- demo date
def test_today_reads_demo_today_env_not_system_clock(monkeypatch):
    monkeypatch.setenv("DEMO_TODAY", "2099-01-01")
    assert ui_data.today() == "2099-01-01"


def test_today_has_a_fixed_default_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("DEMO_TODAY", raising=False)
    assert ui_data.today() == "2026-10-23"


# ---------------------------------------------------------------- stores / cards / question pool
def test_list_stores_returns_the_twelve_demo_stores():
    stores = ui_data.list_stores()
    assert len(stores) == 12
    assert {"store_id", "store_name"} <= set(stores[0])


def test_get_cards_returns_a_default_card_for_the_requested_date():
    cards = ui_data.get_cards("S01", TODAY)
    assert any(c.is_default for c in cards)
    assert all(c.store_id == "S01" for c in cards)


def test_question_pool_has_the_ten_demo_chips():
    pool = ui_data.question_pool()
    assert len(pool) == 10
    assert all({"text", "segments"} <= set(v) for v in pool.values())


# ---------------------------------------------------------------- generate / baseline / edit / compare
def test_generate_runs_the_card_through_run_from_card():
    card = _demo_card()
    result = ui_data.generate(card, deps=Deps.fake())
    assert isinstance(result, RunResult)
    assert result.task.card_id == card.card_id


def test_generate_locked_card_returns_locked_result_without_calling_deps():
    card = dataclasses.replace(_demo_card(), locked=True, locked_reason="fact_card_draft")
    result = ui_data.generate(card, deps=Deps.fake())
    assert isinstance(result, LockedResult)


def test_baseline_never_calls_our_pipeline(monkeypatch):
    calls = []
    monkeypatch.setattr(ui_data, "_generate_baseline", lambda card, deps=None: calls.append(card) or
                        BaselineResult(card_id=card.card_id, model_id=card.model_id, platform=card.platform,
                                      prompt="p", text="t", display_text="【x】t"))
    card = _demo_card()
    result = ui_data.baseline(card, deps=Deps.fake())
    assert isinstance(result, BaselineResult) and calls == [card]


def test_edit_blocks_an_invented_price_before_touching_the_writer():
    card = _demo_card()
    result = ui_data.generate(card, deps=Deps.fake())
    blocked = ui_data.edit(result, "加上立减500", deps=Deps.fake())
    assert isinstance(blocked, EditBlocked)
    assert blocked.prev is result   # the UI must keep showing this unchanged previous result


def test_compare_delegates_to_generate_batch_and_keys_by_store():
    cards = [_demo_card("S01"), _demo_card("S03")]
    batch = ui_data.compare(cards, deps=Deps.fake())
    assert set(batch.results) == {"S01", "S03"}


# ---------------------------------------------------------------- HQ verify / reset
def test_verify_new_product_unlocks_the_fact_card():
    model_id = "matebook-fold-ultimate-design"
    before = next((c for c in ui_data.get_cards("S01", TODAY) if c.slot == "new_release"), None)
    assert before is not None and before.locked and before.locked_reason == "fact_card_draft"
    ui_data.verify_new_product(model_id)
    assert fact_card_overrides().get(model_id) == "verified"
    after = next((c for c in ui_data.get_cards("S01", TODAY) if c.slot == "new_release"), None)
    assert after is not None and not after.locked


def test_reset_clears_backend_overrides_but_never_touches_optional_clear_prepared(monkeypatch):
    calls = []
    monkeypatch.setattr(ui_data, "clear_prepared", lambda *a, **k: calls.append(a))
    ui_data.verify_new_product("matebook-fold-ultimate-design")
    assert fact_card_overrides()
    ui_data.reset()
    assert fact_card_overrides() == {}
    assert calls == []   # reset() must never call clear_prepared - prepared posts survive a retake


# ---------------------------------------------------------------- optional Phase 5 hooks (not merged yet)
def test_prepared_post_falls_back_to_none_when_phase5_is_not_merged():
    assert ui_data.prepared_post("S01", TODAY) is None


def test_clear_prepared_falls_back_to_a_noop_when_phase5_is_not_merged():
    ui_data.clear_prepared(TODAY)   # must not raise


def test_optional_hooks_are_detected_when_present():
    """Not using the monkeypatch fixture here: adding then deleting the SAME attribute name needs to
    happen on our own schedule (reload in between), which the fixture's auto-undo can't give us."""
    import agent.recommend.store_data as store_data

    store_data.prepared_post = lambda store_id, date: {"fake": True}
    store_data.clear_prepared = lambda date: None
    try:
        importlib.reload(ui_data)
        assert ui_data.ACTIVE_PATHS == {"prepared_post": True, "clear_prepared": True}
        assert ui_data.prepared_post("S01", TODAY) == {"fake": True}
    finally:
        del store_data.prepared_post
        del store_data.clear_prepared
        importlib.reload(ui_data)   # restore the fallback state for every test after this one


# ---------------------------------------------------------------- last_real_run
def test_last_real_run_delegates_to_runs_latest_run(monkeypatch):
    monkeypatch.setattr(ui_data, "latest_run", lambda card_id: {"card_id": card_id, "ok": True})
    assert ui_data.last_real_run("S01-x") == {"card_id": "S01-x", "ok": True}


# ---------------------------------------------------------------- plain_error (never leaks secrets)
def test_plain_error_hides_long_tokens():
    msg = ui_data.plain_error(RuntimeError("bad key sk-abcdefghijklmnopqrstuvwxyz123456"))
    assert "sk-" not in msg and "［已隐藏］" in msg


def test_plain_error_recognises_the_quota_code():
    e = RuntimeError("quota exceeded")
    e.code = 220021
    assert "已达上限" in ui_data.plain_error(e)
