"""docs/UI_BACKEND_CONTRACT.md is binding for the UI merge: if a function, parameter, result field or label
the UI relies on is renamed, this fails loudly. Fakes only."""
from __future__ import annotations

import dataclasses
import importlib
import inspect

import pytest

FUNCTIONS = {
    "agent.recommend.store_data.cards_for": ["store_id", "today", "data"],
    "agent.recommend.store_data.default_card": ["store_id", "today", "data"],
    "agent.recommend.store_data.product_card": ["store_id", "model_id", "today", "data"],
    "agent.recommend.store_data.set_fact_card_status": ["model_id", "status"],
    "agent.recommend.store_data.fact_card_overrides": [],
    "agent.recommend.store_data.reset_demo_state": [],
    "agent.pipeline.run_from_card": ["card", "deps", "staff", "on_progress", "fallback"],
    "agent.pipeline.generate_batch": ["cards", "deps", "staff_map", "on_progress"],
    "agent.pipeline.generate_baseline": ["card", "deps", "llm"],
    "agent.pipeline.edit": ["prev", "instruction", "deps", "on_progress"],
    "agent.pipeline.prepare_today": ["date", "deps", "runs_dir", "on_progress", "card_map"],
    "agent.pipeline.run": ["text", "form", "deps", "on_progress"],
    "agent.runs.prepared_post": ["store_id", "date", "card_id", "model_id", "runs_dir"],
    "agent.runs.latest_run": ["card_id", "runs_dir"],
    "agent.runs.clear_prepared": ["date", "runs_dir"],
    "agent.fact_cache.clear_fact_cache": ["day"],
    "agent.formatter.render_publishable": ["post"],
    "agent.formatter.render_report": ["r"],
}

FIELDS = {
    "agent.schemas.RunResult": ["task", "model", "post", "report", "pending", "sources", "timings", "loops", "fallback"],
    "agent.schemas.Clarification": ["questions", "partial"],
    "agent.schemas.Question": ["slot", "text", "options"],
    "agent.schemas.NeedsHuman": ["conflicts", "message"],
    "agent.schemas.LockedResult": ["card", "reason", "message"],
    "agent.schemas.EditBlocked": ["instruction", "message", "rule", "prev"],
    "agent.schemas.BaselineResult": ["card_id", "model_id", "platform", "prompt", "text", "display_text", "hits",
                                     "label", "is_baseline"],
    "agent.schemas.NeedsReview": ["card", "draft", "failing", "message", "attempts"],
    "agent.schemas.FailingSentence": ["field", "sentence", "stage", "code", "reason"],
    "agent.pipeline.BatchResult": ["results", "similarity", "regenerated", "seconds", "regen_seconds", "wall_seconds"],
    "agent.pipeline.SimilarityPair": ["segment", "store_a", "store_b", "before", "after", "regenerated"],
    "agent.pipeline.PreparedDay": ["date", "batch", "paths", "locked", "errors"],
    "agent.schemas.RecommendationCard": ["card_id", "store_id", "store_name", "date", "slot", "slot_label", "model_id",
                                         "display_name", "platform", "segment_label", "angle", "hook", "voice",
                                         "landmark", "reasons", "locked", "locked_reason", "promo",
                                         "question", "is_default"],
    "agent.schemas.CardReason": ["text", "source", "is_demo"],
}


def _obj(path: str):
    mod, name = path.rsplit(".", 1)
    return getattr(importlib.import_module(mod), name)


@pytest.mark.parametrize("path,params", FUNCTIONS.items())
def test_function_exists_with_documented_parameters(path, params):
    fn = _obj(path)
    assert callable(fn), path
    assert list(inspect.signature(fn).parameters)[:len(params)] == params, path


@pytest.mark.parametrize("path,fields", FIELDS.items())
def test_result_type_has_documented_fields(path, fields):
    have = {f.name for f in dataclasses.fields(_obj(path))}
    assert set(fields) <= have, f"{path} is missing {sorted(set(fields) - have)}"


def test_every_documented_name_is_in_the_contract_doc():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[1] / "docs" / "UI_BACKEND_CONTRACT.md").read_text(encoding="utf-8")
    for path in FUNCTIONS:
        assert f"`{path}`" in doc, path
    for path in FIELDS:
        assert path.rsplit(".", 1)[1] in doc, path


def test_labels_the_ui_shows_are_stable():
    from agent.pipeline import LOCKED_MESSAGES
    from agent.recommend.explain import DEMO_RELEASE_REASON
    from agent.schemas import BASELINE_LABEL, NeedsReview
    assert LOCKED_MESSAGES["fact_card_draft"] == "新品资料待总部确认，暂不可生成"
    assert BASELINE_LABEL == "对照组：未经约束的普通大模型输出"
    assert DEMO_RELEASE_REASON == "总部新品推送（演示流程）"
    assert NeedsReview.__dataclass_fields__["message"].default.startswith("需人工确认")


def test_stored_record_keys(tmp_path):
    from agent.pipeline import Deps, prepare_today, run_from_card
    from agent.recommend.store_data import default_card, reload
    from agent.runs import latest_run, log_run, prepared_post
    reload()
    card = dataclasses.replace(default_card("S01", "2026-10-21"), model_id="demobook-14")
    log_run(card, run_from_card(card, Deps.fake()), runs_dir=tmp_path)
    run_keys = {"card_id", "store_id", "store_name", "staff", "scenario", "model", "platform", "temperatures",
                "kind", "timestamp", "result"}
    assert run_keys <= set(latest_run(card.card_id, runs_dir=tmp_path))
    prepare_today("2026-10-21", Deps.fake(), runs_dir=tmp_path,
                  card_map=lambda c: dataclasses.replace(c, model_id="demobook-14"))
    rec = prepared_post("S01", "2026-10-21", card_id=card.card_id, runs_dir=tmp_path)
    prep_keys = {"kind", "card_id", "store_id", "store_name", "date", "slot", "model", "card", "status", "passed",
                 "rewrites", "seconds", "similarity", "regenerated", "dev_mode", "temperatures", "timestamp", "result"}
    assert prep_keys <= set(rec)
