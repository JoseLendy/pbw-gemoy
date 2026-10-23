"""
门店端·今日推荐 session logic without any UI toolkit (PROACTIVE_AGENT_PLAN §2, §9).

This is the former ui/store_tab.py with every Gradio widget removed: the same session dict, the same
rules (prepared-first, publish / edit gating, delivered card, recovery, reset token, inline edit check,
exports), but `render()` returns a plain dict view that server.py sends to the Vue frontend as JSON.
Every backend call goes through agent.ui_data.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import html
import re
import tempfile
import threading
import time
from pathlib import Path

from agent import ui_data
from agent.export import wechat_text
from agent.formatter import render_download, render_publishable, render_report
from agent.schemas import RunResult, StaffContext
from ui.components import (
    LOCKED_LABEL, SLOT_LABELS, banner_html, cached_image_bytes, can_act, card_locked_label,
    default_card_of, fallback_note, fresh_session, images_ready, last_real_run_html,
    last_real_run_notice_html, needs_review_html, other_cards, phone_html, placeholder_png,
    prefetch_images, prepared_post_html, prepared_pub_text, reason_badges, result_kind, role_notice,
    stop_html, talk_card_html,
)

STORES = ui_data.list_stores()
POOL = ui_data.question_pool()
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "hwpc_downloads"
# No login screen in the demo; this is the default person using the store tab. Both roles can generate
# every platform (ui.components.can_act); the role only changes the copy around who is signed in.
DEMO_STAFF = StaffContext(staff_id="demo-staff", display_name="门店店员", role="staff")
DEMO_MANAGER = StaffContext(staff_id="demo-manager", display_name="店长", role="manager")
# Every platform the pipeline writes; 朋友圈 first because it is today's default card version.
PLATFORM_TABS = ("朋友圈", "小红书", "公众号", "海报", "抖音")
QUICK_EDITS = ("短一点", "换卖点", "换个角度", "加上立减500")
EMPTY_PHONE = '<div class="hw-phone-empty">生成后将在这里显示手机预览</div>'


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


def _card_panel(card, prepared: bool, staff: StaffContext | None = None,
                prepared_slot: str | None = None, review: bool = False, generated: str = "") -> dict:
    """Structured card panel (the Vue card renders it); `html` is the same content as one string."""
    if card is None:
        return {"head": "", "product": "", "platform": "", "locked": None, "notice": None, "reasons": [],
                "empty": True, "html": '<div class="hw-card"><p>今日暂无推荐。</p></div>'}
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
    locked = card_locked_label(card)
    notice = role_notice(card, staff)
    reasons = [{"text": text, "is_demo": is_demo} for text, is_demo in reason_badges(card)]
    parts = [f"<h3>{html.escape(head)}</h3>",
             f"<p><b>{html.escape(card.display_name or '')}</b> · {html.escape(card.platform)}</p>"]
    if locked:
        parts.append(f'<div class="hw-banner warn">🔒 {html.escape(locked)}</div>')
    if notice:
        parts.append(f'<div class="hw-banner note">{html.escape(notice)}</div>')
    if reasons:
        items = "".join(f"<li>{html.escape(r['text'])}"
                        + (' <span class="hw-dev">模拟数据</span>' if r["is_demo"] else "") + "</li>"
                        for r in reasons)
        parts.append(f'<div><b>为什么推这条</b><ul>{items}</ul></div>')
    return {"head": head, "product": card.display_name or "", "platform": card.platform, "locked": locked,
            "notice": notice, "reasons": reasons, "empty": False,
            "html": '<div class="hw-card">' + "".join(parts) + "</div>"}


def _card_panel_html(*args, **kwargs) -> str:
    """The card panel as one HTML string (old name, kept for the tests)."""
    return _card_panel(*args, **kwargs)["html"]


def _tapped(session: dict) -> set:
    store_id = session.get("store_id")
    return session.get("chips", {}).get(store_id) or set()


def _chip_status(session: dict) -> str:
    tapped = _tapped(session)
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


def staff_for(account: dict) -> StaffContext:
    """The person behind a login account, for the copy that says who is signed in."""
    role = account.get("role") or "staff"
    name = (account.get("display_name") or account.get("store_name")
            or ("店长" if role == "manager" else "门店店员"))
    return StaffContext(staff_id=account.get("username") or "demo-staff",
                        display_name=name, role="manager" if role == "manager" else "staff")


def bind_account(session: dict, account: dict) -> None:
    """A staff/manager login owns both the store and the role for this session. A developer account has
    no store binding and keeps the demo's store picker."""
    if account.get("role") not in ("staff", "manager") or not account.get("store_id"):
        return
    if session.get("store_id") != account["store_id"] or not session.get("cards"):
        load_store(session, account["store_id"])
    session["staff"] = staff_for(account)


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
    result and let the client's image poll swap the phone in when the cache is ready."""
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


