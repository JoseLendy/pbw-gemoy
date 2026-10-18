"""
Step 6 image plan (WORKFLOW §3 step 6): choose, order and place images for one platform.

Candidates are bundle.images only: they already passed the 3-signal rule in agent/catalog.py.
Never pads with sibling or generic images. Captions come from the KB caption or, if that is empty,
from the scene words in the KB file name. Never invented.
"""
from __future__ import annotations

import re

from agent.schemas import PLATFORM_IMAGE_RANGE, ImagePlan, ImageRef, ModelBundle, PlannedImage, Strategy

# How many images we aim for per platform, clipped to PLATFORM_IMAGE_RANGE and to what exists.
TARGET = {"wechat_article": 3, "xiaohongshu": 6, "moments": 2, "poster": 1, "douyin": 6}

_ROLE_KEYWORDS = [            # first match wins; file name is checked before the caption
    ("main", ("主视觉", "kv")),
    ("scene", ("场景",)),
    ("detail", ("细节", "接口", "键盘")),
    ("color", ("配色", "颜色", "款式")),
]
# Selling-point category -> words in an image's file name or caption that make it a fit.
_CATEGORY_KEYWORDS = {
    "display": ("屏",),
    "design": ("配色", "颜色", "外观", "设计", "款式"),
    "portability": ("轻薄", "机身", "便携"),
    "battery": ("续航",),
    "collaboration": ("协同", "互联", "多设备"),
    "audio_camera": ("影音", "音", "摄像"),
    "ports": ("接口",),
}
# Exterior photos never sit next to these claims (WORKFLOW rule: no image "proves" performance).
_NO_IMAGE_CATEGORIES = {"performance", "storage_memory"}
_ROLE_PRIORITY = {"main": 0, "scene": 1, "detail": 2, "unknown": 3, "color": 4}

SHORTAGE_NOTE = "知识库该型号图片不足，待确认"
TEXT_ONLY_NOTE = "知识库无该型号图片，待确认"
POSTER_NO_IMAGE_NOTE = "海报需要1张主视觉，知识库无可用图片，无法生成海报"
POSTER_NO_MAIN_NOTE = "未找到标注为主视觉的图片，已使用该型号第1张官方图片，待确认"


def scene_words(title: str) -> str:
    """The scene segment of a KB image file name: <prefix>_<slug>_<scene>_<NN>[_<hash>].<ext>."""
    parts = re.sub(r"\.\w+$", "", title or "").split("_")
    return parts[2] if len(parts) >= 3 else ""


def image_role(title: str, caption: str = "") -> str:
    for text in (scene_words(title).lower(), (caption or "").lower()):
        for role, words in _ROLE_KEYWORDS:
            if any(w in text for w in words):
                return role
    return "unknown"


def _text(im: ImageRef) -> str:
    return f"{scene_words(im.title)} {im.caption}"


def _fits(im: ImageRef, category: str) -> bool:
    return any(w in _text(im) for w in _CATEGORY_KEYWORDS.get(category, ()))


def _role(im: ImageRef) -> str:
    return im.role if im.role != "unknown" else image_role(im.title, im.caption)


def _paragraph_categories(strategy: Strategy | None) -> list[str]:
    """Body paragraphs follow the strategy's ranked categories (minus dropped ones)."""
    if not strategy or not strategy.analysis:
        return []
    dropped = set(strategy.dropped_categories or {})
    return [c for c in strategy.analysis.categories if c not in dropped]


def _caption(im: ImageRef) -> str:
    return im.caption or scene_words(im.title)


def plan_images(bundle: ModelBundle, platform: str, strategy: Strategy) -> ImagePlan:
    lo, hi = PLATFORM_IMAGE_RANGE[platform]
    imgs = list(bundle.images)
    if not imgs:
        if platform == "poster":
            return ImagePlan(platform, [], shortage=True, note=POSTER_NO_IMAGE_NOTE)
        note = TEXT_ONLY_NOTE if bundle.model.route == "text_only" or not bundle.model.has_images else SHORTAGE_NOTE
        return ImagePlan(platform, [], shortage=True, note=note)

    if platform == "poster":
        main = next((im for im in imgs if _role(im) == "main"), None)
        pick = main or imgs[0]
        return ImagePlan(platform, [PlannedImage(pick, "海报主视觉", _caption(pick))],
                         note="" if main else POSTER_NO_MAIN_NOTE)

    want = max(lo, min(TARGET.get(platform, hi), hi))
    n = min(want, len(imgs))
    cats = _paragraph_categories(strategy)

    if platform == "moments":
        ordered = sorted(imgs, key=lambda im: ({"main": 0, "scene": 1}.get(_role(im), 2), imgs.index(im)))
        chosen = ordered[:n]
        items = [PlannedImage(im, f"配图第{i + 1}张", _caption(im)) for i, im in enumerate(chosen)]
        return _finish(platform, items, lo)

    # 1 lead image (main first), then one per paragraph category where an image fits, then fill.
    pool = sorted(imgs, key=lambda im: (_ROLE_PRIORITY.get(_role(im), 3), imgs.index(im)))
    chosen: list[tuple[ImageRef, str]] = []
    lead = pool.pop(0)
    chosen.append((lead, "标题下方"))
    for k, cat in enumerate(cats, start=1):
        if len(chosen) >= n:
            break
        if cat in _NO_IMAGE_CATEGORIES:
            continue
        fit = next((im for im in pool if _fits(im, cat)), None)
        if fit:
            pool.remove(fit)
            chosen.append((fit, f"第{k}段后"))
    # Fill: avoid stacking colour swatches; never next to a performance paragraph.
    free_slots = [f"第{k}段后" for k, c in enumerate(cats, start=1) if c not in _NO_IMAGE_CATEGORIES
                  and f"第{k}段后" not in {p for _, p in chosen}]
    pool.sort(key=lambda im: (_role(im) == "color" and any(_role(c) == "color" for c, _ in chosen),
                              _ROLE_PRIORITY.get(_role(im), 3)))
    while len(chosen) < n and pool:
        im = pool.pop(0)
        chosen.append((im, free_slots.pop(0) if free_slots else "文末"))

    order = {"标题下方": 0, "文末": 10_000}
    chosen.sort(key=lambda c: order.get(c[1], int(re.sub(r"\D", "", c[1]) or 0)))
    items = [PlannedImage(im, pos, _caption(im)) for im, pos in chosen]
    return _finish(platform, items, lo)


def _finish(platform: str, items: list[PlannedImage], lo: int) -> ImagePlan:
    short = len(items) < lo
    return ImagePlan(platform, items, shortage=short, note=SHORTAGE_NOTE if short else "")
