"""K1: the KB mirror (kb_snapshot/) is not in the repo. A missing mirror must give a clear message or fall
back to live ima when credentials exist, never a crash. No ima calls: ImaClient is only constructed."""
from __future__ import annotations

import pytest

import agent.ima_wrapper as w
from agent.pipeline import Deps


@pytest.fixture
def no_mirror(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_LOCAL_DIR", str(tmp_path / "missing"))
    return tmp_path


def test_local_backend_without_mirror_raises_a_clear_message(no_mirror, monkeypatch):
    with pytest.raises(w.ImaError) as e:
        w.make_client("local")
    assert e.value.msg == w.MIRROR_MISSING and "README" in e.value.msg and "拷贝" in e.value.msg


def test_hybrid_without_mirror_falls_back_to_live_ima_when_configured(no_mirror, monkeypatch, caplog):
    monkeypatch.setattr(w, "_configured", lambda: True)
    with caplog.at_level("WARNING", logger="agent.ima_wrapper"):
        client = w.make_client("hybrid")
    assert isinstance(client, w.ImaClient) and client.live_calls == 0 and "mirror missing" in caplog.text


def test_hybrid_without_mirror_or_credentials_raises_the_message(no_mirror, monkeypatch):
    monkeypatch.setattr(w, "_configured", lambda: False)
    with pytest.raises(w.ImaError) as e:
        w.make_client("hybrid")
    assert e.value.msg == w.MIRROR_MISSING


def test_deps_auto_degrades_to_dev_mode_and_shows_why(no_mirror, monkeypatch):
    monkeypatch.setenv("KB_BACKEND", "local")
    d = Deps.auto()
    assert d.is_dev_mode and d.status()["error"] == w.MIRROR_MISSING


@pytest.mark.parametrize("module", ["scripts.eval_cards", "scripts.demo_scenes", "scripts.check_canary"])
def test_real_dep_scripts_print_the_reason_instead_of_crashing(module, no_mirror, monkeypatch, capsys):
    import importlib
    monkeypatch.setenv("RUN_E2E", "1")
    monkeypatch.setenv("KB_BACKEND", "local")
    mod = importlib.import_module(module)
    assert mod.main(["--today", "2026-10-23"]) == 2
    assert "本地知识库镜像不存在" in capsys.readouterr().out
