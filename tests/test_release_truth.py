"""Phase 5, Task 2: new-release truthfulness in 8B (card runs) + the demo launch_date never reaches the
writer. Fakes only."""
from __future__ import annotations

import copy
import csv
import dataclasses
import datetime as dt
import json

import pytest

from agent import writer
from agent.checks import run_all
from agent.checks.release import check_release, release_facts
from agent.pipeline import Deps, run_from_card
from agent.recommend import explain
from agent.recommend.common import INPUTS
from agent.recommend.store_data import cards_for, reload, set_fact_card_status
from agent.recommend.to_task import card_to_task
from agent.schemas import RunResult
from tests.fakes import _f, fake_ledger, fake_plan, fake_post

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def new_release_row() -> dict:
    rows = list(csv.DictReader((INPUTS / "models.csv").open(encoding="utf-8")))
    return next(r for r in rows if r["is_new_release"] == "true")


def release_card():
    row = new_release_row()
    set_fact_card_status(row["model_id"], "verified")
    return next(c for c in cards_for("S01", TODAY) if c.slot == "new_release")


def fake_release_card():
    """The real 新品款 card, pointed at the synthetic DemoBook so the fake catalog/ledger can run it."""
    return dataclasses.replace(release_card(), model_id="demobook-14", display_name="DemoBook 14（演示版）")


def card_task():
    return card_to_task(next(c for c in cards_for("S01", TODAY) if c.slot == "potential"))


def ledger_with_release():
    led = copy.deepcopy(fake_ledger())
    led.facts.append(_f(13, "demobook-14", "release_date", "other", "2026 年 8 月 5 日发布",
                        "2026 年 8 月 5 日发布", kind="entity"))
    return led


def post_with(text):
    p = fake_post("moments")
    p.body = [text]
    return p


def codes(issues):
    return [i.code for i in issues]


# ------------------------------------------------------------------ the 8B rule
def test_untagged_new_release_claim_fails():
    issues = check_release(post_with("DemoBook 14 新品首发，重量约 1.25 kg [F1]。"), fake_ledger(), card_task())
    assert codes(issues) == ["release_unsupported"] and issues[0].stage == "8B"


@pytest.mark.parametrize("claim", ["新上市", "刚发布", "即将上市", "10月28日上市", "新款", "首销"])
def test_equivalent_wording_fails(claim):
    assert "release_unsupported" in codes(check_release(post_with(f"DemoBook 14 {claim}。"), fake_ledger(),
                                                        card_task()))


def test_tagged_release_fact_passes():
    led = ledger_with_release()
    assert [f.id for f in release_facts(led)] == ["F13"]
    assert check_release(post_with("DemoBook 14 是新品，2026年8月5日发布[F13]。"), led, card_task()) == []


def test_tagged_release_fact_with_a_different_date_fails():
    issues = check_release(post_with("DemoBook 14 新品，10月28日上市[F13]。"), ledger_with_release(), card_task())
    assert codes(issues) == ["release_unsupported"]


def test_a_non_release_fact_tag_does_not_support_the_claim():
    assert codes(check_release(post_with("新品来了，重量约 1.25 kg [F1]。"), fake_ledger(), card_task())) \
        == ["release_unsupported"]


def test_ordinary_words_are_not_release_claims():
    text = "全新体验，家里该换新机了，重量约 1.25 kg [F1]。"
    assert check_release(post_with(text), fake_ledger(), card_task()) == []


def test_tags_are_checked_too():
    p = fake_post("moments")
    p.tags = ["新品首发"]
    assert codes(check_release(p, fake_ledger(), card_task())) == ["release_unsupported"]


def test_manual_flow_is_unchanged():
    from tests.fakes import fake_task
    assert check_release(post_with("DemoBook 14 新品首发。"), fake_ledger(), fake_task("moments")) == []


def test_run_all_reports_it_for_card_runs():
    report = run_all(post_with("DemoBook 14 新品首发，重量约 1.25 kg [F1]。"), fake_ledger(), {}, card_task(),
                     fake_plan("moments"))
    assert "release_unsupported" in {i.code for i in report.issues} and not report.passed


# ------------------------------------------------------------------ the demo launch_date
def test_release_reason_is_a_demo_push_unless_the_kb_states_the_date():
    launch = dt.date(2026, 10, 28)
    assert explain.release_reason(launch, True) == "总部新品推送（演示流程）"
    assert explain.release_reason(launch, True, dt.date(2026, 8, 5)) == "总部新品推送（演示流程）"
    assert explain.release_reason(launch, True, launch) == "新品 2026-10-28 上市"
    assert explain.release_reason(launch, False) == "新品资料待总部确认，暂不可生成"


def test_release_card_reason_has_no_date_and_is_marked_demo():
    card = release_card()
    r = next(r for r in card.reasons if r.source == "release")
    assert r.text == "总部新品推送（演示流程）" and r.is_demo
    assert new_release_row()["launch_date"] not in json.dumps(card.to_dict(), ensure_ascii=False)


class _CapturingLLM:
    """Records every full prompt; returns a minimal valid writer draft."""

    def __init__(self):
        self.prompts: list[str] = []

    def chat_json(self, system, user, stage="", **kw):
        self.prompts.append(f"{system}\n{user}")
        return {"title": "", "intro": "", "body": ["重量约 1.25 kg [F1]。"], "cta": "来店里看看。",
                "tags": [], "selling_points": ["F1"], "images": []}

    def chat_text(self, system, user, stage="", **kw):
        self.prompts.append(f"{system}\n{user}")
        return ""


def _date_forms(iso: str) -> list[str]:
    d = dt.date.fromisoformat(iso)
    return [iso, d.strftime("%Y/%m/%d"), d.strftime("%Y.%m.%d"), f"{d.month}月{d.day}日", f"{d.month}月{d.day}号"]


def test_demo_launch_date_never_reaches_the_writer_prompt():
    card = fake_release_card()
    llm = _CapturingLLM()
    deps = Deps.fake()
    deps.write_post, deps.llm = writer.write_post, llm
    res = run_from_card(card, deps)
    assert isinstance(res, RunResult)
    assert llm.prompts, "the real writer must have been called"
    blob = "\n".join(llm.prompts)
    for form in _date_forms(new_release_row()["launch_date"]):
        assert form not in blob
    assert "总部新品推送" not in blob          # the card's reason lines are UI text, not writer input
    assert "不得写“新品、首发" in blob          # the card brief carries the release rule


def test_card_fallback_tags_never_say_new_launch():
    card = fake_release_card()
    llm = _CapturingLLM()
    deps = Deps.fake()
    deps.write_post, deps.llm = writer.write_post, llm
    res = run_from_card(card, deps)
    assert res.task.scenario == "new_launch"
    assert "新品首发" not in res.post.tags
