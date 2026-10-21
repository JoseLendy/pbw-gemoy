"""Phase 5 latency work: L1 per-stage timing, L2 per-product fact cache, L3 parallel batch, LLM retry.
Fakes only; no ima or LLM."""
from __future__ import annotations

import dataclasses
import threading
import time

import pytest

import agent.fact_cache as fc
from agent import timing
from agent.pipeline import Deps, generate_batch, run_from_card
from agent.recommend.store_data import cards_for, default_card, reload, reset_demo_state, set_fact_card_status
from agent.schemas import CardHook, LockedResult, RunResult
from tests.fakes import fake_bundle, fake_ledger, fake_post

TODAY = "2026-10-21"


@pytest.fixture(autouse=True)
def _clean():
    reload()
    yield
    reload()


def demo_card(store_id, model_id="demobook-14", **kw):
    card = default_card(store_id, TODAY)
    return dataclasses.replace(card, model_id=model_id, display_name=model_id, **kw)


def counting_deps():
    deps = Deps.fake()
    calls = {"bundle": [], "ledger": []}

    def get_bundle(model_id, catalog=None):
        calls["bundle"].append(model_id)
        return fake_bundle(model_id)

    def build_ledger(bundle, llm=None, use_cache=True):
        calls["ledger"].append(bundle.model.model_id)
        return fake_ledger(bundle.model.model_id)

    deps.get_bundle, deps.build_ledger = get_bundle, build_ledger
    return deps, calls


# ------------------------------------------------------------------ L1 timing
def test_run_records_per_stage_seconds():
    r = run_from_card(demo_card("S01"), Deps.fake())
    t = r.timings
    for key in ("retrieval", "ledger", "analyze", "reconcile", "write", "check", "total", "check.pass1"):
        assert key in t, key
    assert t["total"] >= t["check"] >= 0


def test_check_stages_are_timed_inside_run_all():
    from agent.checks import run_all
    from tests.fakes import fake_plan, fake_task
    out = {}
    with timing.collect(out):
        run_all(fake_post("moments"), fake_ledger(), {}, fake_task("moments"), fake_plan("moments"))
    assert {"check.8A", "check.8B", "check.8C", "check.8D"} <= set(out)


def test_stage_outside_a_run_is_a_no_op():
    with timing.stage("x"):
        pass
    assert timing.current() is None


# ------------------------------------------------------------------ L2 fact cache
def test_second_store_same_model_makes_no_retrieval_or_ledger_calls():
    deps, calls = counting_deps()
    run_from_card(demo_card("S01"), deps)
    first = (list(calls["bundle"]), list(calls["ledger"]))
    assert "demobook-14" in first[0] and "demobook-14-se" in first[0]      # target + sibling
    run_from_card(demo_card("S04"), deps)
    assert (calls["bundle"], calls["ledger"]) == first


def test_different_models_do_not_share_entries():
    deps, calls = counting_deps()
    run_from_card(demo_card("S01", "demobook-14"), deps)
    a, b = fc.get_facts(deps, "demobook-14", TODAY), fc.get_facts(deps, "demobook-14-se", TODAY)
    assert a[1].model_id == "demobook-14" and b[1].model_id == "demobook-14-se"
    assert a[0].model.model_id != b[0].model.model_id


def test_dates_do_not_share_entries():
    deps, calls = counting_deps()
    fc.get_facts(deps, "demobook-14", "2026-10-21")
    fc.get_facts(deps, "demobook-14", "2026-10-22")
    assert calls["bundle"].count("demobook-14") == 2


def test_cache_hands_out_copies():
    deps, _ = counting_deps()
    _, led = fc.get_facts(deps, "demobook-14", TODAY)
    led.facts.clear()
    assert fc.get_facts(deps, "demobook-14", TODAY)[1].facts


def test_fact_card_status_still_gates_locked_cards_with_a_warm_cache():
    deps, calls = counting_deps()
    mid = next(c for c in cards_for("S01", TODAY) if c.slot == "new_release").model_id
    set_fact_card_status(mid, "verified")
    reset_demo_state()                                       # back to draft
    card = next(c for c in cards_for("S01", TODAY) if c.slot == "new_release")
    fc.get_facts(deps, "demobook-14", TODAY)                 # cache warm for the model we point it at
    n = len(calls["bundle"])
    res = run_from_card(dataclasses.replace(card, model_id="demobook-14"), deps)
    assert isinstance(res, LockedResult) and len(calls["bundle"]) == n


def test_reset_demo_state_keeps_and_clear_fact_cache_drops_real_entries(tmp_path, monkeypatch):
    import agent.runs as runs
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path)
    deps, calls = counting_deps()
    deps.fake_fields = []                                    # behave like real deps: global + disk cache
    try:
        fc.get_facts(deps, "demobook-14", TODAY)
        assert (tmp_path / "cache" / TODAY / "demobook-14.pkl").exists()
        reset_demo_state()
        fc._REAL.clear()                                     # a new process: the disk copy is reused
        fc.get_facts(deps, "demobook-14", TODAY)
        assert calls["bundle"] == ["demobook-14"]
        assert fc.clear_fact_cache(TODAY) >= 1
        assert not (tmp_path / "cache" / TODAY).exists()
        fc.get_facts(deps, "demobook-14", TODAY)
        assert calls["bundle"] == ["demobook-14", "demobook-14"]
    finally:
        fc.clear_fact_cache()


