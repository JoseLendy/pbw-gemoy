"""
总部端 view functions (no UI toolkit; server.py calls them).
Stage 2 — 总部端 (docs/UI_SPEC.md, plan §8): posting rate, the demo new-product verification gate,
customer questions, this week's platform plan, today's recommendation distribution, and 重置演示.
Offline reads go through agent.ui_data; no ima/LLM call is made on this tab.
"""
from __future__ import annotations

import html

from agent import ui_data

# Frosted-glass inline styles: the panels are translucent dark glass with white text, so the tables keep
# light text on a translucent/transparent background (no white boxes) and the warn highlight is amber.
_WARN_BG = "rgba(245,158,11,0.16)"
_CELL = "padding:5px 9px;border-bottom:1px solid rgba(255,255,255,0.12);color:rgba(255,255,255,0.92)"
_HEAD = "padding:6px 9px;text-align:left;background:rgba(255,255,255,0.08);border-bottom:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.72)"
_MUTED = "rgba(255,255,255,0.62)"


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
        bar = (f'<div style="height:8px;width:100%;background:rgba(255,255,255,0.14);border-radius:4px">'
               f'<div style="height:8px;width:{pct:.1f}%;background:{"#F87171" if s["low"] else "#4ADE80"};'
               f'border-radius:4px"></div></div>')
        flag = (' <span style="font-size:11px;color:#FCD34D;background:rgba(245,158,11,0.20);border-radius:8px;'
                'padding:1px 6px">偏低</span>' if s["low"] else "")
        rows.append(f'<tr style="background:{_WARN_BG if s["low"] else "transparent"}">'
                    f'<td style="{_CELL}">{_esc(s["store_name"])}</td>'
                    f'<td style="{_CELL}">{s["posted"]}/{s["days"]}</td>'
                    f'<td style="{_CELL};width:45%">{bar}</td>'
                    f'<td style="{_CELL};text-align:right">{pct:.1f}%{flag}</td></tr>')
    window = data["window"]
    return (f'<div style="font-size:13px;color:{_MUTED};margin-bottom:6px">最近 {data["days"]} 个记录日'
            f'（{_esc(window[0])} 至 {_esc(window[1])}，截至最新记录）· 发帖天数 / 应发天数</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
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
        color = "#4ADE80" if d["verified"] else "#FBBF24"
        refs = "".join(
            f'<tr><td style="{_CELL}">{_esc(r["ref_id"])}</td><td style="{_CELL}">{_esc(r["fields"])}</td>'
            f'<td style="{_CELL}">{_esc(r["source_title"])}<div style="font-size:11px;color:rgba(255,255,255,0.55)">'
            f'{_esc(r["source_path"])}</div></td></tr>' for r in d["refs"])
        note = ("已解锁门店生成（演示状态）；具体数值仍需按知识库事实卡核验。"
                if d["verified"] else
                "演示审核清单：以下只是字段与来源参考，不是已核验的事实卡数值。")
        note_style = ("color:#BBF7D0;background:rgba(34,197,94,0.14)" if d["verified"]
                      else "color:#FDE68A;background:rgba(245,158,11,0.14)")
        blocks.append(
            f'<div style="border:1px solid rgba(255,255,255,0.18);border-radius:8px;padding:12px;background:rgba(255,255,255,0.05)">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<b style="font-size:15px;color:#fff">{_esc(d["display_name"])}</b>'
            f'<span style="font-size:12px;color:{color};background:rgba(255,255,255,0.10);border-radius:10px;padding:2px 8px">'
            f'{_esc(status)}</span></div>'
            f'<div style="font-size:12px;color:{_MUTED};margin:4px 0 8px">演示上市日期：{_esc(d["launch_date"])}'
            f' · 总部确认一次，全部门店解锁</div>'
            f'<div style="font-size:12px;{note_style};border-radius:6px;padding:6px 8px;margin-bottom:8px">'
            f'{_esc(note)}</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:12px;background:transparent">'
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
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">#</th><th style="{_HEAD}">顾客问题</th>'
            f'<th style="{_HEAD};text-align:right">次数</th><th style="{_HEAD};text-align:right">覆盖门店</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def plan_html() -> str:
    """本周计划: each store's weekly progress against the minimums (a suggestion, not a fixed rotation).
    A platform still short of its minimum is highlighted."""
    rows_data = ui_data.weekly_progress_all()
    platforms = list(rows_data[0]["progress"]) if rows_data else []
    head = "".join(f'<th style="{_HEAD};text-align:center">{_esc(p)}</th>' for p in platforms)
    rows = []
    for r in rows_data:
        cells = []
        for p in platforms:
            v = r["progress"][p]
            short = p in r["behind"]
            style = f'{_CELL};text-align:center' + (";background:rgba(245,158,11,0.20);color:#FCD34D;font-weight:700" if short else "")
            cells.append(f'<td style="{style}">{v["done"]}/{v["minimum"]}</td>')
        rows.append(f'<tr><td style="{_CELL}">{_esc(r["store_name"])}</td>{"".join(cells)}'
                    f'<td style="{_CELL}">{_esc(r["suggestion"])}</td></tr>')
    n_behind = sum(1 for r in rows_data if r["behind"])
    return (f'<div style="font-size:12px;color:{_MUTED};margin-bottom:6px">本周（周一至今）发布进度 · '
            f'{n_behind} 家门店有平台未达标（橙色）</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">门店</th>{head}<th style="{_HEAD}">今天建议发</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def distribution_html() -> str:
    rows = "".join(
        f'<tr><td style="{_CELL}">{_esc(x["store_name"])}</td>'
        f'<td style="{_CELL}">{_esc(x["display_name"])}</td>'
        f'<td style="{_CELL}">{_esc(x["slot_label"])} · {_esc(x["platform"])}</td>'
        f'<td style="{_CELL}">{_esc(x["segment_label"])} · {_esc(x["angle"])}</td></tr>'
        for x in ui_data.recommendation_distribution())
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">门店</th><th style="{_HEAD}">今日一条</th>'
            f'<th style="{_HEAD}">槽位 · 平台</th><th style="{_HEAD}">客群 · 角度</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def on_verify():
    drafts = [d for d in ui_data.new_release_drafts() if not d["verified"]]
    if not drafts:
        return {**view(), "verify_msg": _banner("没有待确认的新品。", "note"), "reset_msg": ""}
    model = drafts[0]
    ui_data.verify_new_product(model["model_id"])
    msg = _banner(f"已确认发布（演示解锁）：{model['display_name']}。全部门店的新品款已解锁；"
                  "本演示未对具体数值做事实核验，切回门店端即可看到。")
    return {**view(), "verify_msg": msg, "reset_msg": ""}


def on_reset():
    ui_data.reset()
    msg = _banner("已重置演示数据：新品恢复待确认，门店推荐重置；已发布标记与顾客提问将在回到门店端时清空。"
                  "（已准备的口播稿不会被删除。）", "note")
    return {**view(), "verify_msg": "", "reset_msg": msg}


def view() -> dict:
    """Everything the 总部端 screen shows, rendered fresh (all offline reads)."""
    return {"posting": posting_html(), "release": release_html(), "has_draft": has_draft(),
            "questions": questions_html(), "plan": plan_html(), "distribution": distribution_html(),
            "verify_msg": "", "reset_msg": ""}
