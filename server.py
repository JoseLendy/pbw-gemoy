"""
FastAPI backend for the Vue frontend. Exposes the existing agent pipeline over HTTP.

Run in dev alongside the Vite server:
    .venv/Scripts/python.exe -m uvicorn server:app --port 8000
The Vite dev server (port 5173) proxies /api here.

Never returns keys, Client ID or media ids in a form the user can read.
"""
from __future__ import annotations

import asyncio
import io
import json
import queue
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent.formatter import render_download, render_publishable, render_report, strip_fact_tags
from agent.pipeline import Deps, edit as pipeline_edit, run as pipeline_run
from agent.schemas import Clarification, NeedsHuman, PLATFORM_LABELS, RunResult

app = FastAPI(title="华为 PC 图文软文 Agent")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

DEPS = Deps.auto()

# In-memory session store: session_id -> last RunResult (edits reuse it; never serialized out).
SESSIONS: dict[str, RunResult] = {}
# Prefetched other-platform results, keyed session_id -> platform -> RunResult.
SESSION_CACHE: dict[str, dict[str, RunResult]] = {}
SESSION_CACHE_READY: set[str] = set()
_prefetch_cancel: dict[str, threading.Event] = {}
_LABEL_TO_KEY = {v: k for k, v in PLATFORM_LABELS.items()}

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{8,}|[A-Za-z0-9]{32,})")


def plain_error(e: Exception) -> str:
    code = getattr(e, "code", None)
    msg = str(e)
    if code == 220021 or "220021" in msg or "次数已达上限" in msg:
        return "知识库今日调用次数已达上限，已使用缓存/请稍后再试。"
    if code == 403 or "403" in msg or "无权限" in msg:
        return "该资料目录没有访问权限，已跳过。"
    if "LLM" in msg or "openai" in msg.lower() or "api key" in msg.lower():
        return "模型服务暂时不可用，请稍后重试。"
    return "生成失败：" + _SECRET_RE.sub("［已隐藏］", msg)[:200]


def serialize(r: RunResult) -> dict:
    """A RunResult -> JSON-safe dict the frontend renders. [F#] tags are stripped for display."""
    plan_by_id = {it.image.media_id: it for it in r.plan.items}
    images = []
    for im in r.post.images:
        it = plan_by_id.get(im.media_id)
        images.append({
            "media_id": im.media_id,
            "position": im.position,
            "caption": im.caption or (it.caption if it else ""),
            "title": it.image.title if it else "图片",
            "url": f"/api/image/{im.media_id}",
        })
    errors = [{"stage": i.stage, "code": i.code, "message": i.message, "field": i.field, "span": i.span}
              for i in r.report.issues if i.severity == "error"]
    warns = [{"stage": i.stage, "code": i.code, "message": i.message, "field": i.field, "span": i.span}
             for i in r.report.issues if i.severity == "warn"]
    return {
        "platform": r.post.platform,
        "platform_label": PLATFORM_LABELS.get(r.post.platform, r.post.platform),
        "model": r.model.canonical_name,
        "post": {
            "title": strip_fact_tags(r.post.title),
            "intro": strip_fact_tags(r.post.intro),
            "body": [strip_fact_tags(p) for p in r.post.body],
            "cta": strip_fact_tags(r.post.cta),
            "tags": list(r.post.tags),
            "selling_points": list(r.post.selling_points),
        },
        "images": images,
        "talk_card": list(r.strategy.talk_card),
        "banner": {
            "passed": r.report.passed,
            "errors": errors,
            "warns": warns,
            "pending": list(r.pending),
            "loops": r.loops,
        },
        "publishable": render_publishable(r.post),
        "download_md": render_download(r),
        "report": render_report(r),
        "timings": dict(r.timings),
    }


def serialize_post(post) -> dict:
    """Serialize just a Post for the typewriter draft/revision events."""
    return {
        "platform": post.platform,
        "platform_label": PLATFORM_LABELS.get(post.platform, post.platform),
        "post": {
            "title": strip_fact_tags(post.title),
            "intro": strip_fact_tags(post.intro),
            "body": [strip_fact_tags(p) for p in post.body],
            "cta": strip_fact_tags(post.cta),
            "tags": list(post.tags),
        },
        "images": [{"media_id": im.media_id, "position": im.position, "caption": im.caption,
                    "url": f"/api/image/{im.media_id}", "title": "图片"} for im in post.images],
    }


