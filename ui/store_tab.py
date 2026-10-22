"""
Stage 1 — 门店端·今日推荐 (PROACTIVE_AGENT_PLAN §2, §9). Every backend call goes through agent.ui_data;
this module only builds Gradio widgets and wires their events.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import html
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import gradio as gr

from agent import ui_data
from agent.export import wechat_text
from agent.formatter import render_download, render_publishable, render_report
from agent.schemas import RunResult, StaffContext
from ui.components import (
    LOCKED_LABEL, SLOT_LABELS, banner_html, can_act, card_locked_label, default_card_of, fallback_note,
    fresh_session, images_ready, last_real_run_html, last_real_run_notice_html, needs_review_html,
    other_cards, phone_html, placeholder_png, prefetch_images, prepared_post_html, prepared_pub_text,
    cached_image_bytes,
    reason_badges, result_kind,
    role_notice, stop_html, store_choices, talk_card_html,
)

STORES = ui_data.list_stores()
POOL = ui_data.question_pool()
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "hwpc_downloads"
# No login screen in the demo; this is the default person using the store tab. Stage 4's staff picker
# (optional) can replace it later. It makes the role rule real: 小红书/公众号 are manager-only.
DEMO_STAFF = StaffContext(staff_id="demo-staff", display_name="门店店员", role="staff")
DEMO_MANAGER = StaffContext(staff_id="demo-manager", display_name="店长", role="manager")
PLATFORM_TABS = ("朋友圈", "小红书", "公众号")     # every card has a version per platform; 朋友圈 first
# Shared with app.py's manual tab: one bounded pool for all slow (ima + LLM) events.
GEN_QUEUE = {"concurrency_limit": int(os.getenv("UI_GENERATION_CONCURRENCY", "4")),
             "concurrency_id": "generation", "show_progress": "minimal"}
_LOCAL = {"concurrency_limit": None, "show_progress": "hidden"}


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
def _generated_at(payload: dict | None) -> str:
    """「生成于 10-23 08:12」 (Beijing time) from a stored record's UTC timestamp; "" if absent."""
    ts = (payload or {}).get("timestamp")
    try:
        t = dt.datetime.fromisoformat(ts).astimezone(dt.timezone(dt.timedelta(hours=8)))
    except (TypeError, ValueError):
        return ""
    return f"生成于 {t.strftime('%m-%d %H:%M')}"


def _card_panel_html(card, prepared: bool, staff: StaffContext | None = None,
                     prepared_slot: str | None = None, review: bool = False, generated: str = "") -> str:
    if card is None:
        return '<div class="hw-card"><p>今日暂无推荐。</p></div>'
    if prepared and review:      # a prepared record that ended in NeedsReview is not a ready post
        head = "今日一条 · 需人工确认"
    elif prepared and not card.is_default and not prepared_slot:     # a stored 换一条 card, not a fallback
        head = f"{SLOT_LABELS.get(card.slot, card.slot)} · 已预先生成"
    elif prepared:
        head = "今日已为你准备好" + (f" · {prepared_slot}" if prepared_slot else "")
    elif card.is_default:
        head = "今日一条"
    else:
        head = SLOT_LABELS.get(card.slot, card.slot)
    if prepared and generated:
        head += f" · {generated}"
    parts = [f"<h3>{html.escape(head)}</h3>",
             f"<p><b>{html.escape(card.display_name or '')}</b> · {html.escape(card.platform)}</p>"]
    locked = card_locked_label(card)
    if locked:
        parts.append(f'<div class="hw-banner warn">🔒 {html.escape(locked)}</div>')
    notice = role_notice(card, staff)
    if notice:
        parts.append(f'<div class="hw-banner note">{html.escape(notice)}</div>')
    badges = reason_badges(card)
    if badges:
        items = []
        for text, is_demo in badges:
            badge = ' <span class="hw-dev" style="padding:1px 6px">模拟数据</span>' if is_demo else ""
            items.append(f"<li>{html.escape(text)}{badge}</li>")
        parts.append(f'<div><b>为什么推这条</b><ul>{"".join(items)}</ul></div>')
    return '<div class="hw-card">' + "".join(parts) + "</div>"


def _chip_status_html(session: dict) -> str:
    store_id = session.get("store_id")
    tapped = session.get("chips", {}).get(store_id) or set()
    if not tapped:
        return "今天还没有记录顾客提问。"
    names = [POOL[cid]["text"] for cid in tapped if cid in POOL]
    return "今天记录的顾客提问：" + "、".join(names)


