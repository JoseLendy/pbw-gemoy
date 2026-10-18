"""ImaClient over `node ima-skill/ima_api.cjs`, with subprocess mocked. Never calls ima."""
import json
import os
import subprocess
import time

import pytest

from agent import ima_wrapper
from agent.ima_wrapper import ImaClient, ImaError

FAKE_CID, FAKE_KEY = "cid-SECRET-1234567", "key-SECRET-7654321"


class Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def ok(data):
    return Proc(0, json.dumps({"code": 0, "msg": "", "data": data}))


@pytest.fixture
def run(monkeypatch):
    """Queue of fake subprocess results; records argv and env of every call."""
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", FAKE_CID)
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", FAKE_KEY)
    monkeypatch.setattr(ima_wrapper.time, "sleep", lambda s: None)
    q = {"results": [], "argv": [], "env": [], "kw": []}

    def fake_run(argv, **kw):
        q["argv"].append(argv)
        q["env"].append(kw.get("env") or {})
        q["kw"].append(kw)
        return q["results"].pop(0)

    monkeypatch.setattr(ima_wrapper.subprocess, "run", fake_run)
    return q


@pytest.fixture
def client(tmp_path):
    return ImaClient(cache_dir=str(tmp_path / "ima"))


def test_api_error_code_in_stdout_raises(run, client):
    run["results"] = [Proc(0, json.dumps({"code": 110001, "msg": "bad", "data": {}}))]
    with pytest.raises(ImaError) as e:
        client.call("get_knowledge_list", {"knowledge_base_id": "kb"})
    assert e.value.code == 110001 and e.value.api.endswith("get_knowledge_list")


def test_update_available_retries_exactly_once(run, client, caplog):
    upd = Proc(1, json.dumps({"latest_version": "9.9.9"}), json.dumps({"code": -200, "msg": "发现新版本"}))
    run["results"] = [upd, ok({"knowledge_list": [], "is_end": True})]
    with caplog.at_level("WARNING"):
        data = client.call("get_knowledge_list", {"knowledge_base_id": "kb"})
    assert data["is_end"] is True and len(run["argv"]) == 2
    assert "ima skill 有新版本" in caplog.text


def test_update_available_twice_raises(run, client):
    upd = Proc(1, "", json.dumps({"code": -200, "msg": "发现新版本"}))
    run["results"] = [upd, upd]
    with pytest.raises(ImaError) as e:
        client.call("get_knowledge_list", {"knowledge_base_id": "kb"})
    assert e.value.code == -200 and len(run["argv"]) == 2


def test_script_failure_stderr_raises(run, client):
    run["results"] = [Proc(1, "", json.dumps({"code": -100, "msg": "missing credentials"}))]
    with pytest.raises(ImaError) as e:
        client.call("search_knowledge_base", {"query": "x"})
    assert e.value.code == -100


def test_quota_serves_stale_cache(run, client):
    body = {"knowledge_base_id": "kb", "limit": 50, "cursor": ""}
    cp = client._cache_path("openapi/wiki/v1/get_knowledge_list", body)
    cp.write_text(json.dumps({"knowledge_list": [{"title": "cached"}], "is_end": True}), "utf-8")
    old = time.time() - 3 * 86400
    os.utime(cp, (old, old))
    run["results"] = [Proc(0, json.dumps({"code": 220021, "msg": "资料获取次数已达上限"}))]
    data = client.call("get_knowledge_list", body)
    assert data["knowledge_list"][0]["title"] == "cached"
    assert client.stale_served and client.call_log[-1]["stale"] is True
    assert "上限" in client.status()["error"]


def test_quota_without_cache_raises(run, client):
    run["results"] = [Proc(0, json.dumps({"code": 220021, "msg": "资料获取次数已达上限"}))]
    with pytest.raises(ImaError) as e:
        client.call("get_knowledge_list", {"knowledge_base_id": "kb"})
    assert e.value.code == 220021 and len(run["argv"]) == 1   # never retried


