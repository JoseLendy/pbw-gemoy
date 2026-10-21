"""
Per-stage wall-clock timing for one run (Phase 5, L1).

    with collect(timings):           # pipeline: bind the run's RunResult.timings dict
        with stage("check.8A"): ...  # anywhere below: seconds are added to that dict

Context-local (contextvars), so concurrent store runs in generate_batch never mix their numbers. Outside
collect() stage() is a no-op, so checks and the writer can be called directly (tests, the UI) unchanged.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_CURRENT: ContextVar[Optional[dict]] = ContextVar("agent_timing", default=None)


@contextmanager
def collect(timings: dict) -> Iterator[dict]:
    token = _CURRENT.set(timings)
    try:
        yield timings
    finally:
        _CURRENT.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        add(name, time.perf_counter() - t0)


def add(name: str, seconds: float) -> None:
    d = _CURRENT.get()
    if d is not None:
        d[name] = round(d.get(name, 0.0) + seconds, 3)


def current() -> Optional[dict]:
    return _CURRENT.get()


__all__ = ["collect", "stage", "add", "current"]
