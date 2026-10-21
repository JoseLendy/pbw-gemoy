"""
Stage 2 — 三店对比 (docs/UI_SPEC.md): one product, one platform, four fixed stores (S01 / S04 / S08 /
S02). Each store keeps its own segment, scenario, angle, hook, voice and landmark; only the product and
platform are overridden. All backend calls go through agent.ui_data.
"""
from __future__ import annotations

import dataclasses
import html

import gradio as gr

from agent import ui_data
from agent.schemas import RunResult
from ui.components import needs_review_html, phone_html, stop_html, result_kind

COMPARE_STORES = [
    ("S01", "校园店"),
    ("S04", "CBD 店"),
    ("S08", "社区店"),
    ("S02", "校园二店"),
]
PLATFORMS = ["朋友圈", "小红书", "公众号"]
SCENARIO_LABELS = {
    "campus_daily": "校园日常",
    "office": "办公通勤",
    "holiday": "节前购物",
    "new_launch": "新品上市",
}
SEGMENT_LABELS = {"student": "学生客群", "office": "商务办公", "family": "家庭用户", "shopper": "到店顾客"}


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _meta_html(card) -> str:
    voice = getattr(getattr(card, "voice", None), "label", "") or "—"
    hook = getattr(getattr(card, "hook", None), "label", "") or "—"
    scenario = SCENARIO_LABELS.get(card.scenario or "", card.scenario or "—")
    parts = [
        f"<b>{_esc(card.store_name)}</b> · {_esc(card.segment_label or SEGMENT_LABELS.get(card.segment, ''))}",
        f"场景：{_esc(scenario)} · 角度：{_esc(card.angle)}",
        f"语气：{_esc(voice)} · 钩子：{_esc(hook)}",
        f"地标：{_esc(card.landmark or '—')}",
    ]
    return ('<div style="font-size:13px;line-height:1.7;color:#333;margin:2px 4px 14px">'
            + "<br>".join(parts) + "</div>")


def _result_panel(sid: str, card, result, regenerated: bool) -> str:
    head = (f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:6px 4px 4px"><span style="font-weight:700;font-size:16px">{_esc(card.store_name)}</span>'
            f'{"<span style=\"font-size:12px;color:#8a4b00;background:#fff3cd;border-radius:10px;padding:2px 8px\">8E 已重写</span>" if regenerated else ""}</div>')
    kind = result_kind(result)
    if kind == "run_result":
        body = phone_html(result, ui_data.DEPS)
    elif kind == "needs_review":
        body = needs_review_html(result)
    elif isinstance(result, Exception):
        body = stop_html(ui_data.plain_error(result))
    else:
        body = stop_html(getattr(result, "message", "") or "该门店生成失败。")
    return f'<div style="flex:1 1 430px;min-width:380px;max-width:470px">{head}{body}{_meta_html(card)}</div>'


def _similarity_html(pairs: list, names: dict[str, str]) -> str:
    if not pairs:
        return ""
    rows = []
    for p in pairs:
        seg = SEGMENT_LABELS.get(p.segment, p.segment)
        mark = ('<span style="color:#8a4b00">已重写</span>' if p.regenerated
                else '<span style="color:#2e7d32">保持</span>')
        rows.append(
            f"<tr><td style='padding:4px 8px'>{_esc(names.get(p.store_a, p.store_a))} ↔ "
            f"{_esc(names.get(p.store_b, p.store_b))}</td><td style='padding:4px 8px'>{_esc(seg)}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{p.before:.3f} → {p.after:.3f}</td>"
            f"<td style='padding:4px 8px'>{mark}</td></tr>")
    return ('<h4 style="margin:18px 0 6px">跨店相似度（8E：阈值 0.550）</h4>'
            '<table style="border-collapse:collapse;font-size:13px;background:#fff;'
            'border:1px solid #e0e0e0"><thead><tr style="background:#f5f5f5">'
            '<th style="padding:5px 8px;text-align:left">门店</th><th style="padding:5px 8px;text-align:left">客群</th>'
            '<th style="padding:5px 8px;text-align:right">改写前 → 改写后</th>'
            '<th style="padding:5px 8px;text-align:left">8E</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")


def on_compare(model_id: str, platform: str):
    if not model_id:
        return "<p>请选择一个在售产品。</p>", ""
    cards, missing = [], []
    for store_id, label in COMPARE_STORES:
        card = ui_data.product_card(store_id, model_id)
        if card is None:
            missing.append(f"{label}（{store_id}）")
            continue
        cards.append(dataclasses.replace(card, platform=platform, is_default=False))
    if missing:
        return (f"<div class='hw-banner warn'>以下门店当前没有该产品的活动款，无法对比："
                f"{_esc('、'.join(missing))}</div>", "")
    try:
        batch = ui_data.compare(cards)
    except Exception as e:  # noqa: BLE001 - a UI handler must never crash the page
        return f"<div class='hw-banner err'>生成失败：{_esc(ui_data.plain_error(e))}</div>", ""

    names = {c.store_id: c.store_name for c in cards}
    cols = []
    for card in cards:
        result = batch.results.get(card.store_id)
        if result is None:
            result = RuntimeError("该门店没有返回结果。")
        cols.append(_result_panel(card.store_id, card, result, card.store_id in batch.regenerated))
    body = ('<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start">'
            + "".join(cols) + "</div>" + _similarity_html(batch.similarity, names))
    summary = (f"4 店完成 · 总耗时 {batch.wall_seconds:.1f}s · 8E 重写 "
               f"{len(batch.regenerated)} 店（{_esc('、'.join(names.get(s, s) for s in batch.regenerated)) if batch.regenerated else '无'}）")
    return body, summary


def build_compare_tab() -> None:
    with gr.Tab("三店对比"):
        gr.Markdown("### 同一个产品，四家门店各自表达\n"
                    "固定 S01 紫金港店 / S04 钱江新城店 / S08 九堡店 / S02 下沙高教园店；"
                    "产品与平台统一，客群、场景、角度、语气与地标保留各店差异。")
        products = ui_data.compare_products()
        choices = [(p["display_name"], p["model_id"]) for p in products]
        with gr.Row():
            product = gr.Dropdown(choices=choices, value=choices[0][1] if choices else None,
                                  label="产品（演示活动价）", scale=3)
            platform = gr.Dropdown(choices=PLATFORMS, value="朋友圈", label="平台", scale=1)
            run = gr.Button("生成四店对比", variant="primary", scale=1)
        msg = gr.Markdown("")
        out = gr.HTML()
        run.click(on_compare, [product, platform], [out, msg],
                  concurrency_limit=4, concurrency_id="generation", show_progress="minimal")
