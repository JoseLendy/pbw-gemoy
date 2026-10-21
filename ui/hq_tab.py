"""
Stage 2 — 总部端 (docs/UI_SPEC.md, plan §8): posting rate, the demo new-product verification gate,
customer questions, this week's platform plan, today's recommendation distribution, and 重置演示.
Offline reads go through agent.ui_data; no ima/LLM call is made on this tab.
"""
from __future__ import annotations

import html

import gradio as gr

from agent import ui_data

_WARN_BG = "#fff4e5"
_CELL = "padding:5px 9px;border-bottom:1px solid #eee"
_HEAD = "padding:6px 9px;text-align:left;background:#f5f5f5;border-bottom:1px solid #ddd"


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _banner(text: str, kind: str = "ok") -> str:
    cls = {"ok": "hw-banner ok", "warn": "hw-banner warn", "note": "hw-banner note"}.get(kind, "hw-banner note")
    return f'<div class="{cls}" style="margin:8px 0">{_esc(text)}</div>'


def posting_html() -> str:
    data = ui_data.publish_stats()
    rows = []
    for s in data["stats"]:
        pct = s["rate"] * 100
        bar = (f'<div style="height:8px;width:100%;background:#eee;border-radius:4px">'
               f'<div style="height:8px;width:{pct:.1f}%;background:{"#c62828" if s["low"] else "#2e7d32"};'
               f'border-radius:4px"></div></div>')
        flag = (' <span style="font-size:11px;color:#b26a00;background:#ffe9b8;border-radius:8px;'
                'padding:1px 6px">偏低</span>' if s["low"] else "")
        rows.append(f'<tr style="background:{_WARN_BG if s["low"] else "#fff"}">'
                    f'<td style="{_CELL}">{_esc(s["store_name"])}</td>'
                    f'<td style="{_CELL}">{s["posted"]}/{s["days"]}</td>'
                    f'<td style="{_CELL};width:45%">{bar}</td>'
                    f'<td style="{_CELL};text-align:right">{pct:.1f}%{flag}</td></tr>')
    window = data["window"]
    return (f'<div style="font-size:13px;color:#666;margin-bottom:6px">最近 {data["days"]} 个记录日'
            f'（{_esc(window[0])} 至 {_esc(window[1])}，截至最新记录）· 发帖天数 / 应发天数</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;background:#fff">'
            f'<thead><tr><th style="{_HEAD}">门店</th><th style="{_HEAD}">已发</th>'
            f'<th style="{_HEAD}">完成度</th><th style="{_HEAD};text-align:right">发帖率</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def release_html() -> str:
    drafts = ui_data.new_release_drafts()
    if not drafts:
        return _banner("当前没有在售新品草稿。", "note")
    blocks = []
    for d in drafts:
        status = "已确认发布" if d["verified"] else "待总部确认"
        color = "#2e7d32" if d["verified"] else "#b26a00"
        refs = "".join(
            f'<tr><td style="{_CELL}">{_esc(r["ref_id"])}</td><td style="{_CELL}">{_esc(r["fields"])}</td>'
            f'<td style="{_CELL}">{_esc(r["source_title"])}<div style="font-size:11px;color:#888">'
            f'{_esc(r["source_path"])}</div></td></tr>' for r in d["refs"])
        note = ("已解锁门店生成（演示状态）；具体数值仍需按知识库事实卡核验。"
                if d["verified"] else
                "演示审核清单：以下只是字段与来源参考，不是已核验的事实卡数值。")
        note_style = ("color:#1b5e20;background:#eef7ee" if d["verified"]
                      else "color:#8a4b00;background:#fff8e1")
        blocks.append(
            f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;background:#fff">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<b style="font-size:15px">{_esc(d["display_name"])}</b>'
            f'<span style="font-size:12px;color:{color};background:#f5f5f5;border-radius:10px;padding:2px 8px">'
            f'{_esc(status)}</span></div>'
            f'<div style="font-size:12px;color:#666;margin:4px 0 8px">演示上市日期：{_esc(d["launch_date"])}'
            f' · 总部确认一次，全部门店解锁</div>'
            f'<div style="font-size:12px;{note_style};border-radius:6px;padding:6px 8px;margin-bottom:8px">'
            f'{_esc(note)}</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:12px">'
            f'<thead><tr><th style="{_HEAD}">参考</th><th style="{_HEAD}">字段组</th>'
            f'<th style="{_HEAD}">来源</th></tr></thead><tbody>{refs}</tbody></table></div>')
    return "".join(blocks)


def has_draft() -> bool:
    return any(not d["verified"] for d in ui_data.new_release_drafts())


def questions_html() -> str:
    rows = "".join(
        f'<tr><td style="{_CELL};text-align:center">{i + 1}</td><td style="{_CELL}">{_esc(q["text"])}</td>'
        f'<td style="{_CELL};text-align:right">{q["count"]}</td>'
        f'<td style="{_CELL};text-align:right">{q["stores"]} 店</td></tr>'
        for i, q in enumerate(ui_data.question_stats(8)))
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px;background:#fff">'
            f'<thead><tr><th style="{_HEAD}">#</th><th style="{_HEAD}">顾客问题</th>'
            f'<th style="{_HEAD};text-align:right">次数</th><th style="{_HEAD};text-align:right">覆盖门店</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def plan_html() -> str:
    plan = ui_data.weekly_plan()
    chips = []
    for d in plan["days"]:
        today = d["is_today"]
        chips.append(
            f'<div style="flex:1;min-width:74px;text-align:center;border-radius:8px;padding:8px 4px;'
            f'background:{"#fff3e0" if today else "#fff"};border:1px solid '
            f'{"#ff8f00" if today else "#e0e0e0"}">'
            f'<div style="font-size:12px;color:#666">{_esc(d["label"])}</div>'
            f'<div style="font-size:12px;color:#999">{_esc(d["date"][5:])}</div>'
            f'<div style="font-weight:700;margin-top:4px;color:{"#e65100" if today else "#333"}">'
            f'{_esc(d["platform"])}</div></div>')
    minimum = " · ".join(f"{k} ≥ {v}" for k, v in plan["minimum"].items())
    return (f'<div style="font-size:12px;color:#666;margin-bottom:6px">本周最低要求：{_esc(minimum)}'
            f' · 今日：{_esc(plan["today"])}</div>'
            f'<div style="display:flex;gap:6px;flex-wrap:nowrap">{"".join(chips)}</div>')


def distribution_html() -> str:
    rows = "".join(
        f'<tr><td style="{_CELL}">{_esc(x["store_name"])}</td>'
        f'<td style="{_CELL}">{_esc(x["display_name"])}</td>'
        f'<td style="{_CELL}">{_esc(x["slot_label"])} · {_esc(x["platform"])}</td>'
        f'<td style="{_CELL}">{_esc(x["segment_label"])} · {_esc(x["angle"])}</td></tr>'
        for x in ui_data.recommendation_distribution())
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px;background:#fff">'
            f'<thead><tr><th style="{_HEAD}">门店</th><th style="{_HEAD}">今日一条</th>'
            f'<th style="{_HEAD}">槽位 · 平台</th><th style="{_HEAD}">客群 · 角度</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def on_verify():
    drafts = [d for d in ui_data.new_release_drafts() if not d["verified"]]
    if not drafts:
        return (release_html(), gr.update(visible=False), _banner("没有待确认的新品。", "note"), "",
                distribution_html())
    model = drafts[0]
    ui_data.verify_new_product(model["model_id"])
    msg = _banner(f"已确认发布（演示解锁）：{model['display_name']}。全部门店的新品款已解锁；"
                  "本演示未对具体数值做事实核验，切回门店端即可看到。")
    return release_html(), gr.update(visible=has_draft()), msg, "", distribution_html()


def on_reset():
    ui_data.reset()
    msg = _banner("已重置演示数据：新品恢复待确认，门店推荐重置；已发布标记与顾客提问将在回到门店端时清空。"
                  "（已准备的口播稿不会被删除。）", "note")
    return (posting_html(), release_html(), gr.update(visible=has_draft()), msg, "", questions_html(),
            plan_html(), distribution_html())


def build_hq_tab() -> None:
    with gr.Tab("总部端"):
        gr.Markdown("### 总部视图\n发布情况、新品审核、顾客问题、本周计划与推荐分布。")
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("#### 发布情况")
                posting = gr.HTML(posting_html())
                gr.Markdown("#### 演示：模拟新品上市审核流程")
                release = gr.HTML(release_html())
                with gr.Row():
                    verify = gr.Button("确认发布", variant="primary", visible=has_draft())
                verify_msg = gr.HTML()
            with gr.Column(scale=1):
                gr.Markdown("#### 顾客高频问题")
                questions = gr.HTML(questions_html())
                gr.Markdown("#### 本周计划")
                plan = gr.HTML(plan_html())
        gr.Markdown("#### 推荐分布（今日一条）")
        distribution = gr.HTML(distribution_html())
        with gr.Row():
            reset = gr.Button("重置演示")
        reset_msg = gr.HTML()
        verify.click(on_verify, None, [release, verify, verify_msg, reset_msg, distribution],
                     concurrency_limit=None, show_progress="hidden")
        reset.click(on_reset, None,
                    [posting, release, verify, reset_msg, verify_msg, questions, plan, distribution],
                    concurrency_limit=None, show_progress="hidden")
