"""
Runtime API settings (LLM + ima), editable from the UI (developer only).

Stored in a small JSON file next to the account database, overriding the .env values. Secrets (the LLM
key, ima client id and ima key) are never returned by ``public()`` — the UI only sees a configured flag.
Saving a blank secret keeps the current value; a non-blank one replaces it. After a save the live LLM
client is rebuilt (ima credentials are read fresh from the env on every call, so they need no reload).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = Path(os.getenv("APP_SETTINGS_PATH") or (ROOT / "data" / "api_settings.json"))

# field key -> env var name
_ENV = {
    "base_url": "LLM_BASE_URL",
    "api_key": "LLM_API_KEY",
    "model": "LLM_MODEL",
    "ima_client_id": "IMA_OPENAPI_CLIENTID",
    "ima_api_key": "IMA_OPENAPI_APIKEY",
}
_FIELDS = tuple(_ENV)
_SECRETS = ("api_key", "ima_client_id", "ima_api_key")


def load() -> dict:
    """Persisted settings ({} when there is no file / it is unreadable)."""
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return {k: (data.get(k) or "") for k in _FIELDS}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def apply_env_from_file() -> None:
    """Overlay persisted settings onto the environment before Deps.auto() builds the clients."""
    for k, v in load().items():
        if v:
            os.environ[_ENV[k]] = v


def current() -> dict:
    """Effective settings: the persisted file first, else the environment."""
    env = {k: os.environ.get(_ENV[k], "") for k in _FIELDS}
    saved = load()
    return {k: (saved.get(k) or env[k]) for k in _FIELDS}


def save(data: dict) -> dict:
    """Persist new settings and rebuild the live LLM client. A blank secret keeps the current value."""
    cur = current()
    merged = {}
    for k in _FIELDS:
        v = (data.get(k) or "").strip()
        merged[k] = (v if v else cur.get(k, "")) if k in _SECRETS else v
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    for k, v in merged.items():
        if v:
            os.environ[_ENV[k]] = v
    _reload_llm()
    return merged


def public() -> dict:
    """What the UI may see: never the secret values, only whether they are configured."""
    cur = current()
    return {
        "base_url": cur["base_url"],
        "model": cur["model"],
        "key_configured": bool(cur["api_key"]),
        "ima_configured": bool(cur["ima_client_id"] and cur["ima_api_key"]),
    }


def _reload_llm() -> None:
    """Rebuild the LLM client in-place from the new environment."""
    import agent.llm as llm_mod
    from agent.ui_data import DEPS
    DEPS.llm = llm_mod.LLM()
