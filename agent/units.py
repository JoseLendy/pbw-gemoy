"""
Unit normalisation shared by the ledger (P2) and the fact checks (P3).

Owner: P2. This first version is part of the contracts commit so P3 is not blocked;
P2 extends it (more units, edge cases) without changing the function signatures.

    normalize("约 1.33 kg（圆键盘含电池）") -> (1330.0, "g", "约")
    normalize("最高 120 Hz")               -> (120.0, "Hz", "最高")
    normalize("14.2 英寸")                  -> (14.2, "inch", "")
"""
from __future__ import annotations

import re
import unicodedata

# raw unit spelling -> (canonical unit, factor to canonical)
UNIT_MAP: dict[str, tuple[str, float]] = {
    "kg": ("g", 1000.0), "公斤": ("g", 1000.0), "千克": ("g", 1000.0),
    "g": ("g", 1.0), "克": ("g", 1.0),
    "英寸": ("inch", 1.0), "寸": ("inch", 1.0), "inch": ("inch", 1.0), "in": ("inch", 1.0), '"': ("inch", 1.0),
    "wh": ("Wh", 1.0), "瓦时": ("Wh", 1.0),
    "mah": ("mAh", 1.0), "毫安时": ("mAh", 1.0),
    "hz": ("Hz", 1.0), "赫兹": ("Hz", 1.0),
    "nits": ("nits", 1.0), "nit": ("nits", 1.0), "尼特": ("nits", 1.0), "cd/m2": ("nits", 1.0), "cd/m²": ("nits", 1.0),
    "tb": ("GB", 1000.0), "gb": ("GB", 1.0),
    "w": ("W", 1.0), "瓦": ("W", 1.0),
    "mm": ("mm", 1.0), "毫米": ("mm", 1.0), "cm": ("mm", 10.0),
    "小时": ("h", 1.0), "h": ("h", 1.0), "hours": ("h", 1.0), "分钟": ("h", 1 / 60),
    "ppi": ("ppi", 1.0),
    "ghz": ("GHz", 1.0), "mhz": ("GHz", 0.001),
    "%": ("%", 1.0),
    "核": ("cores", 1.0), "线程": ("threads", 1.0),
}

QUALIFIERS = ("约", "典型值", "峰值", "最高", "最长", "最大", "最多", "可达", "额定", "最低", "不低于", "至少")
UPPER_BOUND_WORDS = ("最高", "最长", "最大", "最多", "可达", "up to")

_UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNIT_MAP), key=len, reverse=True))
NUM_UNIT_RE = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNIT_ALT})(?![A-Za-z])", re.IGNORECASE)


def nfkc(s: str) -> str:
    """Full-width -> half-width, normalise spaces."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def find_qualifier(text: str) -> str:
    t = nfkc(text)
    return next((q for q in QUALIFIERS if q in t), "")


def is_upper_bound(text: str) -> bool:
    t = nfkc(text).lower()
    return any(w in t for w in UPPER_BOUND_WORDS)


def normalize(value_text: str) -> tuple[float | None, str, str]:
    """First number+unit in the text -> (canonical value, canonical unit, qualifier).
    Returns (None, "", qualifier) when there is no recognised number+unit."""
    t = nfkc(value_text)
    q = find_qualifier(t)
    m = NUM_UNIT_RE.search(t)
    if not m:
        return None, "", q
    num, unit = float(m.group(1)), m.group(2)
    canon, factor = UNIT_MAP[unit.lower()] if unit.lower() in UNIT_MAP else UNIT_MAP[unit]
    return round(num * factor, 6), canon, q


def find_all(text: str) -> list[tuple[str, float, str]]:
    """Every number+unit in a text: [(matched span, canonical value, canonical unit)]."""
    out = []
    for m in NUM_UNIT_RE.finditer(nfkc(text)):
        unit = m.group(2)
        canon, factor = UNIT_MAP.get(unit.lower(), UNIT_MAP.get(unit, ("", 1.0)))
        if canon:
            out.append((m.group(0), round(float(m.group(1)) * factor, 6), canon))
    return out


def same_value(a_value: float | None, a_unit: str, b_value: float | None, b_unit: str,
               rel_tol: float = 0.005) -> bool:
    """Equal after normalisation. Storage: 1 TB == 1000 GB == 1024 GB."""
    if a_value is None or b_value is None or a_unit != b_unit:
        return False

    def close(x: float, y: float) -> bool:
        return abs(x - y) <= rel_tol * max(abs(x), abs(y), 1e-9)

    if a_unit == "GB" and max(a_value, b_value) >= 1000:   # TB tier: decimal vs binary spelling
        return any(close(a_value * f, b_value) for f in (1.0, 1.024, 1 / 1.024))
    return close(a_value, b_value)
