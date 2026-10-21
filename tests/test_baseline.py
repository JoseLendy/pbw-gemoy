"""Task 7: baseline (control group) output. FakeLLM only."""
from __future__ import annotations

from agent.pipeline import Deps, generate_baseline
from agent.recommend.store_data import cards_for, reload
from agent.schemas import BASELINE_LABEL, BaselineResult, LockedResult
from tests.fakes import FakeLLM

TODAY = "2026-10-21"
RAW = "在这个快节奏的时代，这款热销笔记本赋能你的学习！不仅轻薄，更有超长续航。"


def _card(slot="potential"):
    reload()
    return next(c for c in cards_for("S01", TODAY) if c.slot == slot)


def test_baseline_is_always_labelled_as_control_group():
    llm = FakeLLM({"baseline": RAW})
    r = generate_baseline(_card(), llm=llm)
    assert isinstance(r, BaselineResult) and r.is_baseline
    assert r.label == BASELINE_LABEL == "对照组：未经约束的普通大模型输出"
    assert r.display_text.startswith(f"【{BASELINE_LABEL}】") and RAW in r.display_text
    assert r.text == RAW


def test_baseline_is_one_naive_call_at_the_writer_stage():
    llm = FakeLLM({"baseline": RAW})
    card = _card()
    r = generate_baseline(card, llm=llm)
    assert [c["stage"] for c in llm.calls] == ["baseline"]
    assert r.prompt == f"为{card.display_name}写一篇{card.platform}推广文案"
    from agent.llm import temperature_for
    assert temperature_for("baseline") == temperature_for("writer")


def test_baseline_highlights_8d_hits_but_changes_nothing():
    r = generate_baseline(_card(), llm=FakeLLM({"baseline": RAW}))
    spans = {i.span for i in r.hits}
    assert {"在这个快节奏的时代", "热销", "赋能"} <= spans
    assert any(i.code == "ai_pattern" for i in r.hits)
    assert all(i.stage == "8D" for i in r.hits)
    assert r.text == RAW                      # never rewritten


def test_baseline_never_touches_ima_or_the_pipeline_stages():
    def boom(*a, **k):
        raise AssertionError("baseline must not call pipeline stages")
    deps = Deps.fake()
    for f in ("get_bundle", "build_ledger", "plan_images", "write_post", "rewrite", "run_checks", "analyze"):
        setattr(deps, f, boom)
    deps.llm = FakeLLM({"baseline": RAW})
    assert isinstance(generate_baseline(_card(), deps=deps), BaselineResult)


def test_locked_card_has_no_baseline():
    llm = FakeLLM({"baseline": RAW})
    r = generate_baseline(_card("new_release"), llm=llm)
    assert isinstance(r, LockedResult) and llm.calls == []
