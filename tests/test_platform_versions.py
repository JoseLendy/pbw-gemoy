"""F: one card, every platform (weekly progress is a suggestion, not a lock). D: the demo precompute.
Fakes only (DemoBook rehearsal), tmp runs dir; no ima, no LLM."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from agent.pipeline import Deps, prepare_demo, prepare_today
from agent.recommend.store_data import cards_for, default_card, reload, reset_demo_state
from agent.recommend.weekly import mark_published, progress_line, suggest_platform, weekly_progress
from agent.runs import stored, stored_version

DAY = "2026-10-23"          # a Friday: the week is Mon 10-19 .. Thu 10-22 in the log, plus today's marks


def demo_map(card):
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("BATCH_MAX_WORKERS", "1")
    reload()
    yield
    reload()


def _data(rows, minimum=None):
    return SimpleNamespace(publish=rows, quota={"weekly_minimum": minimum or {"朋友圈": 3, "小红书": 3, "公众号": 1}})


def _row(day, platform, posted=True, store="S01"):
    return {"date": day, "store_id": store, "platform": platform, "posted": str(posted).lower()}


# ---------------------------------------------------------------- weekly progress + suggestion
def test_progress_counts_posted_rows_per_platform_in_this_week_only(tmp_path):
    rows = [_row("2026-10-18", "朋友圈"),                       # last week
            _row("2026-10-19", "公众号"), _row("2026-10-20", "小红书"), _row("2026-10-21", "朋友圈"),
            _row("2026-10-22", "小红书", posted=False), _row("2026-10-21", "朋友圈", store="S02")]
    p = weekly_progress("S01", DAY, _data(rows), runs_dir=tmp_path)
    assert {k: v["done"] for k, v in p.items()} == {"朋友圈": 1, "小红书": 1, "公众号": 1}
    assert [k for k in p] == ["朋友圈", "小红书", "公众号"]


def test_suggestion_picks_the_platform_most_behind(tmp_path):
    rows = [_row("2026-10-19", "公众号"), _row("2026-10-20", "朋友圈"), _row("2026-10-21", "朋友圈")]
    p = weekly_progress("S01", DAY, _data(rows), runs_dir=tmp_path)
    assert suggest_platform(p) == "小红书"                      # 0/3 behind 2/3 and 1/1
    rows = [_row("2026-10-20", "朋友圈"), _row("2026-10-21", "小红书")]
    assert suggest_platform(weekly_progress("S01", DAY, _data(rows), runs_dir=tmp_path)) == "公众号"   # 0/1
    assert "今天建议发：公众号" in progress_line(weekly_progress("S01", DAY, _data(rows), runs_dir=tmp_path))


def test_published_mark_updates_progress_immediately(tmp_path):
    data = _data([])
    before = weekly_progress("S01", DAY, data, runs_dir=tmp_path)["小红书"]["done"]
    mark_published("S01", DAY, "小红书", "S01-x", runs_dir=tmp_path)
    mark_published("S01", DAY, "小红书", "S01-x", runs_dir=tmp_path)      # same mark twice counts once
    assert weekly_progress("S01", DAY, data, runs_dir=tmp_path)["小红书"]["done"] == before + 1
    assert weekly_progress("S02", DAY, data, runs_dir=tmp_path)["小红书"]["done"] == 0


def test_cards_open_on_moments_whatever_the_weekday():
    for day in ("2026-10-19", "2026-10-20", DAY):              # Monday was 公众号 under the old rotation
        assert {c.platform for c in cards_for("S01", day)} == {"朋友圈"}


# ---------------------------------------------------------------- prepare_today: every platform version
def test_all_versions_of_one_card_share_model_and_fact_card(tmp_path):
    day = prepare_today(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo_map)
    card = demo_map(default_card("S03", DAY))
    recs = {p: stored_version(dataclasses.replace(card, platform=p), runs_dir=tmp_path)
            for p in ("朋友圈", "小红书", "公众号")}
    assert all(recs.values()), {p: bool(r) for p, r in recs.items()}
    assert {r["model"] for r in recs.values()} == {"demobook-14"}
    facts = {p: [(f["id"], f["value"]) for f in r["result"]["ledger"]["facts"]] for p, r in recs.items()}
    assert facts["朋友圈"] == facts["小红书"] == facts["公众号"]
    assert {r["result"]["task"]["angle"] for r in recs.values()} == {card.angle}
    assert [r["result"]["task"]["platform"] for r in recs.values()] == ["moments", "xiaohongshu", "wechat_article"]
    assert set(day.batches) == {"朋友圈", "小红书", "公众号"}


def test_wechat_is_skipped_when_this_weeks_wechat_is_done(tmp_path):
    day = prepare_today(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo_map)
    # S01 posted its 公众号 on Monday 10-19 (generated publish_log); S03's 公众号 that day was not posted
    assert "S01" in day.wechat_skipped and "S03" not in day.wechat_skipped
    assert "S01" not in day.versions["公众号"] and "S03" in day.versions["公众号"]
    card = demo_map(default_card("S01", DAY))
    assert stored_version(dataclasses.replace(card, platform="公众号"), runs_dir=tmp_path) is None


def test_prepare_versions_redoes_only_the_named_versions(tmp_path):
    from agent.pipeline import prepare_versions
    prepare_today(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo_map)
    vdir = tmp_path / DAY / "prepared" / "versions"
    before = {p.name: p.read_text("utf-8") for p in vdir.glob("*.json")}
    prepared = (tmp_path / DAY / "prepared" / "S01.json").read_text("utf-8")
    day = prepare_versions(DAY, [("S01", "小红书"), ("S03", "公众号")], Deps.fake(), runs_dir=tmp_path,
                           card_map=demo_map)
    assert set(day.versions) == {"小红书", "公众号"} and not day.errors
    after = {p.name: p.read_text("utf-8") for p in vdir.glob("*.json")}
    changed = {n for n in after if after[n] != before.get(n)}
    s01, s03 = default_card("S01", DAY).card_id, default_card("S03", DAY).card_id
    assert changed == {f"{s01}__xiaohongshu.json", f"{s03}__wechat_article.json"}
    assert (tmp_path / DAY / "prepared" / "S01.json").read_text("utf-8") == prepared   # 朋友圈 post untouched
    rec = stored_version(dataclasses.replace(demo_map(default_card("S01", DAY)), platform="小红书"), runs_dir=tmp_path)
    assert rec["result"]["post"]["platform"] == "xiaohongshu"


def test_moments_version_is_still_the_stores_prepared_post(tmp_path):
    from agent.runs import prepared_post
    prepare_today(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo_map)
    rec = prepared_post("S03", DAY, card_id=default_card("S03", DAY).card_id, runs_dir=tmp_path)
    assert rec and rec["result"]["task"]["platform"] == "moments"


# ---------------------------------------------------------------- prepare_demo: everything the UI shows
def test_prepare_demo_stores_other_slots_compare_and_baseline(tmp_path):
    demo = prepare_demo(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo_map)
    others = [c for c in cards_for("S01", DAY) if not c.is_default and not c.locked]
    assert others and all(stored_version(demo_map(c), runs_dir=tmp_path) for c in others)
    cmp_ = stored(DAY, "compare", f"{demo.compare_model}__moments", runs_dir=tmp_path)
    assert cmp_ and cmp_["stores"] == ["S01", "S04", "S08", "S02"] and cmp_["similarity"]
    base = stored(DAY, "baseline", demo.baseline_card, runs_dir=tmp_path)
    assert base and base["baseline"]["is_baseline"] is True and base["timestamp"]
    assert set(demo.seconds) == {"prepare_today", "other_slots", "compare", "baseline"}


def test_reset_demo_state_keeps_the_precompute(tmp_path):
    demo = prepare_demo(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo_map)
    reset_demo_state()
    assert stored(DAY, "baseline", demo.baseline_card, runs_dir=tmp_path)
    assert stored_version(dataclasses.replace(demo_map(default_card("S03", DAY)), platform="小红书"),
                          runs_dir=tmp_path)
