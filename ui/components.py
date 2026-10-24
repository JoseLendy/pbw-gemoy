"""
Pure display-data helpers + HTML render panels shared by every ui/*_tab.py module and by app.py's
manual-flow tab. No Gradio imports here: every function takes plain data (a RunResult, a
RecommendationCard, a session dict, ...) and returns a string / dict / list that any caller can
render or assert on in a test. Never outputs a model_id or the literal "MODEL_" - always
card.display_name / model.canonical_name, per CLAUDE.md hard rule 1 and the plan's on-screen rules.

phone_html / talk_card_html / banner_html / stop_html / placeholder_png / image_data_uri were moved
here from app.py unchanged (behaviour-identical) so ui/store_tab.py can reuse them without a circular
import; app.py imports them back, so `app.banner_html(...)` etc. keep working for existing callers.
"""
from __future__ import annotations

import base64
import html
import re
import threading
from typing import Any, Optional
from uuid import uuid4

from agent.formatter import strip_fact_tags
from agent.schemas import (
    BaselineResult, EditBlocked, LockedResult, NeedsHuman, NeedsReview, RecommendationCard, RunResult,
    StaffContext,
)

# ---------------------------------------------------------------- stores / slots / role rule (pure data)
SLOT_ORDER = ("potential", "promo", "new_release", "customer_question")
SLOT_LABELS = {"potential": "潜力款", "promo": "活动款", "new_release": "新品款", "customer_question": "顾客问答"}
# Every role may generate every platform (product decision, 2026-10-22); the gate stays as the one
# place a future role rule would go, so callers do not change.
STAFF_ONLY_PLATFORMS: tuple[str, ...] = ()
LOCKED_LABEL = "新品资料待总部确认"


def store_choices(stores: list[dict]) -> list[tuple[str, str]]:
    """(label, value) pairs for a Dropdown: label = store_name (never store_id, never a model id)."""
    return [(s["store_name"], s["store_id"]) for s in stores]


def default_card_of(cards: list[RecommendationCard]) -> Optional[RecommendationCard]:
    return next((c for c in cards if c.is_default), None)


def other_cards(cards: list[RecommendationCard]) -> list[RecommendationCard]:
    """Non-default cards, in the fixed slot order (换一条 reveals these)."""
    by_slot = {c.slot: c for c in cards if not c.is_default}
    return [by_slot[s] for s in SLOT_ORDER if s in by_slot]


def reason_badges(card: RecommendationCard) -> list[tuple[str, bool]]:
    """[(text, is_demo)] in order, for 「为什么推这条」; is_demo drives the 模拟数据 badge."""
    return [(r.text, bool(r.is_demo)) for r in (card.reasons or [])]


def can_act(card: RecommendationCard, staff: Optional[StaffContext] = None) -> bool:
    """Every role can generate every platform; staff is accepted so the signature stays binding."""
    return card.platform not in STAFF_ONLY_PLATFORMS


def role_notice(card: RecommendationCard, staff: Optional[StaffContext] = None) -> Optional[str]:
    """The 「由店长发布」 line, only for a platform the caller's role may not act on (none today)."""
    return None if can_act(card, staff) else "由店长发布"


def card_locked_label(card: RecommendationCard) -> Optional[str]:
    return LOCKED_LABEL if card.locked else None


# ---------------------------------------------------------------- session state shape (reset-friendly)
def fresh_session() -> dict:
    """A blank UI session: 已发布 marks, tapped question chips, last shown result per card. Pure - never
    touches the backend, so calling it can never clear prepared posts (those live server-side). `id` is
    a fresh per-session identifier (each call is a new session), not derived from anything backend-side."""
    return {"id": uuid4().hex, "published": {}, "chips": {}, "results": {}}


# ---------------------------------------------------------------- result classification
# docs/UI_BACKEND_CONTRACT.md (Phase 5, T4): run_from_card / generate_batch / prepare_today all return
# one of these per card.
def result_kind(result: Any) -> str:
    """run_result / locked / needs_human / needs_review / edit_blocked / baseline / clarification /
    unknown. NeedsReview is isinstance-checked first; the duck-typed fallback only guards against a
    future rename, the way every other optional path in this app degrades instead of crashing."""
    if isinstance(result, RunResult):
        return "run_result"
    if isinstance(result, NeedsReview):
        return "needs_review"
    if isinstance(result, LockedResult):
        return "locked"
    if isinstance(result, EditBlocked):
        return "edit_blocked"
    if isinstance(result, NeedsHuman):
        return "needs_human"
    if isinstance(result, BaselineResult):
        return "baseline"
    if hasattr(result, "card") and hasattr(result, "draft") and hasattr(result, "failing"):
        return "needs_review"
    if hasattr(result, "questions"):
        return "clarification"
    return "unknown"


