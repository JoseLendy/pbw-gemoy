"""
Stage 3 — 对照组 (docs/UI_SPEC.md): left is the unchecked single-shot LLM output, always labelled
「对照组：未经约束的普通大模型输出」; right is our knowledge-base-verified run for the same card.
The baseline is never shown anywhere else and never without that label.
"""
from __future__ import annotations

import html
import os

import gradio as gr

from agent import ui_data
from agent.formatter import render_report
from agent.schemas import BASELINE_LABEL, RunResult
from ui.components import fallback_note, needs_review_html, phone_html, result_kind, stop_html, store_choices

STORES = ui_data.list_stores()
GEN_LIMIT = int(os.getenv("UI_GENERATION_CONCURRENCY", "4"))
_MARK_OPEN = '<mark style="background:#ffe08a;padding:0 1px;border-radius:2px">'


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _highlight(text: str, hits) -> str:
    escaped = html.escape(text or "")
    for hit in hits or []:
        span = (getattr(hit, "span", "") or "").strip()
        if span:
            safe = html.escape(span)
            escaped = escaped.replace(safe, f"{_MARK_OPEN}{safe}</mark>")
    return escaped


def baseline_html(result) -> str:
    if not isinstance(result, RunResult) and result_kind(result) == "locked":
        return (f'<div class="hw-banner warn">🔒 {_esc(getattr(result, "message", "新品资料待总部确认"))}'
                '</div>')
    text = getattr(result, "display_text", "") or ""
    prefix = "【" + BASELINE_LABEL + "】"
    if text.startswith(prefix):
        text = text[len(prefix):].lstrip()
    hits = list(getattr(result, "hits", None) or [])
    hit_html = "".join(
        f'<li>[{_esc(h.stage)}] {_esc(h.message)}'
        + (f'（「{_esc(h.span)}」）' if h.span else "") + "</li>" for h in hits) or "<li>未命中已知 8D 问题（仍未经核验）</li>"
    return (
        '<div class="hw-baseline-card" style="min-height:560px;box-sizing:border-box">'
        f'<h3 style="margin:0 0 4px;color:#8a3b00">{BASELINE_LABEL}</h3>'
        '<div style="font-size:12px;color:#8a3b00;margin-bottom:10px">'
        '单次普通大模型生成 · 未读取知识库 · 未做事实/合规核验 · 仅用于对比</div>'
        f'<div style="white-space:pre-wrap;line-height:1.75;font-size:14px;background:#fff;'
        f'border-radius:8px;padding:12px">{_highlight(text, hits)}</div>'
        f'<h4 style="margin:12px 0 4px">8D 命中</h4><ul style="font-size:13px;margin:0 0 0 18px">'
        f'{hit_html}</ul>'
        '<div style="margin-top:14px;font-size:12px;color:#7a5b3a;border-top:1px dashed #e0c9ad;'
        'padding-top:8px">对比口径：同一门店、同一张卡、同一型号与平台。左侧只调用一次普通模型；'
        '右侧走完整 Agent 流程（事实台账、逐条原文核验、8A–8E 检查）。</div></div>')


def ours_html(result, note: str | None = None) -> str:
    kind = result_kind(result)
    if kind == "run_result":
        report = render_report(result)
        body = phone_html(result, ui_data.DEPS)
        evidence = ('<details style="margin-top:8px"><summary style="cursor:pointer;font-size:13px;'
                    'color:#555">四、核验结果</summary>'
                    f'<pre style="white-space:pre-wrap;font-size:12px;line-height:1.55;background:#f7f7f7;'
                    f'padding:10px;border-radius:6px">{_esc(report)}</pre></details>')
        banner = f'<div class="hw-banner note">ℹ️ {_esc(note)}</div>' if note else ""
        return ('<div class="hw-verified-card">'
                '<h3 style="margin:0 0 4px;color:#1b5e20">我们的结果（知识库核验）</h3>'
                '<div style="font-size:12px;color:#2e7d32;margin-bottom:8px">'
                '事实台账 + 逐条原文核验 + 8A–8E 检查</div>'
                f'{banner}{body}{evidence}</div>')
    if kind == "needs_review":
        out = needs_review_html(result)
        draft = getattr(result, "draft", None)
        if isinstance(draft, RunResult):
            out += ('<div style="margin-top:8px;font-size:12px;color:#8a3b00">'
                    '草稿（只读，不可发布）</div>') + phone_html(draft, ui_data.DEPS)
        return out
    return stop_html(getattr(result, "message", "") or "本次生成未通过。")