def test_quota_stops_further_live_calls(run, client):
    run["results"] = [Proc(0, json.dumps({"code": 220021, "msg": "资料获取次数已达上限"}))]
    with pytest.raises(ImaError):
        client.media_info("m1")
    with pytest.raises(ImaError) as e:
        client.media_info("m2")
    assert e.value.code == 220021 and len(run["argv"]) == 1 and client.live_calls == 1


def test_rate_limit_backs_off_and_retries_twice(run, client):
    rl = Proc(0, json.dumps({"code": 110021, "msg": "rate limited"}))
    run["results"] = [rl, rl, ok({"is_end": True})]
    assert client.call("get_knowledge_list", {"knowledge_base_id": "kb"}) == {"is_end": True}
    run["results"] = [rl, rl, rl]
    with pytest.raises(ImaError):
        client.call("search_knowledge", {"query": "y", "knowledge_base_id": "kb"})


def test_fresh_cache_hit_makes_no_call(run, client):
    run["results"] = [ok({"knowledge_list": [], "is_end": True})]
    body = {"knowledge_base_id": "kb"}
    client.call("get_knowledge_list", body)
    client.call("get_knowledge_list", body)
    assert len(run["argv"]) == 1 and client.call_log[-1]["cached"] is True


def test_argv_never_contains_keys_and_env_is_inherited(run, client):
    run["results"] = [ok({"is_end": True})]
    client.call("get_knowledge_list", {"knowledge_base_id": "kb"})
    argv, env, kw = run["argv"][0], run["env"][0], run["kw"][0]
    assert argv[0] == "node" and argv[1].endswith("ima-skill/ima_api.cjs")
    assert argv[2] == "openapi/wiki/v1/get_knowledge_list" and isinstance(argv, list)
    assert not any(FAKE_CID in a or FAKE_KEY in a for a in argv)
    assert env["IMA_OPENAPI_CLIENTID"] == FAKE_CID
    assert env["IMA_LAST_CHECK_FILE"].endswith("last_update_check") and ".cache" in env["IMA_LAST_CHECK_FILE"] \
        or env["IMA_LAST_CHECK_FILE"].startswith(str(client.cache_dir))
    assert kw.get("shell") in (None, False) and kw.get("timeout") == 30


def test_media_info_never_cached(run, client):
    info = {"media_type": 9, "url_info": {"url": "https://example.com/x?sign=1&t=2", "headers": {}}}
    run["results"] = [ok(info), ok(info)]
    client.media_info("m1")
    client.media_info("m1")
    assert len(run["argv"]) == 2
    assert list(client.cache_dir.glob("*.json")) == []


def test_call_log_and_status_hold_no_ids_or_keys(run, client):
    run["results"] = [ok({"is_end": True})]
    client.call("get_knowledge_list", {"knowledge_base_id": "kb-secret-id", "folder_id": "folder_9"})
    entry = client.call_log[-1]
    assert set(entry) == {"api", "cached", "stale", "ok", "ts"}
    dump = json.dumps(client.call_log) + json.dumps(client.status())
    for s in ("kb-secret-id", "folder_9", FAKE_CID, FAKE_KEY, FAKE_CID[:4], FAKE_KEY[-4:]):
        assert s not in dump
    assert client.status()["configured"] is True


def test_unconfigured_raises_without_subprocess(run, client, monkeypatch):
    for k in ("IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY", "IMA_CLIENT_ID", "IMA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ImaError):
        client.call("get_knowledge_list", {"knowledge_base_id": "kb"})
    assert run["argv"] == [] and client.status()["configured"] is False


def test_timeout_becomes_ima_error(monkeypatch, client):
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", FAKE_CID)
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", FAKE_KEY)

    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 30)

    monkeypatch.setattr(ima_wrapper.subprocess, "run", boom)
    with pytest.raises(ImaError) as e:
        client.media_info("m1")
    assert e.value.code == -100
