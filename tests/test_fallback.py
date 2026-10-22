"""Phase 5, T4: fallback policy for card runs that still fail after 2 rewrites. Fakes only."""
from __future__ import annotations

import dataclasses

import pytest

import agent.pipeline as pl
from agent.pipeline import Deps, generate_batch, prepare_today, run_from_card
from agent.recommend.store_data import cards_for, default_card, reload
from agent.runs import prepared_post
from agent.schemas import CheckIssue, CheckReport, NeedsReview, RunResult
from tests.fakes import fake_post

TODAY = "2026-10-21"
BAD = "这台电脑一整天都不用充电"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def demo(card):
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


def deps_with(bad_slots=("potential",), locatable=True, bad_extra=""):
    """Writer: the given slots always produce BAD; checks flag BAD (with or without a span); rewrites
    change nothing, so the 2-rewrite loop cannot fix it."""
    deps = Deps.fake()

    def write(task, strategy, ledger, plan, llm=None):
        p = fake_post("moments")
        p.body = ["重量约 1.25 kg [F1]。"] + ([f"{BAD}{bad_extra}。"] if task.slot in bad_slots else [])
        p.cta = "周末来店里上手掂一掂。"
        return p

    def checks(post, ledger, sib, task, plan, llm=None):
        text = post.all_text()
        if BAD in text:
            return CheckReport([CheckIssue("8A", "error", "uncited_claim", "无依据的续航承诺",
                                           field="body[1]", span=BAD if locatable else "")])
        if not post.selling_points:
            return CheckReport([CheckIssue("8C", "error", "missing_point", "缺少卖点")])
        return CheckReport()

    deps.write_post, deps.run_checks = write, checks
    deps.rewrite = lambda post, *a, **k: post
    return deps


def potential_card():
    return demo(default_card("S01", TODAY))


def test_trimmed_when_removing_the_failing_sentence_passes():
    r = run_from_card(potential_card(), deps_with())
    assert isinstance(r, RunResult) and r.fallback == "trimmed" and r.report.passed
    assert BAD not in r.post.all_text() and r.post.selling_points == ["F1"] and r.post.cta
    assert r.loops == 2                                        # the normal loop ran first


def test_next_card_when_the_error_cannot_be_trimmed(monkeypatch):
    nxt = demo(next(c for c in cards_for("S01", TODAY) if c.slot == "promo"))
    monkeypatch.setattr(pl, "_next_card", lambda card: nxt)
    r = run_from_card(potential_card(), deps_with(locatable=False))
    assert isinstance(r, RunResult) and r.fallback == "next_card" and r.report.passed
    assert r.task.card_id == nxt.card_id and r.task.slot == "promo"


def test_next_card_order_is_potential_promo_question_release():
    cards = {c.slot: c for c in cards_for("S01", TODAY)}
    assert pl._next_card(cards["potential"]).slot == "promo"
    assert pl._next_card(cards["promo"]).slot == "potential"
    assert pl._next_card(cards["customer_question"]).slot == "potential"
    assert all(not c.locked for c in [pl._next_card(c) for c in cards.values()] if c)   # draft 新品 never chosen


def test_next_card_keeps_the_platform_of_the_version_that_failed():
    potential = next(c for c in cards_for("S01", TODAY) if c.slot == "potential")
    for platform in ("小红书", "公众号"):
        nxt = pl._next_card(dataclasses.replace(potential, platform=platform))
        assert nxt.slot == "promo" and nxt.platform == platform


def test_needs_review_when_everything_fails(monkeypatch):
    nxt = demo(next(c for c in cards_for("S01", TODAY) if c.slot == "promo"))
    monkeypatch.setattr(pl, "_next_card", lambda card: nxt)
    r = run_from_card(potential_card(), deps_with(bad_slots=("potential", "promo"), locatable=False))
    assert isinstance(r, NeedsReview) and r.message.startswith("需人工确认")
    assert r.card.slot == "potential" and r.attempts == [r.card.card_id, nxt.card_id]
    assert r.failing and r.failing[0].code == "uncited_claim" and r.failing[0].reason == "无依据的续航承诺"
    assert not r.draft.report.passed                           # the draft is shown for review, not delivered


def test_needs_review_lists_the_exact_failing_sentence_without_tags(monkeypatch):
    monkeypatch.setattr(pl, "_next_card", lambda card: None)
    deps = deps_with()
    deps.run_checks = lambda post, *a, **k: CheckReport([CheckIssue("8B", "error", "false_promise", "承诺",
                                                                     field="body[1]", span=BAD)])
    r = run_from_card(potential_card(), deps)
    assert isinstance(r, NeedsReview)
    assert [(f.field, f.sentence, f.stage) for f in r.failing] == [("body[1]", f"{BAD}。", "8B")]


def test_trim_that_leaves_no_selling_point_is_not_delivered(monkeypatch):
    monkeypatch.setattr(pl, "_next_card", lambda card: None)
    deps = deps_with()
    base_write = deps.write_post

    def write(task, strategy, ledger, plan, llm=None):
        p = base_write(task, strategy, ledger, plan, llm)
        p.body = [f"{BAD}，重量约 1.25 kg [F1]。"]          # the only fact sits in the failing sentence
        return p

    deps.write_post = write
    assert isinstance(run_from_card(potential_card(), deps), NeedsReview)


def test_fallback_can_be_turned_off():
    r = run_from_card(potential_card(), deps_with(), fallback=False)
    assert isinstance(r, RunResult) and r.fallback is None and not r.report.passed


def test_batch_and_prepare_today_apply_the_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_next_card", lambda card: None)
    deps = deps_with(locatable=False)
    batch = generate_batch([potential_card()], deps)
    assert isinstance(batch.results["S01"], NeedsReview)
    day = prepare_today(TODAY, deps_with(), runs_dir=tmp_path, card_map=demo)
    s01 = day.batch.results["S01"]
    assert isinstance(s01, RunResult) and s01.fallback == "trimmed"
    rec = prepared_post("S01", TODAY, card_id=default_card("S01", TODAY).card_id, runs_dir=tmp_path)
    assert rec["status"] == "RunResult" and rec["result"]["fallback"] == "trimmed"
