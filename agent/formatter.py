"""
Formatter (P5): the handbook's 4-section output and the publishable post text.

- render_report(r)      → Markdown with exactly the headings in schemas.SECTION_HEADINGS.
- render_publishable(p) → the post as it would be pasted, [F#] stripped, hashtags only on 小红书/抖音.
- render_download(r)    → the .md the salesperson downloads: our article + a sources appendix
                          (titles and KB paths only; claim quotes only in the fact table).

Never outputs media ids, keys or the Client ID. Sources are shown by title and KB path.
"""
from __future__ import annotations

import re

from agent.schemas import (
    CheckIssue, PLATFORM_LABELS, Post, RunResult, SCENARIO_LABELS, SECTION_HEADINGS,
)

HASHTAG_PLATFORMS = ("xiaohongshu", "douyin")
_TAG_RE = re.compile(r"\s*\[F\d+\]")


def strip_fact_tags(text: str) -> str:
    """Prefer agent.checks.strip_fact_tags (P3) when present; else a local regex."""
    try:
        from agent.checks import strip_fact_tags as _real  # type: ignore
        clean, _ = _real(text)
        return clean
    except Exception:
        return _TAG_RE.sub("", text)


def fact_ids_in(text: str) -> list[str]:
    return re.findall(r"\[(F\d+)\]", text or "")


# ---------------------------------------------------------------- publishable text
def render_publishable(post: Post) -> str:
    parts: list[str] = []
    if post.title:
        parts.append(strip_fact_tags(post.title))
    if post.intro:
        parts.append(strip_fact_tags(post.intro))
    parts.extend(strip_fact_tags(p) for p in post.body if p)
    if post.cta:
        parts.append(strip_fact_tags(post.cta))
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if post.platform in HASHTAG_PLATFORMS and post.tags:
        text += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in post.tags)
    return text


# ---------------------------------------------------------------- 4-section report
def _label(d: dict, key: str | None) -> str:
    return d.get(key or "", key or "—") or "—"


def _issue_line(i: CheckIssue) -> str:
    mark = "❌" if i.severity == "error" else "⚠️"
    where = f"（{i.field}）" if i.field else ""
    span = f"：「{i.span}」" if i.span else ""
    return f"- {mark} [{i.stage}] {i.message}{where}{span}"


def _stage_block(r: RunResult, stage: str, title: str, extra_ok: str = "") -> list[str]:
    issues = [i for i in r.report.issues if i.stage == stage]
    lines = [f"**{title}**"]
    if not issues:
        lines.append(f"- ✅ {extra_ok or '通过'}")
    else:
        lines.extend(_issue_line(i) for i in issues)
    return lines


