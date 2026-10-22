"""
8C. Platform and image conformance.

    check_conformance(post, platform, plan) -> CheckReport

Runs agent.platform_rules.check_post, then the image plan checks:
  image_not_in_plan    a post image whose media_id is not one of plan.items                      error
  image_count          image count outside PLATFORM_IMAGE_RANGE                                   error (warn if plan.shortage)
  image_shortage       KB has fewer images than the platform minimum (plan.shortage)               warn
  image_missing        post has no images (once image_not_in_plan / image_count covers real ones)  error
  plan_platform        plan built for another platform                                             error

    check_product_name(post, task) -> list[CheckIssue]       (run_all adds it to 8C)
  product_unnamed      the publishable text never names the product: neither its full display name nor an
                       unambiguous official short form (「这台/这款」 only, or a bare name that fits several
                       models, e.g. "MateBook 14")                                                  error
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from agent.platform_rules import PLATFORM_RULES, check_post
from agent.schemas import CheckIssue, CheckReport, ImagePlan, PLATFORM_IMAGE_RANGE, Post

STAGE = "8C"


def _issue(code, message, field="", span="", severity="error") -> CheckIssue:
    return CheckIssue(stage=STAGE, severity=severity, code=code, message=message, field=field, span=span)


def check_conformance(post: Post, platform: str, plan: ImagePlan) -> CheckReport:
    issues: list[CheckIssue] = list(check_post(post, platform))

    if plan is None:
        return CheckReport(issues + [_issue("plan_missing", "缺少图片计划", field="images")])
    if plan.platform and plan.platform != platform:
        issues.append(_issue("plan_platform", f"图片计划是为「{PLATFORM_RULES.get(plan.platform, {}).get('label', plan.platform)}」"
                                             f"生成的，与当前平台不符", field="images"))

    plan_ids = {p.image.media_id for p in plan.items}
    for i, im in enumerate(post.images):
        if im.media_id not in plan_ids:
            issues.append(_issue("image_not_in_plan", "这张图不在本型号的图片计划里，不能使用",
                                 field=f"images[{i}]", span=im.media_id))

    lo, hi = PLATFORM_IMAGE_RANGE.get(platform, PLATFORM_RULES.get(platform, {}).get("images", (0, 999)))
    n = len(post.images)
    if plan.shortage:
        if n > hi:
            issues.append(_issue("image_count", f"配图 {n} 张，超过本平台上限 {hi} 张", field="images"))
        elif n < lo:
            min_plan = len([p for p in plan.items])
            issues.append(_issue("image_shortage",
                                 f"知识库该型号可用图片 {max(n, min_plan)} 张，少于本平台最少 {lo} 张；不做补图，已标记待确认",
                                 field="images", severity="warn"))
    elif not (lo <= n <= hi):
        issues.append(_issue("image_count", f"配图 {n} 张，本平台要求 {lo}–{hi} 张", field="images"))
    return CheckReport(issues)


# ---------------------------------------------------------------- product name (8C)
_FACT_TAG = re.compile(r"\[F\d+\]")
_NAME_NOISE = re.compile(r"[\s()（）【】\[\]「」“”\"'·・]+")
_MIN_SHORT_FORM = 4          # normalised characters: "D14" / "GT" are too short to name a model on their own


def _norm_name(text: str) -> str:
    return _NAME_NOISE.sub("", unicodedata.normalize("NFKC", _FACT_TAG.sub("", text or ""))).lower()


@lru_cache(maxsize=1)
def _name_table() -> dict[str, tuple[list[str], list[str]]]:
    """model_id -> (full names, aliases): display names from data/demo/inputs/models.csv, aliases from
    config/model_aliases.yaml. Product names only."""
    from agent.checks import load_yaml
    from agent.recommend.common import INPUTS, load_csv
    table: dict[str, tuple[list[str], list[str]]] = {}
    try:
        for row in load_csv(INPUTS / "models.csv"):
            if row.get("model_id") and row.get("display_name"):
                table.setdefault(row["model_id"], ([], []))[0].append(row["display_name"])
    except Exception:  # noqa: BLE001 - names are optional input; the check then only knows the task's name
        pass
    for mid, cfg in ((load_yaml("model_aliases.yaml") or {}).get("models") or {}).items():
        table.setdefault(mid, ([], []))[1].extend(a for a in (cfg or {}).get("aliases") or [] if a)
    return table


def accepted_product_names(model_id: str | None, display_name: str | None = None) -> list[str]:
    """Names that identify this model on their own: the full display name, plus each alias that is long enough
    and is not part of any other model's name or alias ("MateBook D 16" is the start of "MateBook D 16 SE")."""
    table = _name_table()
    full, aliases = table.get(model_id or "", ([], []))
    others = {_norm_name(n) for mid, (f, a) in table.items() if mid != model_id for n in f + a}
    out = list(dict.fromkeys(n for n in [display_name, *full] if n and _norm_name(n)))
    for name in aliases:
        n = _norm_name(name)
        if name not in out and len(n) >= _MIN_SHORT_FORM and not any(n in o for o in others):
            out.append(name)
    return out


def check_product_name(post: Post, task) -> list[CheckIssue]:
    """error product_unnamed: the publishable text (title, intro, body, CTA) names the product at least once.
    The display name comes from the card (task.product_query) or models.csv; with neither, nothing is judged."""
    model_id = getattr(task, "model_id", None)
    display = getattr(task, "product_query", None) if getattr(task, "source", "manual") == "card" else None
    if display is None and not _name_table().get(model_id or "", ([], []))[0]:
        return []                                   # no display name on record: nothing to judge against
    names = accepted_product_names(model_id, display)
    text = _norm_name(post.all_text())
    if any(_norm_name(n) in text for n in names):
        return []
    return [_issue("product_unnamed", f"全文没有写出产品名称：至少写一次「{names[0]}」（或无歧义的官方简称），"
                                      "不能只写「这台/这款」或会对应多个型号的简称", field="body")]
