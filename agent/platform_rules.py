"""
Platform rules (WORKFLOW v4 §3 step 6) and human-sounding writing rules.

Used twice:
  * ``build_prompt_rules(platform)``  -> Chinese rules block appended to the writer prompt (P4 imports it)
  * ``check_post(post, platform)``    -> deterministic 8C conformance issues (called by checks/conformance.py)

WHICH VALUES ARE HANDBOOK RULES AND WHICH ARE OURS (never present ours as handbook rules):
  Handbook : image ranges (schemas.PLATFORM_IMAGE_RANGE), the block structure of the four official
             platforms, Moments' single selling point, the poster's <=3 selling points,
             no faked personal experience on 小红书, "避免套话" (no AI boilerplate).
  Ours     : body-length ranges, emoji limits, hashtag counts, the poster's 10-char title,
             the douyin 12-char caption limit, the CTA keyword lists, everything about 抖音,
             the AI_TELL word list, and the severity choices below.

Owner: P3. Advertising-law absolutes (最/第一/唯一…) are NOT here; they live in config/banned_words.txt (8B).
"""
from __future__ import annotations

import re

from agent.schemas import CheckIssue, PLATFORM_IMAGE_RANGE, PLATFORM_LABELS, Post

FACT_TAG_RE = re.compile(r"\[F\d+\]")
_ASCII_TAG_RE = re.compile(r"#([^\s#，。！？、]+)")

# Body length is OUR rule, not the handbook's, so it is reported as a warning: an over/under-length
# post is something the writer should fix, not a zero-score trap. (It also keeps synthetic test posts
# honest without forcing them to 800+ characters.)
LENGTH_SEVERITY = "warn"

# ----------------------------------------------------------------- per-platform rules
# "blocks": (post field, Chinese label, required) in the order the platform shows them.
# "cta_keywords": at least one must appear in the CTA (our heuristic for the handbook's CTA types -> warn).
# "forbidden_patterns": (regex, Chinese reason) -> error.
_XHS_FAKE_EXPERIENCE = [
    (r"亲测", "小红书禁止编造个人体验（亲测）"),
    (r"我(用|买|入手|体验)了", "小红书禁止编造个人体验（我用了/我买了）"),
    (r"入手\s*[\d一二三四五六七八九十百半两]+\s*(个月|天|周|年)", "小红书禁止编造个人体验（入手X个月）"),
    (r"用了\s*[\d一二三四五六七八九十百半两]+\s*(个月|天|周|年)", "小红书禁止编造个人体验（用了X天）"),
    (r"(自用|真实体验|实际体验|用下来|上手一周|使用感受|真香)", "小红书禁止编造个人体验"),
]

