"""
ima OpenAPI client (read-only) that calls the handbook's standard script:

    node ima-skill/ima_api.cjs <api_path> '<json body>'

Replaces agent/ima_client.py. Public interface: docs/CONTRACTS.md §3 "P1 Data".

Verified behaviour of ima_api.cjs v1.1.10:
- Credentials come from the inherited env (IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY). Never argv.
- Success path: the raw API response goes to stdout and the script exits 0, EVEN WHEN the API
  returns an error code. So we parse stdout and check `code == 0`.
- Script-level failures print {"code": -100|-200, "msg": ...} to stderr and exit 1.
  -200 = "skill update available". The script stores today's check date BEFORE comparing versions,
  so an immediate retry succeeds: retry exactly once and log a warning.
- The daily check date is written to IMA_LAST_CHECK_FILE (default ~/.config/ima/...). We point it
  into .cache/ima/ so a read-only home directory (ModelScope) cannot break calls.

Disk cache (.cache/ima/, gitignored): listings and searches 24 h, keyed by sha1(api_path + body),
with a stale-on-error fallback. get_media_info is never cached (its URLs are signed).

Backend switch (env KB_BACKEND, default "local"; see agent/kb_local.py):
  local  = the local KB mirror only (zero ima calls), hybrid = mirror + a few cached live
  confirmations, ima = this client (original live behaviour). default_client() picks it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Iterator

import requests

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")   # never overrides variables already set (ModelScope secrets)
except ImportError:  # pragma: no cover
    pass

log = logging.getLogger(__name__)

SCRIPT = ROOT / "ima-skill" / "ima_api.cjs"
WIKI = "openapi/wiki/v1"
KB_NAME = "任德耀新建华为PC知识库"

CACHEABLE = {"search_knowledge_base", "get_knowledge_list", "search_knowledge"}
RATE_LIMITED = {110021}          # back off and retry up to 2 times
DOWNSTREAM_NETWORK = {110010}    # same treatment
QUOTA = 220021                   # daily cap: never retried; callers fall back to stale cache
ERR_PROGRAMMATIC, ERR_UPDATE_AVAILABLE = -100, -200
MAX_PAGES = 20


class ImaError(RuntimeError):
    def __init__(self, code: int, msg: str, api: str):
        super().__init__(f"[{api}] code={code} msg={msg}")
        self.code, self.msg, self.api = code, msg, api


def _configured() -> bool:
    cid = os.getenv("IMA_OPENAPI_CLIENTID") or os.getenv("IMA_CLIENT_ID")
    key = os.getenv("IMA_OPENAPI_APIKEY") or os.getenv("IMA_API_KEY")
    return bool(cid and key)


def _short(api: str) -> str:
    return api.rsplit("/", 1)[-1]


def plain_message(err: Exception) -> str:
    """Plain-language Chinese message for the UI. Never contains ids or keys."""
    if isinstance(err, ImaError):
        if err.code == QUOTA:
            return "ima 今日资料获取次数已达上限，请明天再试"
        if err.code in RATE_LIMITED:
            return "ima 请求过于频繁，请稍后再试"
        if err.code == ERR_PROGRAMMATIC:
            return f"ima 调用失败：{err.msg}"
        return f"ima 返回错误（code {err.code}）"
    return "ima 调用失败，请稍后再试"


class ImaClient:
    def __init__(self, cache_dir: str = ".cache/ima", list_ttl: int = 86400, timeout: int = 30):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir and not self.cache_dir.is_absolute():
            self.cache_dir = ROOT / self.cache_dir
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.list_ttl = list_ttl
        self.timeout = timeout
        self.call_log: list[dict] = []   # {"api", "cached", "stale", "ok", "ts"}: no ids, no keys
        self.live_calls = 0              # script invocations (each one can count toward the ima quota)
        self.stale_served = False
        self.quota_exhausted = False     # after one 220021, no more live calls in this process
        self.kb_name: str | None = None
        self.connected = False
        self.index_status = "unknown"
        self.last_error = ""
        self.session = requests.Session()

    # ------------------------------------------------------------------ subprocess
    def _env(self) -> dict:
        env = os.environ.copy()
        check_dir = self.cache_dir or (ROOT / ".cache" / "ima")
        check_dir.mkdir(parents=True, exist_ok=True)
        env["IMA_LAST_CHECK_FILE"] = str(check_dir / "last_update_check")
        return env

    def _run_once(self, api_path: str, body: dict) -> tuple[int, str, str]:
        argv = ["node", str(SCRIPT), api_path, json.dumps(body, ensure_ascii=False)]
        self.live_calls += 1
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout,
                               env=self._env(), cwd=str(ROOT))
        except subprocess.TimeoutExpired:
            raise ImaError(ERR_PROGRAMMATIC, f"请求超时（{self.timeout} 秒）", api_path)
        except FileNotFoundError:
            raise ImaError(ERR_PROGRAMMATIC, "未找到 node，请安装 Node.js 18+", api_path)
        return p.returncode, p.stdout or "", p.stderr or ""

    def _invoke(self, api_path: str, body: dict) -> dict:
        """One logical API call: handles -200 (retry once) and 110021 (back off, retry ≤ 2)."""
        update_retried, backoffs = False, 0
        while True:
            rc, out, err = self._run_once(api_path, body)
            if rc != 0:
                try:
                    e = json.loads(err.strip() or "{}")
                except ValueError:
                    e = {}
                code = e.get("code", ERR_PROGRAMMATIC)
                msg = e.get("msg") or "脚本执行失败"
                if code == ERR_UPDATE_AVAILABLE and not update_retried:
                    log.warning("ima skill 有新版本，请团队更新")
                    update_retried = True
                    continue
                raise ImaError(code, msg, api_path)
            try:
                resp = json.loads(out)
            except ValueError:
                raise ImaError(ERR_PROGRAMMATIC, "ima 返回的不是合法 JSON", api_path)
            code = resp.get("code", ERR_PROGRAMMATIC)
            if code == 0:
                return resp.get("data") or {}
            if code in RATE_LIMITED | DOWNSTREAM_NETWORK and backoffs < 2:
                backoffs += 1
                time.sleep(2 * backoffs)
                continue
            raise ImaError(code, resp.get("msg", ""), api_path)

    # ------------------------------------------------------------------ cache
    def _cache_path(self, api_path: str, body: dict) -> Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha1((api_path + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        return self.cache_dir / f"{h}.json"

    def _log(self, api: str, cached: bool, stale: bool, ok: bool):
        self.call_log.append({"api": _short(api), "cached": cached, "stale": stale, "ok": ok, "ts": time.time()})

    def call(self, api: str, body: dict, use_cache: bool = True) -> dict:
        """POST to an ima API (short name or full path); returns `data`. Raises ImaError."""
        api_path = api if "/" in api else f"{WIKI}/{api}"
        use_cache = use_cache and _short(api_path) in CACHEABLE
        cp = self._cache_path(api_path, body) if use_cache else None
        if cp and cp.exists() and time.time() - cp.stat().st_mtime < self.list_ttl:
            self._log(api_path, cached=True, stale=False, ok=True)
            return json.loads(cp.read_text("utf-8"))
        if not _configured():
            self.last_error = "ima 凭证未配置"
            if cp and cp.exists():
                return self._stale(cp, api_path)
            self._log(api_path, cached=False, stale=False, ok=False)
            raise ImaError(ERR_PROGRAMMATIC, "ima 凭证未配置", api_path)
        try:
            if self.quota_exhausted:
                raise ImaError(QUOTA, "今日额度已用完（本进程不再重复请求）", api_path)
            data = self._invoke(api_path, body)
        except ImaError as e:
            if e.code == QUOTA:
                self.quota_exhausted = True
            self.last_error = plain_message(e)
            if cp and cp.exists():
                return self._stale(cp, api_path)
            self._log(api_path, cached=False, stale=False, ok=False)
            raise
        if cp:
            cp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        self.connected = True
        self._log(api_path, cached=False, stale=False, ok=True)
        return data

    def _stale(self, cp: Path, api_path: str) -> dict:
        self.stale_served = True
        self.last_error = f"{self.last_error}；已使用缓存数据（可能不是最新）"
        self._log(api_path, cached=True, stale=True, ok=True)
        return json.loads(cp.read_text("utf-8"))

    def _paginate(self, api: str, body: dict, list_key: str) -> Iterator[dict]:
        cursor = ""
        for _ in range(MAX_PAGES):
            data = self.call(api, {**body, "cursor": cursor})
            yield from data.get(list_key) or []
            if data.get("is_end", True) or not data.get("next_cursor"):
                return
            cursor = data["next_cursor"]

    # ------------------------------------------------------------------ KB APIs (read-only)
    def find_kb(self, name: str) -> dict:
        hits = list(self._paginate("search_knowledge_base", {"query": name, "limit": 20}, "info_list"))
        exact = [h for h in hits if (h.get("kb_name") or h.get("name")) == name]
        if not exact:
            raise ImaError(ERR_PROGRAMMATIC, "未找到指定的共享知识库，请确认账号已加入", "search_knowledge_base")
        kb = exact[0]
        self.kb_name = kb.get("kb_name") or kb.get("name")
        return {"id": kb.get("kb_id") or kb.get("id"), "name": self.kb_name}

    def list_folder(self, kb_id: str, folder_id: str | None = None) -> list[dict]:
        body: dict[str, Any] = {"knowledge_base_id": kb_id, "limit": 50}
        if folder_id:
            body["folder_id"] = folder_id
        return list(self._paginate("get_knowledge_list", body, "knowledge_list"))

    def search(self, kb_id: str, query: str, max_pages: int = 3) -> list[dict]:
        out, cursor = [], ""
        for _ in range(max_pages):
            data = self.call("search_knowledge", {"query": query, "knowledge_base_id": kb_id, "cursor": cursor})
            out += data.get("info_list") or []
            if data.get("is_end", True) or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]
        return out

    def media_info(self, media_id: str) -> dict:
        return self.call("get_media_info", {"media_id": media_id}, use_cache=False)

    def fetch_media(self, media_id: str) -> tuple[int | None, bytes | None]:
        """(media_type, raw bytes). Bytes are None if the signed URL is missing or not accessible."""
        info = self.media_info(media_id)
        ui = info.get("url_info") or {}
        url = ui.get("url")
        if not url:
            return info.get("media_type"), None
        try:
            r = self.session.get(url, headers=ui.get("headers") or {}, timeout=self.timeout)
        except requests.RequestException:
            return info.get("media_type"), None
        return info.get("media_type"), (r.content if r.status_code == 200 else None)

    def fetch_text(self, media_id: str) -> str | None:
        _, raw = self.fetch_media(media_id)
        return raw.decode("utf-8", errors="replace").lstrip("﻿") if raw else None

    def status(self) -> dict:
        return {"kb_name": self.kb_name or KB_NAME, "connected": self.connected,
                "configured": _configured(), "index_status": self.index_status, "error": self.last_error,
                "mode": "ima"}


BACKENDS = ("local", "hybrid", "ima")
_DEFAULT: ImaClient | None = None


def kb_backend() -> str:
    b = (os.getenv("KB_BACKEND") or "local").strip().lower()
    if b not in BACKENDS:
        raise ValueError(f"KB_BACKEND must be one of {BACKENDS}")
    return b


MIRROR_MISSING = ("本地知识库镜像不存在（KB_LOCAL_DIR，默认 kb_snapshot/kb_v7）。仓库不包含知识库内容："
                  "请向队友拷贝镜像，或设置 KB_BACKEND=ima 使用实时接口（需要 ima 凭证）。详见 README「本地知识库镜像」。")


def make_client(backend: str | None = None):
    """ImaClient for "ima"; LocalKB / HybridKB (same interface) for "local" / "hybrid".

    The mirror is not in the repo. If it is missing: "hybrid" with ima credentials falls back to the live
    ima client (logged); otherwise ImaError(MIRROR_MISSING), a message the UI / scripts can show as is."""
    backend = backend or kb_backend()
    if backend == "ima":
        return ImaClient()
    from agent.kb_local import HybridKB, LocalKB, local_dir
    if not local_dir().is_dir():
        if backend == "hybrid" and _configured():
            log.warning("local KB mirror missing (%s); using the live ima client", local_dir().name)
            return ImaClient()
        raise ImaError(-100, MIRROR_MISSING, "local")
    return HybridKB(ima=ImaClient()) if backend == "hybrid" else LocalKB()


def default_client() -> ImaClient:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = make_client()
    return _DEFAULT