def _stream(payload: dict, terminal: bool = True) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _ndjson_response(worker: "callable") -> StreamingResponse:
    """Run `worker` (which puts dicts onto a queue) in a thread, stream each dict as one NDJSON line."""
    q: "queue.Queue[dict | None]" = queue.Queue()

    def progress(stage: str, msg: str):
        q.put({"event": "progress", "message": f"· {msg}"})

    def target():
        try:
            worker(progress, q)
        except Exception as e:  # noqa: BLE001
            q.put({"event": "error", "message": plain_error(e)})

    threading.Thread(target=target, daemon=True).start()

    async def gen():
        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                break
            yield _stream(item)
            if item["event"] in ("result", "clarification", "needs_human", "error", "ok"):
                break

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _prefetch_platforms(sid: str, current: RunResult):
    """Generate the other platforms in the background and cache them for instant switches.
    Cancellable via /api/cancel: pending platforms are dropped and in-flight results discarded."""
    cancel = threading.Event()
    _prefetch_cancel[sid] = cancel
    platforms = [p for p in ("wechat_article", "xiaohongshu", "moments", "poster", "douyin")
                 if p != current.post.platform]

    def gen_one(p):
        if cancel.is_set():
            return None
        try:
            return pipeline_edit(current, f"换成{PLATFORM_LABELS[p]}", DEPS)
        except Exception:
            return None

    cache = SESSION_CACHE.get(sid, {})
    ex = ThreadPoolExecutor(max_workers=len(platforms))
    try:
        futs = {p: ex.submit(gen_one, p) for p in platforms}
        for p, f in futs.items():
            if cancel.is_set():
                ex.shutdown(wait=False, cancel_futures=True)
                break
            try:
                r = f.result()
                if isinstance(r, RunResult):
                    cache[p] = r
            except Exception:
                pass
        if cache and not cancel.is_set():
            SESSION_CACHE[sid] = cache
    finally:
        _prefetch_cancel.pop(sid, None)
        SESSION_CACHE_READY.add(sid)
        ex.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------- API
@app.get("/api/status")
def status():
    s = {}
    try:
        s = dict(DEPS.status())
    except Exception as e:  # noqa: BLE001
        s = {"connected": False, "configured": False, "index_status": "stale", "error": plain_error(e)}
    s["configured"] = bool(s.get("configured") or __import__("os").getenv("LLM_API_KEY"))
    s["model"] = __import__("os").getenv("LLM_MODEL", "")
    s["model_fast"] = __import__("os").getenv("LLM_MODEL_FAST", "")
    s["dev_mode"] = DEPS.is_dev_mode
    s["dev_fields"] = list(DEPS.fake_fields)
    return s


@app.post("/api/check")
async def check(body: dict):
    """Run only the intake step. Returns 'ok' if the task is resolvable, else 'clarification'."""
    text = (body.get("text") or "").strip()
    form = body.get("form") or None

    def worker(progress, q):
        progress("intake", "理解需求…")
        try:
            parsed = DEPS.parse_task(text, DEPS.catalog, form, DEPS.llm)
        except Exception as e:  # noqa: BLE001
            q.put({"event": "error", "message": plain_error(e)})
            return
        if isinstance(parsed, Clarification):
            q.put({"event": "clarification",
                   "questions": [{"slot": x.slot, "text": x.text, "options": x.options} for x in parsed.questions]})
        else:
            q.put({"event": "ok"})

    return _ndjson_response(worker)


@app.post("/api/generate")
async def generate(body: dict):
    text = (body.get("text") or "").strip()
    sid = body.get("session_id") or uuid4().hex
    form = body.get("form") or None

    def worker(progress, q):
        def on_post(stage, post):
            q.put({"event": stage, "data": serialize_post(post)})

        r = pipeline_run(text, form, DEPS, progress, on_post)
        if isinstance(r, Clarification):
            q.put({"event": "clarification",
                   "questions": [{"slot": x.slot, "text": x.text, "options": x.options} for x in r.questions]})
        elif isinstance(r, NeedsHuman):
            q.put({"event": "needs_human", "message": r.message})
        else:
            SESSIONS[sid] = r
            SESSION_CACHE[sid] = {r.post.platform: r}
            q.put({"event": "result", "data": serialize(r), "session_id": sid})
            old = _prefetch_cancel.pop(sid, None)
            if old:
                old.set()
            threading.Thread(target=_prefetch_platforms, args=(sid, r), daemon=True).start()

    return _ndjson_response(worker)


