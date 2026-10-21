"""Task 4: price traceability in 8B + the edit flow + the [演示活动] tag. Fakes only."""
from __future__ import annotations

import dataclasses

import pytest

from agent.checks import run_all
from agent.checks.prices import DEMO_TAG, check_prices, mark_demo_prices, price_request_block, valid_price_record
from agent.formatter import render_publishable
from agent.pipeline import Deps, edit, run, run_from_card
from agent.recommend.store_data import cards_for, reload
from agent.recommend.to_task import card_to_task
from agent.schemas import EditBlocked, RunResult
from tests.fakes import fake_ledger, fake_plan, fake_post, fake_task

TODAY = "2026-10-21"
COND = "活动期内有效，以门店实际为准"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def promo_task():
    card = next(c for c in cards_for("S02", TODAY) if c.slot == "promo")
    assert card.promo and card.promo.price_info, "S02 promo card must carry a demo price"
    return card_to_task(card)


def no_promo_task():
    return card_to_task(next(c for c in cards_for("S01", TODAY) if c.slot == "potential"))


def post_with(text, platform="moments"):
    p = fake_post(platform)
    p.body = [text]
    return p


def codes(issues):
    return {i.code for i in issues}


# ------------------------------------------------------------------ the record
def test_valid_record_comes_from_promotions_json_and_is_active():
    rec = valid_price_record(promo_task())
    assert rec["value"] == "4999" and rec["conditions"] == COND and rec["source"] == "DEMO"


def test_record_outside_the_campaign_window_is_not_valid():
    t = promo_task()
    t.card_date = "2026-12-01"            # DEMO-1111-PRE ended 2026-11-11
    assert valid_price_record(t) is None


def test_tampered_card_price_is_not_valid():
    t = promo_task()
    t.promo = {**t.promo, "price_info": {**t.promo["price_info"], "value": "3999"}}
    assert valid_price_record(t) is None


# ------------------------------------------------------------------ 8B on drafts
def test_exact_value_and_conditions_pass():
    issues = check_prices(post_with(f"演示活动价 4999 元，{COND}。"), promo_task())
    assert issues == []


def test_different_amount_fails():
    assert "price_mismatch" in codes(check_prices(post_with(f"演示活动价 4599 元，{COND}。"), promo_task()))


def test_price_without_conditions_fails():
    assert "price_conditions_missing" in codes(check_prices(post_with("演示活动价 4999 元。"), promo_task()))


@pytest.mark.parametrize("claim", ["到店立减500", "再享国家补贴", "支持12期免息", "现货充足", "限量 50 台",
                                   "赠品随箱", "库存有限"])
def test_unrecorded_mechanics_fail_even_with_a_record(claim):
    assert "price_untraceable" in codes(check_prices(post_with(f"演示活动价 4999 元，{COND}，{claim}。"),
                                                     promo_task()))


@pytest.mark.parametrize("claim", ["立减500", "国家补贴", "12期免息", "赠品", "库存有限"])
def test_unrecorded_mechanics_fail_without_a_record(claim):
    assert "price_untraceable" in codes(check_prices(post_with(f"{claim}。"), no_promo_task()))


def test_matching_price_on_a_different_model_fails():
    t = promo_task()
    t.model_id = "matebook-d-14-2024"       # the record does not carry a price for this model
    assert "price_untraceable" in codes(check_prices(post_with(f"演示活动价 4999 元，{COND}。"), t))


def test_money_terms_cover_the_old_8a_price_rule():
    """8B's card price rule must be at least as broad as the old 8A price pattern set."""
    from agent.checks.prices import TERM_RE
    terms = ["免费送", "低价", "仅售", "售价", "起售", "起价", "定价", "价格", "报价", "优惠", "补贴",
             "立减", "直降", "降价", "到手价", "特价", "折扣", "打折", "满减", "买赠", "赠送", "赠品",
             "分期", "免息", "库存", "现货", "仅剩", "限量"]
    assert [t for t in terms if not TERM_RE.search(t)] == []


