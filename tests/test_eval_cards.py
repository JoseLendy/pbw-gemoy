"""Task 9: scripts/eval_cards.py. Offline only: --fake mode and pure helpers; real deps need RUN_E2E=1."""
from __future__ import annotations

import pytest

import scripts.eval_cards as ev


def test_refuses_real_deps_without_run_e2e(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("RUN_E2E", raising=False)
    assert ev.main(["--out", str(tmp_path / "r.md")]) == 2
    assert "RUN_E2E=1" in capsys.readouterr().out
    assert not (tmp_path / "r.md").exists()


def test_jaccard_basics():
    assert ev.jaccard("背着跑一天也不累", "背着跑一天也不累") == 1.0
    assert ev.jaccard("背着跑一天也不累", "会议室里开一下午") == 0.0
    assert 0 < ev.jaccard("背着跑一天也不累", "背着跑一整天") < 1
    assert ev.jaccard("", "") == 0.0


def test_fake_run_writes_a_complete_report(tmp_path):
    out = tmp_path / "report.md"
    assert ev.main(["--fake", "--today", "2026-10-21", "--out", str(out)]) == 0
    md = out.read_text(encoding="utf-8")
    for s in ("S01", "S12", "8A", "8B", "8C", "8D", "改写轮数", "事实编号", "同客群门店相似度"):
        assert s in md, s
    # peer groups are the dominant segments; campus stores S01-S03 are compared with each other
    assert "**student**" in md and "| S01 | S02 |" in md
    assert "LLM_API_KEY" not in md and "IMA_OPENAPI" not in md


def test_report_flags_high_similarity():
    a = ev.StoreEval("S01", "A", "student", status="ok", stage_pass={s: True for s in ev.STAGES}, text="同样的一段文案内容")
    b = ev.StoreEval("S02", "B", "student", status="ok", stage_pass={s: True for s in ev.STAGES}, text="同样的一段文案内容")
    md = ev.build_report([a, b], "2026-10-21", "test")
    assert "| S01 | S02 | 1.0 ⚠️ |" in md
