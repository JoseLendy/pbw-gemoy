"""8E cross-store variety for one day's posts (fakes only; synthetic DemoBook text, no KB sentences).

- every post is compared with every other post of the day, not only its peer group;
- a 6+ character phrase in more than 3 of the day's posts is reworded in the extra posts;
- a stock opener or filler is used by one store only;
- one product's selling point is used by at most 2 stores, and by one store per peer group.
"""
from __future__ import annotations

import dataclasses

import pytest

from agent.pipeline import Deps, generate_batch
from agent.recommend.store_data import default_card, load_store_data, reload
from agent.reconcile import reconcile
from agent.schemas import CardHook, RunResult, ScenarioAnalysis, Task
from agent.style.similarity import repeated_phrases, variety_breaches
from tests.fakes import DEMO, FakeLLM, fake_ledger, fake_post

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("BATCH_MAX_WORKERS", "1")
    reload()
    yield
    reload()


def _card(store_id, hook="scene", angle=None):
    card = default_card(store_id, TODAY, load_store_data())
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）",
                               hook=CardHook(hook, hook), angle=angle or card.angle)


def _texts(batch):
    from agent.formatter import render_publishable
    return {sid: render_publishable(r.post) for sid, r in batch.results.items() if isinstance(r, RunResult)}


# ---------------------------------------------------------------- pure helpers
def _entry(sid, text, seg="student", model="m1", sps=("F1",), keep=()):
    return {"store_id": sid, "segment": seg, "model_id": model, "selling_points": list(sps), "text": text,
            "keep": list(keep), "customer": False}


def test_phrase_in_more_than_three_posts_flags_only_the_extra_posts():
    shared = "周末带上家人一起来逛逛"
    entries = [_entry(f"S0{i}", f"第{i}家店的开头不一样{i}。{shared}。", model=f"m{i}", sps=(f"F{i}",))
               for i in range(1, 6)]
    out = variety_breaches(entries, threshold=0.99)
    assert set(out) == {"S04", "S05"}
    assert any(shared[:6] in p for p in out["S05"]["avoid_phrases"])


def test_phrase_in_exactly_three_posts_is_fine():
    shared = "周末带上家人一起来逛逛"
    entries = [_entry(f"S0{i}", f"开头{i}。{shared}。", model=f"m{i}", sps=(f"F{i}",)) for i in range(1, 4)]
    assert variety_breaches(entries, threshold=0.99) == {}


def test_fact_wording_and_product_names_are_not_counted_as_repetition():
    """Copying a fact's own wording (and the product name) is required, never a style repeat."""
    fact = "演示触控板支持三指手势操作"
    entries = [_entry(f"S0{i}", f"开头{i}。DemoBook 14 演示版{fact}。", model=f"m{i}", sps=(f"F{i}",),
                      keep=[fact, "DemoBook 14 演示版"]) for i in range(1, 6)]
    assert variety_breaches(entries, threshold=0.99) == {}


def test_stock_opener_and_filler_are_one_store_only():
    entries = [_entry("S01", "你可能以为电池只是一行数字。", model="m1", sps=("F1",)),
               _entry("S02", "你可能以为屏幕都一样。", model="m2", sps=("F2",)),
               _entry("S03", "先把这个数字记下来，再来店里。", model="m3", sps=("F3",)),
               _entry("S04", "先把这个数字记下来就行。", model="m4", sps=("F4",))]
    out = variety_breaches(entries, threshold=0.99)
    assert set(out) == {"S02", "S04"}
    assert "你可能以为" in out["S02"]["avoid_phrases"]
    assert "先把这个数字记下来" in out["S04"]["avoid_phrases"]


def test_same_product_selling_point_at_most_two_stores_per_day():
    entries = [_entry("S01", "甲。", seg="student"), _entry("S04", "乙。", seg="office"),
               _entry("S07", "丙。", seg="family")]
    out = variety_breaches(entries, threshold=0.99)
    assert set(out) == {"S07"} and out["S07"]["avoid_facts"] == ["F1"]


def test_same_product_selling_point_in_one_peer_group_is_a_near_duplicate():
    """S10/S11 shape: two shopper stores, same product, same selling point."""
    entries = [_entry("S10", "挑礼物先摸摸触控板。", seg="shopper"),
               _entry("S11", "送人一台电脑，先摸摸触控板。", seg="shopper")]
    out = variety_breaches(entries, threshold=0.99)
    assert set(out) == {"S11"} and out["S11"]["avoid_facts"] == ["F1"]


