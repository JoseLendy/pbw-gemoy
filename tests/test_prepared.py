"""Phase 5, Task 3: prepared posts (prepare_today / prepared_post / clear_prepared). Fakes only;
records go to a tmp dir."""
from __future__ import annotations

import dataclasses

import pytest

from agent.pipeline import Deps, prepare_today
from agent.recommend import store_data
from agent.recommend.store_data import default_card, load_store_data, reload, reset_demo_state
from agent.runs import clear_prepared, prepared_post

TODAY = "2026-10-23"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def demo(card):
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


def stores():
    return [s["store_id"] for s in load_store_data().stores]


def test_prepare_today_stores_one_result_per_unlocked_store(tmp_path):
    day = prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    assert set(day.paths) == set(stores()) and day.locked == {}
    files = sorted(p.name for p in (tmp_path / TODAY / "prepared").glob("*.json"))
    assert files == sorted(f"{sid}.json" for sid in stores())
    rec = prepared_post("S01", TODAY, card_id=default_card("S01", TODAY).card_id, runs_dir=tmp_path)
    assert rec["kind"] == "prepared" and rec["status"] == "RunResult" and rec["dev_mode"] is True
    assert rec["result"]["post"]["body"] and rec["seconds"] is not None and rec["rewrites"] is not None


def test_prepared_post_returns_the_default_cards_result_or_none(tmp_path):
    prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    card = default_card("S04", TODAY)
    rec = prepared_post("S04", TODAY, card_id=card.card_id, model_id="demobook-14", runs_dir=tmp_path)
    assert rec["card_id"] == card.card_id and rec["store_id"] == "S04"
    assert prepared_post("S04", TODAY, card_id="S04-2026-10-23-other", runs_dir=tmp_path) is None
    assert prepared_post("S04", "2026-10-24", card_id=card.card_id, runs_dir=tmp_path) is None


def test_prepared_post_without_ids_checks_the_current_default_card(tmp_path):
    from agent.pipeline import run_from_card
    from agent.runs import log_prepared
    card = default_card("S01", TODAY)
    log_prepared(card, run_from_card(demo(card), Deps.fake()), runs_dir=tmp_path)    # stored under the real card
    rec = prepared_post("S01", TODAY, runs_dir=tmp_path)
    assert rec is not None and rec["model"] == card.model_id
    prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)               # now stored as DemoBook
    assert prepared_post("S01", TODAY, runs_dir=tmp_path) is None                     # no longer the default


def test_locked_stores_are_listed_not_generated(tmp_path, monkeypatch):
    real_default = store_data.default_card

    def default_with_locks(store_id, today, data=None):
        if store_id == "S02":
            return None
        card = real_default(store_id, today, data)
        if store_id == "S01":
            return dataclasses.replace(card, locked=True, locked_reason="fact_card_draft")
        return card

    monkeypatch.setattr(store_data, "default_card", default_with_locks)
    day = prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    assert day.locked == {"S01": "新品资料待总部确认，暂不可生成", "S02": "今日无可生成的卡片"}
    assert "S01" not in day.batch.results and "S02" not in day.batch.results
    assert not (tmp_path / TODAY / "prepared" / "S01.json").exists()
    assert len(day.paths) == len(stores()) - 2


def test_reset_demo_state_keeps_prepared_posts_and_clear_prepared_removes_them(tmp_path):
    prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    card_id = default_card("S01", TODAY).card_id
    reset_demo_state()
    assert prepared_post("S01", TODAY, card_id=card_id, runs_dir=tmp_path) is not None
    n = len(list((tmp_path / TODAY / "prepared").rglob("*.json")))     # prepared posts + every platform version
    assert n >= len(stores()) and clear_prepared(TODAY, runs_dir=tmp_path) == n
    assert prepared_post("S01", TODAY, card_id=card_id, runs_dir=tmp_path) is None
    assert clear_prepared(TODAY, runs_dir=tmp_path) == 0


def test_batch_reports_seconds_per_store(tmp_path):
    day = prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    assert set(day.batch.seconds) == set(day.batch.results)
    assert all(v >= 0 for v in day.batch.seconds.values())


def test_cli_refuses_fakes_without_flag(monkeypatch, capsys):
    import scripts.prepare_today as cli
    fake = Deps.fake()
    monkeypatch.setattr(Deps, "auto", classmethod(lambda cls: fake))
    assert cli.main(["--today", TODAY]) == 2
    assert "--fake" in capsys.readouterr().out


def test_cli_fake_rehearsal_writes_to_the_rehearsal_dir(tmp_path, monkeypatch, capsys):
    import agent.runs as runs
    import scripts.prepare_today as cli
    monkeypatch.setattr(runs, "REHEARSAL_DIR", tmp_path / "_rehearsal")
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "real")
    assert cli.main(["--today", TODAY, "--fake"]) == 0
    out = capsys.readouterr().out
    assert "S01" in out and "S12" in out and "rehearsal" in out
    assert len(list((tmp_path / "_rehearsal" / TODAY / "prepared").glob("*.json"))) == len(stores())
    assert not (tmp_path / "real").exists()


def test_a_crashed_store_never_overwrites_its_prepared_post(tmp_path):
    prepare_today(TODAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    card_id = default_card("S01", TODAY).card_id
    before = prepared_post("S01", TODAY, card_id=card_id, runs_dir=tmp_path)
    deps = Deps.fake()

    def boom(*a, **k):
        raise RuntimeError("Error code: 402 - Insufficient Balance")

    deps.write_post = boom
    day = prepare_today(TODAY, deps, runs_dir=tmp_path, card_map=demo)
    assert {k for k in day.errors if "/" not in k} == set(stores()) and day.paths == {}
    assert {k.split("/")[1] for k in day.errors if "/" in k} >= {"小红书"}      # no version stored either
    assert prepared_post("S01", TODAY, card_id=card_id, runs_dir=tmp_path) == before
