"""
FastAPI server for the Vue frontend: `python server.py` → http://0.0.0.0:7861

Serves /api/* (JSON and NDJSON streams) and the built frontend (frontend/dist). All session rules live in
ui/state.py (门店端), ui/compare_view.py, ui/hq_view.py, ui/baseline_view.py; the manual flow is below.
Every backend call goes through agent.ui_data / agent.pipeline exactly as the Gradio UI did.

Never returns keys, Client ID or media ids in a form the user can read. No raw KB viewer; the only bulk
download is the current post's own images on the 生成 tab (one zip per post).
Public-demo protections: per-session and global rate limits, plain-language errors, one bounded pool for
slow (ima + LLM) work so page loads and store switches never wait behind a generation.
"""
from __future__ import annotations

import io
import json
import logging
import os
import queue
import re
import threading
import time
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    # explicit path: a bare load_dotenv() walks up from the cwd and, in a git worktree, could load another
    # checkout's .env
    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass

# Localhost must never go through a system proxy (Clash / WinHTTP): keeps local calls direct.
for _proxy_var in ("NO_PROXY", "no_proxy"):
    _hosts = [h.strip() for h in os.environ.get(_proxy_var, "").split(",") if h.strip()]
    os.environ[_proxy_var] = ",".join(dict.fromkeys([*_hosts, "127.0.0.1", "localhost", "::1"]))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import accounts  # noqa: E402
