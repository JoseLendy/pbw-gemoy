"""
8C. Platform and image conformance.

    check_conformance(post, platform, plan) -> CheckReport

Runs agent.platform_rules.check_post, then the image plan checks:
  image_not_in_plan    a post image whose media_id is not one of plan.items                      error
  image_count          image count outside PLATFORM_IMAGE_RANGE                                   error (warn if plan.shortage)
  image_shortage       KB has fewer images than the platform minimum (plan.shortage)               warn
  image_missing        post has no images (once image_not_in_plan / image_count covers real ones)  error
  plan_platform        plan built for another platform                                             error
"""
from __future__ import annotations

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
