"""
Gradio UI for the Huawei PC advertorial agent (P5). `python app.py` → http://0.0.0.0:7860

Runs fully on tests/fakes.py until the other workstreams' modules land (Deps.auto picks real ones
as they appear and shows "开发模式" while any fake is in use).

Never shows keys, Client ID or media ids. No raw KB viewer, no bulk export. Public-demo protections:
per-session and global rate limits, plain-language errors.
"""
from __future__ import annotations

import html
import logging
import os
import re
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

# Gradio's launch self-check GETs /gradio_api/startup-events on localhost. With a system proxy
# (Clash / WinHTTP registry) that request is proxied and can return 502, launch aborts before the
# startup endpoint runs, and the queue is never started - every event then hangs at "queue: 1/1".
# Localhost must never go through a proxy: excluded here before Gradio/httpx read the environment.
for _proxy_var in ("NO_PROXY", "no_proxy"):
    _hosts = [h.strip() for h in os.environ.get(_proxy_var, "").split(",") if h.strip()]
    os.environ[_proxy_var] = ",".join(dict.fromkeys([*_hosts, "127.0.0.1", "localhost", "::1"]))

import gradio as gr  # noqa: E402

from agent.formatter import render_download, render_publishable, render_report, strip_fact_tags
from agent.pipeline import edit as pipeline_edit, run as pipeline_run, run_all_platforms
from agent.schemas import Clarification, NeedsHuman, PLATFORM_LABELS, RunResult
from agent.ui_data import DEPS, plain_error, today as demo_today
from ui import baseline_tab, compare_tab, hq_tab, store_tab, theme
from ui.components import banner_html, phone_html, placeholder_png, stop_html, talk_card_html  # noqa: F401

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

ROOT = Path(__file__).parent
CSS = (ROOT / "static" / "phone.css").read_text("utf-8") + "\n" + theme.EXTRA_CSS
KB_NAME = "任德耀新建华为PC知识库"

# ---------------------------------------------------------------- deps + status (cached, never blocking)
# DEPS is the single shared Deps for the whole app (manual tab + proactive tabs): one catalog, one ima
# client. Built once in agent.ui_data and imported here, never re-constructed.
#
# The status bar renders during page load, so the first real DEPS.status() call must not sit in that
# request path: a slow/unreachable ima endpoint would hold the page. Render what is cached and refresh
# in a daemon thread; the timer in build() re-renders once the answer arrives.
_STATUS_TTL = 600.0
_STATUS_STATE: dict = {"data": None, "ts": 0.0, "inflight": False}
_STATUS_LOCK = threading.Lock()


def _placeholder_status() -> dict:
    return {"kb_name": KB_NAME, "connected": False, "configured": bool(os.getenv("LLM_API_KEY")),
            "index_status": "checking", "error": None, "_pending": True}


def _refresh_status() -> None:
    try:
        s = dict(DEPS.status())
    except Exception as e:  # never crash the UI on a status check
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


def llm_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


def status_html() -> str:
    s = kb_status()
    checking = bool(s.get("_pending")) or s.get("index_status") == "checking"
    mode = str(s.get("mode") or "")
    is_mirror = "镜像" in mode or "本地" in mode
    dot = "mid" if checking else ("on" if (s.get("connected") or is_mirror) else "off")
    idx = s.get("index_status") or "stale"
    idx_label = {"complete": "完整", "partial": "部分", "stale": "可能过期",
                 "checking": "连接中…"}.get(idx, idx)
    idx_dot = {"complete": "on", "partial": "mid", "checking": "mid"}.get(idx, "off")
    if checking:
        kb_state = "连接中…"
    elif is_mirror:
        kb_state = "本地镜像 · 可用"
    else:
        kb_state = "已连接" if s.get("connected") else "未连接"
    parts = [
        f'<span><span class="dot {dot}"></span>知识库：{html.escape(s.get("kb_name") or KB_NAME)}'
        f'（{kb_state}）</span>',
        f'<span><span class="dot {idx_dot}"></span>索引：{idx_label}</span>',
        f'<span>模型：{html.escape(os.getenv("LLM_MODEL", "未设置"))}</span>',
        f'<span>密钥：{"已配置 ✓" if (s.get("configured") or llm_configured()) else "未配置"}</span>',
    ]
    if DEPS.is_dev_mode:
        parts.append('<span class="hw-dev">开发模式：部分模块为模拟数据（' +
                     html.escape("、".join(DEPS.fake_fields)) + "）</span>")
    err = s.get("error")
    if err and not s.get("connected") and not checking:
        parts.append(f'<span style="color:#b71c1c">{html.escape(str(err))}</span>')
    return '<div class="hw-status">' + "".join(parts) + "</div>"


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


