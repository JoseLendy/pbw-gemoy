"""
Fit + eligibility thresholds (plan §5.1–§5.2). SINGLE SOURCE OF TRUTH for every constant:
scripts/gen_fake_data.py imports them from here, so the demo data and the app cannot drift.
"""
from __future__ import annotations

from agent.recommend.common import SEGMENTS

HISTORY_WEEKS = 12               # weeks of sales history generated / loaded
SCORE_WINDOW_WEEKS = 8           # weeks used for the under-index
MIN_FIT = 0.50                   # only products that suit the local audience
MAX_INDEX = 0.70                 # only "clearly under-selling" counts, not noise
MIN_PEER_UNITS = 10              # avoid tiny-number noise
RECENT_POST_DAYS = 7             # not posted in the last 7 days
CALENDAR_LOOKAHEAD_DAYS = 30     # calendar events within 30 days add a theme + reason line
NEW_RELEASE_WINDOW_DAYS = 30     # 新品款 card exists within ±30 days of launch
NEW_RELEASE_PRIORITY_DAYS = 7    # verified release within ±7 days of launch → default card


def affinity(model: dict) -> dict[str, float]:
    """aff_* columns of models.csv as {segment: 0..1}."""
    return {s: float(model[f"aff_{s}"]) for s in SEGMENTS}


def fit(model: dict, weights: dict[str, float]) -> float:
    """fit(m, store) = Σ_s w_store[s] × affinity[m][s], in [0, 1], rounded to 3 places."""
    return round(sum(weights[s] * a for s, a in affinity(model).items()), 3)


def fit_table(models: list[dict], weights: dict[str, float]) -> dict[str, float]:
    return {m["model_id"]: fit(m, weights) for m in models}


def potential(fit_value: float, index: float) -> float:
    """potential(m, store) = fit × (1 − index); only meaningful when eligible()."""
    return fit_value * (1 - index)


def eligible(fit_value: float, stats: dict, recently_posted: bool) -> bool:
    """The §5.2 filters: fit ≥ MIN_FIT, index ≤ MAX_INDEX, stock > 0, peer units ≥ MIN_PEER_UNITS,
    not posted in the last RECENT_POST_DAYS."""
    if stats is None or stats.get("index") is None:
        return False
    return (fit_value >= MIN_FIT and stats["index"] <= MAX_INDEX and stats["stock"] > 0
            and stats["peer_units"] >= MIN_PEER_UNITS and not recently_posted)
