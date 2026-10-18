"""
Minimal Python client for the ima OpenAPI (knowledge-base, read-only).

Re-implements the request format of the official ima-skill/ima_api.cjs (v1.1.10):
  POST https://ima.qq.com/<api_path>
  headers: ima-openapi-clientid, ima-openapi-apikey, ima-openapi-ctx, Content-Type
Response envelope: {"code": 0, "msg": "...", "data": {...}}

Credentials are read ONLY from environment variables. Never hard-code them.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

import requests

BASE_URL = os.getenv("IMA_BASE_URL", "https://ima.qq.com")
SKILL_VERSION = "1.1.10"
WIKI = "openapi/wiki/v1"

# Error codes worth retrying (from knowledge-base/references/api.md)
RETRYABLE = {110010, 110021}  # downstream network error, rate limited


class ImaError(RuntimeError):
    def __init__(self, code: int, msg: str, api: str):
        super().__init__(f"[{api}] code={code} msg={msg}")
        self.code, self.msg, self.api = code, msg, api


def _load_credentials() -> tuple[str, str]:
    cid = os.getenv("IMA_OPENAPI_CLIENTID") or os.getenv("IMA_CLIENT_ID")
    key = os.getenv("IMA_OPENAPI_APIKEY") or os.getenv("IMA_API_KEY")
    if not cid or not key:
        raise RuntimeError(
            "Missing ima credentials. Set IMA_OPENAPI_CLIENTID and IMA_OPENAPI_APIKEY "
            "(e.g. in a .env file that is gitignored)."
        )
    return cid, key


def mask(secret: str) -> str:
    """For UI display: never show the full key (handbook module 1)."""
    return secret[:4] + "****" + secret[-2:] if len(secret) > 8 else "****"


class ImaClient:
    def __init__(self, cache_dir: str | None = ".cache/ima", cache_ttl: int = 1800,
                 timeout: int = 30, max_retries: int = 3):
        self.client_id, self.api_key = _load_credentials()
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_ttl = cache_ttl
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.call_log: list[dict] = []  # source/audit trail shown in UI

    # ---------- low level ----------
    def _headers(self) -> dict:
        return {
            "ima-openapi-clientid": self.client_id,
            "ima-openapi-apikey": self.api_key,
            "ima-openapi-ctx": f"skill_version={SKILL_VERSION}",
            "Content-Type": "application/json",
        }

    def _cache_path(self, api: str, body: dict) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha1((api + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        return self.cache_dir / f"{h}.json"

    def call(self, api: str, body: dict, use_cache: bool = True) -> dict:
        """POST to an ima API path; returns `data`. Raises ImaError on code != 0."""
        cp = self._cache_path(api, body) if use_cache else None
        if cp and cp.exists() and time.time() - cp.stat().st_mtime < self.cache_ttl:
            data = json.loads(cp.read_text("utf-8"))
            self.call_log.append({"api": api, "body": body, "cached": True, "ts": time.time()})
            return data

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self.session.post(f"{BASE_URL}/{api}", headers=self._headers(),
                                      data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                      timeout=self.timeout)
                r.raise_for_status()
                resp = r.json()
            except (requests.RequestException, ValueError) as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
                continue
            code = resp.get("code", -1)
            if code == 0:
                data = resp.get("data") or {}
                if cp:
                    cp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
                self.call_log.append({"api": api, "body": body, "cached": False, "ts": time.time()})
                return data
            if code in RETRYABLE and attempt < self.max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise ImaError(code, resp.get("msg", ""), api)
        raise RuntimeError(f"[{api}] request failed after retries: {last_err}")

    def _paginate(self, api: str, body: dict, list_key: str) -> Iterator[dict]:
        cursor = ""
        while True:
            data = self.call(api, {**body, "cursor": cursor})
            yield from data.get(list_key) or []
            if data.get("is_end", True) or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]

    # ---------- knowledge-base APIs (read-only) ----------
    def search_knowledge_base(self, query: str, limit: int = 20) -> list[dict]:
        return list(self._paginate(f"{WIKI}/search_knowledge_base", {"query": query, "limit": limit}, "info_list"))

    def find_kb(self, name: str) -> dict:
        hits = self.search_knowledge_base(name)
        exact = [h for h in hits if (h.get("name") or h.get("kb_name")) == name]
        if not (exact or hits):
            raise RuntimeError(f"Knowledge base '{name}' not found. Did this account join it via QR code?")
        kb = (exact or hits)[0]
        # handbook says fields are kb_id/kb_name; api.md says id/name — accept both
        return {"id": kb.get("kb_id") or kb.get("id"), "name": kb.get("kb_name") or kb.get("name")}

    def list_folder(self, kb_id: str, folder_id: str | None = None) -> list[dict]:
        body: dict[str, Any] = {"knowledge_base_id": kb_id, "limit": 50}
        if folder_id:
            body["folder_id"] = folder_id
        return list(self._paginate(f"{WIKI}/get_knowledge_list", body, "knowledge_list"))

    def search(self, kb_id: str, query: str, max_pages: int = 3) -> list[dict]:
        out, cursor = [], ""
        for _ in range(max_pages):
            data = self.call(f"{WIKI}/search_knowledge", {"query": query, "knowledge_base_id": kb_id, "cursor": cursor})
            out += data.get("info_list") or []
            if data.get("is_end", True) or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]
        return out

    def media_info(self, media_id: str) -> dict:
        # signed URLs expire -> do not cache long
        return self.call(f"{WIKI}/get_media_info", {"media_id": media_id}, use_cache=False)

    def fetch_media(self, media_id: str) -> tuple[int | None, bytes | None, str | None]:
        """Returns (media_type, raw_bytes, url). raw_bytes None if not accessible."""
        info = self.media_info(media_id)
        mtype = info.get("media_type")
        ui = info.get("url_info") or {}
        url = ui.get("url")
        if not url:
            return mtype, None, None
        r = self.session.get(url, headers=ui.get("headers") or {}, timeout=self.timeout)
        if r.status_code != 200:
            return mtype, None, url
        return mtype, r.content, url

    def fetch_text(self, media_id: str) -> str | None:
        _, raw, _ = self.fetch_media(media_id)
        return raw.decode("utf-8", errors="replace") if raw else None