def _current_card(session: dict):
    """(this card's version on the selected platform, its result key "card_id|platform")."""
    cid = session.get("active_card_id")
    card = next((c for c in session.get("cards", []) if c.card_id == cid), None)
    platform = session.get("platform") or PLATFORM_TABS[0]
    if card is None:
        return None, cid
    return dataclasses.replace(card, platform=platform), f"{cid}|{platform}"


def _ensure_stored(session: dict, card, key: str) -> None:
    """Show a precomputed version (prepare_today / prepare_demo) instead of generating, when one exists."""
    results = session.setdefault("results", {})
    if card is None or card.locked or key in results or key in session.setdefault("stored_checked", set()):
        return
    session["stored_checked"].add(key)
    payload = None
    if card.is_default and card.platform == PLATFORM_TABS[0]:
        payload = ui_data.prepared_post(card.store_id)
    payload = payload or ui_data.stored_version(card)
    if payload is not None:
        results[key] = _PreparedDisplay(payload)


def _staff(session: dict) -> StaffContext:
    return session.get("staff") or DEMO_STAFF


def _display_result(display) -> RunResult | None:
    """The live RunResult behind a display slot, including a rehydrated prepared/recovery record."""
    if isinstance(display, RunResult):
        return display
    if isinstance(display, (_PreparedDisplay, _RecoveryDisplay)):
        return ui_data.run_result_from_payload(display.payload)
    return None


def _delivered_card(session: dict, requested, result) -> object:
    """For fallback=next_card: the card that was actually written, if it is in this store's cards."""
    task = getattr(result, "task", None)
    actual_id = getattr(task, "card_id", None)
    if actual_id and actual_id != getattr(requested, "card_id", None):
        found = next((c for c in session.get("cards", []) if c.card_id == actual_id), None)
        return dataclasses.replace(found, platform=requested.platform) if found else requested
    return requested


def _warm_images(session: dict, result: RunResult, allow_fetch: bool) -> None:
    """Page-load/store-switch paths must not block on image bytes. Start one background fetch per
    result and let the store-tab timer swap the phone in when the cache is ready."""
    if allow_fetch or not isinstance(result, RunResult) or images_ready(result):
        return
    key = tuple(im.media_id for im in getattr(getattr(result, "post", None), "images", None) or [])
    if not key or session.get("image_fetch_key") == key:
        return
    session["image_fetch_key"] = key
    session["image_pending"] = True
    threading.Thread(target=prefetch_images, args=(result, ui_data.DEPS), daemon=True,
                     name="hwpc-image-prefetch").start()


def _can_publish(session: dict, card) -> bool:
    if card is None or card.locked or not can_act(card, _staff(session)):
        return False
    display = session.get("results", {}).get(f"{card.card_id}|{card.platform}")
    if isinstance(display, RunResult):
        return bool(display.report.passed)
    # A prepared today's post can be published; a recovery record never can (it is not this run).
    live = _display_result(display) if isinstance(display, _PreparedDisplay) else None
    return isinstance(live, RunResult) and bool(live.report.passed)


def _load_store(session: dict, store_id: str) -> None:
    cards = ui_data.get_cards(store_id)
    session["store_id"] = store_id
    session["cards"] = cards
    session.setdefault("results", {})
    session.setdefault("published", {})
    session.setdefault("chips", {})
    session.setdefault("staff", DEMO_STAFF)
    session["show_other"] = False
    session["image_pending"] = False
    session.pop("image_fetch_key", None)
    session["overrides_seen"] = ui_data.fact_card_overrides()
    session["reset_token_seen"] = ui_data.reset_token()
    session.pop("edit_message", None)
    session.pop("recovery", None)
    session["platform"] = PLATFORM_TABS[0]          # every staff member posts to 朋友圈
    session["stored_checked"] = set()
    default = default_card_of(cards)
    session["active_card_id"] = default.card_id if default else None
    card, key = _current_card(session)
    _ensure_stored(session, card, key)
    session["prepared"] = isinstance(session["results"].get(key), _PreparedDisplay)


# ---------------------------------------------------------------- the single render function
def _final(session: dict, key: str, live):
    """The result as it will be posted: the saved hand edit (「已修改·已核验」) replaces the generated post."""
    saved = session.get("edited", {}).get(key)
    if saved is None or not isinstance(live, RunResult):
        return live
    out = dataclasses.replace(live, post=saved["post"])
    for attr in ("_bundle", "_sibling_ledgers"):
        if hasattr(live, attr):
            setattr(out, attr, getattr(live, attr))
    return out