from agent import api_settings  # noqa: E402
from agent.formatter import render_download, render_publishable, render_report, strip_fact_tags  # noqa: E402
from agent.intake import SCENARIO_CHIPS  # noqa: E402
from agent.pipeline import edit as pipeline_edit, run as pipeline_run  # noqa: E402
from agent.recommend import store_data  # noqa: E402
from agent.schemas import Clarification, NeedsHuman, PLATFORM_LABELS, RunResult  # noqa: E402
from agent.ui_data import DEPS, plain_error, reset_token, today as demo_today  # noqa: E402
from ui import baseline_view, compare_view, hq_view, state  # noqa: E402
from ui.components import (  # noqa: E402
    banner_html, cached_image_bytes, fresh_session, phone_html, stop_html, talk_card_html,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("server")

# ---------------------------------------------------------------- accounts + role sessions
# Accounts live in SQLite (agent/accounts.py); a login binds a role to the browser tab's session id.
# The database is seeded once with staff-<store> / manager-<store> / dev demo accounts. Approvals written
# by a manager are store-scoped, so only that store's staff unlock the new product.
ROLE_LABELS = accounts.ROLE_LABELS
_AUTH: dict[str, dict] = {}
_AUTH_LOCK = threading.Lock()


def _bootstrap_accounts() -> None:
    """Create the schema, seed demo accounts and restore persisted approvals into the recommender."""
    try:
        accounts.init_db()
        accounts.seed_demo_accounts(state.STORES)
        for model_id, store_id in accounts.all_approvals():
            store_data.set_store_approval(model_id, store_id)
    except Exception as e:  # noqa: BLE001 - a missing database must not take the app down
        log.warning("账号数据库不可用，登录与新品审核可能无法使用: %s", e)


_bootstrap_accounts()

KB_NAME = "任德耀新建华为PC知识库"
DIST = ROOT / "frontend" / "dist"
GEN_CONCURRENCY = int(os.getenv("UI_GENERATION_CONCURRENCY", "4"))
# One bounded pool for every slow (ima + LLM) call; local work runs inline in the request.
GEN_POOL = ThreadPoolExecutor(max_workers=GEN_CONCURRENCY, thread_name_prefix="generation")

app = FastAPI(title="华为 PC 图文软文 Agent", docs_url=None, redoc_url=None)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------- status (cached, never blocking)
_STATUS_TTL = 600.0
_STATUS_STATE: dict = {"data": None, "ts": 0.0, "inflight": False}
_STATUS_LOCK = threading.Lock()


def _placeholder_status() -> dict:
    return {"kb_name": KB_NAME, "connected": False, "configured": bool(os.getenv("LLM_API_KEY")),
            "index_status": "checking", "error": None, "_pending": True}


def _refresh_status() -> None:
    try:
        s = dict(DEPS.status())
    except Exception as e:  # noqa: BLE001 - never crash the UI on a status check
        s = {"kb_name": KB_NAME, "connected": False, "configured": False, "index_status": "stale",
             "error": plain_error(e)}
    s["_ts"] = time.time()
    with _STATUS_LOCK:
        _STATUS_STATE.update(data=s, ts=s["_ts"], inflight=False)


def kb_status() -> dict:
    """Cached status snapshot; never waits on the network. A stale cache is returned as-is while a
    background refresh runs, and the very first call returns a "checking" placeholder immediately."""
    now = time.time()
    with _STATUS_LOCK:
        data = _STATUS_STATE["data"]
        stale = data is None or now - _STATUS_STATE["ts"] >= _STATUS_TTL
        if stale and not _STATUS_STATE["inflight"]:
            _STATUS_STATE["inflight"] = True
            threading.Thread(target=_refresh_status, daemon=True, name="kb-status").start()
        if data is None:
            return _placeholder_status()
        return dict(data)


def _friendly_status_error(err) -> str:
    """The status line never shows a raw backend/ima message or code."""
    msg = str(err)
    if "220004" in msg or "220021" in msg or "次数" in msg:
        return "知识库今日调用额度已用完，当前使用本地缓存。"
    return plain_error(RuntimeError(msg)).replace("生成失败：", "")


def status_view() -> dict:
    """What the status HUD shows. Keys and Client ID never appear; 密钥 is only 已配置 / 未配置."""
    s = kb_status()
    checking = bool(s.get("_pending")) or s.get("index_status") == "checking"
    mode = str(s.get("mode") or "")
    is_mirror = "镜像" in mode or "本地" in mode
    idx = s.get("index_status") or "stale"
    if checking:
        kb_state = "连接中…"
    elif is_mirror:
        kb_state = "本地镜像 · 可用"
    else:
        kb_state = "已连接" if s.get("connected") else "未连接"
    err = s.get("error")
    return {
        "kb_name": s.get("kb_name") or KB_NAME,
        "kb_state": kb_state,
        "kb_ok": bool(checking or s.get("connected") or is_mirror),
        "checking": checking,
        "index_status": idx,
        "index_label": {"complete": "完整", "partial": "部分", "stale": "可能过期",
                        "checking": "连接中…"}.get(idx, idx),
        "model": os.getenv("LLM_MODEL", "") or "未设置",
        "model_fast": os.getenv("LLM_MODEL_FAST", "") or "",
        "configured": bool(s.get("configured") or os.getenv("LLM_API_KEY")),
        "dev_mode": bool(DEPS.is_dev_mode),
        "fake_fields": list(DEPS.fake_fields) if DEPS.is_dev_mode else [],
        "error": _friendly_status_error(err) if (err and not s.get("connected") and not checking) else "",
        "today": demo_today(),
    }


# ---------------------------------------------------------------- public demo protections
PER_SESSION_MIN_GAP = float(os.getenv("RATE_MIN_GAP_S", "10"))
PER_SESSION_PER_HOUR = int(os.getenv("RATE_SESSION_PER_HOUR", "20"))
GLOBAL_PER_HOUR = int(os.getenv("RATE_GLOBAL_PER_HOUR", "120"))
_RATE_LOCK = threading.Lock()
_SESSION_RUNS: dict[str, deque] = {}
_GLOBAL_RUNS: deque = deque()


def rate_check(session_id: str, follow_up: bool = False) -> str | None:
    """Returns a Chinese message if the run is not allowed, else None (and records the run).

    follow_up=True (answering the Agent's own clarification questions) skips the min-gap check only;
    the hourly caps still apply.
    """
    now = time.time()
    with _RATE_LOCK:
        while _GLOBAL_RUNS and now - _GLOBAL_RUNS[0] > 3600:
            _GLOBAL_RUNS.popleft()
        q = _SESSION_RUNS.setdefault(session_id, deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if q and not follow_up and now - q[-1] < PER_SESSION_MIN_GAP:
            return f"操作太快了，请 {int(PER_SESSION_MIN_GAP - (now - q[-1])) + 1} 秒后再试。"
        if len(q) >= PER_SESSION_PER_HOUR:
            return "本会话一小时内的生成次数已用完，请稍后再试。"
        if len(_GLOBAL_RUNS) >= GLOBAL_PER_HOUR:
            return "当前使用人数较多，已达到每小时生成上限，请稍后再试。"
        q.append(now)
        _GLOBAL_RUNS.append(now)
    return None


# ---------------------------------------------------------------- sessions
# One server-side dict per browser tab (the SPA keeps its id in sessionStorage). Same dict shape as the
# former gr.State, so every rule in ui/state.py is unchanged. Never serialized out as a whole.
_SESSIONS: dict[str, dict] = {}
_SESSIONS_LOCK = threading.Lock()
_SESSION_MAX = 500


def _session(sid: str) -> dict:
    sid = (sid or "").strip()[:64] or uuid4().hex
    with _SESSIONS_LOCK:
        s = _SESSIONS.get(sid)
        if s is None:
            if len(_SESSIONS) >= _SESSION_MAX:
                oldest = next(iter(_SESSIONS))
                _SESSIONS.pop(oldest, None)
            s = fresh_session()
            s["id"] = sid
            s["manual"] = {"id": sid, "reset_seen": reset_token()}
            s["lock"] = threading.Lock()
            _SESSIONS[sid] = s
        s["_touched"] = time.time()
        return s


def _store_session(sid: str) -> dict:
    s = _session(sid)
    acct = _account_of(sid)
    if acct and acct.get("store_id") and acct.get("role") in ("staff", "manager"):
        # A store login owns the store and the role: a deep link or an old session cannot switch it.
        if (s.get("store_id") != acct["store_id"] or not s.get("cards")
                or s.get("staff") != state.staff_for(acct)):
            with s["lock"]:
                state.bind_account(s, acct)
    elif not s.get("cards"):
        with s["lock"]:
            if not s.get("cards"):
                state.load_store(s, state.STORES[0]["store_id"])
    return s


# ---------------------------------------------------------------- auth helpers
def _sid(value: str) -> str:
    return (value or "").strip()[:64]


def _account_of(sid: str) -> dict | None:
    with _AUTH_LOCK:
        acct = _AUTH.get(_sid(sid))
        return dict(acct) if acct else None


def _require(sid: str, roles: tuple[str, ...] = ("staff", "manager", "developer")) -> dict:
    """Resolve the session's account, or stop with 401/403. Every store / generate endpoint is gated."""
    sid = _sid(sid)
    if not sid:
        raise HTTPException(status_code=401, detail="会话已过期，请刷新页面后重新登录")
    acct = _account_of(sid)
    if acct is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if roles and acct.get("role") not in roles:
        raise HTTPException(status_code=403, detail="当前账号无权访问这个页面")
    return acct


def _require_demo(sid: str) -> None:
    """四店对比 / 对照组: developer accounts only (the demo views are not part of the store flow)."""
    _require(sid, ("developer",))


def _account_payload(user: dict) -> dict:
    """The login account the client stores: no hash, no salt, no password."""
    role = user.get("role") or "staff"
    store_id = user.get("store_id") or ""
    store = next((s for s in state.STORES if s["store_id"] == store_id), {})
    return {
        "username": user.get("username") or "",
        "role": role,
        "role_label": ROLE_LABELS.get(role, role),
        "store_id": store_id,
        "store_name": store.get("store_name") or "",
        "display_name": user.get("display_name") or store.get("store_name") or ROLE_LABELS.get(role, role),
        "kind": "store" if role in ("staff", "manager") else "dev",
    }


def _public_account(acct: dict | None) -> dict | None:
    if not acct:
        return None
    keys = ("username", "role", "role_label", "store_id", "store_name", "display_name", "kind")
    return {k: acct.get(k, "") for k in keys}


def _reset_session(sid: str) -> dict:
    """A fresh session for login / logout. We swap in a brand-new dict (with a new lock) instead of
    clearing the old one in place, so a logout is not blocked by an in-flight generation that holds the
    old lock — the old worker keeps its orphaned copy and finishes harmlessly. The old account's hidden
    platform prefetch is cancelled before the swap."""
    sid = _sid(sid)
    fresh = fresh_session()
    fresh["id"] = sid
    fresh["manual"] = {"id": sid, "reset_seen": reset_token()}
    fresh["lock"] = threading.Lock()
    fresh["_touched"] = time.time()
    with _SESSIONS_LOCK:
        old = _SESSIONS.get(sid)
        if old is not None:
            cancel = (old.get("manual") or {}).get("prefetch_cancel")
            if cancel is not None:
                cancel.set()
        _SESSIONS[sid] = fresh
    return fresh


# ---------------------------------------------------------------- NDJSON streaming helper
def _ndjson(worker: Callable[[Callable[[dict], None]], None]) -> StreamingResponse:
    """Run `worker(emit)` in the generation pool; every emit(dict) becomes one NDJSON line. The worker's
    return is ignored; it must emit its own terminal event. Exceptions become a plain-language error."""
    q: "queue.Queue[Optional[dict]]" = queue.Queue()

    def emit(payload: dict) -> None:
        q.put(payload)

    def target() -> None:
        try:
            worker(emit)
        except Exception as e:  # noqa: BLE001
            log.exception("stream worker failed")
            q.put({"event": "error", "message": plain_error(e)})
        finally:
            q.put(None)

    GEN_POOL.submit(target)

    def gen():
        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _progress(emit: Callable[[dict], None]):
    def cb(stage: str, msg: str) -> None:
        emit({"event": "progress", "stage": stage, "message": f"· {msg}"})
    return cb


def _stream_payload(post) -> dict:
    """One draft / revision event for the live phone preview: the post text and where each image sits.
    Media ids never leave the server (the client asks for images by index)."""
    return {
        "platform": post.platform,
        "post": {
            "title": strip_fact_tags(post.title),
            "intro": strip_fact_tags(post.intro),
            "body": [strip_fact_tags(b) for b in post.body],
            "cta": strip_fact_tags(post.cta),
            "tags": [strip_fact_tags(t) for t in post.tags],
        },
        "images": [{"idx": i, "position": im.position, "caption": im.caption or ""}
                   for i, im in enumerate(post.images)],
    }


def _post_stream(emit: Callable[[dict], None], host: dict):
    """The pipeline's on_post hook: stream the draft after write_post and every revision after a rewrite.
    The latest post is kept on the session so /api/stream-image can serve the preview's images."""
    def cb(kind: str, post) -> None:
        host["stream_post"] = post
        emit({"event": kind, "data": _stream_payload(post)})
    return cb


def _image_bytes(media_id: str) -> bytes | None:
    """Preview image bytes from the local cache, fetching once if needed; None when unavailable."""
    data = cached_image_bytes(media_id)
    if data:
        return data
    fetch = getattr(DEPS, "fetch_image_bytes", None)
    if fetch is not None:
        try:
            return fetch(media_id)
        except Exception as e:  # noqa: BLE001 - a missing preview image must never break a generation
            log.info("stream image fetch failed: %s", e)
    return None


def _file(name: str, data: bytes, media_type: str) -> Response:
    from urllib.parse import quote
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------------------------------------------------------------- request bodies
class Sid(BaseModel):
    session_id: str = ""


class LoginReq(Sid):
    username: str = ""
    password: str = ""
    store_id: str = ""   # the store picked on the login screen; staff/manager must match it


class StoreReq(Sid):
    store_id: str = ""


class IdxReq(Sid):
    idx: int = 0


class PlatformReq(Sid):
    platform: str = ""


class RoleReq(Sid):
    role: str = "店员"


class TextReq(Sid):
    text: str = ""


class EditReq(Sid):
    instruction: str = ""


class ChipReq(Sid):
    chip_id: str = ""


class CompareReq(Sid):
    model_id: str = ""
    platform: str = "朋友圈"
    store_ids: Optional[list] = None


class CreateAccountReq(Sid):
    username: str = ""
    password: str = ""
    role: str = "staff"
    store_id: str = ""
    display_name: str = ""


class ChangePasswordReq(Sid):
    old_password: str = ""
    new_password: str = ""


class RemoveUserReq(Sid):
    username: str = ""


class ManualReq(Sid):
    text: str = ""
    form: Optional[dict] = None


class ManualEditReq(Sid):
    instruction: str = ""


# ---------------------------------------------------------------- status + shell
@app.get("/api/status")
def api_status() -> dict:
    return status_view()


@app.get("/api/meta")
def api_meta() -> dict:
    """Static lists for the shell: stores, question chips, compare products, platforms."""
    products = compare_view_products()
    return {
        "today": demo_today(),
        "stores": [{"store_id": s["store_id"], "store_name": s["store_name"], "district": s.get("district", ""),
                    "anchor": s.get("anchor_poi", "")} for s in state.STORES],
        "chips": [{"chip_id": k, "text": v["text"]} for k, v in state.POOL.items()],
        "platforms": list(state.PLATFORM_TABS),
        "compare_products": products,
        "compare_platforms": list(compare_view.PLATFORMS),
        "compare_stores": [sid for sid, _ in compare_view.COMPARE_STORES],
        "manual_platforms": [PLATFORM_LABELS[p] for p in ("xiaohongshu", "moments", "wechat_article", "poster", "douyin")],
        "manual_examples": MANUAL_EXAMPLES,
        "manual_products": manual_products(),
        "manual_scenarios": list(SCENARIO_CHIPS),
        "quick_edits": list(state.QUICK_EDITS),
    }


def manual_products() -> list[dict]:
    """Catalog models for the 点击输入 product step (names only; resolved again by intake)."""
    try:
        return [{"model_id": m.model_id, "name": m.canonical_name, "route": m.route}
                for m in DEPS.catalog.models.values()]
    except Exception as e:  # noqa: BLE001
        log.warning("manual_products failed: %s", e)
        return []


# ---------------------------------------------------------------- login / logout
@app.post("/api/auth/login")
def api_auth_login(req: LoginReq) -> dict:
    sid = _sid(req.session_id)
    username = (req.username or "").strip().lower()
    store_id = (req.store_id or "").strip().upper()
    if not sid:
        return {"ok": False, "reason": "会话已过期，请刷新页面后重试", "account": None}
    if not username or not req.password:
        return {"ok": False, "reason": "请输入账号和密码", "account": None}
    try:
        user = accounts.authenticate(username, req.password)
    except Exception as e:  # noqa: BLE001
        log.warning("login database unavailable: %s", e)
        return {"ok": False, "reason": "登录服务暂时不可用，请稍后再试", "account": None}
    if user is None:
        time.sleep(0.35)   # slows guessing a little
        return {"ok": False, "reason": "账号或密码不正确", "account": None}
    acct = _account_payload(user)
    # The shop picked on the login screen is part of the credential for a store account: it cannot sign
    # in under another store (the developer account is company-wide and ignores the picker).
    if acct["role"] != "developer":
        if not store_id:
            return {"ok": False, "reason": "请先选择门店", "account": None}
        if store_id != acct["store_id"]:
            where = acct["store_name"] or acct["store_id"] or "门店"
            return {"ok": False, "reason": f"该账号属于{where}，请选择对应门店", "account": None}
    with _AUTH_LOCK:
        _AUTH[sid] = acct
    s = _reset_session(sid)
    with s["lock"]:
        if acct["store_id"]:
            state.bind_account(s, acct)
            state.render(s)
    return {"ok": True, "reason": "", "account": _public_account(acct)}


@app.post("/api/auth/logout")
def api_auth_logout(req: Sid) -> dict:
    sid = _sid(req.session_id)
    with _AUTH_LOCK:
        _AUTH.pop(sid, None)
    if sid:
        _reset_session(sid)
    return {"ok": True}


@app.post("/api/auth/me")
def api_auth_me(req: Sid) -> dict:
    return {"account": _public_account(_account_of(req.session_id))}


@app.get("/api/auth/demo-accounts")
def api_auth_demo_accounts() -> dict:
    """Demo shortcuts for the login screen: usernames and roles, never a hash. The password is only
    included when the operator has not set DEMO_PASSWORD."""
    try:
        users = accounts.list_users()
    except Exception as e:  # noqa: BLE001
        log.warning("demo accounts unavailable: %s", e)
        users = []
    order = {"staff": 0, "manager": 1, "developer": 2}
    out = []
    for u in users:
        p = _account_payload(u)
        out.append({k: p[k] for k in ("username", "role", "role_label", "store_id", "store_name", "display_name")})
    out.sort(key=lambda x: (order.get(x["role"], 9), x["store_id"], x["username"]))
    return {"accounts": out, "password": accounts.demo_password()}


@app.post("/api/auth/create")
def api_auth_create(req: CreateAccountReq) -> dict:
    """A logged-in account creates accounts for strictly lower roles: developer → manager/staff,
    manager → staff. A manager's new staff are bound to the manager's own store."""
    creator = _require(req.session_id)
    creator_role = creator.get("role") or "staff"
    target = (req.role or "").strip().lower()
    if target not in accounts.ROLES:
        return {"ok": False, "reason": "无效的身份"}
    if not accounts.can_create(creator_role, target):
        return {"ok": False, "reason": "无权创建这个身份"}

    store_id = ""
    if target in ("staff", "manager"):
        store_id = (req.store_id or "").strip().upper()
        if creator_role == "manager":
            store_id = creator.get("store_id") or ""   # a manager only adds staff to their own store
        if not store_id:
            return {"ok": False, "reason": "请选择门店"}
        if store_id not in {s["store_id"] for s in state.STORES}:
            return {"ok": False, "reason": "门店不存在"}

    username = (req.username or "").strip()
    if not username or not req.password:
        return {"ok": False, "reason": "请输入账号和密码"}
    if len(req.password) < 4:
        return {"ok": False, "reason": "密码至少 4 位"}

    display_name = (req.display_name or "").strip()
    if not display_name:
        store = next((s for s in state.STORES if s["store_id"] == store_id), {})
        name = store.get("store_name") or store_id or ""
        display_name = f"{name} {accounts.ROLE_LABELS[target]}" if name else accounts.ROLE_LABELS[target]

    try:
        ok = accounts.create_user(username, req.password, target, store_id, display_name)
    except ValueError as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}
    if not ok:
        return {"ok": False, "reason": "账号已存在"}
    return {"ok": True, "reason": ""}


@app.post("/api/auth/change-password")
def api_auth_change_password(req: ChangePasswordReq) -> dict:
    """Each user changes their own password (old password is verified first)."""
    acct = _require(req.session_id)
    if not req.old_password or not req.new_password:
        return {"ok": False, "reason": "请输入旧密码和新密码"}
    if len(req.new_password) < 4:
        return {"ok": False, "reason": "新密码至少 4 位"}
    if not accounts.change_password(acct["username"], req.old_password, req.new_password):
        return {"ok": False, "reason": "旧密码不正确"}
    return {"ok": True, "reason": ""}


@app.post("/api/auth/remove")
def api_auth_remove(req: RemoveUserReq) -> dict:
    """Remove a lower-role account: developer → manager/staff (any store), manager → staff (own store)."""
    creator = _require(req.session_id)
    creator_role = creator.get("role") or "staff"
    username = (req.username or "").strip().lower()
    if not username:
        return {"ok": False, "reason": "请输入账号"}
    target = accounts.get_user(username)
    if target is None:
        return {"ok": False, "reason": "账号不存在"}
    if not accounts.can_create(creator_role, target["role"]):
        return {"ok": False, "reason": "无权删除这个身份"}
    if creator_role == "manager" and target.get("store_id") != creator.get("store_id"):
        return {"ok": False, "reason": "只能删除本店的账号"}
    if username == (creator.get("username") or "").lower():
        return {"ok": False, "reason": "不能删除自己的账号"}
    accounts.delete_user(username)
    return {"ok": True, "reason": ""}


@app.get("/api/settings")
def api_settings_get(session_id: str = "") -> dict:
    """Current API config (developer only). Secrets are never returned — only whether they are set."""
    _require(session_id, ("developer",))
    return api_settings.public()


class SettingsReq(Sid):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    ima_client_id: str = ""
    ima_api_key: str = ""


@app.post("/api/settings")
def api_settings_save(req: SettingsReq) -> dict:
    """Update the API config (developer only); a blank secret keeps the current value."""
    _require(req.session_id, ("developer",))
    try:
        api_settings.save({"base_url": req.base_url, "api_key": req.api_key, "model": req.model,
                           "ima_client_id": req.ima_client_id, "ima_api_key": req.ima_api_key})
    except Exception as e:  # noqa: BLE001
        log.warning("api settings save failed: %s", e)
        return {"ok": False, "reason": plain_error(e)}
    return {"ok": True, "reason": ""}


def compare_view_products() -> list[dict]:
    try:
        return [{"model_id": p["model_id"], "display_name": p["display_name"]} for p in compare_view.ui_data.compare_products()]
    except Exception as e:  # noqa: BLE001
        log.warning("compare_products failed: %s", e)
        return []


# ---------------------------------------------------------------- 门店端
@app.post("/api/store/view")
def api_store_view(req: Sid) -> dict:
    """Opening / returning to the tab: reset and 确认发布 are picked up here (ui/state.on_tab_select)."""
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_tab_select(s)


@app.post("/api/store/select")
def api_store_select(req: StoreReq) -> dict:
    acct = _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        if acct["role"] in ("staff", "manager") and req.store_id != acct["store_id"]:
            return state.render(s)          # a store login cannot switch to another store
        return state.on_store_change(req.store_id, s)


@app.post("/api/store/platform")
def api_store_platform(req: PlatformReq) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_platform(req.platform, s)


@app.post("/api/store/role")
def api_store_role(req: RoleReq) -> dict:
    acct = _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        if acct["role"] in ("staff", "manager"):
            return state.render(s)          # the role comes from the login, not from a client toggle
        return state.on_role(req.role, s)


@app.post("/api/store/toggle-other")
def api_store_toggle(req: Sid) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_switch_toggle(s)


@app.post("/api/store/select-other")
def api_store_select_other(req: IdxReq) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_select_other(int(req.idx), s)


@app.post("/api/store/generate")
def api_store_generate(req: Sid):
    _require(req.session_id)
    s = _store_session(req.session_id)
    blocked = rate_check(s["id"])
    if blocked:
        with s["lock"]:
            card, cid = state._current_card(s)
            s["recovery"] = {"card_id": cid, "error": blocked}
            return JSONResponse({"event": "view", "data": state.render(s)})

    def worker(emit):
        with s["lock"]:
            view = state.on_generate(s, on_progress=_progress(emit), on_post=_post_stream(emit, s))
        emit({"event": "view", "data": view})

    return _ndjson(worker)


@app.post("/api/store/quick-edit")
def api_store_quick_edit(req: EditReq):
    _require(req.session_id)
    s = _store_session(req.session_id)
    instruction = req.instruction if req.instruction in state.QUICK_EDITS else ""
    if not instruction:
        with s["lock"]:
            return JSONResponse({"event": "view", "data": state.render(s)})
    blocked = rate_check(s["id"])
    if blocked:
        with s["lock"]:
            card, cid = state._current_card(s)
            s["edit_message"] = (cid, blocked)
            return JSONResponse({"event": "view", "data": state.render(s)})

    def worker(emit):
        with s["lock"]:
            view = state.on_quick_edit(s, instruction, on_progress=_progress(emit), on_post=_post_stream(emit, s))
        emit({"event": "view", "data": view})

    return _ndjson(worker)


@app.post("/api/store/recovery")
def api_store_recovery(req: Sid) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_show_recovery(s)


@app.post("/api/store/publish")
def api_store_publish(req: Sid) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_publish(s)


@app.post("/api/store/text-input")
def api_store_text_input(req: TextReq) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_text_input(req.text, s)


@app.post("/api/store/check-save")
def api_store_check_save(req: TextReq) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_check_save(req.text, s)


@app.post("/api/store/revert")
def api_store_revert(req: Sid) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_revert(s)


@app.post("/api/store/chip")
def api_store_chip(req: ChipReq) -> dict:
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_chip(req.chip_id, s)


@app.post("/api/store/image-tick")
def api_store_image_tick(req: Sid) -> dict:
    """The client polls this while image_pending: returns {"changed": bool, "data": view?}."""
    _require(req.session_id)
    s = _store_session(req.session_id)
    with s["lock"]:
        view = state.on_image_tick(s)
    return {"changed": view is not None, "data": view}


@app.get("/api/store/export-zip")
def api_store_export_zip(session_id: str = ""):
    _require(session_id)
    s = _store_session(session_id)
    with s["lock"]:
        out = state.export_zip(s)
    if out is None:
        return JSONResponse({"error": "当前内容不可导出。"}, status_code=409)
    return _file(out[0], out[1], "application/zip")


@app.get("/api/store/download-md")
def api_store_download_md(session_id: str = ""):
    _require(session_id)
    s = _store_session(session_id)
    with s["lock"]:
        out = state.download_text(s)
    if out is None:
        return JSONResponse({"error": "当前没有可下载的内容。"}, status_code=409)
    return _file(out[0], out[1], "text/markdown; charset=utf-8")


@app.get("/api/store/save-image")
def api_store_save_image(session_id: str = ""):
    _require(session_id)
    s = _store_session(session_id)
    with s["lock"]:
        out = state.save_image(s)
    if out is None:
        return JSONResponse({"error": "当前没有可保存的图片。"}, status_code=409)
    mime = {"png": "image/png", "svg": "image/svg+xml"}.get(out[0].rsplit(".", 1)[-1], "image/jpeg")
    return _file(out[0], out[1], mime)


# ---------------------------------------------------------------- 三店对比
@app.post("/api/compare/stored")
def api_compare_stored(req: CompareReq) -> dict:
    _require_demo(req.session_id)
    body, summary = compare_view.on_show_stored(req.model_id, req.platform, req.store_ids)
    return {"html": body, "summary": summary}


@app.post("/api/compare/run")
def api_compare_run(req: CompareReq):
    _require_demo(req.session_id)
    s = _session(req.session_id)
    blocked = rate_check(s["id"])
    if blocked:
        return JSONResponse({"event": "result", "html": f'<div class="hw-banner err">{blocked}</div>', "summary": ""})

    def worker(emit):
        body, summary = compare_view.on_compare(req.model_id, req.platform, req.store_ids, on_progress=_progress(emit))
        emit({"event": "result", "html": body, "summary": summary})

    return _ndjson(worker)


# ---------------------------------------------------------------- 总部端
@app.get("/api/hq/view")
def api_hq_view(session_id: str = "") -> dict:
    acct = _require(session_id, ("manager", "developer"))
    if acct["role"] == "manager" and not acct["store_id"]:
        raise HTTPException(status_code=403, detail="这个店长账号还没有绑定门店")
    store_id = acct["store_id"] if acct["role"] == "manager" else ""
    out = hq_view.view(store_id=store_id, store_name=acct.get("store_name", ""))
    out["scope"] = "store" if store_id else "all"
    out["can_reset"] = acct["role"] == "developer"
    return out


@app.post("/api/hq/verify")
def api_hq_verify(req: Sid) -> dict:
    """A manager confirms for their own store; a developer confirms for every store. The approval is
    persisted so it survives a restart, and the recommender is updated in the same request."""
    acct = _require(req.session_id, ("manager", "developer"))
    if acct["role"] == "manager" and not acct["store_id"]:
        raise HTTPException(status_code=403, detail="这个店长账号还没有绑定门店")
    store_id = acct["store_id"] if acct["role"] == "manager" else ""
    out = hq_view.on_verify(store_id=store_id, store_name=acct.get("store_name", ""))
    model_id = out.get("verified_model") or ""
    if model_id:
        try:
            if store_id:
                accounts.approve_product(model_id, store_id, acct.get("username", ""))
            else:
                for st in state.STORES:
                    accounts.approve_product(model_id, st["store_id"], acct.get("username", ""))
        except Exception as e:  # noqa: BLE001 - the in-memory unlock still happened
            log.warning("approval could not be written to the database: %s", e)
    out["scope"] = "store" if store_id else "all"
    out["can_reset"] = acct["role"] == "developer"
    return out


@app.post("/api/hq/reset")
def api_hq_reset(req: Sid) -> dict:
    """重置演示 (developer only): backend state + every UI session (已发布 marks, chips, shown results).
    Prepared posts and accounts stay; persisted approvals are cleared."""
    _require(req.session_id, ("developer",))
    out = hq_view.on_reset()
    try:
        accounts.clear_approvals()
    except Exception as e:  # noqa: BLE001
        log.warning("approvals could not be cleared from the database: %s", e)
    with _SESSIONS_LOCK:
        for s in _SESSIONS.values():
            sid, lock = s.get("id"), s.get("lock")
            s.clear()
            s.update(fresh_session())
            s["id"] = sid
            s["lock"] = lock or threading.Lock()
            s["manual"] = {"id": sid, "reset_seen": reset_token()}
    return out


# ---------------------------------------------------------------- 对照组
@app.post("/api/baseline/stored")
def api_baseline_stored(req: StoreReq) -> dict:
    _require_demo(req.session_id)
    left, right, meta = baseline_view.on_show_stored(req.store_id or state.STORES[0]["store_id"])
    return {"left": left, "right": right, "meta": meta}


@app.post("/api/baseline/run")
def api_baseline_run(req: StoreReq):
    _require_demo(req.session_id)
    s = _session(req.session_id)
    blocked = rate_check(s["id"])
    if blocked:
        return JSONResponse({"event": "result", "left": f'<div class="hw-banner err">{blocked}</div>',
                             "right": "", "meta": ""})

    def worker(emit):
        last = None
        for left, right, meta in baseline_view.on_baseline(req.store_id):
            last = {"event": "partial", "left": left, "right": right, "meta": meta}
            emit(last)
        if last is not None:
            emit({**last, "event": "result"})
        else:
            emit({"event": "result", "left": "", "right": "", "meta": ""})

    return _ndjson(worker)


# ---------------------------------------------------------------- 手动输入 (the original manual flow)
MANUAL_EXAMPLES = [
    "一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书",
    "经常出差的销售想换一台轻薄本，DemoBook 14 SE，发朋友圈",
    "DemoBook 14 开学季 发小红书",
]


def _manual(s: dict) -> dict:
    m = s.setdefault("manual", {"id": s.get("id"), "reset_seen": reset_token()})
    if m.get("reset_seen") != reset_token():       # HQ 重置演示 clears the manual flow too
        m.clear()
        m.update({"id": s.get("id"), "reset_seen": reset_token()})
    return m


# Every platform the 直接输入 / 点选 flow can write. The hidden prefetch walks this order, so 换 is instant.
MANUAL_PLATFORM_KEYS = ("moments", "xiaohongshu", "wechat_article", "poster", "douyin")
_MANUAL_LABEL_TO_KEY = {v: k for k, v in PLATFORM_LABELS.items()}


def _manual_cache(m: dict) -> dict:
    """What the client polls while 换 is disabled: is every platform cached, and how far did we get."""
    cached = m.get("results") or {}
    keys = [k for k in MANUAL_PLATFORM_KEYS if isinstance(cached.get(k), RunResult)]
    job = m.get("prefetch") or {}
    return {"ready": len(keys) == len(MANUAL_PLATFORM_KEYS),
            "cached": [PLATFORM_LABELS[k] for k in keys],
            "state": job.get("state") or "idle", "done": len(keys), "total": len(MANUAL_PLATFORM_KEYS),
            "error": job.get("error") or ""}


def _start_prefetch(m: dict, current: RunResult) -> None:
    """换 is disabled until this finishes: generate every other platform from the current post and cache
    each one under its own platform key. A new generation cancels the old job; edits never touch the
    other platforms' entries (product decision 2026-10-22)."""
    old = m.get("prefetch_cancel")
    if old is not None:
        old.set()
    cancel = threading.Event()
    m["prefetch_cancel"] = cancel
    m["prefetch"] = {"state": "running", "error": ""}
    have = {k for k in (m.get("results") or {}) if isinstance((m.get("results") or {}).get(k), RunResult)}
    todo = [k for k in MANUAL_PLATFORM_KEYS if k not in have]

    def one(key: str) -> None:
        if cancel.is_set():
            return
        try:
            r = pipeline_edit(current, f"换成{PLATFORM_LABELS[key]}", DEPS)
        except Exception as e:  # noqa: BLE001 - one platform failing must not stop the others
            log.info("manual prefetch %s failed: %s", key, e)
            return
        if isinstance(r, RunResult) and not cancel.is_set():
            m.setdefault("results", {})[r.post.platform] = r

    def worker() -> None:
        ex = ThreadPoolExecutor(max_workers=max(1, min(GEN_CONCURRENCY, len(todo))))
        try:
            for f in [ex.submit(one, k) for k in todo]:
                f.result()
        except Exception as e:  # noqa: BLE001
            log.exception("manual prefetch failed")
            m["prefetch"] = {"state": "error", "error": plain_error(e)}
            return
        finally:
            if m.get("prefetch_cancel") is cancel:      # a newer generation may own the slot by now
                m.pop("prefetch_cancel", None)
            ex.shutdown(wait=False, cancel_futures=True)
        if m.get("prefetch_cancel") is not None and m.get("prefetch_cancel") is not cancel:
            return                                      # superseded: the new job owns the status
        if cancel.is_set():
            m["prefetch"] = {"state": "idle", "error": ""}
            return
        cached = m.get("results") or {}
        missing = [k for k in MANUAL_PLATFORM_KEYS if not isinstance(cached.get(k), RunResult)]
        # A failed platform must not leave the client polling forever (换 would stay disabled silently).
        m["prefetch"] = ({"state": "error", "error": "部分平台没有缓存成功"} if missing
                         else {"state": "done", "error": ""})

    threading.Thread(target=worker, daemon=True, name="manual-prefetch").start()


def _manual_render(r: RunResult, m: dict | None = None) -> dict:
    out = {"kind": "result", "phone_html": phone_html(r, DEPS), "talk_html": talk_card_html(r),
           "banner_html": banner_html(r), "report_md": render_report(r), "pub_text": render_publishable(r.post),
           "platform_label": PLATFORM_LABELS.get(r.post.platform, r.post.platform),
           "model": r.model.canonical_name, "images": len(r.post.images)}
    if m is not None:
        out["cache"] = _manual_cache(m)
    return out


def _manual_handle(result, m: dict) -> dict:
    if isinstance(result, Clarification):
        m["clarification"] = result
        return {"kind": "clarification",
                "questions": [{"slot": q.slot, "text": q.text, "options": list(q.options)} for q in result.questions]}
    if isinstance(result, NeedsHuman):
        return {"kind": "stop", "html": stop_html(result.message)}
    if not isinstance(result, RunResult):        # EditBlocked and friends: a message, never a crash
        return {"kind": "stop", "html": stop_html(getattr(result, "message", "无法完成这次修改。"))}
    m["result"] = result
    m.setdefault("results", {})[result.post.platform] = result
    return _manual_render(result, m)


@app.post("/api/manual/generate")
def api_manual_generate(req: ManualReq):
    _require(req.session_id)
    s = _session(req.session_id)
    m = _manual(s)
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html(
            "请先输入一句顾客描述，例如：一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发小红书", "生成失败")}})
    clar = m.get("clarification")
    is_follow_up = bool(clar and clar.partial and clar.partial.raw_text == text and req.form)
    blocked = rate_check(s["id"], follow_up=is_follow_up)
    if blocked:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html(blocked, "生成失败")}})
    form = dict(req.form or {}) if is_follow_up else {}
    m["clarification"] = None
    # A new generation is a new post: cancel the old prefetch and drop its cache, or 换 would offer the
    # previous product's copy. In-flight workers check the cancel flag before writing (see _start_prefetch).
    old = m.get("prefetch_cancel")
    if old is not None:
        old.set()
    m.pop("prefetch_cancel", None)
    m["results"] = {}
    m["prefetch"] = {"state": "idle", "error": ""}
    m.pop("stream_post", None)

    def worker(emit):
        try:
            result = pipeline_run(text, form or None, DEPS, _progress(emit), _post_stream(emit, m))
        except Exception as e:  # noqa: BLE001
            log.exception("manual run failed")
            emit({"event": "done", "data": {"kind": "stop", "html": stop_html(plain_error(e), "生成失败")}})
            return
        data = _manual_handle(result, m)
        if isinstance(result, RunResult) and data.get("kind") == "result":
            _start_prefetch(m, result)     # hidden: cache the other four platforms so 换 is instant
            data["cache"] = _manual_cache(m)
        emit({"event": "done", "data": data})

    return _ndjson(worker)


