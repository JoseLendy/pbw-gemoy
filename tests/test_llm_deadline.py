"""
A stalled LLM response must be cut off at a hard wall-clock deadline.

Incident (prepare_today 2026-10-23): four stores each spent ~3580-3600 s inside ONE LLM call
(llm.8B / llm.reconcile). The httpx timeout the OpenAI SDK uses is per socket read, so an
endpoint that keeps a non-streaming response alive by trickling whitespace never trips it.

These tests reproduce that with a local HTTP server on 127.0.0.1 (no real endpoint, no key):
it sends the headers, then one space every 0.2 s, and only then a valid completion. A real
OpenAI client with a 1 s read timeout happily waits for the whole trickle.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import agent.llm as llm_mod
from agent.llm import LLM, call_deadline

_REAL_LOAD_ENV = llm_mod._load_env     # captured before the autouse fixture replaces it

TRICKLE_SECONDS = 8.0          # how long the fake server stalls before answering
COMPLETION = {
    "id": "x", "object": "chat.completion", "created": 0, "model": "fake-model",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "{\"ok\": true}"}}],
}


def _handler(stop: threading.Event, hits: list):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep pytest output clean
            pass

        def do_POST(self):
            hits.append(time.monotonic())
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.dumps(COMPLETION).encode()
            pad = b" " * int(TRICKLE_SECONDS / 0.2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(pad) + len(body)))
            self.end_headers()
            try:
                for _ in pad:                      # leading whitespace is valid JSON padding
                    if stop.is_set():
                        return
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.2)
                self.wfile.write(body)
            except OSError:
                pass

    return H


@pytest.fixture()
def trickle_server():
    stop, hits = threading.Event(), []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(stop, hits))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1", hits
    stop.set()
    srv.shutdown()
    srv.server_close()


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Never load any .env here: these tests only ever talk to the local fake server."""
    monkeypatch.setattr(llm_mod, "_load_env", lambda: None)


def _llm(base_url: str) -> LLM:
    # read timeout 1 s: far shorter than the stall, and still never fires (bytes keep arriving)
    return LLM(base_url=base_url, api_key="test-not-a-key", model="fake-model", timeout=1.0)


def test_stalled_call_is_cut_off_at_the_deadline(monkeypatch, trickle_server):
    url, hits = trickle_server
    monkeypatch.setenv("LLM_CALL_DEADLINE", "1.5")
    monkeypatch.setattr(llm_mod, "RATE_RETRIES", 0)
    llm = _llm(url)
    t0 = time.monotonic()
    with pytest.raises(Exception) as ei:
        llm.chat_json("s", "u", stage="8B")
    elapsed = time.monotonic() - t0
    assert elapsed < 4.0, f"stalled call ran {elapsed:.1f}s; deadline is 1.5s"
    assert "timeout" in type(ei.value).__name__.lower()       # same class of failure as today
    assert llm.calls[-1]["ok"] is False and llm.calls[-1]["stage"] == "8B"


def test_deadline_timeout_is_retried_then_raises(monkeypatch, trickle_server, caplog):
    url, hits = trickle_server
    monkeypatch.setenv("LLM_CALL_DEADLINE", "1")
    monkeypatch.setattr(llm_mod, "RATE_BACKOFF", (0.0, 0.0))
    llm = _llm(url)
    t0 = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="agent.llm"), pytest.raises(Exception) as ei:
        llm.chat_text("s", "u", stage="writer")
    elapsed = time.monotonic() - t0
    assert type(ei.value).__name__ == "APITimeoutError"
    assert len(hits) == llm_mod.RATE_RETRIES + 1               # every attempt went out
    assert llm.rate_retries == llm_mod.RATE_RETRIES
    assert sum("APITimeoutError" in r.getMessage() and "retry" in r.getMessage()
               for r in caplog.records) == llm_mod.RATE_RETRIES
    assert elapsed < (llm_mod.RATE_RETRIES + 1) * 1.0 + 2.5


def test_fast_answer_is_unaffected(monkeypatch, trickle_server):
    url, _ = trickle_server
    monkeypatch.setattr(llm_mod, "RATE_RETRIES", 0)
    monkeypatch.setenv("LLM_CALL_DEADLINE", "30")
    monkeypatch.setitem(globals(), "TRICKLE_SECONDS", 0.4)      # a slow-ish but healthy answer
    assert _llm(url).chat_json("s", "u", stage="8B") == {"ok": True}


@pytest.mark.parametrize("raw, want", [("", 120.0), ("45", 45.0), ("abc", 120.0), ("0", 120.0),
                                       ("-3", 120.0), ("2.5", 2.5)])
def test_call_deadline_env(monkeypatch, raw, want):
    monkeypatch.setenv("LLM_CALL_DEADLINE", raw)
    assert call_deadline() == want


def test_dotenv_is_the_repo_root_one_only(monkeypatch):
    """A bare load_dotenv() walks up the tree; from a git worktree it finds the main checkout's .env."""
    import pathlib
    import sys
    import types
    seen = []
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: seen.append(a)))
    _REAL_LOAD_ENV()                    # the real function, but with a recording fake python-dotenv
    root = pathlib.Path(llm_mod.__file__).resolve().parent.parent
    assert seen == [(root / ".env",)]