def _edit_state(session: dict, key: str, publishable: bool) -> tuple:
    """(edit_status html, copy/export allowed): blocked while a change is unchecked or failed its check."""
    fails = session.get("edit_fail", {}).get(key)
    dirty = session.get("dirty", {}).get(key)
    if fails:
        items = "".join(f"<li><mark>{html.escape(f.sentence or '（整篇）')}</mark> — {html.escape(f.reason)}</li>"
                        for f in fails)
        return (f'<div class="hw-banner err">❌ 修改未通过核验，复制和导出已停用（改好后再「检查并保存」，或「恢复原文」）'
                f'<ul>{items}</ul></div>', False)
    if dirty:
        return ('<div class="hw-banner warn">✏️ 有未检查的修改：点「检查并保存」核验后才能复制和导出</div>', False)
    if session.get("edited", {}).get(key):
        return '<div class="hw-banner ok">✅ 已修改·已核验</div>', publishable
    return "", publishable


def _extra_outputs(session: dict, card, key: str, publishable: bool, final) -> tuple:
    store_id = session.get("store_id")
    line = ui_data.weekly_progress(store_id)["line"] if store_id else ""
    progress = f'<div class="hw-banner note">{html.escape(line)}</div>' if line else ""
    status, can_export = _edit_state(session, key, publishable)
    final_text = wechat_text(final.post) if isinstance(final, RunResult) and publishable else ""
    zip_path = _zip_for(card, final) if can_export and final_text else None
    return (progress, gr.update(value=session.get("platform") or PLATFORM_TABS[0]),
            gr.update(visible=publishable), status,
            gr.update(visible=publishable, interactive=can_export),
            gr.update(visible=publishable, interactive=bool(zip_path), value=zip_path), final_text)


def _zip_for(card, final) -> str | None:
    """The 发布包 attached to the button (one click downloads it; a DownloadButton fn would need a second
    click). Built from the in-process image cache only, so a store switch never waits on image bytes; until
    the images are cached the image timer attaches it (on_image_tick)."""
    if not isinstance(final, RunResult) or not images_ready(final):
        return None
    try:
        return ui_data.export_zip(final.post, card.store_id, wechat_text(final.post), fetch=cached_image_bytes)
    except Exception as e:  # noqa: BLE001 - export must never break the page
        ui_data.log.warning("export zip failed: %s", e)
        return None