@app.post("/api/edit")
async def edit(body: dict):
    instruction = (body.get("instruction") or "").strip()
    sid = body.get("session_id") or ""
    prev = SESSIONS.get(sid)

    platform_key = next((key for label, key in _LABEL_TO_KEY.items() if instruction == f"换成{label}"), None)
    cached = SESSION_CACHE.get(sid, {}).get(platform_key) if platform_key else None

    def worker(progress, q):
        def on_post(stage, post):
            q.put({"event": stage, "data": serialize_post(post)})

        if cached is not None:
            SESSIONS[sid] = cached
            q.put({"event": "result", "data": serialize(cached), "session_id": sid})
            return
        # Cache miss: wait for the running prefetch to finish this platform (no error, no double work).
        if platform_key and _prefetch_cancel.get(sid) is not None:
            progress("edit", "正在生成其他平台…")
            deadline = time.time() + 180
            while time.time() < deadline and _prefetch_cancel.get(sid) is not None:
                c = SESSION_CACHE.get(sid, {}).get(platform_key)
                if c is not None:
                    SESSIONS[sid] = c
                    q.put({"event": "result", "data": serialize(c), "session_id": sid})
                    return
                time.sleep(0.5)
            c = SESSION_CACHE.get(sid, {}).get(platform_key)
            if c is not None:
                SESSIONS[sid] = c
                q.put({"event": "result", "data": serialize(c), "session_id": sid})
                return
        if prev is None:
            q.put({"event": "error", "message": "请先生成一篇内容。"})
            return
        r = pipeline_edit(prev, instruction, DEPS, progress, on_post)
        if isinstance(r, Clarification):
            q.put({"event": "clarification",
                   "questions": [{"slot": x.slot, "text": x.text, "options": x.options} for x in r.questions]})
        elif isinstance(r, NeedsHuman):
            q.put({"event": "needs_human", "message": r.message})
        else:
            SESSIONS[sid] = r
            SESSION_CACHE.setdefault(sid, {})[r.post.platform] = r
            q.put({"event": "result", "data": serialize(r), "session_id": sid})

    return _ndjson_response(worker)


@app.post("/api/cancel")
async def cancel(body: dict):
    sid = body.get("session_id") or ""
    ev = _prefetch_cancel.pop(sid, None)
    if ev:
        ev.set()
    return {"ok": True}


@app.post("/api/download-images")
async def download_images(body: dict):
    """Zip the actual image files used in the current post (not a screenshot)."""
    sid = body.get("session_id") or ""
    r = SESSIONS.get(sid)
    if r is None:
        return Response(status_code=404)
    plan_by_id = {it.image.media_id: it.image for it in r.plan.items}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for im in r.post.images:
            it = plan_by_id.get(im.media_id)
            title = re.sub(r'[\\/:*?"<>|]', "_", (it.title if it else f"image_{im.media_id}.png"))
            try:
                data = DEPS.fetch_image_bytes(im.media_id)
                zf.writestr(title, data)
            except Exception:
                pass
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{r.model.model_id}_images.zip"'})


@app.post("/api/cache-status")
async def cache_status(body: dict):
    sid = body.get("session_id") or ""
    return {"ready": sid in SESSION_CACHE_READY}


@app.get("/api/image/{media_id}")
def image(media_id: str):
    if DEPS.fetch_image_bytes is None:
        return Response(status_code=404)
    try:
        data = DEPS.fetch_image_bytes(media_id)
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        return Response(content=data, media_type=mime)
    except Exception:  # noqa: BLE001
        return Response(status_code=404)


# ---------------------------------------------------------------- static (production build)
_DIST = Path(__file__).parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(__import__("os").getenv("PORT", "8000")))
