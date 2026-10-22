"""Phase 4: generate_batch / 8E regeneration. Fakes only; no ima or LLM."""
from __future__ import annotations

import dataclasses

import pytest

from agent.pipeline import Deps, generate_batch
from agent.recommend.store_data import default_card, load_store_data, reload
from agent.schemas import CardHook
from tests.fakes import fake_post

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def _demo_card(store_id):
    data = load_store_data()
    card = default_card(store_id, TODAY, data)
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）",
                               hook=CardHook("myth", "误区澄清"), angle="同一角度")


def test_generate_batch_regenerates_similar_peers_and_reports_before_after():
    deps = Deps.fake()

    def write(task, strategy, ledger, plan, llm=None):
        p = fake_post("moments")
        p.body = [f"同一段通用文案 {task.hook} {task.angle}"]
        return p

    deps.write_post = write
    cards = [_demo_card(sid) for sid in ("S01", "S02", "S03")]
    batch = generate_batch(cards, deps)
    assert set(batch.results) == {"S01", "S02", "S03"}
    assert batch.similarity, "same-segment peers must produce similarity pairs"
    assert any(p.before == 1.0 for p in batch.similarity)
    assert any(p.before > p.after for p in batch.similarity), [(p.before, p.after) for p in batch.similarity]
    assert batch.regenerated, "a high-similarity later store should be regenerated once"


def test_generate_batch_never_picks_the_current_hook_or_angle():
    """Regression: the candidate must exclude the card's own current values, or a 'regeneration' no-ops."""
    deps = Deps.fake()
    s01 = dataclasses.replace(_demo_card("S01"), hook=CardHook("scene", "场景开头"))
    s02 = dataclasses.replace(_demo_card("S02"), hook=CardHook("question", "问题开头"))
    s03 = dataclasses.replace(_demo_card("S03"), hook=CardHook("myth", "误区澄清"))
    batch = generate_batch([s01, s02, s03], deps)
    assert "S02" in batch.regenerated
    assert batch.results["S02"].task.hook != "question"


def test_generate_batch_never_regenerates_a_customer_question_card():
    deps = Deps.fake()
    from agent.recommend.store_data import cards_for
    pcard = dataclasses.replace(default_card("S01", TODAY), model_id="demobook-14",
                                display_name="DemoBook 14（演示版）", hook=CardHook("myth", "误区澄清"),
                                angle="同一角度")
    qcard = next(c for c in cards_for("S02", TODAY) if c.slot == "customer_question")
    qcard = dataclasses.replace(qcard, model_id="demobook-14", display_name="DemoBook 14（演示版）",
                                hook=CardHook("customer", "顾客问答开头"), angle="同一角度")
    batch = generate_batch([pcard, qcard], deps)
    assert "S02" not in batch.regenerated
