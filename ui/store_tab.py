"""
Stage 1 — 门店端·今日推荐 (PROACTIVE_AGENT_PLAN §2, §9). Every backend call goes through agent.ui_data;
this module only builds Gradio widgets and wires their events.
"""
from __future__ import annotations

import html
import re
import tempfile
import time
from pathlib import Path

import gradio as gr

from agent import ui_data
from agent.formatter import render_download, render_publishable, render_report
from agent.schemas import RunResult
from ui.components import (
    LOCKED_LABEL, SLOT_LABELS, banner_html, card_locked_label, default_card_of, fallback_note,
    fresh_session, last_real_run_html, needs_review_html, other_cards, phone_html, placeholder_png,
    prepared_post_html, prepared_pub_text, reason_badges, result_kind, role_notice, stop_html,
    store_choices, talk_card_html,
)

STORES = ui_data.list_stores()
POOL = ui_data.question_pool()
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "hwpc_downloads"


class _RecoveryDisplay:
    """UI-only sentinel: last_real_run() raw payload shown in place of a fresh result after a failed
    generate(), always labelled with its own timestamp (never presented as a fresh run). Excluded from
    "has a result" so the action button still reads 生成, not 重新生成."""

    def __init__(self, payload: dict):
        self.payload = payload


class _PreparedDisplay:
    """UI-only sentinel: agent.ui_data.prepared_post()'s raw payload, shown as today's content as-is
    (「今日已为你准备好」). Counts as "has a result" - the action button reads 重新生成 (live)."""

    def __init__(self, payload: dict):
        self.payload = payload


# ---------------------------------------------------------------- pure-ish view helpers (session in, strings out)
def _card_panel_html(card, prepared: bool) -> str:
    if card is None:
        return "<p>今日暂无推荐。</p>"
    if prepared:
        head = "今日已为你准备好"
    elif card.is_default:
        head = "今日一条"
    else:
        head = SLOT_LABELS.get(card.slot, card.slot)
    parts = [f"<h3>{html.escape(head)}</h3>",
             f"<p><b>{html.escape(card.display_name or '')}</b> · {html.escape(card.platform)}</p>"]
    locked = card_locked_label(card)
    if locked:
        parts.append(f'<div class="hw-banner warn">🔒 {html.escape(locked)}</div>')
    notice = role_notice(card, None)
    if notice:
        parts.append(f'<div class="hw-banner note">{html.escape(notice)}</div>')
    badges = reason_badges(card)
    if badges:
        items = []
        for text, is_demo in badges:
            badge = ' <span class="hw-dev" style="padding:1px 6px">模拟数据</span>' if is_demo else ""
            items.append(f"<li>{html.escape(text)}{badge}</li>")
        parts.append(f'<div><b>为什么推这条</b><ul>{"".join(items)}</ul></div>')
    return "".join(parts)


def _chip_status_html(session: dict) -> str:
    store_id = session.get("store_id")
    tapped = session.get("chips", {}).get(store_id) or set()
    if not tapped:
        return "今天还没有记录顾客提问。"
    names = [POOL[cid]["text"] for cid in tapped if cid in POOL]
    return "今天记录的顾客提问：" + "、".join(names)


def _current_card(session: dict):
    cid = session.get("active_card_id")
    return next((c for c in session.get("cards", []) if c.card_id == cid), None), cid


def _load_store(session: dict, store_id: str) -> None:
    cards = ui_data.get_cards(store_id)
    session["store_id"] = store_id
    session["cards"] = cards
    session.setdefault("results", {})
    session.setdefault("published", {})
    session.setdefault("chips", {})
    session["show_other"] = False
    session.pop("edit_message", None)
    session.pop("recovery", None)
    default = default_card_of(cards)
    session["active_card_id"] = default.card_id if default else None
    session["prepared"] = False
    if default is not None:
        prepared = ui_data.prepared_post(store_id)
        if prepared is not None:
            session["results"][default.card_id] = _PreparedDisplay(prepared)
            session["prepared"] = True


