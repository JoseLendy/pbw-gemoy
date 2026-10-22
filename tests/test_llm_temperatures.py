"""Two-temperature design (plan §6.2): facts locked at 0, only the writer is creative.

Env: FACT_TEMPERATURE (0), WRITER_TEMPERATURE (0.85), CHECK_TEMPERATURE (0).
A model that rejects the temperature parameter must be sent without it (logged once), never crash.
"""
from __future__ import annotations

import logging

import pytest

from agent.llm import LLM, temperature_for, temperatures

ENV_KEYS = ("FACT_TEMPERATURE", "WRITER_TEMPERATURE", "CHECK_TEMPERATURE")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


# ------------------------------------------------------------------ defaults
def test_defaults_are_0_085_0():
    assert temperatures() == {"fact": 0.0, "writer": 0.85, "check": 0.0}


@pytest.mark.parametrize("stage", ["writer", "rewrite", "baseline"])
def test_writer_stages_are_creative(stage):
    assert temperature_for(stage) == 0.85


@pytest.mark.parametrize("stage", ["ledger", "ledger_claims", "intake", "scenario", "reconcile", "extract", ""])
def test_fact_stages_are_zero(stage):
    assert temperature_for(stage) == 0.0


@pytest.mark.parametrize("stage", ["8A", "8B", "8C", "8D", "8E", "check", "check_facts", "check_compliance"])
def test_check_stages_are_zero(stage):
    assert temperature_for(stage) == 0.0


def test_stage_case_and_suffix_are_normalised():
    assert temperature_for("Writer") == 0.85
    assert temperature_for("writer:retry") == 0.85
    assert temperature_for("8d:judge") == 0.0


# ------------------------------------------------------------------ env overrides
def test_env_overrides_each_bucket(monkeypatch):
    monkeypatch.setenv("FACT_TEMPERATURE", "0.1")
    monkeypatch.setenv("WRITER_TEMPERATURE", "0.5")
    monkeypatch.setenv("CHECK_TEMPERATURE", "0.05")
    assert temperatures() == {"fact": 0.1, "writer": 0.5, "check": 0.05}
    assert temperature_for("writer") == 0.5
    assert temperature_for("8A") == 0.05
    assert temperature_for("ledger") == 0.1


def test_explicit_override_beats_env(monkeypatch):
    monkeypatch.setenv("WRITER_TEMPERATURE", "0.5")
    assert temperature_for("writer", override=1.2) == 1.2


# ------------------------------------------------------------------ bad values never crash
def test_non_numeric_env_falls_back(monkeypatch, caplog):
    monkeypatch.setenv("WRITER_TEMPERATURE", "hot")
    with caplog.at_level(logging.WARNING, logger="agent.llm"):
        assert temperature_for("writer") == 0.85
    assert any("WRITER_TEMPERATURE" in r.message for r in caplog.records)


def test_out_of_range_env_falls_back(monkeypatch):
    monkeypatch.setenv("CHECK_TEMPERATURE", "7")
    assert temperature_for("8B") == 0.0


def test_empty_env_is_the_default(monkeypatch):
    monkeypatch.setenv("FACT_TEMPERATURE", "  ")
    assert temperature_for("ledger") == 0.0


# ------------------------------------------------------------------ model rejects temperature
class _StubCompletions:
    """Fails the first call with a temperature error, succeeds after the parameter is dropped."""

    def __init__(self):
        self.params: list[dict] = []

    def create(self, **params):
        self.params.append(dict(params))
        if "temperature" in params:
            raise RuntimeError("400 invalid_request_error: temperature is not supported by this model")
        msg = type("M", (), {"content": "{}"})()
        choice = type("C", (), {"message": msg})()
        return type("R", (), {"choices": [choice]})()


def _llm_with(completions: _StubCompletions) -> LLM:
    llm = object.__new__(LLM)          # bypass __init__: no env, no network client
    llm._client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    llm.model = llm.model_fast = "stub-model"
    llm._json_mode_ok = {}
    llm._temperature_ignored = False
    llm.timings, llm.calls = {}, []
    return llm


def test_model_that_rejects_temperature_is_retried_without_it(caplog):
    comp = _StubCompletions()
    llm = _llm_with(comp)
    with caplog.at_level(logging.WARNING, logger="agent.llm"):
        out = llm.chat_json("s", "u", stage="writer")
    assert out == {}
    assert "temperature" in comp.params[0] and "temperature" not in comp.params[-1]
    assert llm._temperature_ignored is True
    assert sum("rejects temperature" in r.message for r in caplog.records) == 1


def test_temperature_is_dropped_for_later_calls_too():
    comp = _StubCompletions()
    llm = _llm_with(comp)
    llm.chat_json("s", "u", stage="writer")
    n = len(comp.params)
    llm.chat_json("s", "u", stage="ledger")
    assert all("temperature" not in p for p in comp.params[n:])


def test_other_errors_still_raise():
    class _Boom(_StubCompletions):
        def create(self, **params):
            raise RuntimeError("500 upstream exploded")

    with pytest.raises(RuntimeError, match="upstream exploded"):
        _llm_with(_Boom()).chat_json("s", "u", stage="writer")
