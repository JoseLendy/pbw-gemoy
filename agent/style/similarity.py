"""8E similarity helpers: character 3-gram Jaccard, threshold from env (default 0.55), and the day-level
variety rules (variety_breaches) that generate_batch enforces across ALL of one day's posts:

  similar        Jaccard with an earlier post of the day above the threshold (any peer group)
  phrase         a 6+ character phrase in more than 3 of the day's posts (the 4th and later are reworded);
                 fact wording, product names and store details are never counted
  stock          a stock opener / filler (agent.style.profile.STOCK_PHRASES) in more than one post
  selling_point  one product's selling point in more than 2 stores, or twice in one peer group

The later store (by store id) is the one regenerated; customer-question cards are never targets."""
from __future__ import annotations

import os
import re

DEFAULT_THRESHOLD = 0.55
_WS_RE = re.compile(r"\s+")

__all__ = ["char_ngrams", "jaccard", "similarity_threshold", "DEFAULT_THRESHOLD", "repeated_phrases",
           "variety_breaches", "PHRASE_LEN", "MAX_POSTS_PER_PHRASE", "MAX_STORES_PER_POINT"]

PHRASE_LEN = 6                 # characters
MAX_POSTS_PER_PHRASE = 3       # a phrase may appear in at most 3 of the day's posts
MAX_STORES_PER_POINT = 2       # one product's selling point: at most 2 stores a day
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_KEEP_NOISE = re.compile(r"[^\u4e00-\u9fff]+")


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


def _grams(text: str, keep: list[str] = (), n: int = PHRASE_LEN) -> set[str]:
    """Chinese n-grams of a post, minus any that sit inside a kept string (fact wording, names)."""
    text = text or ""
    for k in sorted((k for k in keep if k), key=len, reverse=True):     # cut kept wording out first, so no
        text = text.replace(k, "|")                                       # n-gram straddles it
    kept = [_KEEP_NOISE.sub("", k) for k in keep if k]
    out = set()
    for run in _CJK_RUN.findall(text):
        for i in range(len(run) - n + 1):
            g = run[i:i + n]
            if not any(g in k for k in kept):
                out.add(g)
    return out


def _merge(text: str, grams: set[str]) -> list[str]:
    """Maximal phrases of `text` covered by `grams` (overlapping n-grams joined)."""
    out: list[str] = []
    for run in _CJK_RUN.findall(text or ""):
        covered = [False] * len(run)
        for i in range(len(run) - PHRASE_LEN + 1):
            if run[i:i + PHRASE_LEN] in grams:
                covered[i:i + PHRASE_LEN] = [True] * PHRASE_LEN
        i = 0
        while i < len(run):
            if covered[i]:
                j = i
                while j < len(run) and covered[j]:
                    j += 1
                if run[i:j] not in out:
                    out.append(run[i:j])
                i = j
            else:
                i += 1
    return out


def repeated_phrases(texts: dict[str, str], min_posts: int = 2, keep: dict[str, list[str]] | None = None,
                     top: int = 10) -> list[tuple[str, int]]:
    """[(phrase, number of posts)] for phrases of PHRASE_LEN+ characters in >= min_posts posts, most common first."""
    keep = keep or {}
    grams = {sid: _grams(t, keep.get(sid, [])) for sid, t in texts.items()}
    counts: dict[str, int] = {}
    for gs in grams.values():
        for g in gs:
            counts[g] = counts.get(g, 0) + 1
    hot = {g for g, c in counts.items() if c >= min_posts}
    phrases: dict[str, int] = {}
    for sid, t in texts.items():
        for ph in _merge(t, hot & grams[sid]):
            phrases[ph] = sum(1 for t2 in texts.values() if ph in _KEEP_NOISE.sub("", t2))
    ranked = sorted(phrases.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    out: list[tuple[str, int]] = []
    for ph, c in ranked:
        if c >= min_posts and not any(ph in o and c == oc for o, oc in out):
            out.append((ph, c))
    return out[:top]


def variety_breaches(entries: list[dict], threshold: float | None = None,
                     stock: tuple[str, ...] | None = None) -> dict[str, dict]:
    """Which stores must be regenerated, and what each must avoid.

    entries: [{"store_id", "segment", "model_id", "selling_points", "text", "keep", "customer"}] (any order).
    Returns {store_id: {"reasons": [...], "avoid_facts": [...], "avoid_phrases": [...], "similar_to": id|None}}."""
    if threshold is None:
        threshold = similarity_threshold()
    if stock is None:
        from agent.style.profile import STOCK_PHRASES as stock
    rows = sorted(entries, key=lambda e: e["store_id"])
    out: dict[str, dict] = {}

    def hit(e, reason, facts=(), phrases=(), similar_to=None):
        if e.get("customer"):
            return
        b = out.setdefault(e["store_id"], {"reasons": [], "avoid_facts": [], "avoid_phrases": [], "similar_to": None})
        if reason not in b["reasons"]:
            b["reasons"].append(reason)
        b["avoid_facts"] += [f for f in facts if f not in b["avoid_facts"]]
        b["avoid_phrases"] += [p for p in phrases if p not in b["avoid_phrases"]]
        if similar_to and not b["similar_to"]:
            b["similar_to"] = similar_to

    # similar: any earlier post of the day
    for i, b in enumerate(rows):
        best = max(((jaccard(a["text"], b["text"]), a["store_id"]) for a in rows[:i] if a["text"] and b["text"]),
                   default=(0.0, None))
        if best[1] and best[0] > threshold:
            hit(b, "similar", similar_to=best[1])

    # selling_point: per product, at most MAX_STORES_PER_POINT stores and one per peer group
    users: dict[tuple, list[dict]] = {}
    for e in rows:
        clash = []
        for fid in e.get("selling_points") or []:
            seen = users.get((e["model_id"], fid), [])
            if len(seen) >= MAX_STORES_PER_POINT or any(s["segment"] == e["segment"] for s in seen):
                clash.append(fid)
        if clash and not e.get("customer"):
            hit(e, "selling_point", facts=clash)
            continue                                   # it will move to another point: not counted as a user
        for fid in e.get("selling_points") or []:
            users.setdefault((e["model_id"], fid), []).append(e)

    # stock: one store per stock opener / filler
    for ph in stock:
        holders = [e for e in rows if ph in (e["text"] or "")]
        for e in holders[1:]:
            hit(e, "stock", phrases=[ph])

    # phrase: a 6+ character phrase in more than MAX_POSTS_PER_PHRASE posts
    grams = {e["store_id"]: _grams(e["text"], e.get("keep") or []) for e in rows}
    seen_in: dict[str, list[str]] = {}
    for e in rows:
        for g in grams[e["store_id"]]:
            seen_in.setdefault(g, []).append(e["store_id"])
    for e in rows:
        extra = {g for g in grams[e["store_id"]]
                 if len(seen_in[g]) > MAX_POSTS_PER_PHRASE and seen_in[g].index(e["store_id"]) >= MAX_POSTS_PER_PHRASE}
        if extra:
            hit(e, "phrase", phrases=_merge(e["text"], extra))
    return out
