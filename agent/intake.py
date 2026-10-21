"""
Step 1: intake. Free text (+ optional UI form) -> Task, or ONE Clarification listing every missing slot.

The LLM (fast model) only extracts raw phrases. Mapping to keys and resolving the product are done in code.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from agent.schemas import (
    Clarification, PLATFORM_LABELS, Question, SCENARIO_LABELS, Task,
)

# ---------------------------------------------------------------- synonyms (code, not LLM)
PLATFORM_SYNONYMS: dict[str, list[str]] = {
    "wechat_article": ["公众号", "微信文章", "微信公众号", "公号"],
    "xiaohongshu": ["小红书", "红书"],
    "moments": ["朋友圈", "门店朋友圈"],
    "poster": ["海报", "门店海报"],
    "douyin": ["抖音", "抖音图文"],
}
SCENARIO_SYNONYMS: dict[str, list[str]] = {
    "back_to_school": ["开学", "新生", "大学", "上学"],
    "office": ["出差", "办公", "商务", "职场"],
    "creator": ["设计", "剪辑", "摄影", "创作"],
    "family_upgrade": ["家用", "换机", "家庭", "换新"],
    "enterprise": ["企业", "采购", "团购", "政企"],
    "store_visit": ["到店", "门店"],
    "new_launch": ["新品", "首发"],
    "holiday": ["送礼", "节日", "双十一", "礼物"],
    "campus_daily": ["校园日常", "期中", "学期中", "图书馆", "宿舍"],
}

# Ledger attributes whose listed options are SKU configurations (memory/storage size, colour, keyboard, screen).
SKU_ATTRIBUTES = {"memory", "storage", "color", "keyboard", "display_type", "touchscreen"}

PLATFORM_CHIPS = ["小红书", "朋友圈", "公众号", "海报"]
SCENARIO_CHIPS = ["开学季", "职场办公", "内容创作", "家庭换新"]

_EXTRA_RE = re.compile(r"^(?:再)?(?:加上|加入|写上|写明|要写|要有|承诺|补充|附上|强调)")


def _norm_key(value: Optional[str], synonyms: dict[str, list[str]], labels: dict[str, str]) -> Optional[str]:
    """Map a raw phrase (key, label or synonym) to a key; None if nothing matches."""
    if not value:
        return None
    v = str(value).strip()
    if v in synonyms:
        return v
    for key, label in labels.items():
        if v == label:
            return key
    for key, words in synonyms.items():
        if any(w in v for w in words):
            return key
    return None


def map_platform(value: Optional[str]) -> Optional[str]:
    return _norm_key(value, PLATFORM_SYNONYMS, PLATFORM_LABELS)


def map_scenario(value: Optional[str]) -> Optional[str]:
    return _norm_key(value, SCENARIO_SYNONYMS, SCENARIO_LABELS)


def _extra_from_text(text: str) -> list[str]:
    """Fallback if the LLM misses an explicit request: clauses that start with 加上/写上/承诺..."""
    parts = re.split(r"[，,。；;\n]", text or "")
    return [p.strip() for p in parts if _EXTRA_RE.match(p.strip())]


def _clean(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("null", "none") else None


def _found(res) -> bool:
    return res.status in ("resolved", "text_only") and res.model is not None


def _norm_variant(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\s()（）【】\[\]·,，、/]+", "", s)
    return re.sub(r"(版|款|配置)$", "", s)


def ledger_variants(ledger) -> set[str]:
    """Normalised SKU configurations of a model: fact variant labels (方键盘, 柔光版 …) plus the options listed
    under the SKU attributes ("24 GB / 32 GB" -> 24gb, 32gb). Block-local 配置1/配置2 labels are not names."""
    out = set()
    for f in ledger.facts:
        v = (f.variant or "all").strip()
        if v != "all" and not re.fullmatch(r"配置\d+", v):
            out.add(_norm_variant(v))
        if f.attribute in SKU_ATTRIBUTES:
            out.update(_norm_variant(o) for o in re.split(r"[/／、,，;；|]", f.value))
    return {v for v in out if len(v) >= 2}


def check_variant(task: Task, ledger) -> Optional[str]:
    """After the ledger is built: keep task.variant only if it matches one of the model's configurations
    (normalised substring either way). Otherwise drop it and return a 待确认 note."""
    if not task.variant:
        return None
    want = _norm_variant(task.variant)
    if want and any(want in k or k in want for k in ledger_variants(ledger)):
        return None
    note = f"配置「{task.variant}」未在该型号资料中找到，已按全部配置处理"
    task.variant = None
    return note


def parse_task(text: str, catalog, form: dict | None = None, llm=None) -> Task | Clarification:
    form = form or {}
    if llm is None:
        from agent.llm import LLM, load_prompt  # noqa: F401
        llm = LLM()
    from agent.llm import load_prompt

    data = llm.chat_json(load_prompt("intake"), f"导购原话：{text}", stage="intake", fast=True) or {}

    product_query = _clean(form.get("product")) or _clean(data.get("product_query"))
    audience = _clean(form.get("audience")) or _clean(data.get("audience"))
    variant = _clean(form.get("variant")) or _clean(data.get("variant"))

    scenario = (map_scenario(form.get("scenario")) if form.get("scenario") else None) \
        or map_scenario(_clean(data.get("scenario")))
    platform = (map_platform(form.get("platform")) if form.get("platform") else None) \
        or map_platform(_clean(data.get("platform")))
    # Code fallback on the raw text if the LLM missed an obvious keyword.
    platform = platform or map_platform(text)
    # Remove platform words first so "门店朋友圈" is not read as the 到店 scenario.
    bare = text
    for words in PLATFORM_SYNONYMS.values():
        for w in sorted(words, key=len, reverse=True):
            bare = bare.replace(w, "")
    scenario = scenario or map_scenario(bare)

    extras = data.get("extra_requirements") or []
    if isinstance(extras, str):
        extras = [extras]
    extras = [str(e).strip() for e in extras if str(e).strip()]
    for e in _extra_from_text(text):
        if not any(e in x or x in e for x in extras):
            extras.append(e)
    for e in (form.get("extra_requirements") or []):
        if e and e not in extras:
            extras.append(e)

    task = Task(raw_text=text, product_query=product_query, variant=variant, audience=audience,
                scenario=scenario, platform=platform, extra_requirements=extras)

    questions: list[Question] = []

    # --- product: the LLM sometimes puts series/OS words (酷睿 Ultra, 鸿蒙版, SE …) into variant.
    # Resolve query + variant first; if the variant is what picked the model, it was part of the name.
    if product_query:
        res = None
        if variant:
            full = catalog.resolve(f"{product_query} {variant}")
            if _found(full):
                res = full
                plain = catalog.resolve(product_query)
                if not (_found(plain) and plain.model.model_id == full.model.model_id):
                    task.product_query = f"{product_query} {variant}"
                    task.variant = None
        res = res or catalog.resolve(product_query)
        if res.status in ("resolved", "text_only") and res.model:
            task.model_id = res.model.model_id
        elif res.status == "ambiguous":
            names = [m.canonical_name for m in res.candidates][:4]
            questions.append(Question("product", "这个名称对应多个型号，请选一个具体型号：", names))
        else:
            names = [m.canonical_name for m in res.candidates][:4]
            questions.append(Question("product", "知识库中没有找到这个型号，是不是下面这些？", names))
    else:
        names = [m.canonical_name for m in list(catalog.models.values())[:4]]
        questions.append(Question("product", "想推荐哪个型号？", names))

    # --- audience or scenario (one of them is enough)
    if not audience and not scenario:
        questions.append(Question("scenario", "这位客户是什么场景？", SCENARIO_CHIPS))

    # --- platform
    if not platform:
        questions.append(Question("platform", "文章发到哪个平台？", PLATFORM_CHIPS))

    if questions:
        return Clarification(questions=questions, partial=task)
    return task