# plain_error, placeholder_png, image_data_uri, phone_html, talk_card_html, banner_html, stop_html now
# live in ui.components (imported above) so ui/store_tab.py can share them without a circular import.


# ---------------------------------------------------------------- event handlers
EDIT_BTNS = {"短一点": "短一点", "换卖点": "换卖点", "换个角度": "换个角度"}
PLATFORM_CHOICES = [PLATFORM_LABELS[p] for p in ("xiaohongshu", "moments", "wechat_article", "poster", "douyin")]
# Slow (ima + LLM) events share one small pool, so finite model/KB resources stay bounded. Local-only
# events (store switch, tab select, publish, chips, page load) use concurrency_limit=None instead.
GEN_CONCURRENCY = int(os.getenv("UI_GENERATION_CONCURRENCY", "4"))
_GEN_QUEUE = {"concurrency_limit": GEN_CONCURRENCY, "concurrency_id": "generation",
              "show_progress": "minimal"}


def _empty_outputs():
    return {"phone": "", "talk": "", "banner": "", "report": "", "pub": "", "clar_vis": False}


def _render(r: RunResult, session: dict):
    session["result"] = r
    session["results"] = session.get("results", {})
    session["results"][r.post.platform] = r
    return phone_html(r, DEPS), talk_card_html(r), banner_html(r), render_report(r), render_publishable(r.post)


def _handle(result, session: dict, progress_lines: list[str]):
    """Common tail for run/edit: returns the output tuple for the UI."""
    if isinstance(result, Clarification):
        qs = result.questions
        session["clarification"] = result
        radios = []
        for k in range(3):
            if k < len(qs):
                radios.append(gr.update(visible=True, label=qs[k].text, choices=qs[k].options, value=None))
            else:
                radios.append(gr.update(visible=False, choices=[], value=None))
        return ("\n".join(progress_lines), "", "", "", "", "", gr.update(visible=True), *radios)
    hidden = [gr.update(visible=False)] * 3
    if isinstance(result, NeedsHuman):
        return ("\n".join(progress_lines), stop_html(result.message), "", "", "", "", gr.update(visible=False), *hidden)
    phone, talk, banner, report, pub = _render(result, session)
    return ("\n".join(progress_lines), phone, talk, banner, report, pub, gr.update(visible=False), *hidden)


def _fail(progress_lines, msg):
    hidden = [gr.update(visible=False)] * 3
    return ("\n".join(progress_lines), stop_html(msg, "生成失败"), "", "", "", "", gr.update(visible=False), *hidden)


def on_generate(text: str, session: dict, a1, a2, a3):
    session = session or {"id": uuid4().hex}
    text = (text or "").strip()
    lines: list[str] = []
    if not text:
        yield (*_fail(lines, "请先输入一句顾客描述，例如：一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发小红书"), session)
        return
    clar = session.get("clarification")
    is_follow_up = bool(clar and clar.partial and clar.partial.raw_text == text)
    blocked = rate_check(session["id"], follow_up=is_follow_up)
    if blocked:
        yield (*_fail(lines, blocked), session)
        return
    form = {}
    if is_follow_up:
        for q, ans in zip(clar.questions, (a1, a2, a3)):
            if ans:
                form[q.slot] = ans
    session["clarification"] = None

    def progress(stage, msg):
        lines.append(f"· {msg}")

    try:
        result = None
        done = threading.Event()
        box: dict = {}

        def worker():
            try:
                box["r"] = pipeline_run(text, form or None, DEPS, progress)
            except Exception as e:  # noqa: BLE001
                log.exception("run failed")
                box["e"] = e
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        shown = 0
        while not done.wait(0.15):
            if len(lines) != shown:
                shown = len(lines)
                yield ("\n".join(lines), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                       gr.update(), gr.update(), gr.update(), gr.update(), session)
        if "e" in box:
            yield (*_fail(lines, plain_error(box["e"])), session)
            return
        result = box["r"]
    except Exception as e:  # noqa: BLE001
        yield (*_fail(lines, plain_error(e)), session)
        return
    yield (*_handle(result, session, lines), session)