@app.post("/api/manual/check")
def api_manual_check(req: ManualReq) -> dict:
    """Intake only, before the 直接输入 flow leaves the input page: ask the missing questions first, so the
    result page is never a dead end. The clarification is remembered, so the follow-up generate call with
    the same text + form is accepted as a continuation (api_manual_generate)."""
    _require(req.session_id)
    s = _session(req.session_id)
    m = _manual(s)
    text = (req.text or "").strip()
    if not text:
        return {"kind": "stop", "html": stop_html("请先输入一句顾客描述。", "生成失败")}
    form = dict(req.form or {}) or None

    def work():
        return DEPS.parse_task(text, DEPS.catalog, form, DEPS.llm)

    try:
        parsed = GEN_POOL.submit(work).result(timeout=240)
    except Exception as e:  # noqa: BLE001
        log.exception("manual check failed")
        return {"kind": "stop", "html": stop_html(plain_error(e), "生成失败")}
    if isinstance(parsed, Clarification):
        m["clarification"] = parsed
        return {"kind": "clarification",
                "questions": [{"slot": q.slot, "text": q.text, "options": list(q.options)} for q in parsed.questions]}
    return {"kind": "ok"}


@app.post("/api/manual/edit")
def api_manual_edit(req: ManualEditReq):
    _require(req.session_id)
    s = _session(req.session_id)
    m = _manual(s)
    prev = m.get("result")
    if prev is None:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html("请先生成一篇内容。", "生成失败")}})
    blocked = rate_check(s["id"])
    if blocked:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html(blocked, "生成失败")}})
    instruction = (req.instruction or "").strip()[:40]

    def worker(emit):
        try:
            result = pipeline_edit(prev, instruction, DEPS, _progress(emit), _post_stream(emit, m))
        except Exception as e:  # noqa: BLE001
            log.exception("manual edit failed")
            emit({"event": "done", "data": {"kind": "stop", "html": stop_html(plain_error(e), "生成失败")}})
            return
        data = _manual_handle(result, m)
        if isinstance(result, RunResult):
            data["cache"] = _manual_cache(m)    # an edit only re-caches its own platform
        emit({"event": "done", "data": data})

    return _ndjson(worker)