# RunResult.fallback (docs/UI_BACKEND_CONTRACT.md): None | "trimmed" | "next_card".
FALLBACK_NOTES = {"trimmed": "已删去未通过核验的句子", "next_card": "今日一条未通过核验，已换成下一条推荐"}


def fallback_note(result: Any) -> Optional[str]:
    return FALLBACK_NOTES.get(getattr(result, "fallback", None))


# 「检查并保存」's reason for a flagged sentence that is still in the text (ui/state.py, server.py).
STILL_FAILING_REASON = "这句未通过自动核验，请改写或删除后再保存"


def group_failing(failing) -> list[tuple[str, list[str], list[str]]]:
    """[(sentence, reasons, stages)], one entry per sentence ("" = the whole post), in first-seen order.
    One sentence can fail several checks (two numbers on the wrong fact + an absolute term), and 「检查并保存」
    adds STILL_FAILING_REASON for it too: listed once, reasons joined, the generic reason only when the
    sentence has no specific one."""
    groups: dict[str, tuple[list[str], list[str]]] = {}
    for f in failing or []:
        key = strip_fact_tags(getattr(f, "sentence", "") or "").strip()
        reasons, stages = groups.setdefault(key, ([], []))
        reason = (getattr(f, "reason", "") or "").strip()
        stage = (getattr(f, "stage", "") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
        if stage and stage not in stages:
            stages.append(stage)
    out = []
    for sentence, (reasons, stages) in groups.items():
        specific = [r for r in reasons if r != STILL_FAILING_REASON]
        out.append((sentence, specific or reasons, stages))
    return out


def failing_list_html(failing, whole_post_label: str = "（整篇）") -> str:
    """The failing sentences as <ul>, each sentence once (see group_failing)."""
    items = "".join(f"<li><mark>{html.escape(s or whole_post_label)}</mark> — {html.escape('；'.join(rs))}</li>"
                    for s, rs, _ in group_failing(failing))
    return f"<ul>{items}</ul>" if items else ""


def needs_review_html(result: NeedsReview) -> str:
    """「需人工确认」 panel: result.message + each failing sentence once with its reasons (or the field, for a
    whole-post problem). The draft itself is rendered separately via phone_html(result.draft, deps) - its
    own check-failure spans already get the .flag highlight."""
    failing = getattr(result, "failing", None) or []
    fields = {strip_fact_tags(f.sentence or "").strip(): f.field for f in failing}
    li = "".join(
        f"<li>[{html.escape('/'.join(stages))}] "
        + (f"「{html.escape(s)}」" if s else html.escape(fields.get(s) or "")) +
        f" — {html.escape('；'.join(rs))}</li>"
        for s, rs, stages in group_failing(failing))
    return (f'<div class="hw-banner err">⛔ {html.escape(result.message)}'
           + (f"<ul>{li}</ul>" if li else "") + '</div>')


# ---------------------------------------------------------------- HTML render panels (moved from app.py)
_IMG_CACHE: dict[str, str] = {}


def placeholder_png(label: str, w: int = 600, h: int = 450) -> bytes:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
           f'<rect width="100%" height="100%" fill="#dfe6ee"/>'
           f'<text x="50%" y="48%" font-size="34" text-anchor="middle" fill="#607d8b" font-family="sans-serif">示例图</text>'
           f'<text x="50%" y="60%" font-size="18" text-anchor="middle" fill="#90a4ae" font-family="sans-serif">'
           f'{html.escape(label)}</text></svg>')
    return svg.encode("utf-8")


def image_data_uri(media_id: str, title: str, deps: Any = None, allow_fetch: bool = True) -> str:
    """deps is any object with an optional .fetch_image_bytes(media_id); never raises, never shows the
    media id - falls back to a labelled placeholder (fake mode, or a fetch failure). allow_fetch=False
    is used by page-load paths so a prepared post can never block on a network image fetch."""
    if media_id in _IMG_CACHE:
        return _IMG_CACHE[media_id]
    uri = ""
    fetch = getattr(deps, "fetch_image_bytes", None) if allow_fetch else None
    if fetch is not None:
        try:
            data = fetch(media_id)
            mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
            uri = f"data:{mime};base64," + base64.b64encode(data).decode()
        except Exception:  # noqa: BLE001 - image fetch must never break the render
            uri = ""
    if not uri:
        # Never cache a placeholder: a later live render with deps must still be able to load the
        # real image (the page-load path intentionally passes allow_fetch=False).
        return "data:image/svg+xml;base64," + base64.b64encode(placeholder_png(title)).decode()
    _IMG_CACHE[media_id] = uri
    return uri


