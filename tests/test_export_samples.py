"""K2: scripts/export_samples.py builds samples/ only from run records and refuses to write anything that
leaks keys, KB ids or verbatim KB quotes. Records here come from fake runs (allow_dev=True)."""
from __future__ import annotations

import dataclasses
import json

import pytest

import scripts.export_samples as ex
from agent.pipeline import Deps, edit, prepare_today, run_from_card
from agent.recommend.store_data import cards_for, default_card, reload
from agent.runs import log_run

DAY = "2026-10-23"


def demo(card):
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


@pytest.fixture
def runs(tmp_path):
    reload()
    prepare_today(DAY, Deps.fake(), runs_dir=tmp_path, card_map=demo)
    locked = next(c for c in cards_for("S01", DAY) if c.slot == "new_release")
    log_run(locked, run_from_card(demo(locked), Deps.fake()), runs_dir=tmp_path)
    s01 = demo(default_card("S01", DAY))
    res = run_from_card(s01, Deps.fake())
    log_run(s01, edit(res, "加上立减500", Deps.fake()), kind="edit_blocked", runs_dir=tmp_path)
    yield tmp_path
    reload()


def test_builds_the_selected_samples_and_readme(runs, tmp_path):
    out = tmp_path / "samples"
    written = dict(ex.build(DAY, runs, out, allow_dev=True))
    names = set(written)
    assert {"S01-potential-moments.md", "S02-promo-moments.md", "S04-potential-moments.md", "README.md"} <= names
    assert "S01-new_release-locked.md" in names and "S01-edit-blocked.md" in names
    s01 = written["S01-potential-moments.md"]
    assert "[F" not in s01.split("```text")[1].split("```")[0]           # publishable text has no fact tags
    assert "模拟数据" in s01 and "四、核验结果" in s01 and "| F1 |" in s01
    assert "新品资料待总部确认" in written["S01-new_release-locked.md"]
    assert "已拦截「加上立减500」" in written["S01-edit-blocked.md"]
    readme = written["README.md"]
    assert "模拟数据" in readme and "S02-promo-moments.md" in readme and "相似度" in readme
    for name, text in written.items():
        assert (out / name).read_text(encoding="utf-8").strip() == text.strip()


def test_no_media_ids_or_ledger_quotes_in_samples(runs, tmp_path):
    written = dict(ex.build(DAY, runs, tmp_path / "s", allow_dev=True))
    rec = json.loads((runs / DAY / "prepared" / "S01.json").read_text(encoding="utf-8"))
    ids = ex._media_ids(rec["result"])
    long_quotes = [f["quote"] for f in rec["result"]["ledger"]["facts"] if len(f["quote"]) >= 12]
    for text in written.values():
        assert not any(i in text for i in ids)
        assert not any(q in text.split("```text")[0] for q in long_quotes)


def test_dev_mode_prepared_posts_are_ignored_by_default(runs, tmp_path):
    """Prepared posts from a --fake rehearsal carry dev_mode; run logs are only ever written for real deps."""
    written = dict(ex.build(DAY, runs, tmp_path / "s"))
    assert not [n for n in written if n.endswith("-moments.md")]


def test_scan_flags_quotes_ids_and_keys():
    ledger = {"facts": [{"id": "F1", "quote": "这是一段知识库原文引用，长度足够"}]}
    assert ex.scan("说明：这是一段知识库原文引用，长度足够", "", [ledger], set())
    assert ex.scan("图片 media-123456", "", [], {"media-123456"})
    assert ex.scan("key " + "sk" + "-" + "abcdefghijklmnopqrstuvwx", "", [], set())   # built at run time
    assert not ex.scan("文案：重量约 1.25 kg", "文案：重量约 1.25 kg", [ledger], {"media-1"})


def test_leak_aborts_without_writing(runs, tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "scan", lambda *a, **k: ["planted leak"])
    with pytest.raises(ex.LeakError):
        ex.build(DAY, runs, tmp_path / "s", allow_dev=True)
    assert not (tmp_path / "s").exists()