def test_similarity_is_checked_across_peer_groups():
    text = "完全相同的一段文案，用来测试跨客群的相似度。"
    entries = [_entry("S01", text, seg="student", model="m1", sps=("F1",)),
               _entry("S04", text, seg="office", model="m2", sps=("F2",))]
    out = variety_breaches(entries, threshold=0.55)
    assert set(out) == {"S04"} and out["S04"]["similar_to"] == "S01"


def test_repeated_phrases_reports_the_top_phrases():
    texts = {f"S0{i}": f"开头{i}。周末带上家人一起来逛逛。" for i in range(1, 5)}
    top = repeated_phrases(texts, min_posts=2)
    assert top and top[0][1] == 4 and "周末带上家人" in top[0][0]


# ---------------------------------------------------------------- reconcile honours avoid_facts
def _analysis():
    return ScenarioAnalysis(audience="学生", buying_stage="比较", problem="背着跑", content_goal="到店",
                            categories=["portability", "battery"])


def test_reconcile_never_picks_an_avoided_fact_when_another_exists():
    led = fake_ledger()
    llm = FakeLLM({"reconcile": {"angle": "背着跑", "selling_points": [{"fact_id": "F1", "reason": "轻"}],
                                 "cta_type": "到店体验"}})
    task = Task(raw_text="", model_id="demobook-14", platform="moments", avoid_facts=["F1"])
    s = reconcile(task, _analysis(), led, DEMO, llm)
    assert s.selling_points and "F1" not in [sp.fact_id for sp in s.selling_points]


def test_reconcile_without_avoid_list_is_unchanged():
    led = fake_ledger()
    llm = FakeLLM({"reconcile": {"angle": "背着跑", "selling_points": [{"fact_id": "F1", "reason": "轻"}],
                                 "cta_type": "到店体验"}})
    s = reconcile(Task(raw_text="", model_id="demobook-14", platform="moments"), _analysis(), led, DEMO, llm)
    assert [sp.fact_id for sp in s.selling_points] == ["F1"]


# ---------------------------------------------------------------- generate_batch end to end (fakes)
def _always_f1(deps):
    """Every store's reconcile wants F1 (the real reconcile, so avoid_facts is enforced by the real code)."""
    llm = FakeLLM({"reconcile": {"angle": "背着跑", "selling_points": [{"fact_id": "F1", "reason": "轻"}],
                                 "cta_type": "到店体验"}})
    deps.reconcile = lambda task, analysis, ledger, model, _llm=None: reconcile(task, analysis, ledger, model, llm)
    return deps


def test_batch_spreads_one_products_selling_point_over_at_most_two_stores():
    deps = _always_f1(Deps.fake())
    cards = [_card("S01", "scene"), _card("S04", "question"), _card("S07", "checklist")]
    batch = generate_batch(cards, deps)
    sps = {sid: tuple(r.post.selling_points) for sid, r in batch.results.items()}
    firsts = [s[0] for s in sps.values()]
    assert max(firsts.count(f) for f in set(firsts)) <= 2, sps
    assert "S07" in batch.regenerated


def test_batch_rewords_a_phrase_repeated_in_more_than_three_posts():
    deps = Deps.fake()

    def write(task, strategy, ledger, plan, llm=None):
        p = fake_post("moments")
        filler = "下班顺路进店聊聊天" if "下班顺路进店聊聊天" not in task.avoid_phrases else "改天得空再来坐坐"
        p.body = [f"{task.store_id} 自己的开头。重量约 1.25 kg [F1]。{filler}。"]
        return p

    deps.write_post = write
    cards = [_card(s, h) for s, h in (("S01", "scene"), ("S04", "question"), ("S07", "myth"), ("S10", "checklist"),
                                      ("S12", "scene"))]
    batch = generate_batch(cards, deps)
    texts = _texts(batch)
    assert sum("下班顺路进店聊聊天" in t for t in texts.values()) <= 3, texts


def test_a_failing_regeneration_never_replaces_a_passing_post():
    deps = _always_f1(Deps.fake())
    base_checks = deps.run_checks
    calls = {"n": 0}

    def checks(post, ledger, siblings, task, plan, llm=None):
        report = base_checks(post, ledger, siblings, task, plan, llm)
        if task.avoid_facts or task.avoid_phrases:          # every variety rerun fails its checks
            from agent.schemas import CheckIssue, CheckReport
            calls["n"] += 1
            return CheckReport(report.issues + [CheckIssue("8B", "error", "banned_word", "x")])
        return report

    deps.run_checks = checks
    cards = [_card("S01", "scene"), _card("S04", "question"), _card("S07", "checklist")]
    batch = generate_batch(cards, deps)
    assert calls["n"] > 0
    assert all(isinstance(r, RunResult) and r.report.passed for r in batch.results.values())