def _render(session: dict, allow_fetch: bool = False) -> tuple:
    card, cid = _current_card(session)
    _ensure_stored(session, card, cid)
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
               gr.update(visible=False), "", "", "", "", "", "",
               gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), "",
               "", _chip_status_html(session), gr.update(value=session.get("store_id")),
               gr.update(visible=False), gr.update(value="标记为已发布"),
               *_extra_outputs(session, None, cid, False, None))

    staff = _staff(session)
    locked = bool(card.locked)
    results = session.get("results", {})
    display = results.get(cid)
    live = _final(session, cid, _display_result(display))
    prepared = isinstance(display, _PreparedDisplay)
    publishable = _can_publish(session, card)
    editable = (isinstance(live, RunResult) and not isinstance(display, _RecoveryDisplay)
                and can_act(card, staff) and not locked)
    downloadable = isinstance(live, RunResult) and not isinstance(display, _RecoveryDisplay)
    image_ok = downloadable and bool(getattr(live, "post", None) and live.post.images)
    actual_card = _delivered_card(session, card, live) if isinstance(live, RunResult) else card
    if actual_card is not card:
        # The generated post belongs to the next card; never act on it under the requested card's
        # platform/role, and hide the edit controls that would still talk about the old card.
        publishable = publishable and can_act(actual_card, staff)
        editable = False
    prepared_slot = (SLOT_LABELS.get(getattr(actual_card, "slot", None), "")
                     if prepared and actual_card is not card else None)
    review = prepared and (display.payload or {}).get("status") == "NeedsReview"
    panel_html = _card_panel_html(actual_card, prepared and not locked, staff, prepared_slot, review,
                                  _generated_at(display.payload) if prepared else "")
    label = ("重新生成" if display is not None else
             "生成公众号文章" if card.platform == "公众号" else "生成")
    action_update = gr.update(value=label, visible=not locked and can_act(card, staff))

    em = session.get("edit_message")
    edit_msg_html = (f'<div class="hw-banner err">❌ {html.escape(em[1])}</div>'
                     if em and em[0] == cid else "")

    recovery = session.get("recovery")
    recovery_on = bool(recovery and recovery.get("card_id") == cid)
    recovery_msg = f"⚠️ {recovery['error']}" if recovery_on else ""

    talk_out = status_box = banner_out = phone_out = report_md = pub_text = ""
    if locked:
        status_box = stop_html(LOCKED_LABEL, "新品未解锁")
    elif isinstance(display, _RecoveryDisplay):
        if isinstance(live, RunResult):
            _warm_images(session, live, allow_fetch)
            status_box = last_real_run_notice_html(display.payload)
            talk_out = talk_card_html(live)
            banner_out = banner_html(live)
            phone_out = phone_html(live, None, allow_fetch=False)
            report_md = render_report(live)
        else:
            status_box = last_real_run_html(display.payload)
    elif isinstance(display, _PreparedDisplay):
        if isinstance(live, RunResult):
            _warm_images(session, live, allow_fetch)
            note = fallback_note(live)
            if note:
                if getattr(live, "fallback", None) == "next_card":
                    actual_slot = SLOT_LABELS.get(getattr(live.task, "slot", None), "")
                    note = f"{note}（{actual_slot}）" if actual_slot else note
                status_box = f'<div class="hw-banner note">ℹ️ {html.escape(note)}</div>'
            talk_out = talk_card_html(live)
            banner_out = banner_html(live)
            phone_out = phone_html(live, None, allow_fetch=False)
            report_md = render_report(live)
            if publishable:
                pub_text = render_publishable(live.post)
        else:
            status_box = prepared_post_html(display.payload, None)
            pub_text = prepared_pub_text(display.payload) if publishable else ""
    elif display is not None:
        kind = result_kind(display)
        note = fallback_note(display)
        if note:
            if getattr(display, "fallback", None) == "next_card":
                actual_slot = SLOT_LABELS.get(getattr(display.task, "slot", None), "")
                note = f"{note}（{actual_slot}）" if actual_slot else note
            status_box = f'<div class="hw-banner note">ℹ️ {html.escape(note)}</div>'
        if kind == "run_result":
            talk_out = talk_card_html(live)
            banner_out = banner_html(live)
            phone_out = phone_html(live, ui_data.DEPS if allow_fetch else None,
                                   allow_fetch=allow_fetch)
            report_md = render_report(live)
            if publishable:
                pub_text = render_publishable(live.post)
        elif kind == "locked":
            status_box += stop_html(display.message, "新品未解锁")
        elif kind == "needs_human":
            status_box += stop_html(display.message)
            conflicts = getattr(display, "conflicts", None) or []
            if conflicts:
                items = "".join(f"<li>{html.escape(str(c))}</li>" for c in conflicts)
                status_box += f'<div class="hw-banner warn"><ul>{items}</ul></div>'
        elif kind == "needs_review":
            status_box += needs_review_html(display)
            draft = getattr(display, "draft", None)
            if isinstance(draft, RunResult):
                phone_out = phone_html(draft, ui_data.DEPS if allow_fetch else None,
                                       allow_fetch=allow_fetch)   # read-only: no pub_text
        elif kind == "baseline":
            status_box += f'<div class="hw-banner note">{html.escape(display.display_text)}</div>'

    if not locked and display is None:
        phone_out = ('<div style="height:360px;display:flex;align-items:center;justify-content:center;'
                     'border:1px dashed #d0d0d0;border-radius:12px;color:#999;font-size:14px;'
                     'margin:8px 0">生成后将在这里显示手机预览</div>')
    if publishable and session.get("dirty", {}).get(cid):
        pub_text = session.get("drafts", {}).get(cid, pub_text)
    elif publishable and session.get("edited", {}).get(cid):
        pub_text = session["edited"][cid]["text"]
    published_label = ((f"已发布 ✓（{card.platform}，已记录）" if session.get("published", {}).get(cid)
                        else f"标记为已发布（{card.platform}）") if publishable else "")
    return (panel_html, action_update, other_row_update, *slot_updates, edit_msg_html,
           gr.update(visible=recovery_on), recovery_msg, talk_out, status_box, banner_out, phone_out,
           report_md, gr.update(visible=editable), gr.update(visible=publishable),
           gr.update(visible=downloadable), pub_text, "", _chip_status_html(session),
           gr.update(value=session.get("store_id")), gr.update(visible=image_ok),
           gr.update(value=published_label or "标记为已发布"),
           *_extra_outputs(session, card, cid, publishable, live))


# ---------------------------------------------------------------- event handlers
def on_store_change(store_id: str, session: dict):
    session = session or fresh_session()
    if not store_id:
        return (*_render(session), session)
    _load_store(session, store_id)
    return (*_render(session), session)