PLATFORM_RULES: dict[str, dict] = {
    "wechat_article": {
        "label": PLATFORM_LABELS["wechat_article"],
        "images": PLATFORM_IMAGE_RANGE["wechat_article"],   # handbook
        "body_chars": (800, 1500),                           # ours
        "emoji_max": 0,                                      # ours
        "hashtags": 0,                                       # ours: no visible hashtags
        "paragraphs": (3, 8),                                # ours (warn)
        "blocks": [("title", "标题", True), ("intro", "导语", True), ("body", "分段正文", True), ("cta", "结尾引导", True)],
        "structure": "标题 + 导语 + 分段正文 + 结尾引导",       # handbook
        "tone": "可读性强的说明文，像资深销售在认真介绍，不堆砌形容词",
        "title_max": None,
        "caption_max": None,
        "selling_points_max": None,
        "cta_types": ["到店", "关注", "留言"],                   # handbook
        "cta_keywords": ["到店", "来店", "门店", "关注", "留言", "评论", "咨询", "私信", "体验"],
        "forbidden_patterns": [],
    },
    "xiaohongshu": {
        "label": PLATFORM_LABELS["xiaohongshu"],
        "images": PLATFORM_IMAGE_RANGE["xiaohongshu"],
        "body_chars": (300, 600),
        "emoji_max": 6,
        "hashtags": (3, 8),
        "paragraphs": (3, 8),
        "blocks": [("title", "口语化标题", True), ("body", "短段落 + 场景", True), ("cta", "行动引导", True), ("tags", "话题标签", True)],
        "structure": "口语化标题 + 短段落 + 场景 + 话题标签",   # handbook
        "tone": "口语化、有画面感的分享语气，但不编造个人使用经历",
        "title_max": None,
        "caption_max": None,
        "selling_points_max": None,
        "cta_types": ["收藏", "评论", "到店"],                   # handbook
        "cta_keywords": ["收藏", "评论", "到店", "来店", "门店", "留言", "私信", "体验"],
        "forbidden_patterns": _XHS_FAKE_EXPERIENCE,          # handbook: no faked personal experience
    },
    "moments": {
        "label": PLATFORM_LABELS["moments"],
        "images": PLATFORM_IMAGE_RANGE["moments"],
        "body_chars": (50, 150),
        "emoji_max": 2,
        "hashtags": 0,
        "paragraphs": (1, 3),
        "blocks": [("body", "一个核心卖点", True), ("cta", "到店或咨询引导", True)],
        "structure": "一个核心卖点 + 到店或咨询引导",            # handbook
        "tone": "门店销售发给熟客的口吻，短、具体、一句话一个点",
        "title_max": None,
        "caption_max": None,
        "selling_points_max": 1,                             # handbook: 一个核心卖点 (exactly one)
        "cta_types": ["到店", "私信"],                         # handbook
        "cta_keywords": ["到店", "来店", "门店", "店里", "私信", "咨询", "微信"],
        "forbidden_patterns": [],
    },
    "poster": {
        "label": PLATFORM_LABELS["poster"],
        "images": PLATFORM_IMAGE_RANGE["poster"],
        "body_chars": (20, 80),
        "emoji_max": 0,
        "hashtags": 0,
        "paragraphs": (1, 4),
        "blocks": [("title", "主标题", True), ("intro", "副标题", True), ("body", "卖点（≤3）", True), ("cta", "到店引导", True)],
        "structure": "主标题（≤10字）+ 副标题 + ≤3 个卖点 + 活动说明（仅限知识库内容）",  # ≤3 points: handbook; 10 chars: ours
        "tone": "短语式，一行一个点，可直接上版",
        "title_max": 10,                                     # ours
        "caption_max": None,
        "selling_points_max": 3,                             # handbook
        "cta_types": ["到店"],                                # handbook
        "cta_keywords": ["到店", "来店", "门店", "店里", "体验"],
        "forbidden_patterns": [],
    },
    "douyin": {                                              # entirely our extension
        "label": PLATFORM_LABELS["douyin"],
        "images": PLATFORM_IMAGE_RANGE["douyin"],
        "body_chars": (100, 300),
        "emoji_max": 4,
        "hashtags": (2, 5),
        "paragraphs": (2, 3),
        "blocks": [("intro", "钩子首句", True), ("body", "2–3 短段", True), ("cta", "行动引导", True), ("tags", "话题", True)],
        "structure": "钩子首句 + 2–3 短段 + 话题；每张图说明 ≤12 字",
        "tone": "第一句抓注意力，后面每段只讲一件事",
        "title_max": None,
        "caption_max": 12,                                   # ours
        "selling_points_max": None,
        "cta_types": ["评论", "私信", "到店"],
        "cta_keywords": ["评论", "私信", "到店", "来店", "门店", "留言", "体验"],
        "forbidden_patterns": [],
    },
}

