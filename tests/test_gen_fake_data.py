"""Phase 4: gen_fake_data --check-only must print the sanity table and write nothing."""
from __future__ import annotations

from pathlib import Path

import scripts.gen_fake_data as gen


def test_check_only_does_not_touch_generated_files(monkeypatch, capsys):
    generated = Path(gen.OUT)
    watched = [generated / "today_cards.json", generated / "summary.txt", generated / "store_signals.json"]
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.exists()}
    monkeypatch.setattr("sys.argv", ["gen_fake_data.py", "--check-only"])
    gen.main()
    out = capsys.readouterr().out
    assert "All checks passed." in out and "check-only: no files were written." in out
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.exists()}
    assert before == after