def test_card_without_a_record_blocks_any_price():
    assert "price_untraceable" in codes(check_prices(post_with("只要 4999 元。"), no_promo_task()))


def test_run_all_allows_the_one_recorded_price():
    post = post_with(f"重量约 1.25 kg [F1]，演示活动价 4999 元，{COND}。")
    r = run_all(post, fake_ledger(), {}, promo_task(), fake_plan("moments"))
    price_errors = {i.code for i in r.issues if i.code.startswith(("price_", "invented_price"))}
    assert price_errors == set(), [(i.code, i.message) for i in r.issues]


def test_manual_flow_price_rules_unchanged():
    p = fake_post()
    p.cta = "到店立减500元"
    r = run_all(p, fake_ledger(), {}, fake_task(), fake_plan())
    cs = {i.code for i in r.issues}
    assert "invented_price" in cs and not any(c.startswith("price_") for c in cs)


# ------------------------------------------------------------------ [演示活动]
def test_demo_price_gets_the_tag_once_in_publishable_text():
    t = promo_task()
    post = mark_demo_prices(post_with(f"演示活动价 4999 元，{COND}。"), t)
    pub = render_publishable(post)
    assert f"4999 元 {DEMO_TAG}" in pub and pub.count(DEMO_TAG) == 1
    again = mark_demo_prices(post, t)
    assert render_publishable(again).count(DEMO_TAG) == 1


def test_no_tag_without_a_demo_record():
    post = mark_demo_prices(post_with("重量约 1.25 kg [F1]。"), no_promo_task())
    assert DEMO_TAG not in render_publishable(post)


# ------------------------------------------------------------------ edit flow
def test_edit_with_invented_discount_is_blocked_before_the_writer():
    deps = Deps.fake()
    calls = []
    deps.write_post = lambda *a, **k: calls.append("write")
    deps.rewrite = lambda *a, **k: calls.append("rewrite")
    prev = run("一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书", deps=Deps.fake())
    out = edit(prev, "加上立减500", deps)
    assert isinstance(out, EditBlocked)
    assert "价格可追溯规则" in out.message and "立减" in out.message
    assert out.prev is prev and calls == []


def test_price_request_matching_the_record_is_allowed():
    t = promo_task()
    assert price_request_block("写上演示活动价4999元", t) is None
    assert price_request_block("加上立减500", t)
    assert price_request_block("写上 3999 元", t)
    assert price_request_block("短一点", t) is None


def test_card_run_end_to_end_marks_the_demo_price():
    """Real promo card (MateBook 14 HarmonyOS, DEMO 4999) through run_from_card; the fake catalog is taught
    that model id, with synthetic DemoBook facts standing in for its KB data."""
    from tests import fakes as F
    card = next(c for c in cards_for("S02", TODAY) if c.slot == "promo")
    mid = card.model_id
    deps = Deps.fake()
    model_a = dataclasses.replace(F.DEMO, model_id=mid, siblings=[])
    deps.catalog = F.FakeCatalog({**F.MODELS, mid: model_a})
    deps.get_bundle = lambda model_id, catalog=None: dataclasses.replace(F.fake_bundle("demobook-14"),
                                                                        model=deps.catalog.get(model_id))
    deps.build_ledger = lambda bundle, llm=None, use_cache=True: F.fake_ledger("demobook-14")
    base_write = deps.write_post

    def write(task, strategy, ledger, plan, llm=None):
        post = base_write(task, strategy, ledger, plan, llm)
        post.body = [post.body[0] + f"演示活动价 4999 元，{COND}。"]
        return post

    deps.write_post = write
    r = run_from_card(card, deps)
    assert isinstance(r, RunResult) and r.task.model_id == mid
    pub = render_publishable(r.post)
    assert f"4999 元 {DEMO_TAG}" in pub and pub.count(DEMO_TAG) == 1
