"""8E similarity helpers: character 3-gram Jaccard, threshold from env (default 0.55)."""
from __future__ import annotations

import os
import re

DEFAULT_THRESHOLD = 0.55
_WS_RE = re.compile(r"\s+")

__all__ = ["char_ngrams", "jaccard", "similarity_threshold", "DEFAULT_THRESHOLD"]


def char_ngrams(text: str, n: int = 3) -> set[str]:
    s = _WS_RE.sub("", text or "")
    if not s:
        return set()
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}


def jaccard(a: str, b: str, n: int = 3) -> float:
    x, y = char_ngrams(a, n), char_ngrams(b, n)
    if not x and not y:
        return 0.0
    return len(x & y) / len(x | y)


def similarity_threshold() -> float:
    try:
        return float(os.getenv("SIMILARITY_THRESHOLD", DEFAULT_THRESHOLD))
    except ValueError:
        return DEFAULT_THRESHOLD