def on_initial(session: dict):
    session = session or fresh_session()
    if not session.get("cards"):
        _load_store(session, STORES[0]["store_id"])
    return (*_render(session), session)


def on_image_tick(session: dict):
    """Swap placeholders for prefetched prepared/recovery images without blocking a local event, and attach
    the 发布包 once its images are cached."""
    if not session.get("image_pending"):
        return gr.update(), gr.update(), session
    card, cid = _current_card(session)
    live = _final(session, cid, _display_result(session.get("results", {}).get(cid))) if card is not None else None
    if not isinstance(live, RunResult) or not images_ready(live):
        return gr.update(), gr.update(), session
    session["image_pending"] = False
    ok = _can_publish(session, card) and _edit_state(session, cid, True)[1]
    zip_path = _zip_for(card, live) if ok else None
    return (phone_html(live, None, allow_fetch=False),
            gr.update(value=zip_path, interactive=bool(zip_path)) if ok else gr.update(), session)


def on_tab_select(session: dict):
    """Returning from 总部端: reset clears this session; a verified new product reloads the cards so the
    newly unlocked 新品款 appears without restarting the app."""
    session = session or fresh_session()
    if session.get("reset_token_seen") != ui_data.reset_token():
        sid = session.get("id")
        session.clear()
        session.update(fresh_session())
        session["id"] = sid
        _load_store(session, STORES[0]["store_id"])
    elif session.get("cards") and session.get("overrides_seen") != ui_data.fact_card_overrides():
        _load_store(session, session.get("store_id") or STORES[0]["store_id"])
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
    if card is None or card.locked or not can_act(card, _staff(session)):
        return (*_render(session), session)
    session.pop("recovery", None)
    session.pop("edit_message", None)
    session.setdefault("published", {}).pop(cid, None)   # a new version is unpublished
    _drop_edit(session, cid)
    try:
        result = ui_data.generate(card, _staff(session))
    except Exception as e:  # noqa: BLE001 - a UI handler must never crash the page
        session["recovery"] = {"card_id": cid, "error": ui_data.plain_error(e)}
        return (*_render(session), session)
    session["results"][cid] = result
    session["prepared"] = False
    session["image_pending"] = False
    session.pop("image_fetch_key", None)
    return (*_render(session, allow_fetch=True), session)


def on_show_recovery(session: dict):
    card, cid = _current_card(session)
    if card is not None:
        payload = ui_data.last_real_run(card.card_id)
        status = (payload or {}).get("status")
        kind = (payload or {}).get("kind") or "run_from_card"
        if payload and kind == "run_from_card" and status in (None, "RunResult", "NeedsReview"):
            session["results"][cid] = _RecoveryDisplay(payload)
            session.pop("recovery", None)
        else:
            session["recovery"] = {"card_id": cid, "error":
                                   "没有可用于恢复的门店生成记录。" if not payload else
                                   "最近一次记录不是门店生成结果，无法在这里展示。"}
    return (*_render(session), session)


def _do_edit(session: dict, instruction: str):
    card, cid = _current_card(session)
    if card is None or card.locked or not can_act(card, _staff(session)):
        return (*_render(session), session)
    prev = session.get("results", {}).get(cid)
    prev_live = _display_result(prev)
    if isinstance(prev, _RecoveryDisplay) or not isinstance(prev_live, RunResult):
        msg = ("历史运行结果只能查看，请先重新生成。" if isinstance(prev, _RecoveryDisplay)
               else "需人工确认的内容不能直接改，请重新生成。" if result_kind(prev) == "needs_review"
               else "请先生成一条内容。")
        session["edit_message"] = (cid, msg)
        return (*_render(session), session)
    try:
        result = ui_data.edit(prev_live, instruction)
    except Exception as e:  # noqa: BLE001
        session["edit_message"] = (cid, ui_data.plain_error(e))
        return (*_render(session), session)
    if result_kind(result) == "edit_blocked":
        session["edit_message"] = (cid, result.message)
    else:
        session["results"][cid] = result
        session["prepared"] = False
        session["image_pending"] = False
        session.pop("image_fetch_key", None)
        session.setdefault("published", {}).pop(cid, None)
        session.pop("edit_message", None)
        _drop_edit(session, cid)
    return (*_render(session, allow_fetch=True), session)


def on_short(session: dict):
    return _do_edit(session, "短一点")


def on_point(session: dict):
    return _do_edit(session, "换卖点")


def on_angle(session: dict):
    return _do_edit(session, "换个角度")


def on_price(session: dict):
    return _do_edit(session, "加上立减500")


