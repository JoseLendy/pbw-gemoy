"""B2: scripts/freeze_check.py helpers. The full script runs the suite itself, so only the cheap checks
are exercised here."""
from __future__ import annotations

import scripts.freeze_check as fc


def test_placeholder_pattern():
    assert fc.PLACEHOLDER_RE.search('name = "MODEL_A"') and fc.PLACEHOLDER_RE.search("<型号名，从catalog填写>")
    assert not fc.PLACEHOLDER_RE.search('os.environ.get("LLM_MODEL_FAST")')


def test_secret_patterns_catch_key_shapes_but_not_ordinary_text():
    hit = lambda t: any(r.search(t) for r in fc.SECRET_RES)       # noqa: E731
    fake_key = "sk" + "-" + "abcdefghijklmnopqrstuv"            # built at run time: no literal key-like token in
    fake_hex = "0123456789abcdef" * 2                            # this file, so the secrets scan stays strict
    assert hit(f"LLM_API_KEY='{fake_key}'") and hit(f"id {fake_hex}")
    assert not hit("重量约 1.25 kg [F1]") and not hit("WRITER_TEMPERATURE=0.85")


def test_kb_snapshot_is_not_tracked():
    mark, _ = fc.check_kb_untracked("2026-10-23")
    assert mark == fc.OK


def test_labels_come_out_of_the_backend():
    mark, detail = fc.check_labels("2026-10-23")
    assert mark == fc.OK, detail