@app.post("/api/manual/platform")
def api_manual_platform(req: PlatformReq):
    """换平台: a cached platform switches instantly (the current one is always cached before the switch);
    only a platform the hidden prefetch has not reached yet is generated on demand."""
    _require(req.session_id)
    s = _session(req.session_id)
    m = _manual(s)
    prev = m.get("result")
    if prev is None:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html("请先生成一篇内容。", "提示")}})
    key = _MANUAL_LABEL_TO_KEY.get(req.platform)
    if key is None:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html("不认识这个平台。", "提示")}})
    cached = (m.get("results") or {}).get(key)
    if isinstance(cached, RunResult):
        m["result"] = cached
        return JSONResponse({"event": "done", "data": _manual_render(cached, m), "cached": True})
    blocked = rate_check(s["id"])
    if blocked:
        return JSONResponse({"event": "done", "data": {"kind": "stop", "html": stop_html(blocked, "生成失败")}})

    def worker(emit):
        try:
            result = pipeline_edit(prev, f"换成{req.platform}", DEPS, _progress(emit), _post_stream(emit, m))
        except Exception as e:  # noqa: BLE001
            log.exception("manual platform switch failed")
            emit({"event": "done", "data": {"kind": "stop", "html": stop_html(plain_error(e), "生成失败")}})
            return
        emit({"event": "done", "data": _manual_handle(result, m)})

    return _ndjson(worker)