# ----------------------------------------------------------------- writing rules (all platforms)
# Boilerplate phrases that make text sound machine-written. NOT advertising-law terms (those are 8B).
AI_TELL_PHRASES: list[str] = [
    "赋能", "打造", "不仅仅是", "更是", "综上所述", "总而言之", "值得一提的是", "让我们",
    "在当今", "时代", "无论是", "还是", "不难发现", "毋庸置疑", "众所周知", "助力", "新篇章",
    "全方位", "一站式", "卓越", "匠心", "重新定义", "深度融合", "强势来袭",
]
# Phrase pairs: only flagged when both halves appear in the same sentence.
AI_TELL_PAIRS: list[tuple[str, str]] = [("不仅仅是", "更是"), ("无论是", "还是"), ("在当今", "时代")]
# Phrases flagged on their own (the pair halves are excluded here so 还是/时代 alone don't trigger).
_SOLO_PHRASES = [p for p in AI_TELL_PHRASES if p not in {h for pair in AI_TELL_PAIRS for h in pair}]

AI_TELL_PATTERNS: list[tuple[str, str]] = [
    ("——", "破折号「——」是常见的机器写法，改用逗号或句号"),
]
MAX_EXCLAMATIONS = 2
REPEATED_OPENING_MIN = 3

WRITING_RULES: list[str] = [
    "像一个熟悉产品的真人在说话：用具体的事实和场景，不堆砌形容词。",
    "每一个产品数值和功能都要标注事实编号，例如写“重量约X kg [F1]”；没有编号的参数一律不写。",
    "不用套话：不写 赋能、打造、不仅仅是…更是、综上所述、总而言之、值得一提的是、让我们…、在当今…时代、无论是…还是…。",
    "不用破折号「——」；全文感叹号不超过 2 个；避免连续三句用同样的开头。",
    "长短句交错，段落短；一段只讲一件事。",
    "不写价格、优惠、销量、库存、奖项、评价、测试成绩、售后政策，除非事实清单里有对应条目。",
    "不出现绝对化用语（最、第一、唯一、顶级、全网、首选等），上限值写成“可达 / 最多 X”。",
    "不提及任何其他品牌或竞品，不做对比。",
    "不编造个人使用经历（亲测、我用了X天、入手X个月）。",
]

# ----------------------------------------------------------------- helpers
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿⭐⭕‼⁉〰〽㊗㊙]"
)
_SENT_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")


def strip_tags(text: str) -> str:
    return FACT_TAG_RE.sub("", text or "")


def count_chars(text: str) -> int:
    """字数: non-whitespace characters after removing [F#] tags."""
    return len(re.sub(r"\s+", "", strip_tags(text)))


def count_emoji(text: str) -> int:
    return len(_EMOJI_RE.findall(text or ""))


def visible_hashtags(text: str) -> list[str]:
    return _ASCII_TAG_RE.findall(text or "")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(strip_tags(text)) if s.strip()]


def _fields(post: Post) -> list[tuple[str, str]]:
    out = [("title", post.title), ("intro", post.intro)]
    out += [(f"body[{i}]", p) for i, p in enumerate(post.body)]
    out.append(("cta", post.cta))
    out += [(f"images[{i}].caption", im.caption) for i, im in enumerate(post.images)]
    return out


def _issue(code: str, message: str, field: str = "", span: str = "", severity: str = "error") -> CheckIssue:
    return CheckIssue(stage="8C", severity=severity, code=code, message=message, field=field, span=span)