def on_publish(session: dict):
    """已发布 ✓ per platform version; the weekly progress line updates at once (agent.recommend.weekly)."""
    card, cid = _current_card(session)
    if card is not None and _can_publish(session, card) and _edit_state(session, cid, True)[1]:
        if not session.setdefault("published", {}).get(cid):
            ui_data.mark_published(card.store_id, card.platform, card.card_id)
        session["published"][cid] = True
    return (*_render(session), session)


# ---------------------------------------------------------------- platform versions + demo role
def on_platform(platform: str, session: dict):
    if platform in PLATFORM_TABS and platform != session.get("platform"):
        session["platform"] = platform
        session.pop("edit_message", None)
        session.pop("recovery", None)
    return (*_render(session), session)


def on_role(role: str, session: dict):
    session["staff"] = DEMO_MANAGER if role == "店长" else DEMO_STAFF
    return (*_render(session), session)


# ---------------------------------------------------------------- inline edit (「检查并保存」/「恢复原文」)
def _drop_edit(session: dict, key: str) -> None:
    for name in ("edited", "edit_fail", "dirty", "drafts"):
        session.setdefault(name, {}).pop(key, None)


def _shown_text(session: dict, key: str) -> str:
    saved = session.get("edited", {}).get(key)
    if saved:
        return saved["text"]
    live = _display_result(session.get("results", {}).get(key))
    return render_publishable(live.post) if isinstance(live, RunResult) else ""


def on_text_input(text: str, session: dict):
    """Typing in the text box: copy / export / 已发布 stay off until the change is checked."""
    card, key = _current_card(session)
    prev = session.get("drafts", {}).get(key)
    if card is None or text == prev or (prev is None and (text or "").strip() == _shown_text(session, key).strip()):
        return gr.update(), gr.update(), gr.update(), session     # a render set the box: not a user change
    if card is not None:
        session.setdefault("drafts", {})[key] = text
        session.setdefault("dirty", {})[key] = (text or "").strip() != _shown_text(session, key).strip()
        session.setdefault("edit_fail", {}).pop(key, None)
    publishable = card is not None and _can_publish(session, card)
    status, ok = _edit_state(session, key, publishable)
    return status, gr.update(interactive=ok), gr.update(interactive=ok), session


def on_check_save(text: str, session: dict):
    """Deterministic checks only (no LLM). Pass → 「已修改·已核验」, used for preview, copy and export, and
    logged as a human edit; fail → the failing sentences with reasons, copy/export stay off."""
    card, key = _current_card(session)
    live = _display_result(session.get("results", {}).get(key)) if card is not None else None
    if not isinstance(live, RunResult) or not _can_publish(session, card):
        return (*_render(session), session)
    original = render_publishable(live.post)
    if (text or "").strip() == original.strip():          # back to the generated text: nothing to save
        _drop_edit(session, key)
        return (*_render(session), session)
    chk = ui_data.check_edit(text, live)
    if chk.passed:
        session.setdefault("edited", {})[key] = {"text": text.strip(), "post": chk.post}
        session.setdefault("dirty", {})[key] = False
        session.setdefault("edit_fail", {}).pop(key, None)
        session.setdefault("published", {}).pop(key, None)   # the edited version is a new, unpublished one
        ui_data.log_human_edit(card, card.platform, original, text.strip())
    else:
        session.setdefault("edit_fail", {})[key] = chk.failing
        session.setdefault("drafts", {})[key] = text
        session.setdefault("dirty", {})[key] = True
    return (*_render(session), session)


def on_revert(session: dict):
    card, key = _current_card(session)
    _drop_edit(session, key)
    return (*_render(session), session)


def on_export_zip(session: dict):
    """「下载发布包」: <store>-<date>-<platform>.zip with 文案.txt (the copied text) and the images in order."""
    card, key = _current_card(session)
    live = _final(session, key, _display_result(session.get("results", {}).get(key))) if card else None
    if not isinstance(live, RunResult) or not _can_publish(session, card) or not _edit_state(session, key, True)[1]:
        return None
    return ui_data.export_zip(live.post, card.store_id, wechat_text(live.post))


def on_chip(chip_id: str, session: dict):
    store_id = session.get("store_id")
    session.setdefault("chips", {}).setdefault(store_id, set()).add(chip_id)
    return (*_render(session), session)


def on_download_text(session: dict):
    card, cid = _current_card(session)
    stored = session.get("results", {}).get(cid)
    result = _final(session, cid, _display_result(stored))
    if isinstance(stored, _RecoveryDisplay) or not isinstance(result, RunResult):
        return None
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{result.model.canonical_name}_{card.store_name}")[:60]
    path = DOWNLOAD_DIR / f"{name}_{int(time.time())}.md"
    path.write_text(render_download(result), "utf-8")
    return str(path)