def on_edit(instruction: str, session: dict):
    session = session or {"id": uuid4().hex}
    lines: list[str] = []
    prev = session.get("result")
    if prev is None:
        yield (*_fail(lines, "请先生成一篇内容。"), session)
        return
    blocked = rate_check(session["id"])
    if blocked:
        yield (*_fail(lines, blocked), session)
        return
    try:
        result = pipeline_edit(prev, instruction, DEPS, lambda s, m: lines.append(f"· {m}"))
    except Exception as e:  # noqa: BLE001
        log.exception("edit failed")
        yield (*_fail(lines, plain_error(e)), session)
        return
    yield (*_handle(result, session, lines), session)


def on_switch_platform(label: str, session: dict):
    yield from on_edit(f"换成{label}", session)


def on_all_platforms(session: dict):
    session = session or {"id": uuid4().hex}
    prev = session.get("result")
    if prev is None:
        return stop_html("请先生成一篇内容。", "提示"), session
    blocked = rate_check(session["id"])
    if blocked:
        return stop_html(blocked, "提示"), session
    try:
        outs = run_all_platforms(prev, deps=DEPS)
    except Exception as e:  # noqa: BLE001
        return stop_html(plain_error(e), "生成失败"), session
    cols = []
    for p, res in outs.items():
        if isinstance(res, RunResult):
            session.setdefault("results", {})[p] = res
            cols.append(f'<div style="flex:1;min-width:320px"><div style="text-align:center;font-weight:600">'
                        f'{PLATFORM_LABELS[p]}</div>{banner_html(res)}{phone_html(res, DEPS)}</div>')
        else:
            cols.append(f'<div style="flex:1;min-width:320px">{stop_html(getattr(res, "message", "需要补充信息"))}</div>')
    return '<div style="display:flex;gap:12px;flex-wrap:wrap">' + "".join(cols) + "</div>", session


def on_download(session: dict):
    r = (session or {}).get("result")
    if r is None:
        return None
    out_dir = Path(tempfile.gettempdir()) / "hwpc_downloads"
    out_dir.mkdir(exist_ok=True)
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{r.model.canonical_name}_{PLATFORM_LABELS[r.post.platform]}")[:60]
    path = out_dir / f"{name}_{int(time.time())}.md"
    path.write_text(render_download(r), "utf-8")
    return str(path)


EXAMPLES = [
    "一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书",
    "经常出差的销售想换一台轻薄本，DemoBook 14 SE，发朋友圈",
    "DemoBook 14 开学季 发小红书",
]


