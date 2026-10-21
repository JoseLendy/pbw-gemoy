"""
Sales → under-index (plan §4.2, §5.2). Sales are fake and only ever used to CHOOSE products;
nothing here may end up in copy.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from agent.recommend.scoring import HISTORY_WEEKS, SCORE_WINDOW_WEEKS


def week_starts(today: dt.date, n: int = HISTORY_WEEKS) -> list[dt.date]:
    """The last `n` full weeks (Mondays), oldest first; the current partial week is excluded."""
    this_monday = today - dt.timedelta(days=today.weekday())
    last_full = this_monday - dt.timedelta(weeks=1)
    return [last_full - dt.timedelta(weeks=i) for i in reversed(range(n))]


def under_index(sales: list[dict], signals: dict, today: dt.date) -> dict:
    """share vs peer share (same dominant segment). Reference implementation.

    share(m, store)    = units(m, store, last 8 weeks) / units(all models, store, last 8 weeks)
    expected(m, store) = mean share(m, peer) over peer stores (same dominant; else all stores)
    index(m, store)    = share / expected        1.0 = normal, < 1 = under-selling
    Returns {(store_id, model_id): {share, peer_share, index, peer_units, peer_basis, stock}}.
    """
    weeks = week_starts(today)[-SCORE_WINDOW_WEEKS:]
    wset = {w.isoformat() for w in weeks}
    units = defaultdict(int)
    store_total = defaultdict(int)
    stock = {}
    last_week = weeks[-1].isoformat()
    for r in sales:
        if r["week_start"] in wset:
            units[(r["store_id"], r["model_id"])] += int(r["units"])
            store_total[r["store_id"]] += int(r["units"])
        if r["week_start"] == last_week:
            stock[(r["store_id"], r["model_id"])] = int(r["stock_on_hand"])
    share = {k: v / store_total[k[0]] for k, v in units.items() if store_total[k[0]]}
    model_ids = sorted({k[1] for k in units})
    out = {}
    for sid, sig in signals.items():
        peers = [p for p, ps in signals.items() if p != sid and ps["dominant"] == sig["dominant"]]
        peer_basis = "same_segment"
        if not peers:                       # no peer with the same segment -> compare with all stores
            peers = [p for p in signals if p != sid]
            peer_basis = "all_stores"
        for m in model_ids:
            exp_share = sum(share.get((p, m), 0) for p in peers) / len(peers)
            peer_units = sum(units.get((p, m), 0) for p in peers)
            idx = share.get((sid, m), 0) / exp_share if exp_share else None
            out[(sid, m)] = {"share": round(share.get((sid, m), 0), 4), "peer_share": round(exp_share, 4),
                             "index": round(idx, 3) if idx is not None else None, "peer_units": peer_units,
                             "peer_basis": peer_basis, "stock": stock.get((sid, m), 0)}
    return out