def on_save_image(session: dict):
    """保存图片: one image at a time (never a bulk zip - WORKFLOW v4 rule 11 / CLAUDE.md rule 2)."""
    card, cid = _current_card(session)
    stored = session.get("results", {}).get(cid)
    result = _display_result(stored)
    if isinstance(stored, _RecoveryDisplay) or not isinstance(result, RunResult) or not result.post.images:
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
def build_store_tab(demo: gr.Blocks) -> dict:
    session = gr.State(fresh_session)
    with gr.Row():
        store_dd = gr.Dropdown(choices=store_choices(STORES), value=STORES[0]["store_id"],
                               label="演示模式：切换门店账号", scale=3)
        role_rb = gr.Radio(["店员", "店长"], value="店员", label="演示身份", scale=1)
    progress_html = gr.HTML(elem_id="store-week-progress")
    platform_rb = gr.Radio(list(PLATFORM_TABS), value=PLATFORM_TABS[0], label="平台版本", elem_id="store-platform")
    card_panel = gr.HTML(elem_id="store-card-panel")
    with gr.Row():
        action_btn = gr.Button("生成", variant="primary")
        switch_btn = gr.Button("换一条")
    with gr.Row(visible=False) as other_row:
        slot_btns = [gr.Button(visible=False) for _ in range(4)]
    edit_msg = gr.HTML()
    with gr.Group(visible=False) as recovery_group:
        recovery_msg = gr.Markdown()
        recovery_btn = gr.Button("显示最近一次真实运行结果")
    with gr.Row():
        with gr.Column(scale=1):
            gr.HTML('<div class="hw-workflow"><b>店员今天怎么用</b><br>'
                    '1. 选门店 → 2. 看「今日一条」和推荐原因 → 3. 点「生成」 → '
                    '4. 在右侧手机预览检查文案与图片 → 5. 复制/下载，发到门店账号。<br>'
                    '<span style="font-size:13px;opacity:.85">公众号 / 小红书由店长发布；'
                    '朋友圈可直接使用。所有事实与图片都按型号从知识库核验。</span></div>')
            talk = gr.HTML()
            status_box = gr.HTML()
            banner = gr.HTML()
            with gr.Accordion("详细信息（四段式输出）", open=False):
                report = gr.Markdown()
            with gr.Group(visible=False) as edit_group:
                with gr.Row():
                    b_short = gr.Button("短一点")
                    b_point = gr.Button("换卖点")
                    b_angle = gr.Button("换个角度")
                    b_price = gr.Button("加上立减500")
        with gr.Column(scale=1):
            phone = gr.HTML()
            with gr.Group(visible=False) as pub_group:
                pub = gr.Textbox(label="正文（可直接修改，改完点「检查并保存」）", lines=8, interactive=True,
                                 elem_id="store-pub-text")
                with gr.Row(visible=False) as edit_actions:
                    b_check = gr.Button("检查并保存", elem_id="store-check-save")
                    b_revert = gr.Button("恢复原文", elem_id="store-revert")
                edit_status = gr.HTML(elem_id="store-edit-status")
                with gr.Row():
                    b_copy = gr.Button("复制文案", variant="primary", visible=False, elem_id="store-copy")
                    b_zip = gr.DownloadButton("下载发布包", visible=False, elem_id="store-zip")
                final_text = gr.Textbox(elem_id="store-final-text", elem_classes=["hw-hidden"], show_label=False,
                                        container=False, interactive=False)
                b_pub_btn = gr.Button("标记为已发布")
            with gr.Group(visible=False) as file_group:
                with gr.Row():
                    b_dl = gr.DownloadButton("下载 .md")
                    with gr.Group(visible=False) as image_group:
                        b_img = gr.DownloadButton("保存图片")
            published_note = gr.Markdown()
    gr.Markdown("### 今天顾客问了什么？")
    with gr.Row():
        chip_buttons = [gr.Button(c["text"]) for c in POOL.values()]
    chip_status = gr.Markdown()

    OUTS = [card_panel, action_btn, other_row, *slot_btns, edit_msg, recovery_group, recovery_msg,
            talk, status_box, banner, phone, report, edit_group, pub_group, file_group, pub,
            published_note, chip_status, store_dd, image_group, b_pub_btn,
            progress_html, platform_rb, edit_actions, edit_status, b_copy, b_zip, final_text]
    full_outs = [*OUTS, session]

    # Local-only events bypass the queue entirely (concurrency_limit=None): a running generation can
    # never delay opening the app or switching stores.
    store_dd.change(on_store_change, [store_dd, session], full_outs, **_LOCAL)
    switch_btn.click(on_switch_toggle, [session], full_outs, **_LOCAL)
    for i, b in enumerate(slot_btns):
        b.click(lambda s, idx=i: on_select_other(idx, s), [session], full_outs, **_LOCAL)
    action_btn.click(on_generate, [session], full_outs, **GEN_QUEUE)
    recovery_btn.click(on_show_recovery, [session], full_outs, **_LOCAL)
    b_short.click(on_short, [session], full_outs, **GEN_QUEUE)
    b_point.click(on_point, [session], full_outs, **GEN_QUEUE)
    b_angle.click(on_angle, [session], full_outs, **GEN_QUEUE)
    b_price.click(on_price, [session], full_outs, **GEN_QUEUE)
    b_pub_btn.click(on_publish, [session], full_outs, **_LOCAL)
    b_dl.click(on_download_text, [session], [b_dl], **_LOCAL)
    b_img.click(on_save_image, [session], [b_img], **GEN_QUEUE)
    for chip_id, b in zip(POOL.keys(), chip_buttons):
        b.click(lambda s, c=chip_id: on_chip(c, s), [session], full_outs, **_LOCAL)
    platform_rb.change(on_platform, [platform_rb, session], full_outs, **_LOCAL)
    role_rb.change(on_role, [role_rb, session], full_outs, **_LOCAL)
    # .change (not .input: Gradio 6 did not deliver .input from this box in the browser); on_text_input ignores
    # the changes a render makes, so only a real edit turns copy / export off.
    pub.change(on_text_input, [pub, session], [edit_status, b_copy, b_zip, session], **_LOCAL)
    b_check.click(on_check_save, [pub, session], full_outs, **_LOCAL)        # code checks only: < 2 s
    b_revert.click(on_revert, [session], full_outs, **_LOCAL)
    b_copy.click(None, [final_text], None,
                 js="(t) => { navigator.clipboard && navigator.clipboard.writeText(t); return []; }")

    demo.load(on_initial, [session], full_outs, **_LOCAL)
    image_timer = gr.Timer(1.5)
    image_timer.tick(on_image_tick, [session], [phone, b_zip, session], **_LOCAL)
    return {"session": session, "outputs": full_outs, "on_refresh": on_tab_select, "final_text": final_text}


