"""Regression tests for the queue freeze: page load / store switch must bypass the slow-generation
pool, localhost must not go through the system proxy, and the KB status check must never block a
page-load request."""
import os
import threading
import time


def test_queue_has_a_bounded_generation_pool_and_local_bypass():
    import app
    demo = app.build()
    assert demo._queue is not None
    assert demo._queue.default_concurrency_limit == app.GEN_CONCURRENCY
    assert app.GEN_CONCURRENCY >= 2

    generation = [d for d in demo.fns.values() if d.concurrency_id == "generation"]
    assert generation, "generate/edit/compare events must share the generation pool"
    assert all(d.concurrency_limit == app.GEN_CONCURRENCY for d in generation)

    # Gradio's own helpers (Examples.load_example, State init) inherit the default of 4, never 1.
    # Every local event we wire ourselves must bypass the queue entirely.
    local_names = {"on_initial", "on_store_change", "on_switch_toggle", "on_show_recovery",
                   "on_publish", "on_download_text", "on_download"}
    local = [d for d in demo.fns.values() if getattr(d.fn, "__name__", "") in local_names]
    assert len(local) == len(local_names)
    assert all(d.concurrency_limit is None for d in local), \
        "local-only events must not wait behind a running generation"


def test_page_load_and_store_switch_bypass_the_queue():
    import app
    demo = app.build()

    def limits(fn_name):
        return [d.concurrency_limit for d in demo.fns.values()
                if getattr(d.fn, "__name__", "") == fn_name]

    assert limits("on_initial") == [None]
    assert limits("on_store_change") == [None]


def test_kb_status_returns_immediately_then_refreshes(monkeypatch):
    import app
    started, release = threading.Event(), threading.Event()

    def slow_status():
        started.set()
        release.wait(2)
        return {"kb_name": "test-kb", "connected": True, "configured": True,
                "index_status": "complete", "error": None}

    monkeypatch.setattr(app.DEPS, "status", slow_status)
    with app._STATUS_LOCK:
        app._STATUS_STATE.update(data=None, ts=0.0, inflight=False)

    t0 = time.perf_counter()
    snapshot = app.kb_status()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.2, f"kb_status blocked for {elapsed:.2f}s"
    assert snapshot["index_status"] == "checking"
    assert "连接中" in app.status_html()
    assert started.wait(1), "the status refresh thread never started"

    release.set()
    for _ in range(100):
        if app._STATUS_STATE["data"] is not None:
            break
        time.sleep(0.02)
    assert app._STATUS_STATE["data"]["connected"] is True

    with app._STATUS_LOCK:   # don't leak this fake status into other tests
        app._STATUS_STATE.update(data=None, ts=0.0, inflight=False)


def test_localhost_bypasses_the_system_proxy():
    import app  # noqa: F401 - import installs the NO_PROXY entries
    for var in ("NO_PROXY", "no_proxy"):
        hosts = {h.strip() for h in os.environ.get(var, "").split(",")}
        assert {"127.0.0.1", "localhost", "::1"} <= hosts
