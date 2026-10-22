"""
FastAPI server for the Vue frontend: `python server.py` → http://0.0.0.0:7861

Serves /api/* (JSON and NDJSON streams) and the built frontend (frontend/dist). All session rules live in
ui/state.py (门店端), ui/compare_view.py, ui/hq_view.py, ui/baseline_view.py; the manual flow is below.
Every backend call goes through agent.ui_data / agent.pipeline exactly as the Gradio UI did.

Never returns keys, Client ID or media ids in a form the user can read. No raw KB viewer, no bulk export.
Public-demo protections: per-session and global rate limits, plain-language errors, one bounded pool for
slow (ima + LLM) work so page loads and store switches never wait behind a generation.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
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

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent.formatter import render_download, render_publishable, render_report  # noqa: E402
from agent.pipeline import edit as pipeline_edit, run as pipeline_run, run_all_platforms  # noqa: E402
from agent.schemas import Clarification, NeedsHuman, PLATFORM_LABELS, RunResult  # noqa: E402
from agent.ui_data import DEPS, plain_error, reset_token, today as demo_today  # noqa: E402
from ui import baseline_view, compare_view, hq_view, state  # noqa: E402
from ui.components import banner_html, fresh_session, phone_html, stop_html, talk_card_html  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("server")

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
        "error": str(err) if (err and not s.get("connected") and not checking) else "",
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
    if not s.get("cards"):
        with s["lock"]:
            if not s.get("cards"):
                state.load_store(s, state.STORES[0]["store_id"])
    return s


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


def _file(name: str, data: bytes, media_type: str) -> Response:
    from urllib.parse import quote
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------------------------------------------------------------- request bodies
class Sid(BaseModel):
    session_id: str = ""


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
        "stores": [{"store_id": s["store_id"], "store_name": s["store_name"]} for s in state.STORES],
        "chips": [{"chip_id": k, "text": v["text"]} for k, v in state.POOL.items()],
        "platforms": list(state.PLATFORM_TABS),
        "compare_products": products,
        "compare_platforms": list(compare_view.PLATFORMS),
        "manual_platforms": [PLATFORM_LABELS[p] for p in ("xiaohongshu", "moments", "wechat_article", "poster", "douyin")],
        "manual_examples": MANUAL_EXAMPLES,
        "quick_edits": list(state.QUICK_EDITS),
    }


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
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_tab_select(s)


@app.post("/api/store/select")
def api_store_select(req: StoreReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_store_change(req.store_id, s)


@app.post("/api/store/platform")
def api_store_platform(req: PlatformReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_platform(req.platform, s)


@app.post("/api/store/role")
def api_store_role(req: RoleReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_role(req.role, s)


@app.post("/api/store/toggle-other")
def api_store_toggle(req: Sid) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_switch_toggle(s)


@app.post("/api/store/select-other")
def api_store_select_other(req: IdxReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_select_other(int(req.idx), s)


@app.post("/api/store/generate")
def api_store_generate(req: Sid):
    s = _store_session(req.session_id)
    blocked = rate_check(s["id"])
    if blocked:
        with s["lock"]:
            card, cid = state._current_card(s)
            s["recovery"] = {"card_id": cid, "error": blocked}
            return JSONResponse({"event": "view", "data": state.render(s)})

    def worker(emit):
        with s["lock"]:
            view = state.on_generate(s, on_progress=_progress(emit))
        emit({"event": "view", "data": view})

    return _ndjson(worker)


@app.post("/api/store/quick-edit")
def api_store_quick_edit(req: EditReq):
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
            view = state.on_quick_edit(s, instruction, on_progress=_progress(emit))
        emit({"event": "view", "data": view})

    return _ndjson(worker)


@app.post("/api/store/recovery")
def api_store_recovery(req: Sid) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_show_recovery(s)


@app.post("/api/store/publish")
def api_store_publish(req: Sid) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_publish(s)


@app.post("/api/store/text-input")
def api_store_text_input(req: TextReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_text_input(req.text, s)


@app.post("/api/store/check-save")
def api_store_check_save(req: TextReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_check_save(req.text, s)


@app.post("/api/store/revert")
def api_store_revert(req: Sid) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_revert(s)


@app.post("/api/store/chip")
def api_store_chip(req: ChipReq) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.on_chip(req.chip_id, s)


@app.post("/api/store/image-tick")
def api_store_image_tick(req: Sid) -> dict:
    """The client polls this while image_pending: returns {"changed": bool, "data": view?}."""
    s = _store_session(req.session_id)
    with s["lock"]:
        view = state.on_image_tick(s)
    return {"changed": view is not None, "data": view}


@app.get("/api/store/export-zip")
def api_store_export_zip(session_id: str = ""):
    s = _store_session(session_id)
    with s["lock"]:
        out = state.export_zip(s)
    if out is None:
        return JSONResponse({"error": "当前内容不可导出。"}, status_code=409)
    return _file(out[0], out[1], "application/zip")


@app.get("/api/store/download-md")
def api_store_download_md(session_id: str = ""):
    s = _store_session(session_id)
    with s["lock"]:
        out = state.download_text(s)
    if out is None:
        return JSONResponse({"error": "当前没有可下载的内容。"}, status_code=409)
    return _file(out[0], out[1], "text/markdown; charset=utf-8")


@app.get("/api/store/save-image")
def api_store_save_image(session_id: str = ""):
    s = _store_session(session_id)
    with s["lock"]:
        out = state.save_image(s)
    if out is None:
        return JSONResponse({"error": "当前没有可保存的图片。"}, status_code=409)
    mime = {"png": "image/png", "svg": "image/svg+xml"}.get(out[0].rsplit(".", 1)[-1], "image/jpeg")
    return _file(out[0], out[1], mime)


@app.post("/api/mobile/view")
def api_mobile_view(req: Sid) -> dict:
    s = _store_session(req.session_id)
    with s["lock"]:
        return state.mobile_view(s)


# ---------------------------------------------------------------- 三店对比
@app.post("/api/compare/stored")
def api_compare_stored(req: CompareReq) -> dict:
    body, summary = compare_view.on_show_stored(req.model_id, req.platform)
    return {"html": body, "summary": summary}


@app.post("/api/compare/run")
def api_compare_run(req: CompareReq):
    s = _session(req.session_id)
    blocked = rate_check(s["id"])
    if blocked:
        return JSONResponse({"event": "result", "html": f'<div class="hw-banner err">{blocked}</div>', "summary": ""})

    def worker(emit):
        body, summary = compare_view.on_compare(req.model_id, req.platform, on_progress=_progress(emit))
        emit({"event": "result", "html": body, "summary": summary})

    return _ndjson(worker)


# ---------------------------------------------------------------- 总部端
@app.get("/api/hq/view")
def api_hq_view() -> dict:
    return hq_view.view()


@app.post("/api/hq/verify")
def api_hq_verify() -> dict:
    return hq_view.on_verify()


@app.post("/api/hq/reset")
def api_hq_reset() -> dict:
    """重置演示: backend state + every UI session (已发布 marks, chips, shown results). Prepared posts stay."""
    out = hq_view.on_reset()
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
    left, right, meta = baseline_view.on_show_stored(req.store_id or state.STORES[0]["store_id"])
    return {"left": left, "right": right, "meta": meta}


@app.post("/api/baseline/run")
def api_baseline_run(req: StoreReq):
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


def _manual_render(r: RunResult) -> dict:
    return {"kind": "result", "phone_html": phone_html(r, DEPS), "talk_html": talk_card_html(r),
            "banner_html": banner_html(r), "report_md": render_report(r), "pub_text": render_publishable(r.post),
            "platform_label": PLATFORM_LABELS.get(r.post.platform, r.post.platform),
            "model": r.model.canonical_name, "images": len(r.post.images)}


def _manual_handle(result, m: dict) -> dict:
    if isinstance(result, Clarification):
        m["clarification"] = result
        return {"kind": "clarification",
                "questions": [{"slot": q.slot, "text": q.text, "options": list(q.options)} for q in result.questions]}
    if isinstance(result, NeedsHuman):
        return {"kind": "stop", "html": stop_html(result.message)}
    m["result"] = result
    m.setdefault("results", {})[result.post.platform] = result
    return _manual_render(result)


@app.post("/api/manual/generate")
def api_manual_generate(req: ManualReq):
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

    def worker(emit):
        try:
            result = pipeline_run(text, form or None, DEPS, _progress(emit))
        except Exception as e:  # noqa: BLE001
            log.exception("manual run failed")
            emit({"event": "done", "data": {"kind": "stop", "html": stop_html(plain_error(e), "生成失败")}})
            return
        emit({"event": "done", "data": _manual_handle(result, m)})

    return _ndjson(worker)


@app.post("/api/manual/edit")
def api_manual_edit(req: ManualEditReq):
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
            result = pipeline_edit(prev, instruction, DEPS, _progress(emit))
        except Exception as e:  # noqa: BLE001
            log.exception("manual edit failed")
            emit({"event": "done", "data": {"kind": "stop", "html": stop_html(plain_error(e), "生成失败")}})
            return
        emit({"event": "done", "data": _manual_handle(result, m)})

    return _ndjson(worker)


@app.post("/api/manual/all-platforms")
def api_manual_all(req: Sid):
    s = _session(req.session_id)
    m = _manual(s)
    prev = m.get("result")
    if prev is None:
        return JSONResponse({"event": "done", "html": stop_html("请先生成一篇内容。", "提示")})
    blocked = rate_check(s["id"])
    if blocked:
        return JSONResponse({"event": "done", "html": stop_html(blocked, "提示")})

    def worker(emit):
        try:
            outs = run_all_platforms(prev, deps=DEPS)
        except Exception as e:  # noqa: BLE001
            emit({"event": "done", "html": stop_html(plain_error(e), "生成失败")})
            return
        cols = []
        for p, res in outs.items():
            if isinstance(res, RunResult):
                m.setdefault("results", {})[p] = res
                cols.append(f'<div class="hw-all-col"><div class="hw-all-head">{PLATFORM_LABELS[p]}</div>'
                            f'{banner_html(res)}{phone_html(res, DEPS)}</div>')
            else:
                cols.append(f'<div class="hw-all-col">{stop_html(getattr(res, "message", "需要补充信息"))}</div>')
        emit({"event": "done", "html": '<div class="hw-all-row">' + "".join(cols) + "</div>"})

    return _ndjson(worker)


@app.get("/api/manual/download-md")
def api_manual_download(session_id: str = ""):
    s = _session(session_id)
    r = _manual(s).get("result")
    if r is None:
        return JSONResponse({"error": "当前没有可下载的内容。"}, status_code=409)
    import re
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{r.model.canonical_name}_{PLATFORM_LABELS[r.post.platform]}")[:60]
    return _file(f"{name}.md", render_download(r).encode("utf-8"), "text/markdown; charset=utf-8")


@app.post("/api/manual/reset")
def api_manual_reset(req: Sid) -> dict:
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
