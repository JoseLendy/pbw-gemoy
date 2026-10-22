"""
总部端 view functions (no UI toolkit; server.py calls them).
Stage 2 — 总部端 (docs/UI_SPEC.md, plan §8): posting rate, the demo new-product verification gate,
customer questions, this week's platform plan, today's recommendation distribution, and 重置演示.
Offline reads go through agent.ui_data; no ima/LLM call is made on this tab.
"""
from __future__ import annotations

import html

from agent import ui_data

# Light pastel inline styles: the panels are white cards on a warm cream page, so the tables use dark ink on
# white with hairline rules, and the warn highlight is a soft apricot.
_WARN_BG = "#FFF5E6"
_CELL = "padding:9px 10px;border-bottom:1px solid #F2ECE6;color:#1F1F1F"
_HEAD = "padding:8px 10px;text-align:left;background:#FAF6F2;border-bottom:1px solid #EFE6DD;color:#8A817A;font-weight:600;font-size:12.5px"
_MUTED = "#8A817A"


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _banner(text: str, kind: str = "ok") -> str:
    cls = {"ok": "hw-banner ok", "warn": "hw-banner warn", "note": "hw-banner note"}.get(kind, "hw-banner note")
    return f'<div class="{cls}" style="margin:8px 0">{_esc(text)}</div>'


def posting_html(store_id: str = "") -> str:
    """Posting rate per store; a manager's view is scoped to their own store."""
    data = ui_data.publish_stats()
    rows = []
    stats = [s for s in data["stats"] if not store_id or s["store_id"] == store_id]
    for s in stats:
        pct = s["rate"] * 100
        bar = (f'<div style="height:6px;width:100%;background:#F1ECE7;border-radius:3px">'
               f'<div style="height:6px;width:{pct:.1f}%;background:{"#F0907F" if s["low"] else "#7FCBA4"};'
               f'border-radius:3px"></div></div>')
        flag = (' <span style="font-size:11px;color:#C2410C;background:#FFE8D6;border-radius:8px;'
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


def release_html(store_id: str = "") -> str:
    """The new-product gate. With `store_id` (a manager) each product shows whether *this store* may
    generate it; without one (a developer) it is the company-wide demo state."""
    drafts = ui_data.new_release_drafts(store_id or None)
    if not drafts:
        return _banner("当前没有在售新品草稿。", "note")
    blocks = []
    for d in drafts:
        if store_id:
            status = "已确认发布（本店）" if d["verified"] else "待本店确认"
        else:
            status = "已确认发布" if d["verified"] else "待总部确认"
            if d["approved_stores"]:
                status += f"（{len(d['approved_stores'])} 家门店）"
        color = "#2F8F5B" if d["verified"] else "#B45309"
        refs = "".join(
            f'<tr><td style="{_CELL}">{_esc(r["ref_id"])}</td><td style="{_CELL}">{_esc(r["fields"])}</td>'
            f'<td style="{_CELL}">{_esc(r["source_title"])}<div style="font-size:11px;color:#A39A92">'
            f'{_esc(r["source_path"])}</div></td></tr>' for r in d["refs"])
        if d["verified"]:
            note = ("本店店员已可生成这条新品（演示状态）；具体数值仍需按知识库事实卡核验。" if store_id
                    else "已解锁门店生成（演示状态）；具体数值仍需按知识库事实卡核验。")
        else:
            note = ("确认后，本店店员即可生成这条新品。以下只是字段与来源参考，不是已核验的事实卡数值。"
                    if store_id else
                    "演示审核清单：以下只是字段与来源参考，不是已核验的事实卡数值。")
        note_style = ("color:#2F6B47;background:#E8F6EE" if d["verified"]
                      else "color:#8A5300;background:#FFF3DC")
        blocks.append(
            f'<div style="border:1px solid #F0E8E0;border-radius:14px;padding:14px;background:#FFFCF9">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<b style="font-size:15px;color:#1F1F1F">{_esc(d["display_name"])}</b>'
            f'<span style="font-size:12px;color:{color};background:#F6F1EC;border-radius:10px;padding:2px 8px">'
            f'{_esc(status)}</span></div>'
            f'<div style="font-size:12px;color:{_MUTED};margin:4px 0 8px">演示上市日期：{_esc(d["launch_date"])}'
            f' · {"店长确认本店后，本店店员解锁" if store_id else "总部确认一次，全部门店解锁"}</div>'
            f'<div style="font-size:12px;{note_style};border-radius:6px;padding:6px 8px;margin-bottom:8px">'
            f'{_esc(note)}</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:12px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">参考</th><th style="{_HEAD}">字段组</th>'
            f'<th style="{_HEAD}">来源</th></tr></thead><tbody>{refs}</tbody></table></div>')
    return "".join(blocks)


def has_draft(store_id: str = "") -> bool:
    return any(not d["verified"] for d in ui_data.new_release_drafts(store_id or None))


def questions_html(store_id: str = "") -> str:
    rows = "".join(
        f'<tr><td style="{_CELL};text-align:center">{i + 1}</td><td style="{_CELL}">{_esc(q["text"])}</td>'
        f'<td style="{_CELL};text-align:right">{q["count"]}</td>'
        f'<td style="{_CELL};text-align:right">{q["stores"]} 店</td></tr>'
        for i, q in enumerate(ui_data.question_stats(8, store_id or None)))
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">#</th><th style="{_HEAD}">顾客问题</th>'
            f'<th style="{_HEAD};text-align:right">次数</th><th style="{_HEAD};text-align:right">覆盖门店</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>')