# ---------------------------------------------------------------- 手机发布 (phone view of the current post)
def mobile_view(session: dict) -> tuple[str, str]:
    """(html, text) for the 手机发布 tab: the final text (edited if edited) and each image as a plain <img>
    from the download folder, so staff on a phone can long-press → 保存图片 in WeChat's browser."""
    from agent.export import image_files
    session = session or {}
    card, key = _current_card(session) if session.get("cards") else (None, "")
    live = _final(session, key, _display_result(session.get("results", {}).get(key))) if card else None
    if card is None or not isinstance(live, RunResult) or not _can_publish(session, card) \
            or not _edit_state(session, key, True)[1]:
        return ('<div class="hw-banner note">先在「门店端·今日推荐」打开一条可发布的内容（修改需先通过「检查并保存」），'
                '再回到这里。</div>', "")
    text = wechat_text(live.post)
    folder = DOWNLOAD_DIR / "mobile" / re.sub(r"[^\w-]+", "_", key)
    folder.mkdir(parents=True, exist_ok=True)
    imgs = []
    for name, data in image_files(live.post, getattr(ui_data.DEPS, "fetch_image_bytes", None)):
        path = folder / name
        path.write_bytes(data)
        imgs.append(f'<img src="/gradio_api/file={html.escape(str(path))}" alt="配图{name[:-4]}" '
                    f'style="width:100%;max-width:480px;display:block;margin:10px 0;border-radius:8px">')
    head = f"{card.store_name} · {card.platform} · {card.display_name or ''}"
    return (f'<div style="max-width:520px;margin:0 auto;font-size:16px;line-height:1.7">'
            f'<div style="color:#666;font-size:13px">{html.escape(head)}</div>'
            f'<div id="mobile-post-text" style="white-space:pre-wrap;background:#fff;padding:12px;'
            f'border-radius:8px;margin:8px 0">{html.escape(text)}</div>'
            f'<div style="color:#666;font-size:13px">长按图片 → 保存图片（按顺序发布）</div>{"".join(imgs)}</div>', text)