# ---------------------------------------------------------------- the single render function
def _render(session: dict) -> tuple:
    card, cid = _current_card(session)
    others = other_cards(session.get("cards", []))
    session["other_card_ids"] = [c.card_id for c in others]
    slot_updates = []
    for i in range(4):
        if i < len(others):
            c = others[i]
            label = f"{SLOT_LABELS.get(c.slot, c.slot)} · {c.display_name or ''}" + (" 🔒" if c.locked else "")
            slot_updates.append(gr.update(value=label, visible=True))
        else:
            slot_updates.append(gr.update(visible=False))
    other_row_update = gr.update(visible=session.get("show_other", False))

    if card is None:
        return ("<p>今日暂无推荐。</p>", gr.update(visible=False), other_row_update, *slot_updates, "",
               gr.update(visible=False), "", "", "", "", "", "", "", "标记已发布", _chip_status_html(session))

    locked = bool(card.locked)
    results = session.get("results", {})
    has_result = cid in results and not isinstance(results.get(cid), _RecoveryDisplay)
    panel_html = _card_panel_html(card, session.get("prepared", False) and has_result)
    action_update = gr.update(value="重新生成" if has_result else "生成", visible=not locked)

    em = session.get("edit_message")
    edit_msg_html = (f'<div class="hw-banner err">❌ {html.escape(em[1])}</div>'
                     if em and em[0] == cid else "")

    recovery = session.get("recovery")
    recovery_on = bool(recovery and recovery.get("card_id") == cid and cid not in results)
    recovery_msg = f"⚠️ {recovery['error']}" if recovery_on else ""

    talk_out = status_box = banner_out = phone_out = report_md = pub_text = ""
    if locked:
        status_box = stop_html(LOCKED_LABEL, "新品未解锁")
    else:
        result = results.get(cid)
        if isinstance(result, _RecoveryDisplay):
            status_box = last_real_run_html(result.payload)
            pub_text = prepared_pub_text(result.payload)
        elif isinstance(result, _PreparedDisplay):
            status_box = prepared_post_html(result.payload, ui_data.DEPS)
            pub_text = prepared_pub_text(result.payload)
        elif result is not None:
            kind = result_kind(result)
            note = fallback_note(result)
            if note:
                if getattr(result, "fallback", None) == "next_card":
                    actual = SLOT_LABELS.get(getattr(result.task, "slot", None), "")
                    note = f"{note}（{actual}）" if actual else note
                status_box = f'<div class="hw-banner note">ℹ️ {html.escape(note)}</div>'
            if kind == "run_result":
                talk_out = talk_card_html(result)
                banner_out = banner_html(result)
                phone_out = phone_html(result, ui_data.DEPS)
                report_md = render_report(result)
                pub_text = render_publishable(result.post)
            elif kind == "locked":
                status_box += stop_html(result.message, "新品未解锁")
            elif kind == "needs_human":
                status_box += stop_html(result.message)
            elif kind == "needs_review":
                status_box += needs_review_html(result)
                draft = getattr(result, "draft", None)
                if isinstance(draft, RunResult):
                    phone_out = phone_html(draft, ui_data.DEPS)   # read-only: pub_text stays empty, no copy
            elif kind == "baseline":
                status_box += f'<div class="hw-banner note">{html.escape(result.display_text)}</div>'

    published_label = "已发布 ✓（已记录）" if (has_result and session.get("published", {}).get(cid)) else "标记为已发布"
    return (panel_html, action_update, other_row_update, *slot_updates, edit_msg_html,
           gr.update(visible=recovery_on), recovery_msg, talk_out, status_box, banner_out, phone_out,
           report_md, pub_text, published_label, _chip_status_html(session))


# ---------------------------------------------------------------- event handlers
def on_store_change(store_id: str, session: dict):
    session = session or fresh_session()
    _load_store(session, store_id)
    return (*_render(session), session)


def on_initial(session: dict):
    session = session or fresh_session()
    if not session.get("cards"):
        _load_store(session, STORES[0]["store_id"])
    return (*_render(session), session)


def on_switch_toggle(session: dict):
    session["show_other"] = not session.get("show_other", False)
    return (*_render(session), session)


def on_select_other(idx: int, session: dict):
    ids = session.get("other_card_ids") or []
    if idx < len(ids):
        session["active_card_id"] = ids[idx]
        session.pop("edit_message", None)
        session.pop("recovery", None)
    return (*_render(session), session)


def on_generate(session: dict):
    card, cid = _current_card(session)
    if card is None or card.locked:
        return (*_render(session), session)
    session.pop("recovery", None)
    session.pop("edit_message", None)
    try:
        result = ui_data.generate(card)
    except Exception as e:  # noqa: BLE001 - a UI handler must never crash the page
        session["recovery"] = {"card_id": cid, "error": ui_data.plain_error(e)}
        return (*_render(session), session)
    session["results"][cid] = result
    session["prepared"] = False
    return (*_render(session), session)


def on_show_recovery(session: dict):
    card, cid = _current_card(session)
    if card is not None:
        payload = ui_data.last_real_run(cid)
        if payload:
            session["results"][cid] = _RecoveryDisplay(payload)
            session.pop("recovery", None)
    return (*_render(session), session)


def _do_edit(session: dict, instruction: str):
    card, cid = _current_card(session)
    if card is None:
        return (*_render(session), session)
    prev = session.get("results", {}).get(cid)
    if prev is None or isinstance(prev, (_RecoveryDisplay, _PreparedDisplay)):
        msg = "请先点击「重新生成」。" if isinstance(prev, _PreparedDisplay) else "请先生成一条内容。"
        session["edit_message"] = (cid, msg)
        return (*_render(session), session)
    try:
        result = ui_data.edit(prev, instruction)
    except Exception as e:  # noqa: BLE001
        session["edit_message"] = (cid, ui_data.plain_error(e))
        return (*_render(session), session)
    if result_kind(result) == "edit_blocked":
        session["edit_message"] = (cid, result.message)
    else:
        session["results"][cid] = result
        session.pop("edit_message", None)
    return (*_render(session), session)