@app.post("/api/manual/cache-status")
def api_manual_cache_status(req: Sid) -> dict:
    """Polled while 换 is disabled: ready once every platform is cached."""
    _require(req.session_id)
    return _manual_cache(_manual(_session(req.session_id)))


@app.get("/api/manual/download-image")
def api_manual_download_image(session_id: str = "", idx: int = 0):
    """保存图片: one image at a time. 下载所有图片 (below) zips the same per-post images."""
    _require(session_id)
    s = _session(session_id)
    r = _manual(s).get("result")
    if r is None:
        return JSONResponse({"error": "还没有生成内容，请先生成后再下载。"}, status_code=409)
    images = list(getattr(getattr(r, "post", None), "images", None) or [])
    if not images:
        return JSONResponse({"error": "这篇内容没有可下载的图片。"}, status_code=409)
    i = max(0, min(int(idx), len(images) - 1))
    im = images[i]
    data = cached_image_bytes(im.media_id)
    if not data:
        fetch = getattr(DEPS, "fetch_image_bytes", None)
        if fetch is not None:
            try:
                data = fetch(im.media_id)
            except Exception as e:  # noqa: BLE001
                log.info("manual image fetch failed: %s", e)
    if not data:
        return JSONResponse({"error": "图片还在准备中，请稍后再试。"}, status_code=409)
    ext = "png" if data[:4] == b"\x89PNG" else ("svg" if data[:4] == b"<svg" else "jpg")
    mime = {"png": "image/png", "svg": "image/svg+xml", "jpg": "image/jpeg"}[ext]
    label = PLATFORM_LABELS.get(getattr(r.post, "platform", ""), "")
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{r.model.canonical_name}_{label}_图{i + 1}")[:60] + f".{ext}"
    return _file(name, data, mime)


