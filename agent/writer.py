"""
Step 7: writer + targeted rewrite. The LLM writes; code validates every field against the ledger and image plan.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

from agent.schemas import (
    CheckIssue, ImagePlan, Ledger, Post, PostImage, PLATFORM_IMAGE_RANGE, PLATFORM_LABELS, Strategy, Task,
)

TAG_RE = re.compile(r"\[(F\d+)\]")
FIELDS = ("title", "intro", "body", "cta", "tags", "images")
_ABSOLUTE_RE = re.compile(r"最|第一|唯一|顶级|全网|首选|史上")

_FALLBACK_RULES = {
    "wechat_article": "公众号：标题 + 导语 + 分段正文 + 结尾引导；正文 800 到 1500 字；不用表情和话题标签；图片 2 到 4 张。",
    "xiaohongshu": "小红书：口语化标题 + 短段落 + 场景 + 话题标签；正文 300 到 600 字；表情不超过 6 个；标签 3 到 8 个；图片 3 到 6 张；不写亲身使用经历。",
    "moments": "门店朋友圈：只讲一个核心卖点 + 到店或私信引导；正文 50 到 150 字；表情不超过 2 个；不加话题标签；图片 1 到 3 张。",
    "poster": "门店海报：主标题不超过 10 个字 + 副标题 + 最多 3 个卖点；正文 20 到 80 字；图片 1 张。",
    "douyin": "抖音图文：钩子首句 + 2 到 3 个短段 + 话题；每图说明不超过 12 个字；图片 3 到 9 张。",
}


def _platform_rules(platform: str) -> str:
    try:  # P3 builds this module; fall back until it exists
        from agent.platform_rules import build_prompt_rules  # type: ignore
        return build_prompt_rules(platform)
    except Exception:
        return _FALLBACK_RULES.get(platform, "")


def _fact_line(f) -> str:
    return f"{f.id} | {f.attribute} | {f.value} | 变体={f.variant} | 来源={f.source_title}"


def _usable(ledger: Ledger, strategy: Strategy) -> tuple[list, list]:
    """(chosen facts, optional context facts). Conflicting and pending facts are never offered."""
    chosen_ids = [sp.fact_id for sp in strategy.selling_points]
    blocked = {fid for c in ledger.conflicts for fid in c.fact_ids}
    chosen = [f for i in chosen_ids if (f := ledger.get(i))]
    others = [f for f in ledger.facts if f.id not in chosen_ids and f.id not in blocked]
    return chosen, others


def _boundaries(ledger: Ledger, chosen: list) -> list[str]:
    cats = {f.category for f in chosen}
    return [b["text"] for b in ledger.boundaries if b.get("category") in cats or not b.get("category")]


def _plan_lines(plan: ImagePlan) -> str:
    return "\n".join(f"{p.image.media_id} | 位置={p.position} | 说明={p.caption} | 来源={p.image.source_path}"
                     for p in plan.items) or "（无可用图片，images 留空）"


def _context(task: Task, strategy: Strategy, ledger: Ledger, plan: ImagePlan) -> str:
    chosen, others = _usable(ledger, strategy)
    lo, hi = PLATFORM_IMAGE_RANGE.get(task.platform or "", (0, 0))
    parts = [
        f"## 任务\n型号={task.model_id}；人群={strategy.analysis.audience}；场景={task.scenario}；"
        f"平台={PLATFORM_LABELS.get(task.platform or '', task.platform)}；变体={task.variant or '未指定'}\n"
        f"额外要求（若涉及价格、补贴、销量、奖项、评价、测试结果、政策承诺，一律不写）：{task.extra_requirements or '无'}",
        f"## 策略\n切入点：{strategy.angle}\n行动引导类型：{strategy.cta_type}\n卖点顺序：\n"
        + "\n".join(f"- {sp.fact_id}：{sp.reason}" for sp in strategy.selling_points),
        "## 已选事实（必须引用）\n" + "\n".join(_fact_line(f) for f in chosen),
        "## 背景事实（可选，用则标编号）\n" + ("\n".join(_fact_line(f) for f in others) or "（无）"),
        "## 表达边界（逐条遵守）\n" + ("\n".join(f"- {t}" for t in _boundaries(ledger, chosen)) or "（无）"),
        f"## 图片方案（图片数量范围 {lo} 到 {hi}，只能用下列 media_id）\n{_plan_lines(plan)}",
    ]
    return "\n\n".join(parts)


def _system(task: Task, stage_prompt: str) -> str:
    from agent.llm import load_prompt
    return "\n\n---\n\n".join([load_prompt("system_prompt"), load_prompt(stage_prompt),
                               "## 平台规则\n" + _platform_rules(task.platform or "")])


# ---------------------------------------------------------------- validation
def has_absolute_word(post: Post) -> bool:
    """Cheap pre-check (P3's checks stay authoritative): any 最 or other absolute word in the visible text."""
    return bool(_ABSOLUTE_RE.search(post.all_text()))


def _strip_bad_tags(text: str, valid: set[str]) -> str:
    return TAG_RE.sub(lambda m: m.group(0) if m.group(1) in valid else "", text or "")


def _as_str(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _no_dash(text: str) -> str:
    """8C forbids em-dashes; normalize them to commas so the check never has to loop on it."""
    return text.replace("——", "，").replace("—", "，")


def _clean_images(raw, plan: ImagePlan) -> list[PostImage]:
    by_id = {p.image.media_id: p for p in plan.items}
    out: list[PostImage] = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        mid = it.get("media_id") or it.get("image_id")
        p = by_id.get(mid)
        if p is None or any(o.media_id == mid for o in out):
            continue
        out.append(PostImage(mid, _as_str(it.get("position")) or p.position,
                             _as_str(it.get("caption")) or p.caption))
    return out


def _clean_fields(data: dict, ledger: Ledger, plan: ImagePlan, allowed_ids: set[str]) -> dict:
    """Return only well-formed fields present in `data`. Tags outside allowed_ids are removed."""
    out: dict = {}
    for k in ("title", "intro", "cta"):
        if k in data:
            out[k] = _no_dash(_strip_bad_tags(_as_str(data[k]), allowed_ids))
    if "body" in data:
        body = data["body"] if isinstance(data["body"], list) else [data["body"]]
        out["body"] = [s for s in (_no_dash(_strip_bad_tags(_as_str(p), allowed_ids)) for p in body) if s]
    if "tags" in data:
        tags = data["tags"] if isinstance(data["tags"], list) else [data["tags"]]
        out["tags"] = [t.strip().lstrip("#") for t in tags if isinstance(t, str) and t.strip()]
    if "images" in data:
        out["images"] = _clean_images(data["images"], plan)
    return out


def _used_ids(post: Post) -> list[str]:
    seen: list[str] = []
    for i in TAG_RE.findall(post.all_text()):
        if i not in seen:
            seen.append(i)
    return seen


def write_post(task: Task, strategy: Strategy, ledger: Ledger, plan: ImagePlan, llm=None) -> Post:
    if llm is None:
        from agent.llm import LLM
        llm = LLM()
    chosen, others = _usable(ledger, strategy)
    allowed = {f.id for f in chosen + others}

    data = llm.chat_json(_system(task, "writer"), _context(task, strategy, ledger, plan),
                         stage="writer") or {}
    f = _clean_fields(data, ledger, plan, allowed)

    # selling_points: ids that exist in the ledger and are actually cited in the text
    post = Post(platform=task.platform or plan.platform, title=f.get("title", ""), intro=f.get("intro", ""),
                body=f.get("body", []), cta=f.get("cta", ""), tags=f.get("tags", []), selling_points=[],
                images=f.get("images", []))
    declared = [i for i in (data.get("selling_points") or []) if isinstance(i, str) and ledger.get(i)]
    post.selling_points = list(dict.fromkeys(declared + _used_ids(post)))
    post.selling_points = [i for i in post.selling_points if i in allowed]

    # One self-repair pass: a stray 最 / absolute word in the draft is rewritten before the checks see it.
    if has_absolute_word(post):
        parts = {"title": post.title, "intro": post.intro, "cta": post.cta, "body": " ".join(post.body)}
        fields = [n for n, v in parts.items() if _ABSOLUTE_RE.search(v)]
        issues = [CheckIssue("8B", "error", "banned_word", "含绝对化用语，请改写，不要出现“最”字等绝对化词。",
                             field=n) for n in fields]
        post = rewrite(post, issues, task, strategy, ledger, plan, llm)

    # tags are always filled
    if not post.tags:
        post.tags = [PLATFORM_LABELS.get(post.platform, post.platform)]
        if task.scenario:
            from agent.schemas import SCENARIO_LABELS
            post.tags.append(SCENARIO_LABELS.get(task.scenario, task.scenario))
    return post


def rewrite(post: Post, issues: list[CheckIssue], task: Task, strategy: Strategy, ledger: Ledger,
            plan: ImagePlan, llm=None) -> Post:
    """Targeted: only the failing fields are sent and replaced; no new facts can enter."""
    if llm is None:
        from agent.llm import LLM
        llm = LLM()

    failing: set[str] = set()
    for i in issues:
        if i.severity != "error":
            continue
        name = (i.field or "").split("[")[0]
        failing.update(FIELDS if name not in FIELDS else {name})
    if not failing:
        return post

    chosen, others = _usable(ledger, strategy)
    # Never add new facts: only ids the post already cites or the strategy chose.
    allowed = set(_used_ids(post)) | set(post.selling_points) | {f.id for f in chosen}

    current = {k: getattr(post, k) for k in failing if k != "images"}
    if "images" in failing:
        current["images"] = [im.__dict__ for im in post.images]
    msgs = [{"field": i.field, "code": i.code, "message": i.message, "span": i.span, "fact_id": i.fact_id}
            for i in issues if i.severity == "error"]
    user = (_context(task, strategy, ledger, plan)
            + "\n\n## 需要修改的字段（当前内容）\n" + json.dumps(current, ensure_ascii=False)
            + "\n\n## 核验问题\n" + json.dumps(msgs, ensure_ascii=False)
            + "\n\n只输出需要修改的字段。不得新增事实。")
    data = llm.chat_json(_system(task, "rewrite"), user, stage="rewrite") or {}

    data = {k: v for k, v in data.items() if k in failing}
    f = _clean_fields(data, ledger, plan, allowed)

    new = Post(platform=post.platform, title=f.get("title", post.title), intro=f.get("intro", post.intro),
               body=f.get("body", post.body) or post.body, cta=f.get("cta", post.cta) or post.cta,
               tags=f.get("tags", post.tags) or post.tags, selling_points=list(post.selling_points),
               images=f.get("images", post.images))
    used = _used_ids(new)
    new.selling_points = [i for i in dict.fromkeys(post.selling_points + used) if i in allowed and ledger.get(i)]
    return new