# ---------------------------------------------------------------- UI
def build() -> gr.Blocks:
    with gr.Blocks(title="华为 PC 图文软文 Agent") as demo:
        gr.Markdown(f"## 华为 PC 图文软文 Agent\n演示日期：{demo_today()}")
        status = gr.HTML(status_html())
        with gr.Tabs():
            with gr.Tab("门店端·今日推荐") as store_tab_ui:
                store_handles = store_tab.build_store_tab(demo)
            compare_tab.build_compare_tab()
            hq_tab.build_hq_tab()
            baseline_tab.build_baseline_tab()
            with gr.Tab("手动输入"):
                session = gr.State(lambda: {"id": uuid4().hex})
                gr.Markdown("输入一句顾客描述，生成经知识库核验的平台软文。")
                with gr.Row():
                    text = gr.Textbox(label="顾客描述", placeholder=EXAMPLES[0], lines=2, scale=5)
                    gen = gr.Button("生成", variant="primary", scale=1)
                gr.Examples(EXAMPLES, inputs=text)
                with gr.Group(visible=False) as clar_box:
                    gr.Markdown("**还需要补充一点信息：**")
                    r1 = gr.Radio(choices=[], label="", visible=False)
                    r2 = gr.Radio(choices=[], label="", visible=False)
                    r3 = gr.Radio(choices=[], label="", visible=False)
                    cont = gr.Button("继续生成", variant="primary")
                progress = gr.HTML(elem_classes=["hw-progress"])
                with gr.Row():
                    with gr.Column(scale=1):
                        talk = gr.HTML()
                        banner = gr.HTML()
                        with gr.Row():
                            b_short = gr.Button("短一点")
                            b_point = gr.Button("换卖点")
                            b_angle = gr.Button("换个角度")
                        with gr.Row():
                            plat = gr.Dropdown(PLATFORM_CHOICES, label="换平台", value=None, scale=2)
                            b_plat = gr.Button("切换", scale=1)
                            b_all = gr.Button("全平台", scale=1)
                        pub = gr.Textbox(label="可直接复制的正文", lines=8, buttons=["copy"])
                        b_dl = gr.DownloadButton("下载 .md")
                    with gr.Column(scale=1):
                        phone = gr.HTML()
                all_out = gr.HTML()
                with gr.Accordion("详细信息（四段式输出）", open=False):
                    report = gr.Markdown()
                gr.Markdown("<small>知识库内容仅用于生成与核验，不提供原文浏览或批量导出。密钥仅存于环境变量。</small>")

                outs = [progress, phone, talk, banner, report, pub, clar_box, r1, r2, r3, session]
                gen.click(on_generate, [text, session, r1, r2, r3], outs, **_GEN_QUEUE)
                text.submit(on_generate, [text, session, r1, r2, r3], outs, **_GEN_QUEUE)
                cont.click(on_generate, [text, session, r1, r2, r3], outs, **_GEN_QUEUE)
                b_short.click(lambda s: (yield from on_edit("短一点", s)), [session], outs, **_GEN_QUEUE)
                b_point.click(lambda s: (yield from on_edit("换卖点", s)), [session], outs, **_GEN_QUEUE)
                b_angle.click(lambda s: (yield from on_edit("换个角度", s)), [session], outs, **_GEN_QUEUE)
                b_plat.click(on_switch_platform, [plat, session], outs, **_GEN_QUEUE)
                b_all.click(on_all_platforms, [session], [all_out, session], **_GEN_QUEUE)
                b_dl.click(on_download, [session], [b_dl], concurrency_limit=None, show_progress="hidden")
        # Returning from 总部端 introduces newly verified/unlocked cards (and a reset clears the session).
        store_tab_ui.select(store_handles["on_refresh"], [store_handles["session"]],
                            store_handles["outputs"], concurrency_limit=None, show_progress="hidden")
        # The status bar must never block or delay page load: render the cache immediately and let the
        # timer pick up the background check's result a moment later.
        status_timer = gr.Timer(2.0)
        demo.load(lambda: status_html(), None, status, concurrency_limit=None, show_progress="hidden")
        status_timer.tick(lambda: status_html(), None, status, concurrency_limit=None,
                          show_progress="hidden")
    # Every event that can take tens of seconds shares one 4-slot pool; pure-local events opt out with
    # concurrency_limit=None so a running generation can never sit in front of a page load or tab switch.
    demo.queue(default_concurrency_limit=GEN_CONCURRENCY)
    return demo


if __name__ == "__main__":
    port = int(os.getenv("GRADIO_SERVER_PORT", os.getenv("PORT", "7861")))
    demo = build()
    try:
        demo.launch(server_name="0.0.0.0", server_port=port, show_error=False, ssr_mode=False,
                   css=CSS, allowed_paths=[str(Path(tempfile.gettempdir()) / "hwpc_downloads")])
    except Exception as e:
        # Gradio's post-launch self-check (GET .../startup-events) can still fail transiently. That
        # endpoint is also what starts the queue, so retry it directly (trust_env=False ignores the
        # system proxy); otherwise the page loads but every event sits at "queue: 1/1" forever.
        if "startup-events" not in str(e):
            raise
        log.warning("Gradio startup self-check failed, retrying startup events directly: %s", e)
        try:
            import httpx
            resp = httpx.get(f"{demo.local_api_url}startup-events", timeout=10, trust_env=False)
            if not resp.is_success:
                log.error("startup-events retry returned HTTP %s; the queue may not be running",
                          resp.status_code)
        except Exception as retry_err:  # noqa: BLE001
            log.error("startup-events retry failed; the queue may not be running: %s", retry_err)
        demo.block_thread()