@app.get("/api/manual/download-images")
def api_manual_download_images(session_id: str = ""):
    """下载所有图片: the current post's images as one zip, numbered like the per-image saves (1.png, 2.jpg …).
    Product decision 2026-10-22: the 生成 tab offers the zip the lead asked for; still per post, never the KB.
    Images that are not cached yet are fetched once; ones that fail are left out instead of failing the zip."""
    _require(session_id)
    s = _session(session_id)
    r = _manual(s).get("result")
    if r is None:
        return JSONResponse({"error": "还没有生成内容，请先生成后再下载。"}, status_code=409)
    images = list(getattr(getattr(r, "post", None), "images", None) or [])
    if not images:
        return JSONResponse({"error": "这篇内容没有可下载的图片。"}, status_code=409)
    fetch = getattr(DEPS, "fetch_image_bytes", None)
    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, im in enumerate(images):
            data = cached_image_bytes(im.media_id)
            if not data and fetch is not None:
                try:
                    data = fetch(im.media_id)
                except Exception as e:  # noqa: BLE001
                    log.info("manual image fetch failed: %s", e)
            if not data:
                continue
            ext = "png" if data[:4] == b"\x89PNG" else ("svg" if data[:4] == b"<svg" else "jpg")
            z.writestr(f"{i + 1}.{ext}", data)      # same numbering as 第 N 张
            added += 1
    if not added:
        return JSONResponse({"error": "图片还在准备中，请稍后再试。"}, status_code=409)
    label = PLATFORM_LABELS.get(getattr(r.post, "platform", ""), "")
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{r.model.canonical_name}_{label}_图片")[:60] + ".zip"
    return _file(name, buf.getvalue(), "application/zip")