# ----------------------------------------------------------------- prompt text
def build_prompt_rules(platform: str) -> str:
    """Chinese rules block for the writer prompt. States the rules only (no handbook/ours labelling)."""
    r = PLATFORM_RULES[platform]
    lo, hi = r["images"]
    bmin, bmax = r["body_chars"]
    lines = [f"【平台：{r['label']}】",
             f"- 结构：{r['structure']}",
             f"- 语气：{r['tone']}",
             f"- 正文（导语+正文）字数：{bmin}–{bmax} 字",
             f"- 配图：{lo}–{hi} 张，只能用图片计划里的图片，按给定位置插入",
             f"- 行动引导类型：{' / '.join(r['cta_types'])}（必须有，且只用知识库里有的到店或咨询方式）"]
    lines.append(f"- 表情符号：最多 {r['emoji_max']} 个" if r["emoji_max"] else "- 不用表情符号")
    if r["hashtags"]:
        lines.append(f"- 话题标签：{r['hashtags'][0]}–{r['hashtags'][1]} 个，写在 tags 字段，正文末尾可以 #话题 形式出现")
    else:
        lines.append("- 平台标签写在 tags 字段即可，正文里不要出现 #话题")
    if r["selling_points_max"] == 1:
        lines.append("- 只讲一个核心卖点：selling_points 只放一个事实编号，正文只围绕这一个点")
    elif r["selling_points_max"]:
        lines.append(f"- 卖点不超过 {r['selling_points_max']} 个")
    if r["title_max"]:
        lines.append(f"- 主标题不超过 {r['title_max']} 个字")
    if r["caption_max"]:
        lines.append(f"- 每张图片说明不超过 {r['caption_max']} 个字")
    if r["forbidden_patterns"]:
        lines.append("- 不得编造个人使用经历（亲测、我用了X天、入手X个月、自用、真实体验等）")
    lines.append("- 所有字段都要填写（title / intro / body / cta / tags / selling_points / images），平台不展示的字段也要填")
    lines.append("")
    lines.append("【写作要求（所有平台）】")
    lines += [f"- {w}" for w in WRITING_RULES]
    return "\n".join(lines)


# ----------------------------------------------------------------- 8C check
def check_post(post: Post, platform: str) -> list[CheckIssue]:
    """Deterministic platform + writing conformance. Returns stage-8C issues (image checks live in conformance.py)."""
    if platform not in PLATFORM_RULES:
        return [_issue("unknown_platform", f"未知平台：{platform}")]
    r = PLATFORM_RULES[platform]
    issues: list[CheckIssue] = []

    # --- required blocks (handbook structure)
    for fld, label, required in r["blocks"]:
        val = getattr(post, fld, None)
        empty = (not val) if not isinstance(val, list) else not any((x or "").strip() for x in val)
        if required and empty:
            issues.append(_issue("missing_block", f"缺少「{label}」", field=fld))
    if not (post.cta or "").strip():
        if not any(i.code == "missing_block" and i.field == "cta" for i in issues):
            issues.append(_issue("missing_cta", "缺少行动引导", field="cta"))
    elif r["cta_keywords"] and not any(k in post.cta for k in r["cta_keywords"]):
        issues.append(_issue("cta_type", f"行动引导不属于本平台类型（{' / '.join(r['cta_types'])}）",
                             field="cta", span=post.cta, severity="warn"))
    if not post.tags or not any((t or "").strip() for t in post.tags):
        if not any(i.code == "missing_block" and i.field == "tags" for i in issues):
            issues.append(_issue("tags_missing", "平台标签（tags）为空", field="tags"))

    # --- body length (ours -> warn), both bounds
    n = count_chars(post.intro) + sum(count_chars(p) for p in post.body)
    bmin, bmax = r["body_chars"]
    if n < bmin:
        issues.append(_issue("body_too_short", f"正文 {n} 字，少于本平台下限 {bmin} 字", field="body",
                             severity=LENGTH_SEVERITY))
    elif n > bmax:
        issues.append(_issue("body_too_long", f"正文 {n} 字，超过本平台上限 {bmax} 字", field="body",
                             severity=LENGTH_SEVERITY))
    pmin, pmax = r["paragraphs"]
    paras = [p for p in post.body if (p or "").strip()]
    if paras and not (pmin <= len(paras) <= pmax):
        issues.append(_issue("paragraph_count", f"正文 {len(paras)} 段，本平台建议 {pmin}–{pmax} 段",
                             field="body", severity="warn"))

    # --- emoji
    text_all = post.all_text()
    e = count_emoji(text_all)
    if e > r["emoji_max"]:
        issues.append(_issue("emoji_count", f"表情符号 {e} 个，超过上限 {r['emoji_max']} 个"
                             if r["emoji_max"] else f"本平台不用表情符号（出现 {e} 个）", field="body"))

    # --- hashtags: visible only where allowed; count in range where allowed
    visible = visible_hashtags(text_all)
    if r["hashtags"]:
        hmin, hmax = r["hashtags"]
        distinct = {t.strip().lstrip("#") for t in post.tags if (t or "").strip()} | set(visible)
        if not (hmin <= len(distinct) <= hmax):
            issues.append(_issue("hashtag_count", f"话题标签 {len(distinct)} 个，本平台要求 {hmin}–{hmax} 个",
                                 field="tags", span="，".join(sorted(distinct))))
    elif visible:
        issues.append(_issue("hashtag_not_allowed", "本平台正文不展示 #话题，标签只放在 tags 字段",
                             span="#" + " #".join(visible)))

    # --- selling points / title / captions
    cited = []
    for m in FACT_TAG_RE.finditer(text_all):
        if m.group(0) not in cited:
            cited.append(m.group(0))
    if r["selling_points_max"] == 1:
        if len(post.selling_points) != 1:
            issues.append(_issue("moments_focus", f"朋友圈只讲一个核心卖点，selling_points 有 {len(post.selling_points)} 个",
                                 field="selling_points", span="，".join(post.selling_points)))
        if len(cited) > 1:
            issues.append(_issue("moments_focus", f"朋友圈正文引用了 {len(cited)} 个事实，只能围绕一个核心卖点",
                                 field="body", span="".join(cited)))
    elif r["selling_points_max"] and len(post.selling_points) > r["selling_points_max"]:
        issues.append(_issue("too_many_selling_points",
                             f"卖点 {len(post.selling_points)} 个，超过上限 {r['selling_points_max']} 个",
                             field="selling_points", span="，".join(post.selling_points)))
    if r["title_max"] and count_chars(post.title) > r["title_max"]:
        issues.append(_issue("title_too_long", f"主标题 {count_chars(post.title)} 字，超过 {r['title_max']} 字",
                             field="title", span=post.title))
    if r["caption_max"]:
        for i, im in enumerate(post.images):
            if count_chars(im.caption) > r["caption_max"]:
                issues.append(_issue("caption_too_long", f"图片说明 {count_chars(im.caption)} 字，超过 {r['caption_max']} 字",
                                     field=f"images[{i}].caption", span=im.caption))

    # --- platform-specific forbidden patterns (e.g. xhs fake experience)
    for fld, text in _fields(post):
        clean = strip_tags(text)
        for pat, reason in r["forbidden_patterns"]:
            m = re.search(pat, clean)
            if m:
                issues.append(_issue("fake_experience", reason, field=fld, span=m.group(0)))

    # --- AI tells
    issues += _ai_tell_issues(post)
    return issues