# ------------------------------------------------------------------ L3 parallel batch
def _slow_writer(order: list, lock=threading.Lock()):
    def write(task, strategy, ledger, plan, llm=None):
        time.sleep(0.05 if task.store_id == "S01" else 0.0)   # S01 finishes last
        with lock:
            order.append(task.store_id)
        p = fake_post("moments")
        p.body = [f"{task.store_id} 独有的一段文案，重量约 1.25 kg [F1]。"]
        return p
    return write


def test_batch_runs_concurrently_and_keeps_input_order(monkeypatch):
    monkeypatch.setenv("BATCH_MAX_WORKERS", "4")
    deps = Deps.fake()
    finished: list = []
    deps.write_post = _slow_writer(finished)
    sids = ["S01", "S04", "S08", "S02"]
    batch = generate_batch([demo_card(s) for s in sids], deps)
    assert list(batch.results) == sids
    first_pass = finished[:len(sids)]                         # later entries are 8E regenerations
    assert sorted(first_pass) == sorted(sids) and first_pass[-1] == "S01"   # ran alongside the others
    assert all(isinstance(r, RunResult) for r in batch.results.values())
    assert batch.wall_seconds < sum(batch.seconds.values()) + 0.05


def test_one_store_failure_does_not_kill_the_batch(monkeypatch):
    monkeypatch.setenv("BATCH_MAX_WORKERS", "4")
    deps = Deps.fake()
    base = deps.write_post

    def write(task, strategy, ledger, plan, llm=None):
        if task.store_id == "S04":
            raise RuntimeError("provider down")
        return base(task, strategy, ledger, plan, llm)

    deps.write_post = write
    batch = generate_batch([demo_card(s) for s in ("S01", "S04", "S08")], deps)
    assert isinstance(batch.results["S04"], RuntimeError)
    assert isinstance(batch.results["S01"], RunResult) and isinstance(batch.results["S08"], RunResult)


@pytest.mark.parametrize("workers", ["1", "4"])
def test_8e_still_regenerates_the_later_peer_once(monkeypatch, workers):
    monkeypatch.setenv("BATCH_MAX_WORKERS", workers)
    deps = Deps.fake()

    def write(task, strategy, ledger, plan, llm=None):
        p = fake_post("moments")
        p.body = [f"同一段通用文案 {task.hook} {task.angle}"]
        return p

    deps.write_post = write
    cards = [demo_card(s, hook=CardHook("myth", "误区澄清"), angle="同一角度") for s in ("S01", "S02", "S03")]
    batch = generate_batch(cards, deps)
    assert batch.regenerated and "S01" not in batch.regenerated
    assert len(batch.regenerated) == len(set(batch.regenerated))
    assert set(batch.regen_seconds) <= set(batch.regenerated)


# ------------------------------------------------------------------ LLM 429 / timeout retry
class _Transient(Exception):
    status_code = 429


def _llm_with(responses):
    from agent.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = llm.model_fast = "m"
    llm.timings, llm.calls, llm._json_mode_ok = {}, [], {}
    llm._temperature_ignored, llm.rate_retries = False, 0
    seq = list(responses)

    class _Create:
        def create(self, **params):
            r = seq.pop(0)
            if isinstance(r, Exception):
                raise r

            class _Msg:
                content = r
            return type("R", (), {"choices": [type("C", (), {"message": _Msg})]})

    llm._client = type("Cl", (), {"chat": type("Ch", (), {"completions": _Create()})})
    return llm


def test_rate_limit_is_retried_with_backoff_and_logged(monkeypatch, caplog):
    import agent.llm as llm_mod
    monkeypatch.setattr(llm_mod, "RATE_BACKOFF", (0.0, 0.0))
    llm = _llm_with([_Transient("429 too many"), '{"ok": 1}'])
    with caplog.at_level("WARNING", logger="agent.llm"):
        assert llm.chat_json("s", "u", stage="writer") == {"ok": 1}
    assert llm.rate_retries == 1 and "retry 1/2" in caplog.text


def test_rate_limit_gives_up_after_two_retries(monkeypatch):
    import agent.llm as llm_mod
    monkeypatch.setattr(llm_mod, "RATE_BACKOFF", (0.0, 0.0))
    llm = _llm_with([_Transient("429"), _Transient("429"), _Transient("429"), '{"ok": 1}'])
    with pytest.raises(_Transient):
        llm.chat_json("s", "u", stage="writer")
    assert llm.rate_retries == 2


def test_other_errors_are_not_retried(monkeypatch):
    llm = _llm_with([ValueError("bad request"), '{"ok": 1}'])
    with pytest.raises(ValueError):
        llm.chat_json("s", "u", stage="writer")
    assert llm.rate_retries == 0