def on_baseline(store_id: str):
    if not store_id:
        yield EMPTY_LEFT, EMPTY_RIGHT, "请选择门店。"
        return
    card = ui_data.default_card(store_id)
    if card is None:
        yield "<p>该门店今日没有推荐卡片。</p>", EMPTY_RIGHT, ""
        return
    if card.locked:
        yield '<div class="hw-banner warn">🔒 新品资料待总部确认，暂不可生成</div>', "", ""
        return
    meta = f"同一张卡：**{card.display_name}** · {card.platform} · {card.segment_label} · {card.angle}"
    try:
        base = ui_data.baseline(card)
        left = baseline_html(base)
    except Exception as e:  # noqa: BLE001
        left = (f'<div style="min-height:560px"><h3 style="color:#8a3b00">{BASELINE_LABEL}</h3>'
                f'<div class="hw-banner err">{_esc(ui_data.plain_error(e))}</div></div>')
    yield left, '<div class="hw-banner note">正在生成我们的结果（需要读取知识库并核验，请稍候）…</div>', meta
    try:
        ours = ui_data.generate(card)
        note = fallback_note(ours)
        right = ours_html(ours, note)
        if getattr(ours, "fallback", None) == "next_card":
            delivered = ui_data.model_display_name(getattr(getattr(ours, "task", None), "model_id", None))
            meta = (f"原卡 {card.display_name} 未通过核验，已换成下一条推荐"
                    + (f"：{delivered}。" if delivered else "。"))
        elif note:
            meta += f" · {note}"
    except Exception as e:  # noqa: BLE001
        right = f'<div class="hw-banner err">{_esc(ui_data.plain_error(e))}</div>'
    yield left, right, meta


EMPTY_LEFT = ('<div style="min-height:300px;display:flex;align-items:center;justify-content:center;'
              'border:1px dashed #d0d0d0;border-radius:10px;color:#888">点击「生成对照」查看普通模型输出</div>')
EMPTY_RIGHT = ('<div style="min-height:300px;display:flex;align-items:center;justify-content:center;'
               'border:1px dashed #d0d0d0;border-radius:10px;color:#888">点击「生成对照」查看我们经过核验的结果</div>')


def on_tab_select(token: int):
    now = ui_data.reset_token()
    if token != now:
        return EMPTY_LEFT, EMPTY_RIGHT, "", now
    return gr.update(), gr.update(), gr.update(), token


def build_baseline_tab() -> None:
    with gr.Tab("对照组") as tab:
        gr.Markdown("### 对照组：普通大模型 vs 我们的核验流程\n"
                    "选一家门店的今日一条，左边是一次普通生成，右边是经过知识库核验的结果。"
                    "对照组始终明确标注，绝不作为门店可用文案。")
        with gr.Row():
            store = gr.Dropdown(choices=store_choices(STORES), value=STORES[0]["store_id"],
                                label="门店", scale=3)
            run = gr.Button("生成对照", variant="primary", scale=1)
        msg = gr.Markdown("")
        with gr.Row():
            with gr.Column(scale=1):
                left = gr.HTML(EMPTY_LEFT)
            with gr.Column(scale=1):
                right = gr.HTML(EMPTY_RIGHT)
        token = gr.State(ui_data.reset_token())
        run.click(on_baseline, [store], [left, right, msg],
                  concurrency_limit=GEN_LIMIT, concurrency_id="generation", show_progress="minimal")
        tab.select(on_tab_select, [token], [left, right, msg, token],
                   concurrency_limit=None, show_progress="hidden")