_IMG_INFLIGHT: set[str] = set()
_IMG_LOCK = threading.Lock()


def cached_image_bytes(media_id: str) -> Optional[bytes]:
    """Bytes of an image already in the in-process cache, else None (never fetches)."""
    uri = _IMG_CACHE.get(media_id)
    return base64.b64decode(uri.split(",", 1)[1]) if uri else None


def images_ready(r: RunResult) -> bool:
    """True when every post image is already in the in-process cache (or there are none)."""
    return all(im.media_id in _IMG_CACHE for im in (getattr(getattr(r, "post", None), "images", None) or []))


def prefetch_images(r: RunResult, deps: Any = None) -> None:
    """Warm the image cache without blocking a Gradio page-load/store-switch event. The store tab's
    timer re-renders the phone when images_ready() becomes true."""
    fetch = getattr(deps, "fetch_image_bytes", None)
    if fetch is None:
        return
    for im in getattr(getattr(r, "post", None), "images", None) or []:
        if im.media_id in _IMG_CACHE:
            continue
        with _IMG_LOCK:
            if im.media_id in _IMG_INFLIGHT:
                continue
            _IMG_INFLIGHT.add(im.media_id)
        try:
            image_data_uri(im.media_id, im.caption or "图片", deps, allow_fetch=True)
        finally:
            with _IMG_LOCK:
                _IMG_INFLIGHT.discard(im.media_id)


def _flagged_spans(r: RunResult) -> set[str]:
    return {i.span for i in r.report.issues if i.severity == "error" and i.span}


def _sentence_html(text: str, r: RunResult, flagged: set[str]) -> str:
    """Each sentence with an [F#] gets an expandable source line (fact value, quote, source title)."""
    out = []
    for sent in re.split(r"(?<=[。！？!?])", text):
        if not sent.strip():
            continue
        ids = re.findall(r"\[(F\d+)\]", sent)
        clean = html.escape(strip_fact_tags(sent))
        for sp in flagged:
            if sp and sp in sent:
                clean = clean.replace(html.escape(sp), f'<span class="flag">{html.escape(sp)}</span>')
        facts = [r.ledger.get(i) for i in ids if r.ledger.get(i)]
        if facts:
            src = "".join(f'<div class="src">依据 {f.id}：{html.escape(f.value)}<br>原文：「{html.escape(f.quote)}」'
                          f'<br>来源：{html.escape(f.source_title)}</div>' for f in facts)
            out.append(f'<details><summary><span class="fact">{clean}</span></summary>{src}</details>')
        else:
            out.append(clean)
    return "".join(out)


def _img_tag(im, r: RunResult, deps: Any = None, allow_fetch: bool = True) -> str:
    it = next((p for p in r.plan.items if p.image.media_id == im.media_id), None)
    title = it.image.title if it else "图片"
    cap = html.escape(im.caption or (it.caption if it else ""))
    return (f'<img src="{image_data_uri(im.media_id, title, deps, allow_fetch)}" '
            f'alt="{html.escape(title)}"><div class="cap">{cap}</div>')


