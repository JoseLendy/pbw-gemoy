"""
Unit normalisation shared by the ledger (P2) and the fact checks (P3).

Owner: P2. This first version is part of the contracts commit so P3 is not blocked;
P2 extends it (more units, edge cases) without changing the function signatures.

    normalize("约 1.33 kg（圆键盘含电池）") -> (1330.0, "g", "约")
    normalize("最高 120 Hz")               -> (120.0, "Hz", "最高")
    normalize("14.2 英寸")                  -> (14.2, "inch", "")
    find_values("16 GB / 32 GB")           -> [(16.0, "GB"), (32.0, "GB")]
    parse_resolution("2880 × 1920")        -> (2880, 1920)       a pair, never two numbers
    parse_dimensions("313 mm × 222 mm × 15.9 mm") -> [313.0, 222.0, 15.9]   (mm)
    canonical("2880 × 1920")               -> "2880x1920"         key for comparing non-numeric values
"""
from __future__ import annotations

import re
import unicodedata

# raw unit spelling -> (canonical unit, factor to canonical)
UNIT_MAP: dict[str, tuple[str, float]] = {
    "kg": ("g", 1000.0), "公斤": ("g", 1000.0), "千克": ("g", 1000.0),
    "g": ("g", 1.0), "克": ("g", 1.0),
    "英寸": ("inch", 1.0), "寸": ("inch", 1.0), "inch": ("inch", 1.0), '"': ("inch", 1.0),
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

# In priority order: an upper bound wins over 约 ("最长约 14 小时" -> 最长).
QUALIFIERS = ("最高", "最长", "最大", "最多", "可达", "典型值", "峰值", "额定", "最低", "不低于", "至少", "约")
UPPER_BOUND_WORDS = ("最高", "最长", "最大", "最多", "可达", "up to")

_UNIT_ALT = "|".join(sorted((re.escape(u) for u in UNIT_MAP), key=len, reverse=True))
# No letter/digit right before the number ("X90", "i5"), no letter right after the unit.
NUM_UNIT_RE = re.compile(rf"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)\s*({_UNIT_ALT})(?![A-Za-z])", re.IGNORECASE)
# Single-letter units are case-sensitive: "155H" is a CPU suffix, "5G" a network, not hours / grams.
_CASE_SENSITIVE = {"h": "h", "g": "g"}

RES_RE = re.compile(r"(?<![\d.])(\d{3,5})\s*[×xX*]\s*(\d{3,5})(?![\d.]|\s*(?:mm|毫米|cm|[×xX*]))")
_LEN = r"(\d+(?:\.\d+)?)\s*(mm|毫米|cm)?"
DIM_RE = re.compile(rf"{_LEN}\s*[×xX*]\s*{_LEN}(?:\s*[×xX*]\s*{_LEN})?")


def nfkc(s: str) -> str:
    """Full-width -> half-width, normalise spaces."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def find_qualifier(text: str) -> str:
    t = nfkc(text)
    return next((q for q in QUALIFIERS if q in t), "")


def is_upper_bound(text: str) -> bool:
    t = nfkc(text).lower()
    return any(w in t for w in UPPER_BOUND_WORDS)


def _unit(raw: str) -> tuple[str, float] | None:
    low = raw.lower()
    if low in _CASE_SENSITIVE and raw != _CASE_SENSITIVE[low]:
        return None
    return UNIT_MAP.get(low) or UNIT_MAP.get(raw)


def _matches(t: str):
    """(match, canonical value, canonical unit) for every number+unit, skipping resolution pairs."""
    res_spans = [m.span() for m in RES_RE.finditer(t)]
    for m in NUM_UNIT_RE.finditer(t):
        u = _unit(m.group(2))
        if u is None or any(a <= m.start() < b for a, b in res_spans):
            continue
        yield m, round(float(m.group(1)) * u[1], 6), u[0]


def normalize(value_text: str) -> tuple[float | None, str, str]:
    """First number+unit in the text -> (canonical value, canonical unit, qualifier).
    Returns (None, "", qualifier) when there is no recognised number+unit."""
    t = nfkc(value_text)
    q = find_qualifier(t)
    m = next(_matches(t), None)
    if not m:
        return None, "", q
    return m[1], m[2], q


def find_all(text: str) -> list[tuple[str, float, str]]:
    """Every number+unit in a text: [(matched span, canonical value, canonical unit)]."""
    return [(m.group(0), v, u) for m, v, u in _matches(nfkc(text))]


def find_values(text: str) -> list[tuple[float, str]]:
    """All values of a multi-value text ("16 GB / 32 GB", "313 mm × 222 mm × 15.9 mm")."""
    return [(v, u) for _, v, u in find_all(text)]


def parse_resolution(text: str) -> tuple[int, int] | None:
    m = RES_RE.search(nfkc(text))
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_dimensions(text: str) -> list[float] | None:
    """3 lengths joined by × (or 2 that both carry a unit), in mm. A unit on the last part applies to
    parts without one. "1 × 3.5 mm 耳机接口" is a count, not a dimension."""
    t = nfkc(text)
    if parse_resolution(t) and not re.search(r"mm|毫米|cm", t):
        return None
    m = DIM_RE.search(t)
    if not m:
        return None
    parts = [(m.group(i), m.group(i + 1)) for i in (1, 3, 5) if m.group(i)]
    units = [u for _, u in parts if u]
    if not units or (len(parts) == 2 and len(units) < 2):
        return None
    out = []
    for num, unit in parts:
        factor = UNIT_MAP[(unit or units[-1]).lower()][1]
        out.append(round(float(num) * factor, 6))
    return out


def canonical(text: str) -> str:
    """Comparison key for non-numeric values: width/case/space-insensitive, pairs kept as pairs."""
    t = nfkc(text)
    r = parse_resolution(t)
    if r:
        return f"{r[0]}x{r[1]}"
    d = parse_dimensions(t)
    if d:
        return "x".join(f"{v:g}" for v in d) + "mm"
    t = re.sub(r"[（(][^）)]*[）)]", "", t.lower())
    return re.sub(r"[\s，,。、；;：:/]+|\.(?!\d)", "", t)


def same_value(a_value, a_unit, b_value=None, b_unit=None, rel_tol: float = 0.005) -> bool:
    """Equal after normalisation. Storage: 1 TB == 1000 GB == 1024 GB.
    Two call styles: same_value(a_value, a_unit, b_value, b_unit) or, as in CONTRACTS §3,
    same_value(fact, b_value, b_unit) where fact has norm_value / norm_unit."""
    if hasattr(a_value, "norm_value"):
        a_value, a_unit, b_value, b_unit = a_value.norm_value, a_value.norm_unit, a_unit, b_value
    if a_value is None or b_value is None or a_unit != b_unit:
        return False

    def close(x: float, y: float) -> bool:
        return abs(x - y) <= rel_tol * max(abs(x), abs(y), 1e-9)

    if a_unit == "GB" and max(a_value, b_value) >= 1000:   # TB tier: decimal vs binary spelling
        return any(close(a_value * f, b_value) for f in (1.0, 1.024, 1 / 1.024))
    return close(a_value, b_value)
