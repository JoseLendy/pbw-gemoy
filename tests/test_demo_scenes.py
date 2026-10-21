"""Phase 5, Task 5: 三店对比 product_card helper + demo_scenes.py gate. Fakes only."""
from __future__ import annotations

import pytest

import scripts.demo_scenes as scenes
from agent.checks.prices import valid_price_record
from agent.recommend.store_data import cards_for, product_card, reload
from agent.recommend.to_task import card_to_task

TODAY = "2026-10-23"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


@pytest.mark.parametrize("sid", scenes.COMPARE_STORES)
def test_product_card_keeps_the_store_brief_and_swaps_the_product(sid):
    base = next(c for c in cards_for(sid, TODAY) if c.slot == "promo")
    card = product_card(sid, scenes.COMPARE_MODEL, TODAY)
    assert card.model_id == scenes.COMPARE_MODEL and card.display_name == "HUAWEI MateBook 14 酷睿 Ultra"
    assert (card.hook, card.voice, card.angle, card.landmark) == (base.hook, base.voice, base.angle, base.landmark)
    assert card.card_id != base.card_id and not card.is_default and not card.locked
    rec = valid_price_record(card_to_task(card))          # the price comes from the campaign record
    assert rec is not None and rec["value"] == "6999"


def test_product_card_needs_an_active_campaign_for_the_model():
    assert product_card("S01", "matebook-gt-14", TODAY) is None          # in no campaign
    assert product_card("S01", scenes.COMPARE_MODEL, "2026-12-01") is None   # campaign over


def test_compare_stores_have_two_peers_in_one_segment():
    segs = [cards_for(sid, TODAY)[0].segment for sid in scenes.COMPARE_STORES]
    assert segs.count("student") == 2                     # S01 + S02: same-type stores still differ (8E)


def test_refuses_real_deps_without_run_e2e(monkeypatch, capsys):
    monkeypatch.delenv("RUN_E2E", raising=False)
    assert scenes.main(["--today", TODAY]) == 2
    assert "RUN_E2E=1" in capsys.readouterr().out