@app.get("/api/stream-image")
def api_stream_image(session_id: str = "", scope: str = "manual", idx: int = 0):
    """The live preview's own image, addressed by index so no media id is ever sent to the browser.
    Served inline for the streaming phone (draft / revision events); 404 when not available yet."""
    _require(session_id)
    s = _store_session(session_id) if scope == "store" else _session(session_id)
    host = s if scope == "store" else _manual(s)
    post = host.get("stream_post")
    images = list(getattr(post, "images", None) or [])
    if not (0 <= int(idx) < len(images)):
        return Response(status_code=404)
    data = _image_bytes(images[int(idx)].media_id)
    if not data:
        return Response(status_code=404)
    mime = ("image/png" if data[:4] == b"\x89PNG"
            else "image/svg+xml" if data[:4] == b"<svg" else "image/jpeg")
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=600"})


@app.get("/api/manual/download-md")
def api_manual_download(session_id: str = ""):
    _require(session_id)
    s = _session(session_id)
    r = _manual(s).get("result")
    if r is None:
        return JSONResponse({"error": "当前没有可下载的内容。"}, status_code=409)
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{r.model.canonical_name}_{PLATFORM_LABELS[r.post.platform]}")[:60]
    return _file(f"{name}.md", render_download(r).encode("utf-8"), "text/markdown; charset=utf-8")


@app.post("/api/manual/reset")
def api_manual_reset(req: Sid) -> dict:
    _require(req.session_id)
    s = _session(req.session_id)
    s["manual"] = {"id": s.get("id"), "reset_seen": reset_token()}
    return {"ok": True}


# ---------------------------------------------------------------- frontend (built dist) + SPA fallback
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"error": "not found"}, status_code=404)
    candidate = (DIST / path) if path else None
    if candidate and candidate.is_file() and DIST in candidate.resolve().parents:
        return FileResponse(str(candidate))
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(str(index), headers={"Cache-Control": "no-store"})
    return Response("frontend 未构建：请先执行  npm --prefix frontend install && npm --prefix frontend run build",
                    media_type="text/plain; charset=utf-8", status_code=503)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", os.getenv("GRADIO_SERVER_PORT", "7861")))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=os.getenv("UVICORN_LOG", "info"))