def on_short(session: dict):
    return _do_edit(session, "短一点")


def on_point(session: dict):
    return _do_edit(session, "换卖点")


def on_angle(session: dict):
    return _do_edit(session, "换个角度")


def on_price(session: dict):
    return _do_edit(session, "加上立减500")


def on_publish(session: dict):
    card, cid = _current_card(session)
    if card is not None:
        session.setdefault("published", {})[cid] = True
    return (*_render(session), session)


def on_chip(chip_id: str, session: dict):
    store_id = session.get("store_id")
    session.setdefault("chips", {}).setdefault(store_id, set()).add(chip_id)
    return (*_render(session), session)


def on_download_text(session: dict):
    card, cid = _current_card(session)
    result = session.get("results", {}).get(cid)
    if not isinstance(result, RunResult):
        return None
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{result.model.canonical_name}_{card.store_name}")[:60]
    path = DOWNLOAD_DIR / f"{name}_{int(time.time())}.md"
    path.write_text(render_download(result), "utf-8")
    return str(path)


def on_save_image(session: dict):
    """保存图片: one image at a time (never a bulk zip - WORKFLOW v4 rule 11 / CLAUDE.md rule 2)."""
    card, cid = _current_card(session)
    result = session.get("results", {}).get(cid)
    if not isinstance(result, RunResult) or not result.post.images:
        return None
    im = result.post.images[0]
    data = None
    fetch = getattr(ui_data.DEPS, "fetch_image_bytes", None)
    if fetch is not None:
        try:
            data = fetch(im.media_id)
        except Exception:  # noqa: BLE001
            data = None
    if not data:
        data = placeholder_png(card.display_name or "图片")
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    ext = "png" if data[:4] == b"\x89PNG" else "jpg"
    path = DOWNLOAD_DIR / f"img_{cid}_{int(time.time())}.{ext}"
    path.write_bytes(data)
    return str(path)


# ---------------------------------------------------------------- build
def build_store_tab(demo: gr.Blocks) -> None:
    session = gr.State(fresh_session)
    gr.Markdown(f"演示日期：{ui_data.today()}")
    store_dd = gr.Dropdown(choices=store_choices(STORES), value=STORES[0]["store_id"],
                           label="演示模式：切换门店账号")
    card_panel = gr.HTML()
    with gr.Row():
        action_btn = gr.Button("生成", variant="primary")
        switch_btn = gr.Button("换一条")
    with gr.Row(visible=False) as other_row:
        slot_btns = [gr.Button(visible=False) for _ in range(4)]
    edit_msg = gr.HTML()
    with gr.Group(visible=False) as recovery_group:
        recovery_msg = gr.Markdown()
        recovery_btn = gr.Button("显示最近一次真实运行结果")
    talk = gr.HTML()
    status_box = gr.HTML()
    banner = gr.HTML()
    with gr.Row():
        with gr.Column(scale=1):
            pass
        with gr.Column(scale=1):
            phone = gr.HTML()
    with gr.Accordion("详细信息（四段式输出）", open=False):
        report = gr.Markdown()
    pub = gr.Textbox(label="可直接复制的正文", lines=6, buttons=["copy"])
    with gr.Row():
        b_short = gr.Button("短一点")
        b_point = gr.Button("换卖点")
        b_angle = gr.Button("换个角度")
        b_price = gr.Button("加上立减500")
    with gr.Row():
        b_dl = gr.DownloadButton("下载 .md")
        b_img = gr.DownloadButton("保存图片")
        b_pub_btn = gr.Button("已发布 ✓")
    published_note = gr.Markdown()
    gr.Markdown("### 今天顾客问了什么？")
    with gr.Row():
        chip_buttons = [gr.Button(c["text"]) for c in POOL.values()]
    chip_status = gr.Markdown()

    OUTS = [card_panel, action_btn, other_row, *slot_btns, edit_msg, recovery_group, recovery_msg,
            talk, status_box, banner, phone, report, pub, published_note, chip_status]
    full_outs = [*OUTS, session]

    store_dd.change(on_store_change, [store_dd, session], full_outs)
    switch_btn.click(on_switch_toggle, [session], full_outs)
    for i, b in enumerate(slot_btns):
        b.click(lambda s, idx=i: on_select_other(idx, s), [session], full_outs)
    action_btn.click(on_generate, [session], full_outs)
    recovery_btn.click(on_show_recovery, [session], full_outs)
    b_short.click(on_short, [session], full_outs)
    b_point.click(on_point, [session], full_outs)
    b_angle.click(on_angle, [session], full_outs)
    b_price.click(on_price, [session], full_outs)
    b_pub_btn.click(on_publish, [session], full_outs)
    b_dl.click(on_download_text, [session], [b_dl])
    b_img.click(on_save_image, [session], [b_img])
    for chip_id, b in zip(POOL.keys(), chip_buttons):
        b.click(lambda s, c=chip_id: on_chip(c, s), [session], full_outs)

    demo.load(on_initial, [session], full_outs)