def render_report(r: RunResult) -> str:
    t, post, ledger = r.task, r.post, r.ledger
    h1, h2, h3, h4 = SECTION_HEADINGS
    used_ids = list(dict.fromkeys([*post.selling_points, *fact_ids_in(post.all_text())]))
    used = [ledger.get(i) for i in used_ids if ledger.get(i)]
    out: list[str] = []

    # 一、场景判断
    out += [f"## {h1}", "",
            f"- 目标人群：{r.strategy.analysis.audience or t.audience or '—'}",
            f"- 使用场景：{_label(SCENARIO_LABELS, t.scenario)}",
            f"- 用户问题：{r.strategy.analysis.problem}",
            f"- 内容目标：{r.strategy.analysis.content_goal}",
            f"- 平台：{_label(PLATFORM_LABELS, post.platform)}",
            f"- 切入点：{r.strategy.angle}", ""]

    # 二、知识库依据
    out += [f"## {h2}", "", f"- 产品型号：{r.model.canonical_name}", "", "**事实点**", "",
            "| ID | 事实 | 原文摘录 | 资料标题 |", "|---|---|---|---|"]
    for f in used:
        out.append(f"| {f.id} | {f.value} | {f.quote} | {f.source_title} |")
    if not used:
        out.append("| — | 未引用台账事实 | | |")
    titles = list(dict.fromkeys([f"{s.title}（{s.source_path}）" for s in r.sources]))
    out += ["", "**资料标题**", ""] + [f"- {x}" for x in titles] if titles else ["", "- 资料标题：—"]
    out += ["", "**图片来源**", ""]
    if r.plan.items:
        out += [f"- {it.image.title}：{it.image.source_path}" for it in r.plan.items]
    else:
        out.append(f"- 待确认：{r.plan.note or '知识库无该型号图片'}")
    out.append("")

    # 三、图文软文
    out += [f"## {h3}", "",
            f"- 标题：{strip_fact_tags(post.title) or '（该平台无标题）'}",
            f"- 导语：{strip_fact_tags(post.intro) or '（该平台无导语）'}", "- 正文："]
    out += [f"  {k + 1}. {strip_fact_tags(p)}" for k, p in enumerate(post.body)]
    out += [f"- 行动引导：{strip_fact_tags(post.cta)}",
            f"- 平台标签：{'、'.join(post.tags) if post.tags else '—'}", "", "**配图**", ""]
    plan_by_id = {it.image.media_id: it for it in r.plan.items}
    if post.images:
        for k, im in enumerate(post.images, 1):
            it = plan_by_id.get(im.media_id)
            name = it.image.title if it else "（图片不在图片规划中）"
            src = it.image.source_path if it else "—"
            out += [f"{k}. 图片名称：{name}", f"   - 来源：{src}", f"   - 插入位置：{im.position}",
                    f"   - 图片说明：{im.caption or (it.caption if it else '')}"]
    else:
        out.append(f"- 待确认：{r.plan.note or '知识库无该型号图片，本文不配图'}")
    out.append("")

    # 四、核验结果
    out += [f"## {h4}", ""]
    out += _stage_block(r, "8A", "产品事实", f"{len(used)} 个事实点均来自目标型号台账")
    out += [""]
    img_lines = ["**图片型号**"]
    bad = [im for im in post.images if im.media_id not in plan_by_id]
    if bad:
        img_lines += [f"- ❌ {len(bad)} 张图片不在该型号的图片规划中"]
    elif post.images:
        img_lines += [f"- ✅ {len(post.images)} 张图片均属于 {r.model.canonical_name}"]
    else:
        img_lines += ["- ⚠️ 无配图"]
    out += img_lines + [""]
    out += _stage_block(r, "8B", "合规", "无绝对化用语、无虚构价格/销量/奖项/政策")
    out += [""]
    out += _stage_block(r, "8C", "平台规范", "结构、篇幅、图片数量符合平台要求")
    out += ["", "**待确认信息**", ""]
    out += [f"- ⚠️ {p}" for p in r.pending] if r.pending else ["- ✅ 无"]
    if r.loops:
        out += ["", f"（定向改写 {r.loops} 轮）"]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- download
def render_download(r: RunResult) -> str:
    """Our article + sources appendix (titles and paths only). No KB text beyond claim quotes, no images."""
    lines = [f"# {strip_fact_tags(r.post.title) or r.model.canonical_name}", "",
             f"平台：{_label(PLATFORM_LABELS, r.post.platform)} · 场景：{_label(SCENARIO_LABELS, r.task.scenario)}"
             f" · 型号：{r.model.canonical_name}", "", render_publishable(r.post), "", "---", "",
             "## 配图（请从知识库按名称取图）", ""]
    for k, it in enumerate(r.plan.items, 1):
        lines.append(f"{k}. {it.image.title} — 插入位置：{it.position} — 来源：{it.image.source_path}")
    if not r.plan.items:
        lines.append("无配图（知识库无该型号图片）")
    lines += ["", "## 资料来源", ""]
    for s in dict.fromkeys(f"{s.title} — {s.source_path}" for s in r.sources):
        lines.append(f"- {s}")
    if r.pending:
        lines += ["", "## 待确认", ""] + [f"- {p}" for p in r.pending]
    lines += ["", render_report(r)]
    return "\n".join(lines)
