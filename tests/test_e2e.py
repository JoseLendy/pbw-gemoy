"""
End-to-end on the real modules and the real KB. Runs only with RUN_E2E=1 (integration time, P5 only).
Keeps ima calls minimal: one model, cache makes repeats free. Never prints keys or ids.
"""
from __future__ import annotations

import os

import pytest

from agent.schemas import RunResult, SECTION_HEADINGS

pytestmark = pytest.mark.skipif(os.getenv("RUN_E2E") != "1", reason="set RUN_E2E=1 to run against ima + LLM")

MODEL_TEXT = os.getenv("E2E_TEXT", "一位妈妈想给下个月上大学的女儿买 MateBook 14 酷睿 Ultra，发小红书")


def test_e2e_one_real_model_xiaohongshu():
    from agent.formatter import render_report
    from agent.pipeline import Deps, run

    deps = Deps.real()
    assert not deps.is_dev_mode
    lines: list[str] = []
    r = run(MODEL_TEXT, deps=deps, on_progress=lambda s, m: lines.append(f"[{s}] {m}"))
    print("\n".join(lines))
    assert isinstance(r, RunResult), getattr(r, "message", r)
    md = render_report(r)
    for h in SECTION_HEADINGS:
        assert f"## {h}" in md
    assert r.post.platform == "xiaohongshu"
    for fid in r.post.selling_points:
        assert r.ledger.get(fid) is not None
    print("timings:", r.timings)
    print("pending:", r.pending)
    print("passed:", r.report.passed, "loops:", r.loops)
