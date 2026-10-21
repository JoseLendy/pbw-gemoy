"""Phase 5, T5: scripts/check_canary.py. Offline: --fake runs the real check stack on DemoBook."""
from __future__ import annotations

import scripts.check_canary as canary


def test_fake_canary_catches_every_planted_draft_and_passes_the_clean_ones(capsys):
    assert canary.main(["--fake"]) == 0
    out = capsys.readouterr().out
    assert "caught 9/9 planted · false positives 0/2 clean" in out
    assert "LLM_API_KEY" not in out


def test_refuses_real_deps_without_run_e2e(monkeypatch, capsys):
    monkeypatch.delenv("RUN_E2E", raising=False)
    assert canary.main([]) == 2 and "RUN_E2E=1" in capsys.readouterr().out
