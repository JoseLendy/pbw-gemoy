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


# ------------------------------------------------------------------ real 2026-10-23 export: two renderer leaks
_QUOTE = "这是一段知识库原文引用，长度足够长"


def test_samples_carry_no_image_file_names_or_kb_paths(runs, tmp_path):
    """Decision 2026-10-21: samples/ keeps store, reasons, the post text and check results, but no image file
    names, no KB article paths and no verbatim quotes; the source is a generic label."""
    written = dict(ex.build(DAY, runs, tmp_path / "s", allow_dev=True))
    rec = json.loads((runs / DAY / "prepared" / "S01.json").read_text(encoding="utf-8"))
    res = rec["result"]
    titles = {it["image"].get("title") for it in (res.get("plan") or {}).get("items", []) if it["image"].get("title")}
    paths = {f.get("source_path") for f in res["ledger"]["facts"] if f.get("source_path")}
    for name, text in written.items():
        assert not any(t in text for t in titles), name
        assert not any(p in text for p in paths), name
    s01 = written["S01-potential-moments.md"]
    assert "来源：知识库产品参数" in s01 and "| F1 |" in s01


def test_scan_refuses_image_names_and_kb_paths():
    res = {"plan": {"items": [{"image": {"media_id": "m1", "title": "demobook_外观_01.jpg"}}]},
           "ledger": {"facts": [{"id": "F1", "quote": "", "source_path": "P1-产品参数库/DemoBook/产品事实.md"}]}}
    assert ex.scan("配图 demobook_外观_01.jpg", "", [res["ledger"]], set(), ex._kb_names([res]))
    assert ex.scan("来源 P1-产品参数库/DemoBook/产品事实.md", "", [res["ledger"]], set(), ex._kb_names([res]))


def test_needs_review_reason_names_the_fact_instead_of_quoting_it():
    """Real S01 NeedsReview: the 8A reason embeds the fact value ('应同时标注 [F5]（<value>）')."""
    ledger = {"facts": [{"id": "F5", "value": _QUOTE, "quote": _QUOTE}]}
    reason = f"数值「1.38 kg」不属于所标编号 F14，应同时标注 [F5]（{_QUOTE}）"
    out = ex._redact(reason, ledger)
    assert _QUOTE not in out and "F5" in out and "1.38 kg" in out


def test_review_record_can_be_chosen_by_file_name(runs, tmp_path):
    recs = [{"_path": tmp_path / "a.json", "result": {"failing": []}},
            {"_path": tmp_path / "b.json", "result": {"failing": []}}]
    assert ex.select(recs)["review"]["_path"].name == "b.json"                 # default: latest, unchanged
    assert ex.select(recs, review="a.json")["review"]["_path"].name == "a.json"


def test_a_next_card_sample_shows_the_published_card_not_the_morning_one(runs):
    """Real 2026-10-23 S04: the morning card failed, the next card (another model, another slot) was published,
    but the sample header named the morning card's model and reasons."""
    rec = json.loads((runs / DAY / "prepared" / "S01.json").read_text(encoding="utf-8"))
    rec["_path"] = runs / DAY / "prepared" / "S01.json"
    nxt = next(c for c in cards_for("S01", DAY) if c.card_id != rec["card_id"])
    rec["result"]["task"]["card_id"], rec["result"]["task"]["model_id"] = nxt.card_id, "demobook-14-se"
    rec["result"]["fallback"] = "next_card"
    name, text = ex.render_post_sample(rec)
    assert "`demobook-14-se`" in text and f"-{nxt.slot}-" in name
    reasons = [r.text for r in nxt.reasons if r.text]
    assert reasons and reasons[0] in text


def test_redact_removes_a_whole_quote_whose_value_is_inside_it():
    """Review: the value was replaced first, leaving the rest of the quote; the scan then no longer matched it."""
    quote = "演示标签：演示取值说明一二三四五，用于测试。"
    ledger = {"facts": [{"id": "F5", "value": "演示取值说明一二三四五", "quote": quote}]}
    out = ex._redact(f"原因：应同时标注 [F5]（{quote}）", ledger)
    assert "演示标签" not in out and "用于测试" not in out and "F5" in out
