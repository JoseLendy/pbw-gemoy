"""Phase 4: real-run log + reset_demo_state. Fakes only; logs go to a tmp dir."""
from __future__ import annotations

import dataclasses

from agent.pipeline import Deps, run_from_card
from agent.recommend.store_data import default_card, fact_card_overrides, reset_demo_state, set_fact_card_status
from agent.runs import latest_run, log_run

TODAY = "2026-10-21"


def _card():
    card = default_card("S01", TODAY)
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


def test_log_run_writes_a_full_record_and_latest_run_finds_it(tmp_path):
    card = _card()
    result = run_from_card(card, Deps.fake())
    path = log_run(card, result, kind="run_from_card", runs_dir=tmp_path)
    assert path.exists() and path.parent.name == TODAY
    payload = latest_run(card.card_id, runs_dir=tmp_path)
    assert payload["card_id"] == card.card_id and payload["store_id"] == "S01"
    assert payload["scenario"] == card.scenario and payload["model"] == "demobook-14"
    assert payload["temperatures"]["check"] == 0
    assert payload["result"]["post"]["platform"] == "moments"
    assert payload["result"]["report"] is not None


def test_reset_demo_state_clears_fact_card_overrides():
    set_fact_card_status("matebook-fold-ultimate-design", "verified")
    assert fact_card_overrides()
    reset_demo_state()
    assert fact_card_overrides() == {}