def _ai_tell_issues(post: Post) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for fld, text in _fields(post):
        clean = strip_tags(text)
        for ph in _SOLO_PHRASES:
            if ph in clean:
                issues.append(_issue("ai_tell", f"套话「{ph}」，换成具体的说法", field=fld, span=ph))
        for a, b in AI_TELL_PAIRS:
            for s in sentences(clean):
                if a in s and b in s:
                    issues.append(_issue("ai_tell", f"套话「{a}…{b}」，换成具体的说法", field=fld, span=f"{a}…{b}"))
                    break
        for pat, reason in AI_TELL_PATTERNS:
            if pat in clean:
                issues.append(_issue("ai_tell", reason, field=fld, span=pat))
    full = strip_tags(post.all_text())
    excl = full.count("！") + full.count("!")
    if excl > MAX_EXCLAMATIONS:
        issues.append(_issue("ai_tell", f"感叹号 {excl} 个，超过 {MAX_EXCLAMATIONS} 个", span="！" * excl))
    openings: dict[str, int] = {}
    for s in sentences(full):
        if len(s) >= 2:
            openings[s[:2]] = openings.get(s[:2], 0) + 1
    for op, c in openings.items():
        if c >= REPEATED_OPENING_MIN:
            issues.append(_issue("ai_tell", f"连续 {c} 句以「{op}」开头，换换句式", span=op))
    return issues