def phone_html(r: RunResult, deps: Any = None, allow_fetch: bool = True) -> str:
    p, post = r.post.platform, r.post
    flagged = _flagged_spans(r)
    S = lambda t: _sentence_html(t, r, flagged)  # noqa: E731
    title = html.escape(strip_fact_tags(post.title))
    paras = "".join(f'<div class="p">{S(b)}</div>' for b in post.body)
    imgs = post.images
    tags = " ".join(f"<span>#{html.escape(t)}</span>" for t in post.tags)
    if p == "wechat_article":
        body_parts = []
        for k, b in enumerate(post.body):
            body_parts.append(f'<div class="p">{S(b)}</div>')
            for im in imgs:
                if im.position == f"第{k + 1}段后":
                    body_parts.append(_img_tag(im, r, deps, allow_fetch))
        top = "".join(_img_tag(im, r, deps, allow_fetch) for im in imgs if im.position == "标题下方")
        rest = "".join(_img_tag(im, r, deps, allow_fetch) for im in imgs if im.position not in ("标题下方",) and not re.match(r"第\d+段后", im.position))
        screen = (f'<div class="topbar"><span>‹</span><span>公众号</span><span>···</span></div>'
                  f'<h2>{title}</h2><div class="meta">华为门店 · 刚刚</div><div class="body">{top}'
                  f'<div class="p">{S(post.intro)}</div>{"".join(body_parts)}{rest}'
                  f'<div class="cta">{S(post.cta)}</div></div>')
        skin = "skin-wechat"
    elif p == "moments":
        n = "one" if len(imgs) == 1 else ""
        # 朋友圈 has no title field, but the copied text opens with the title and intro (agent.export
        # .wechat_text), so the preview shows them too: the phone must show every word that gets posted.
        lead = (f'<div class="p"><b>{title}</b></div>' if title else "") + \
               (f'<div class="p">{S(post.intro)}</div>' if post.intro else "")
        screen = (f'<div class="topbar"><span>‹</span><span>朋友圈</span><span>📷</span></div>'
                  f'<div class="post"><div class="avatar"></div><div style="flex:1"><div class="name">华为授权体验店</div>'
                  f'{lead}{paras}<div class="grid {n}">{"".join(_img_tag(im, r, deps, allow_fetch) for im in imgs)}</div>'
                  f'<div class="cta">{S(post.cta)}</div><div class="time">刚刚</div></div></div>')
        skin = "skin-moments"
    elif p == "poster":
        pts = "".join(f'<div class="pt">{S(b)}</div>' for b in post.body)
        screen = (f'{"".join(_img_tag(im, r, deps, allow_fetch) for im in imgs[:1])}<h2>{title}</h2><div class="sub">{S(post.intro)}</div>'
                  f'{pts}<div class="cta">{S(post.cta)}</div>')
        skin = "skin-poster"
    elif p == "douyin":
        screen = (f'<div class="gallery">{"".join(_img_tag(im, r, deps, allow_fetch) for im in imgs)}</div>'
                  f'<div class="body"><b>{title}</b><div class="p">{S(post.intro)}</div>{paras}'
                  f'<div class="cta">{S(post.cta)}</div><div class="tags">{tags}</div></div>')
        skin = "skin-douyin"
    else:  # xiaohongshu
        screen = (f'<div class="author"><div class="avatar"></div><span>华为门店小助手</span></div>'
                  f'<div class="gallery">{"".join(_img_tag(im, r, deps, allow_fetch) for im in imgs)}</div>'
                  f'<h2>{title}</h2><div class="body"><div class="p">{S(post.intro)}</div>{paras}'
                  f'<div class="cta">{S(post.cta)}</div><div class="tags">{tags}</div></div>')
        skin = "skin-xhs"
    if not imgs:
        screen = '<div class="cap">（知识库无该型号图片，本文不配图）</div>' + screen
    return f'<div class="hw-phone {skin}"><div class="notch"></div><div class="screen">{screen}</div></div>'


def talk_card_html(r: RunResult) -> str:
    items = "".join(f"<li>{html.escape(strip_fact_tags(t))}</li>" for t in r.strategy.talk_card)
    return f'<div class="hw-talk"><h4>💬 导购话术（{html.escape(r.model.canonical_name)}）</h4><ol>{items}</ol></div>'


def banner_html(r: RunResult) -> str:
    errs = [i for i in r.report.issues if i.severity == "error"]
    shown = set(r.pending)
    notes = [i for i in r.report.issues if i.severity == "warn" and i.message not in shown]
    out = []
    if r.report.passed and not r.pending:
        out.append('<div class="hw-banner ok">✅ 已核验：所有产品事实均来自知识库台账，图片属于目标型号，未发现合规问题。'
                   f'（{len(r.post.selling_points)} 个事实点 · {len(r.post.images)} 张图 · 改写 {r.loops} 轮）</div>')
    if errs:
        li = "".join(f"<li>{html.escape(i.message)}" + (f"：「{html.escape(i.span)}」" if i.span else "") + "</li>" for i in errs)
        out.append(f'<div class="hw-banner err">❌ {len(errs)} 处未通过核验（已标红，请人工处理）<ul>{li}</ul></div>')
    if r.pending:
        li = "".join(f"<li>{html.escape(p)}</li>" for p in r.pending)
        out.append(f'<div class="hw-banner warn">⚠️ 待确认<ul>{li}</ul></div>')
    if notes:  # warnings (e.g. 表达边界) are 核验提示, not 待确认 lines
        li = "".join(f"<li>{html.escape(i.message)}</li>" for i in notes)
        out.append(f'<div class="hw-banner note">ℹ️ 核验提示<ul>{li}</ul></div>')
    return "".join(out)


def stop_html(msg: str, title: str = "已停止输出，需人工确认") -> str:
    return f'<div class="hw-stop"><b>⛔ {html.escape(title)}</b><div style="margin-top:6px">{html.escape(msg)}</div></div>'