def load_store(session: dict, store_id: str) -> None:
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
    # both a process-wide HQ confirmation and a manager's per-store one can unlock a new product
    session["overrides_seen"] = (ui_data.fact_card_overrides(), ui_data.store_approvals())
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


_load_store = load_store   # old name, kept for the tests


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


def _base_view(session: dict, slots: list, show_other: bool) -> dict:
    staff = _staff(session)
    return {
        "panel": _card_panel(None, False), "action": {"label": "生成", "visible": False},
        "show_other": show_other, "slots": slots, "edit_msg_html": "",
        "recovery": {"visible": False, "message": ""}, "talk_html": "", "status_html": "",
        "banner_html": "", "phone_html": "", "report_md": "", "editable": False, "publishable": False,
        "downloadable": False, "pub_text": "", "chip_status": _chip_status(session),
        "tapped_chips": sorted(_tapped(session)),
        "store_id": session.get("store_id"), "image_ok": False, "publish_label": "标记为已发布",
        "published": False, "progress_html": "", "platform": session.get("platform") or PLATFORM_TABS[0],
        "edit_status_html": "", "can_copy": False, "can_export": False, "final_text": "",
        "role": "店长" if staff.role == "manager" else "店员",
        "image_pending": bool(session.get("image_pending")), "platforms": list(PLATFORM_TABS),
        "quick_edits": list(QUICK_EDITS),
    }


def render(session: dict, allow_fetch: bool = False) -> dict:
    card, cid = _current_card(session)
    _ensure_stored(session, card, cid)
    others = other_cards(session.get("cards", []))
    session["other_card_ids"] = [c.card_id for c in others]
    slots = [{"idx": i, "label": f"{SLOT_LABELS.get(c.slot, c.slot)} · {c.display_name or ''}" + (" 🔒" if c.locked else ""),
              "locked": bool(c.locked)} for i, c in enumerate(others[:4])]
    show_other = bool(session.get("show_other", False))
    view = _base_view(session, slots, show_other)
    if card is None:
        return view

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
    panel = _card_panel(actual_card, prepared and not locked, staff, prepared_slot, review, "")
    label = ("重新生成" if display is not None else
             "生成公众号文章" if card.platform == "公众号" else "生成")
    action = {"label": label, "visible": not locked and can_act(card, staff)}

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
            phone_out = phone_html(live, ui_data.DEPS if allow_fetch else None, allow_fetch=allow_fetch)
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
        phone_out = EMPTY_PHONE
    if publishable and session.get("dirty", {}).get(cid):
        pub_text = session.get("drafts", {}).get(cid, pub_text)
    elif publishable and session.get("edited", {}).get(cid):
        pub_text = session["edited"][cid]["text"]
    published = bool(session.get("published", {}).get(cid))
    published_label = ((f"已发布 ✓（{card.platform}，已记录）" if published
                        else f"标记为已发布（{card.platform}）") if publishable else "")

    store_id = session.get("store_id")
    line = ui_data.weekly_progress(store_id)["line"] if store_id else ""
    progress_html = f'<div class="hw-banner note">{html.escape(line)}</div>' if line else ""
    edit_status, can_export = _edit_state(session, cid, publishable)
    final_text = wechat_text(live.post) if isinstance(live, RunResult) and publishable else ""
    zip_ready = bool(can_export and final_text and isinstance(live, RunResult) and images_ready(live))
    view.update({
        "panel": panel, "action": action, "edit_msg_html": edit_msg_html,
        "recovery": {"visible": recovery_on, "message": recovery_msg},
        "talk_html": talk_out, "status_html": status_box, "banner_html": banner_out, "phone_html": phone_out,
        "report_md": report_md, "editable": bool(editable), "publishable": bool(publishable),
        "downloadable": bool(downloadable), "pub_text": pub_text,
        "image_ok": bool(image_ok), "publish_label": published_label or "标记为已发布",
        "published": published and publishable, "progress_html": progress_html,
        "edit_status_html": edit_status, "can_copy": bool(publishable and can_export), "can_export": zip_ready,
        "final_text": final_text, "image_pending": bool(session.get("image_pending")),
    })
    return view


_render = render   # old name, kept for the tests