def plan_html(store_id: str = "") -> str:
    """本周计划: each store's weekly progress against the minimums (a suggestion, not a fixed rotation).
    A platform still short of its minimum is highlighted."""
    rows_data = [r for r in ui_data.weekly_progress_all() if not store_id or r["store_id"] == store_id]
    platforms = list(rows_data[0]["progress"]) if rows_data else []
    head = "".join(f'<th style="{_HEAD};text-align:center">{_esc(p)}</th>' for p in platforms)
    rows = []
    for r in rows_data:
        cells = []
        for p in platforms:
            v = r["progress"][p]
            short = p in r["behind"]
            style = f'{_CELL};text-align:center' + (";background:#FFF1DD;color:#B45309;font-weight:700" if short else "")
            cells.append(f'<td style="{style}">{v["done"]}/{v["minimum"]}</td>')
        rows.append(f'<tr><td style="{_CELL}">{_esc(r["store_name"])}</td>{"".join(cells)}'
                    f'<td style="{_CELL}">{_esc(r["suggestion"])}</td></tr>')
    n_behind = sum(1 for r in rows_data if r["behind"])
    return (f'<div style="font-size:12px;color:{_MUTED};margin-bottom:6px">本周（周一至今）发布进度 · '
            f'{n_behind} 家门店有平台未达标（橙色）</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">门店</th>{head}<th style="{_HEAD}">今天建议发</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def distribution_html(store_id: str = "") -> str:
    rows = "".join(
        f'<tr><td style="{_CELL}">{_esc(x["store_name"])}</td>'
        f'<td style="{_CELL}">{_esc(x["display_name"])}</td>'
        f'<td style="{_CELL}">{_esc(x["slot_label"])} · {_esc(x["platform"])}</td>'
        f'<td style="{_CELL}">{_esc(x["segment_label"])} · {_esc(x["angle"])}</td></tr>'
        for x in ui_data.recommendation_distribution() if not store_id or x["store_id"] == store_id)
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px;background:transparent">'
            f'<thead><tr><th style="{_HEAD}">门店</th><th style="{_HEAD}">今日一条</th>'
            f'<th style="{_HEAD}">槽位 · 平台</th><th style="{_HEAD}">客群 · 角度</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def on_verify(store_id: str = "", store_name: str = "") -> dict:
    """Confirm the first new product this account still needs to confirm. A manager (store_id) unlocks it
    for their own store only; a developer confirms it for every store. `verified_model` is returned so
    server.py can persist the approval in the accounts database."""
    drafts = [d for d in ui_data.new_release_drafts(store_id or None) if not d["verified"]]
    if not drafts:
        return {**view(store_id, store_name), "verify_msg": _banner("没有待确认的新品。", "note"),
                "verified_model": "", "reset_msg": ""}
    model = drafts[0]
    if store_id:
        ui_data.verify_new_product_for_store(model["model_id"], store_id)
        msg = _banner(f"已确认本店发布（演示解锁）：{model['display_name']}。"
                      f"{store_name or '本店'}的店员现在可以生成这条新品；本演示未对具体数值做事实核验。")
    else:
        ui_data.verify_new_product(model["model_id"])
        msg = _banner(f"已确认发布（演示解锁）：{model['display_name']}。全部门店的新品款已解锁；"
                      "本演示未对具体数值做事实核验，切回门店端即可看到。")
    return {**view(store_id, store_name), "verify_msg": msg, "verified_model": model["model_id"],
            "reset_msg": ""}


def on_reset():
    ui_data.reset()
    msg = _banner("已重置演示数据：新品恢复待确认，门店推荐重置；已发布标记与顾客提问将在回到门店端时清空。"
                  "（已准备的口播稿不会被删除。）", "note")
    return {**view(), "verify_msg": "", "verified_model": "", "reset_msg": msg}


def view(store_id: str = "", store_name: str = "") -> dict:
    """Everything the 总部端 screen shows, rendered fresh (all offline reads). A manager's view is
    scoped to their store; a developer's view covers every store."""
    return {"posting": posting_html(store_id), "release": release_html(store_id),
            "has_draft": has_draft(store_id), "questions": questions_html(store_id),
            "plan": plan_html(store_id), "distribution": distribution_html(store_id),
            "scope": "store" if store_id else "all", "store_name": store_name,
            "verify_msg": "", "verified_model": "", "reset_msg": ""}
