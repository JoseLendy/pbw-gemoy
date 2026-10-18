"""
Step 4 fact ledger (WORKFLOW §3 step 4, kb_structure §e). Every fact carries a verbatim quote.

- 产品事实.md is parsed by code: "## <section>", then a label line and one or more value lines
  (blank lines between), footnotes starting with "*", a leave-site banner at the end. Some sections
  have no label line (the section name is the label). "标准版：" lines mark the variant of the values
  that follow. One Fact per value line; footnotes go to Ledger.boundaries.
- 卖点与限制.md: inside 六个沟通角度 each angle has 可用结论 / 支撑事实 / 表达边界, written either
  inline ("- 可用结论：…") or as a bold label line followed by lines/bullets. 可用结论 -> claim fact,
  支撑事实 -> linked to spec facts by value (new spec fact if nothing matches), 表达边界 and the
  "不要写/不应写" compliance examples -> boundaries. An LLM (optional) is used only when no angle
  could be parsed by code.
- Grounding: every row, parser or LLM, must pass quote_ok() or it lands in Ledger.dropped.
- Conflict = same model + attribute + variant (+ same kind of qualifier) and different normalised
  values. Several values under ONE label are a variant set (options), never a conflict.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from agent.schemas import CATEGORIES, Conflict, Fact, Ledger, ModelBundle
from agent.units import (canonical, find_all, find_qualifier, find_values, is_upper_bound, nfkc, normalize,
                         parse_dimensions, parse_resolution, same_value)

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
LEDGER_CACHE = ROOT / ".cache" / "ledger"
PARSER_VERSION = "ledger-v1"
FACTS_TITLE, CLAIMS_TITLE = "产品事实.md", "卖点与限制.md"

# ---------------------------------------------------------------------- maps
SECTION_CATEGORY = {
    "尺寸与重量": "portability", "屏幕": "display", "处理器": "performance", "显卡": "performance",
    "内存": "storage_memory", "存储": "storage_memory", "内存与存储": "storage_memory", "电池": "battery",
    "接口": "ports", "无线连接": "ports", "操作系统": "system", "系统与协同": "system", "特色应用": "system",
    "键盘和触控板": "design", "摄像头": "audio_camera", "音频": "audio_camera", "安全": "security",
    "包装清单": "other",
}
SKIP_SECTIONS = {"来源", "官方规格摘录", "事实来源"}
NO_LABEL_SECTIONS = {"包装清单"}       # every line is an item (an item may look like a label: 电源适配器)

LABEL_ATTR = {
    "重量": "weight", "长度": "length", "宽度": "width", "厚度": "thickness", "深度": "depth", "高度": "height",
    "分辨率": "resolution", "刷新率": "refresh_rate", "亮度": "brightness", "色域": "color_gamut",
    "对比度": "contrast_ratio", "色准": "color_accuracy", "屏占比": "screen_to_body", "屏幕比例": "aspect_ratio",
    "可视角度": "viewing_angle", "像素密度": "ppi", "ppi": "ppi", "触摸屏": "touchscreen",
    "容量": "battery_capacity", "续航": "battery_life", "cpu": "cpu", "处理器": "cpu", "gpu": "gpu", "显卡": "gpu",
    "内存": "memory", "存储": "storage", "硬盘": "storage", "接口": "ports", "操作系统": "os", "系统": "os",
    "协同": "collaboration", "wlan": "wlan", "wi-fi": "wlan", "蓝牙": "bluetooth", "nfc": "nfc", "星闪": "nearlink",
    "材料": "material", "材质": "material", "颜色": "color", "配色": "color", "电源键": "power_button",
    "指纹电源键": "fingerprint", "扬声器": "speaker", "麦克风": "microphone", "摄像头": "camera",
    "键盘": "keyboard", "触控板": "touchpad", "电源适配器": "charger", "适配器": "charger", "充电": "charging",
    # sections that hold values without a label line
    "包装清单": "package", "特色应用": "feature", "音频": "audio", "键盘和触控板": "keyboard",
    "无线连接": "wireless",
}
SECTION_LABEL_ATTR = {"尺寸": ("screen_size", "dimensions"), "类型": ("display_type", None)}

ATTR_CATEGORY = {
    **dict.fromkeys(["weight", "dimensions", "length", "width", "thickness", "depth", "height"], "portability"),
    **dict.fromkeys(["screen_size", "resolution", "refresh_rate", "brightness", "color_gamut", "contrast_ratio",
                     "color_accuracy", "screen_to_body", "aspect_ratio", "viewing_angle", "ppi", "touchscreen",
                     "display_type"], "display"),
    **dict.fromkeys(["battery_capacity", "battery_life", "battery_type", "charger", "charging"], "battery"),
    **dict.fromkeys(["cpu", "gpu"], "performance"),
    **dict.fromkeys(["memory", "storage"], "storage_memory"),
    **dict.fromkeys(["ports", "wlan", "bluetooth", "nfc", "nearlink", "wireless"], "ports"),
    **dict.fromkeys(["os", "feature"], "system"),
    "collaboration": "collaboration",
    **dict.fromkeys(["camera", "speaker", "microphone", "audio"], "audio_camera"),
    **dict.fromkeys(["material", "color", "keyboard", "touchpad"], "design"),
    **dict.fromkeys(["fingerprint", "power_button"], "security"),
    "package": "other",
}
# Attributes with ONE value per variant. Everything else (ports, features, colours …) is a list:
# several values are items, never alternatives, and never a conflict.
SINGLE_VALUED = {"weight", "dimensions", "length", "width", "thickness", "depth", "height", "screen_size",
                 "resolution", "refresh_rate", "brightness", "contrast_ratio", "screen_to_body", "aspect_ratio",
                 "ppi", "battery_capacity", "battery_life", "battery_type", "cpu", "gpu", "memory", "storage",
                 "display_type", "charger"}
ENTITY_ATTRS = {"cpu", "gpu", "ports", "os", "collaboration", "feature", "display_type", "wlan", "bluetooth",
                "nfc", "nearlink", "wireless"}
AUTO_VARIANT = "配置"            # unlabeled alternatives under one label: 配置1, 配置2 … (block-local)

ANGLE_CATEGORY = [               # first match on the angle title wins
    ("portability", ("便携", "轻薄", "重量", "机身", "出行", "通勤")),
    ("battery", ("续航", "电池", "充电")),
    ("display", ("屏", "显示", "护眼", "画质")),
    ("collaboration", ("协同", "互联", "多设备", "跨设备", "生态")),
    ("performance", ("性能", "处理器", "芯片", "算力", "散热")),
    ("storage_memory", ("内存", "存储")),
    ("ports", ("接口", "扩展", "连接")),
    ("audio_camera", ("影音", "音频", "音效", "摄像", "会议")),
    ("security", ("安全", "隐私")),
    ("system", ("系统", "鸿蒙", "ai", "智能", "应用", "办公")),
    ("design", ("设计", "外观", "配色", "颜色", "质感", "键盘")),
    ("service", ("服务", "售后", "保修")),
]
UNIT_ATTR = {"g": "weight", "Wh": "battery_capacity", "h": "battery_life", "Hz": "refresh_rate",
             "inch": "screen_size", "nits": "brightness", "W": "charger", "mm": "dimensions", "ppi": "ppi"}

_NON_VARIANT = ("含电池", "典型值", "额定容量", "额定值", "额定", "峰值", "最高", "约", "实测", "标称")
_PAREN_RE = re.compile(r"[（(]([^（）()]{1,20})[）)]\s*[。.]?\s*$")
_SUBLABEL_RE = re.compile(r"^(?:\*\*)?([^：:\d]{1,10}?)(?:\*\*)?\s*[：:]$")
_INLINE_VARIANT_RE = re.compile(r"^([^：:\d\s]{1,8}[版款])[：:]\s*(.+)$")
_MARK_RE = re.compile(r"^[-*•]?\s*(?:\*\*)?(可用结论|支撑事实|表达边界)(?:\*\*)?\s*[：:]?\s*(?:\*\*)?\s*(.*)$")
_DONT_RE = re.compile(r"^[-*•]?\s*(?:\*\*)?(不要写|不应写|不能写|不可写|避免写|禁止写)(?:\*\*)?\s*[：:]\s*(.+)$")
_ANGLE_RE = re.compile(r"^###\s*(?:(\d+)\s*[.、．]\s*)?(.+)$")
_COUNT_RE = re.compile(r"^\d+\s*[×xX*]\s*")
_DISPLAY_TECH_RE = re.compile(r"(?<![A-Za-z])(AMOLED|OLED|IPS|LCD|LTPO|Mini[- ]?LED)(?![A-Za-z])", re.IGNORECASE)
_PUNCT = "，,。；;、：:"


# ---------------------------------------------------------------------- grounding
def _gnorm(s: str) -> str:
    return nfkc((s or "").replace("**", ""))


def quote_ok(quote: str, value: str, source_text: str) -> bool:
    """quote is verbatim in the source AND value is inside quote (NFKC + whitespace-normalised)."""
    q, v = _gnorm(quote), _gnorm(value)
    return bool(q) and bool(v) and q in _gnorm(source_text) and v in q


def strip_banner(text: str) -> str:
    """Drop the scraped leave-site dialog at the end of a spec page (one line or several)."""
    lines = (text or "").splitlines()
    for i in range(len(lines) - 1, max(-1, len(lines) - 15), -1):
        if lines[i].strip().startswith("即将离开") and "继续访问" in "\n".join(lines[i:]):
            return "\n".join(lines[:i]).rstrip() + "\n"
    return text or ""


# ---------------------------------------------------------------------- helpers
def _clean_label(s: str) -> str:
    return s.strip().rstrip("*：: ").strip()


def _label_like(s: str | None) -> bool:
    if not s or s.startswith(("#", "-", "*", ">")):
        return False
    c = _clean_label(s)
    return 0 < len(c) <= 10 and not re.search(r"[\d，。；、,;/×()（）]", c)


def _attr_for(section: str, label: str) -> str | None:
    key = label.lower()
    if key in SECTION_LABEL_ATTR:
        in_screen, other = SECTION_LABEL_ATTR[key]
        if "屏" in section:
            return in_screen
        if key == "类型" and "电池" in section:
            return "battery_type"
        return other
    return LABEL_ATTR.get(key)


def _variant(value: str) -> str:
    m = _PAREN_RE.search(nfkc(value).replace("(", "（").replace(")", "）"))
    if not m:
        return "all"
    inner = m.group(1)
    for w in _NON_VARIANT:
        inner = inner.replace(w, "")
    inner = inner.strip(" " + _PUNCT)
    return inner if 1 <= len(inner) <= 10 and not inner.isdigit() else "all"


def _angle_category(title: str) -> str:
    t = nfkc(title).lower()
    return next((cat for cat, words in ANGLE_CATEGORY if any(w in t for w in words)), "other")


def _qualifier_class(q: str) -> str:
    if q in ("最高", "最长", "最大", "最多", "可达"):
        return "max"
    return {"约": "", "典型值": "typ", "峰值": "peak", "额定": "rated", "最低": "min", "不低于": "min",
            "至少": "min"}.get(q, q)


def _make_fact(model_id, attribute, category, value, quote, title, path, kind="spec", variant="all") -> Fact:
    value = value.strip()
    vals = find_values(value)
    res, dims = parse_resolution(value), parse_dimensions(value)
    norm_value, norm_unit, qualifier = normalize(value)
    unit = ""
    if res:
        norm_value, norm_unit = None, "resolution"
    elif vals:
        span = find_all(value)[0][0]
        unit = re.sub(r"^[\d.\s]+", "", span)
        if dims or len(vals) > 1:
            norm_value = None
            norm_unit = vals[0][1] if len({u for _, u in vals}) == 1 else ""
    if category not in CATEGORIES:
        category = "other"
    return Fact(id="", model_id=model_id, attribute=attribute, category=category, value=value, quote=quote.strip(),
                source_title=title, source_path=path, kind=kind, variant=variant or "all", unit=unit,
                norm_value=norm_value, norm_unit=norm_unit, qualifier=qualifier or find_qualifier(value),
                upper_bound=is_upper_bound(value))


def _entities_from(attr: str, value: str, section: str) -> list[str]:
    v = re.sub(r"[（(][^）)]*[）)]", "", nfkc(value)).strip(" " + _PUNCT)
    out = [m.group(1) for m in _DISPLAY_TECH_RE.finditer(v)] if attr in ("display_type", "touchscreen") \
        or "屏" in section else []
    if attr == "ports":
        out += [_COUNT_RE.sub("", p).strip() for p in re.split(r"[，,、；;/]", v)]
    elif attr in ("collaboration", "feature"):
        out += [p.strip() for p in re.split(r"[，,、；;]", v) if len(p.strip()) <= 20]
    elif attr in ENTITY_ATTRS:
        out.append(v)
    return [e for e in out if e and len(e) <= 40 and (attr == "ports" or not find_values(e))]


# ---------------------------------------------------------------------- 产品事实.md
def parse_specs(text: str, model_id: str, title: str = FACTS_TITLE, path: str = FACTS_TITLE
                ) -> tuple[list[Fact], list[dict], list[str]]:
    """(facts, boundaries from footnotes, entities). Facts have no ids yet."""
    lines = [l.strip() for l in strip_banner(text).splitlines()]
    seq = [s for s in lines if s]
    facts, boundaries, entities = [], [], []
    section, label, label_raw, label_adjacent, variant_ctx = "", None, "", False, None
    prev, block = "heading", 0
    unknown: dict[tuple[str, str], str] = {}
    blocks: dict[int, list[Fact]] = defaultdict(list)

    def nxt(k):
        for s in seq[k + 1:]:
            if not (s.startswith("*") and not s.startswith("**")):
                return None if s.startswith("#") else s
        return None

    for k, s in enumerate(seq):
        if s.startswith("# ") or s.startswith(">"):
            continue
        if s.startswith("##"):
            section, label, variant_ctx, prev = s.lstrip("#").strip(), None, None, "heading"
            block += 1
            continue
        if not section or section in SKIP_SECTIONS:
            continue
        cat = SECTION_CATEGORY.get(section, "other")
        if s.startswith("*") and not s.startswith("**"):
            boundaries.append({"category": cat, "text": s.lstrip("* ").strip(), "source_title": title})
            continue
        sub = _SUBLABEL_RE.match(s)
        if sub:
            variant_ctx, prev = sub.group(1).strip(), "label"
            continue
        if prev != "label" and section not in NO_LABEL_SECTIONS and (_clean_label(s).lower() in LABEL_ATTR or SECTION_LABEL_ATTR.get(_clean_label(s))
                                or (_label_like(s) and nxt(k) is not None and not _label_like(nxt(k)))):
            label, label_raw, label_adjacent, variant_ctx, prev = _clean_label(s), s, True, None, "label"
            block += 1
            continue
        value = re.sub(r"^[-•·]\s*", "", s)
        variant = variant_ctx or "all"
        inline = _INLINE_VARIANT_RE.match(value)
        if inline:
            variant = inline.group(1)
        if variant == "all":
            variant = _variant(value)
        lab = label or section
        attr = _attr_for(section, lab)
        quote = value
        if attr is None:
            attr = unknown.setdefault((section, lab), f"spec_{len(unknown) + 1}")
            # the label travels with the value when the two lines are verbatim neighbours in the source
            if label and label_adjacent and quote_ok(f"{label_raw} {s}", value, text):
                quote = f"{label_raw} {s}"
            if section == "特色应用" and label:
                entities.append(label)
        kind = "entity" if attr in ENTITY_ATTRS and (attr == "ports" or not find_values(value)) else "spec"
        f = _make_fact(model_id, attr, ATTR_CATEGORY.get(attr, cat), value, quote, title, path, kind, variant)
        if attr == "ports":                       # "1 × 3.5 mm 耳机接口" is a port, not a 3.5 mm value
            f.unit, f.norm_value, f.norm_unit = "", None, ""
        facts.append(f)
        blocks[block].append(f)
        entities += _entities_from(attr, value, section)
        label_adjacent, prev = False, "value"

    _label_alternatives(blocks)
    return facts, boundaries, entities


def _label_alternatives(blocks: dict[int, list[Fact]]) -> None:
    """Several different values of a single-valued attribute under ONE label are configuration options
    (variant set), not a conflict: give each its own block-local variant 配置1, 配置2 …"""
    for facts in blocks.values():
        groups = defaultdict(list)
        for f in facts:
            if f.attribute in SINGLE_VALUED and f.variant == "all":
                groups[(f.attribute, _qualifier_class(f.qualifier))].append(f)
        for fs in groups.values():
            if len({canonical(f.value) for f in fs}) > 1:
                for j, f in enumerate(fs, start=1):
                    f.variant = f"{AUTO_VARIANT}{j}"


# ---------------------------------------------------------------------- 卖点与限制.md
def parse_claims(text: str, model_id: str, specs: list[Fact], title: str = CLAIMS_TITLE,
                 path: str = CLAIMS_TITLE) -> tuple[list[Fact], list[dict], int]:
    """(facts, boundaries, number of angles found). Supporting facts that match a spec fact add nothing."""
    facts, boundaries = [], []
    section, angle_n, angle_cat, marker, angles = "", 0, "other", None, 0

    def add(marker, content, raw):
        content = content.strip()
        if not content:
            return
        if marker == "可用结论":
            facts.append(_make_fact(model_id, f"angle_{angle_n}", angle_cat, content.rstrip("。. "), raw, title,
                                    path, kind="claim"))
        elif marker == "支撑事实":
            for item in [p.strip() for p in re.split(r"[；;]", content) if p.strip(" 。")]:
                item_value = item.rstrip("。. ")
                if not _linked(item_value, specs + facts):
                    vals = find_values(item_value)
                    attr = UNIT_ATTR.get(vals[0][1], "feature") if len(vals) == 1 else "feature"
                    facts.append(_make_fact(model_id, attr, angle_cat, item_value, item, title, path,
                                            kind="spec", variant=_variant(item_value)))
        elif marker == "表达边界":
            boundaries.append({"category": angle_cat, "text": content, "source_title": title})

    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("## "):
            section, marker = s[3:].strip(), None
            continue
        if section == "六个沟通角度" and s.startswith("###"):
            m = _ANGLE_RE.match(s)
            angles += 1
            angle_n = int(m.group(1)) if m and m.group(1) else angles
            angle_cat = _angle_category(m.group(2) if m else s)
            marker = None
            continue
        if section == "合规表达示例":
            d = _DONT_RE.match(s)
            if d:
                text = d.group(2).strip().strip('"“”「」『』\'。. ')
                boundaries.append({"category": "other", "text": text, "source_title": title})
            continue
        if section != "六个沟通角度" or not angle_n:
            continue
        m = _MARK_RE.match(s)
        if m:
            marker = m.group(1)
            inline = m.group(2).strip().strip("*").strip()
            if inline:
                add(marker, inline, re.sub(r"^[-*•]\s*", "", s).replace("**", ""))
            continue
        if marker:
            content = re.sub(r"^[-*•]\s*|^\d+[.、]\s*", "", s)
            add(marker, content, content)
    return facts, boundaries, angles


def _linked(item: str, facts: list[Fact]) -> bool:
    """A supporting fact is already covered when all its numbers (or its text) match a ledger fact."""
    nums = find_values(item)
    specs = [f for f in facts if f.kind != "claim"]
    if nums:
        have = [(v, u) for f in specs for v, u in find_values(f.value)]
        return all(any(same_value(v, u, hv, hu) for hv, hu in have) for v, u in nums)
    c = canonical(item)
    return len(c) >= 2 and any((cf := canonical(f.value)) and (cf in c or c in cf) for f in specs)


# ---------------------------------------------------------------------- optional LLM rows
LLM_SYSTEM = (
    "你从华为电脑产品资料中抽取卖点。只输出 JSON：{\"rows\": [{\"attribute\", \"category\", \"value\", "
    "\"quote\", \"variant\"}]}。quote 必须逐字摘自原文，value 必须是 quote 中的一段。category 取值："
    + "/".join(CATEGORIES) + "。不要编造，不要改写数字。"
)


def _llm_rows(llm, text: str, model_id: str, title: str, path: str) -> tuple[list[Fact], list[dict]]:
    try:
        resp = llm.chat_json(LLM_SYSTEM, text, stage="ledger_claims", fast=True)
    except Exception as e:  # noqa: BLE001  the ledger must still build without the LLM
        log.warning("ledger_claims LLM failed: %s", type(e).__name__)
        return [], []
    rows = resp.get("rows", []) if isinstance(resp, dict) else resp if isinstance(resp, list) else []
    facts, dropped = [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        value, quote = str(r.get("value") or ""), str(r.get("quote") or "")
        if not quote_ok(quote, value, text):
            dropped.append({"row": r, "reason": "LLM 行未通过原文核对（quote 不在原文中或 value 不在 quote 中）"})
            continue
        attr = re.sub(r"[^a-z0-9_]", "", str(r.get("attribute") or "").lower()) or "feature"
        facts.append(_make_fact(model_id, attr, str(r.get("category") or "other"), value, quote, title, path,
                                kind="claim", variant=str(r.get("variant") or "all")))
    return facts, dropped


# ---------------------------------------------------------------------- conflicts
def _comparable(a: Fact, b: Fact) -> bool | None:
    """True = same value, False = different, None = not comparable."""
    ra, rb = parse_resolution(a.value), parse_resolution(b.value)
    if ra or rb:
        return None if not (ra and rb) else ra == rb
    va, vb = find_values(a.value), find_values(b.value)
    if va or vb:
        if not (va and vb) or {u for _, u in va} != {u for _, u in vb}:
            return None
        if len(va) == 1 and len(vb) == 1:
            return same_value(va[0][0], va[0][1], vb[0][0], vb[0][1])
        return (all(any(same_value(x, u, y, w) for y, w in vb) for x, u in va)
                and all(any(same_value(y, w, x, u) for x, u in va) for y, w in vb))
    if a.variant != "all":
        return None
    return canonical(a.value) == canonical(b.value)


def find_conflicts(facts: list[Fact]) -> list[Conflict]:
    groups = defaultdict(list)
    for f in facts:
        if f.kind == "claim" or f.attribute not in SINGLE_VALUED or f.variant.startswith(AUTO_VARIANT):
            continue
        groups[(f.model_id, f.attribute, f.variant, _qualifier_class(f.qualifier))].append(f)
    out = []
    for (_, attr, variant, _), fs in groups.items():
        ids = []
        for i, a in enumerate(fs):
            for b in fs[i + 1:]:
                if _comparable(a, b) is False:
                    ids += [x.id for x in (a, b) if x.id not in ids]
        if ids:
            vals = "；".join(dict.fromkeys(f.value for f in fs if f.id in ids))
            out.append(Conflict(attribute=attr, variant=variant, fact_ids=ids,
                                reason=f"同一型号、同一配置（{variant}）的 {attr} 出现不同取值：{vals}"))
    return out


# ---------------------------------------------------------------------- build
def _cache_path(bundle: ModelBundle, llm) -> Path:
    h = hashlib.sha1(f"{PARSER_VERSION}\0{bundle.facts_text}\0{bundle.claims_text}\0{bool(llm)}".encode()).hexdigest()
    return LEDGER_CACHE / f"{bundle.model.model_id}-{h}.json"


def _from_dict(d: dict) -> Ledger:
    return Ledger(model_id=d["model_id"], facts=[Fact(**f) for f in d["facts"]],
                  conflicts=[Conflict(**c) for c in d.get("conflicts", [])], dropped=d.get("dropped", []),
                  entities=d.get("entities", []), boundaries=d.get("boundaries", []))


def build_ledger(bundle: ModelBundle, llm=None, use_cache: bool = True) -> Ledger:
    cp = _cache_path(bundle, llm)
    if use_cache and cp.exists():
        return _from_dict(json.loads(cp.read_text("utf-8")))

    mid = bundle.model.model_id
    fs, cs = bundle.facts_source, bundle.claims_source
    f_title, f_path = (fs.title, fs.source_path) if fs else (FACTS_TITLE, FACTS_TITLE)
    c_title, c_path = (cs.title, cs.source_path) if cs else (CLAIMS_TITLE, CLAIMS_TITLE)

    specs, boundaries, entities = parse_specs(bundle.facts_text, mid, f_title, f_path)
    claims, c_bounds, angles = parse_claims(bundle.claims_text, mid, specs, c_title, c_path)
    boundaries += c_bounds
    dropped: list[dict] = []
    if llm is not None and bundle.claims_text.strip() and not angles:
        llm_facts, llm_dropped = _llm_rows(llm, bundle.claims_text, mid, c_title, c_path)
        claims += llm_facts
        dropped += llm_dropped

    facts = []
    for f, src in [(f, bundle.facts_text) for f in specs] + [(f, bundle.claims_text) for f in claims]:
        if quote_ok(f.quote, f.value, src):
            facts.append(f)
        else:
            dropped.append({"row": asdict(f), "reason": "未通过原文核对（quote 不在原文中或 value 不在 quote 中）"})
    for i, f in enumerate(facts, start=1):
        f.id = f"F{i}"

    ledger = Ledger(model_id=mid, facts=facts, conflicts=find_conflicts(facts), dropped=dropped,
                    entities=list(dict.fromkeys(e for e in entities if e)), boundaries=boundaries)
    if use_cache:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(asdict(ledger), ensure_ascii=False, indent=1), "utf-8")
    return ledger