# ---------------------------------------------------------------- raw logged-dict payloads
# agent.runs.prepared_post() and agent.runs.last_real_run() both hand back the RAW logged record
# (agent.runs._payload shape: {"status": type(result).__name__, "result": result.to_dict(), ...}) -
# never a live RunResult/NeedsReview, so these render straight from the dict (no Ledger.get(), no
# live image plan) and are shared by 「今日已为你准备好」 and the real-run-recovery fallback.
def prepared_payload_view(payload: dict) -> dict:
    """{"post": dict, "is_review": bool, "failing": list[dict], "message": str, "fallback": str|None}."""
    result_dict = payload.get("result") or {}
    is_review = (payload.get("status") == "NeedsReview"
                or ("draft" in result_dict and "failing" in result_dict))
    if is_review:
        draft = result_dict.get("draft") or {}
        return {"post": draft.get("post") or {}, "is_review": True,
               "failing": result_dict.get("failing") or [],
               "message": result_dict.get("message") or "需人工确认", "fallback": None,
               "conflicts": result_dict.get("conflicts") or []}
    return {"post": result_dict.get("post") or {}, "is_review": False, "failing": [],
           "message": result_dict.get("message") or "", "fallback": result_dict.get("fallback"),
           "conflicts": result_dict.get("conflicts") or []}


def _post_dict_html(post: dict, deps: Any = None) -> str:
    strip = lambda t: strip_fact_tags(t or "")  # noqa: E731
    imgs = post.get("images") or []
    img_tags = "".join(
        f'<img src="{image_data_uri(im.get("media_id", ""), im.get("caption") or "图片", deps)}" alt="图片">'
        for im in imgs if im.get("media_id"))
    body = "".join(f'<div class="p">{html.escape(strip(b))}</div>' for b in post.get("body") or [])
    screen = (f'{img_tags}<h2>{html.escape(strip(post.get("title")))}</h2>'
             f'<div class="p">{html.escape(strip(post.get("intro")))}</div>{body}'
             f'<div class="cta">{html.escape(strip(post.get("cta")))}</div>')
    return f'<div class="hw-phone"><div class="screen">{screen}</div></div>'


def prepared_post_html(payload: dict, deps: Any = None) -> str:
    """「今日已为你准备好」: render a prepared-post record as-is (it genuinely is today's content, so
    no "not a fresh run" disclaimer - that's only for last_real_run_html's recovery case below)."""
    v = prepared_payload_view(payload)
    if not v["post"]:
        if v["message"]:
            out = stop_html(v["message"])
            if v["conflicts"]:
                out += ('<div class="hw-banner warn"><ul>'
                        + "".join(f"<li>{html.escape(str(c))}</li>" for c in v["conflicts"])
                        + "</ul></div>")
            return out
        return '<div class="hw-banner note">该记录没有可展示的正文。</div>'
    out = _post_dict_html(v["post"], deps)
    if v["is_review"]:
        li = "".join(f"<li>{html.escape(f.get('reason', ''))}" +
                     (f"：「{html.escape(f.get('sentence'))}」" if f.get("sentence") else "") + "</li>"
                     for f in v["failing"])
        return (f'<div class="hw-banner err">⛔ {html.escape(v["message"])}'
               + (f"<ul>{li}</ul>" if li else "")
               + "<p>下方为未发布草稿，仅供人工确认，不能直接复制或发布。</p></div>") + out
    note = FALLBACK_NOTES.get(v["fallback"])
    if note:
        out = f'<div class="hw-banner note">ℹ️ {html.escape(note)}</div>' + out
    return out


def prepared_pub_text(payload: dict) -> str:
    """Publishable copy text for a prepared/last-real-run record; empty for a NeedsReview record (no
    copy button for unreviewed content, per docs/UI_BACKEND_CONTRACT.md)."""
    v = prepared_payload_view(payload)
    if v["is_review"]:
        return ""
    strip = lambda t: strip_fact_tags(t or "")  # noqa: E731
    post = v["post"]
    parts = [strip(post.get("title")), strip(post.get("intro")), *[strip(b) for b in post.get("body") or []],
            strip(post.get("cta"))]
    return "\n\n".join(p for p in parts if p)


def last_real_run_notice_html(payload: dict) -> str:
    ts = payload.get("timestamp", "")
    return (f'<div class="hw-banner warn">⏱ 以下为最近一次真实运行结果（非本次生成）'
            f'· 时间：{html.escape(ts)}</div>')


def last_real_run_html(payload: dict) -> str:
    """Fallback panel for ui_data.last_real_run(): never presented as a fresh run - the label and the
    original timestamp are always shown together, on top of the same dict rendering as a prepared post."""
    return last_real_run_notice_html(payload) + prepared_post_html(payload)