# ---------------------------------------------------------------- event handlers (session in, view out)
def on_store_change(store_id: str, session: dict) -> dict:
    if store_id:
        load_store(session, store_id)
    return render(session)


def on_initial(session: dict) -> dict:
    if not session.get("cards"):
        load_store(session, STORES[0]["store_id"])
    return render(session)


def on_image_tick(session: dict) -> dict | None:
    """Swap placeholders for prefetched prepared/recovery images once the cache is ready; None = no change."""
    if not session.get("image_pending"):
        return None
    card, cid = _current_card(session)
    live = _final(session, cid, _display_result(session.get("results", {}).get(cid))) if card is not None else None
    if not isinstance(live, RunResult) or not images_ready(live):
        return None
    session["image_pending"] = False
    return render(session)


def on_tab_select(session: dict) -> dict:
    """Returning from 总部端: reset clears this session; a verified new product reloads the cards so the
    newly unlocked 新品款 appears without restarting the app."""
    if session.get("reset_token_seen") != ui_data.reset_token():
        sid = session.get("id")
        session.clear()
        session.update(fresh_session())
        session["id"] = sid
        load_store(session, STORES[0]["store_id"])
    elif (session.get("cards")
          and session.get("overrides_seen") != (ui_data.fact_card_overrides(), ui_data.store_approvals())):
        load_store(session, session.get("store_id") or STORES[0]["store_id"])
    elif not session.get("cards"):
        load_store(session, STORES[0]["store_id"])
    return render(session)


def on_switch_toggle(session: dict) -> dict:
    session["show_other"] = not session.get("show_other", False)
    return render(session)


def on_select_other(idx: int, session: dict) -> dict:
    ids = session.get("other_card_ids") or []
    if 0 <= idx < len(ids):
        session["active_card_id"] = ids[idx]
        session.pop("edit_message", None)
        session.pop("recovery", None)
    return render(session)


def on_generate(session: dict, on_progress=None, on_post=None) -> dict:
    card, cid = _current_card(session)
    if card is None or card.locked or not can_act(card, _staff(session)):
        return render(session)
    session.pop("recovery", None)
    session.pop("edit_message", None)
    session.setdefault("published", {}).pop(cid, None)   # a new version is unpublished
    _drop_edit(session, cid)
    try:
        result = ui_data.generate(card, _staff(session), on_progress=on_progress, on_post=on_post)
    except Exception as e:  # noqa: BLE001 - a UI handler must never crash the page
        session["recovery"] = {"card_id": cid, "error": ui_data.plain_error(e)}
        return render(session)
    session["results"][cid] = result
    session["prepared"] = False
    session["image_pending"] = False
    session.pop("image_fetch_key", None)
    return render(session, allow_fetch=True)


def on_show_recovery(session: dict) -> dict:
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
    return render(session)


def on_quick_edit(session: dict, instruction: str, on_progress=None, on_post=None) -> dict:
    card, cid = _current_card(session)
    if card is None or card.locked or not can_act(card, _staff(session)):
        return render(session)
    prev = session.get("results", {}).get(cid)
    prev_live = _display_result(prev)
    if isinstance(prev, _RecoveryDisplay) or not isinstance(prev_live, RunResult):
        msg = ("历史运行结果只能查看，请先重新生成。" if isinstance(prev, _RecoveryDisplay)
               else "需人工确认的内容不能直接改，请重新生成。" if result_kind(prev) == "needs_review"
               else "请先生成一条内容。")
        session["edit_message"] = (cid, msg)
        return render(session)
    try:
        result = ui_data.edit(prev_live, instruction, on_progress=on_progress, on_post=on_post)
    except Exception as e:  # noqa: BLE001
        session["edit_message"] = (cid, ui_data.plain_error(e))
        return render(session)
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
    return render(session, allow_fetch=True)


def _do_edit(session: dict, instruction: str) -> dict:   # old name, kept for the tests
    return on_quick_edit(session, instruction)


def on_publish(session: dict) -> dict:
    """已发布 ✓ per platform version; the weekly progress line updates at once (agent.recommend.weekly)."""
    card, cid = _current_card(session)
    if card is not None and _can_publish(session, card) and _edit_state(session, cid, True)[1]:
        if not session.setdefault("published", {}).get(cid):
            ui_data.mark_published(card.store_id, card.platform, card.card_id)
        session["published"][cid] = True
    return render(session)


# ---------------------------------------------------------------- platform versions + demo role
def on_platform(platform: str, session: dict) -> dict:
    if platform in PLATFORM_TABS and platform != session.get("platform"):
        session["platform"] = platform
        session.pop("edit_message", None)
        session.pop("recovery", None)
    return render(session)


def on_role(role: str, session: dict) -> dict:
    session["staff"] = DEMO_MANAGER if role in ("店长", "manager") else DEMO_STAFF
    return render(session)


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


def on_text_input(text: str, session: dict) -> dict:
    """Typing in the text box: copy / export / 已发布 stay off until the change is checked.
    Returns {"edit_status_html", "can_copy", "can_export"}."""
    card, key = _current_card(session)
    if card is not None:
        session.setdefault("drafts", {})[key] = text
        session.setdefault("dirty", {})[key] = (text or "").strip() != _shown_text(session, key).strip()
        session.setdefault("edit_fail", {}).pop(key, None)
    publishable = card is not None and _can_publish(session, card)
    status, ok = _edit_state(session, key, publishable)
    return {"edit_status_html": status, "can_copy": bool(ok and publishable), "can_export": bool(ok and publishable)}


def on_check_save(text: str, session: dict) -> dict:
    """Deterministic checks only (no LLM). Pass → 「已修改·已核验」, used for preview, copy and export, and
    logged as a human edit; fail → the failing sentences with reasons, copy/export stay off."""
    card, key = _current_card(session)
    live = _display_result(session.get("results", {}).get(key)) if card is not None else None
    if not isinstance(live, RunResult) or not _can_publish(session, card):
        return render(session)
    original = render_publishable(live.post)
    if (text or "").strip() == original.strip():          # back to the generated text: nothing to save
        _drop_edit(session, key)
        return render(session)
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
    return render(session)


def on_revert(session: dict) -> dict:
    card, key = _current_card(session)
    _drop_edit(session, key)
    return render(session)


def on_chip(chip_id: str, session: dict) -> dict:
    """Tap a customer question; tap the same one again to take it back (the UI shows chips as toggles)."""
    store_id = session.get("store_id")
    if chip_id in POOL:
        tapped = session.setdefault("chips", {}).setdefault(store_id, set())
        if chip_id in tapped:
            tapped.discard(chip_id)
        else:
            tapped.add(chip_id)
    return render(session)


# ---------------------------------------------------------------- downloads ((file name, bytes) or None)
def export_zip(session: dict) -> tuple[str, bytes] | None:
    """「下载发布包」: <store>-<date>-<platform>.zip with 文案.txt (the copied text) and the images in order.
    Built from the in-process image cache only, so it never waits on image bytes."""
    card, key = _current_card(session)
    live = _final(session, key, _display_result(session.get("results", {}).get(key))) if card else None
    if not isinstance(live, RunResult) or not _can_publish(session, card) or not _edit_state(session, key, True)[1]:
        return None
    if not images_ready(live):
        return None
    path = Path(ui_data.export_zip(live.post, card.store_id, wechat_text(live.post), fetch=cached_image_bytes))
    return path.name, path.read_bytes()


def download_text(session: dict) -> tuple[str, bytes] | None:
    card, cid = _current_card(session)
    stored = session.get("results", {}).get(cid)
    result = _final(session, cid, _display_result(stored))
    if isinstance(stored, _RecoveryDisplay) or not isinstance(result, RunResult):
        return None
    name = re.sub(r"[^\w一-鿿-]+", "_", f"{result.model.canonical_name}_{card.store_name}")[:60]
    return f"{name}.md", render_download(result).encode("utf-8")


def save_image(session: dict) -> tuple[str, bytes] | None:
    """保存图片: one image at a time (never a bulk zip - WORKFLOW v4 rule 11 / CLAUDE.md rule 2)."""
    card, cid = _current_card(session)
    stored = session.get("results", {}).get(cid)
    result = _display_result(stored)
    if isinstance(stored, _RecoveryDisplay) or not isinstance(result, RunResult) or not result.post.images:
        return None
    im = result.post.images[0]
    data = cached_image_bytes(im.media_id)
    fetch = getattr(ui_data.DEPS, "fetch_image_bytes", None)
    if not data and fetch is not None:
        try:
            data = fetch(im.media_id)
        except Exception:  # noqa: BLE001
            data = None
    if not data:
        data = placeholder_png(card.display_name or "图片")
    ext = "png" if data[:4] == b"\x89PNG" else ("svg" if data[:4] == b"<svg" else "jpg")
    return f"img_{re.sub(r'[^\w-]+', '_', cid)}_{int(time.time())}.{ext}", data

