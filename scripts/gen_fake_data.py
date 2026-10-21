#!/usr/bin/env python3
"""
pbw gemoy - demo data generator (复赛).

Reads the editable templates in data/demo/inputs/ and writes everything else to
data/demo/generated/. Deterministic: same seed + same inputs = same output.

    python scripts/gen_fake_data.py                    # today = 2026-10-21, seed = 42
    python scripts/gen_fake_data.py --today 2026-10-23 --seed 7

Standard library only. The scoring (segment_weights, under_index, build_cards, thresholds)
lives in agent/recommend/ and is IMPORTED here, so the app and the demo data cannot disagree.
This script only generates the fake inputs (POI fixtures, sales, logs) and the sanity table.

Everything written is marked is_demo. Real product facts are NOT generated here:
they come from the ima knowledge base through the existing fact ledger.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.recommend import poi, sales as sales_mod, slots  # noqa: E402
from agent.recommend.common import (  # noqa: E402
    GENERATED as OUT, INPUTS, load_csv, load_json, parse_date, write_csv, write_json,
)
from agent.recommend.profiles import build_profiles  # noqa: E402
from agent.recommend.scoring import RECENT_POST_DAYS, affinity  # noqa: E402

# ---------------------------------------------------------------- generation-only knobs
# Used ONLY to synthesize sales. The app must derive audience from POI, never from these.
GEN_WEIGHTS = {
    "campus":      {"student": .65, "family": .15, "office": .05, "shopper": .15},
    "office":      {"student": .05, "family": .15, "office": .65, "shopper": .15},
    "residential": {"student": .10, "family": .65, "office": .10, "shopper": .15},
    "mall":        {"student": .15, "family": .25, "office": .10, "shopper": .50},
}
TOTAL_UNITS = {1: 15, 2: 30, 3: 50}          # avg weekly units per store tier

# Planted stories: (store, model) -> sales multiplier. These make the demo surface
# clear, explainable 潜力款 picks. Change freely, then re-run and read the sanity table.
PLANTED = {
    ("S01", "MODEL_A"): 0.40,   # campus store under-sells the light/long-battery model
    ("S04", "MODEL_B"): 0.45,   # CBD store under-sells the business model
    ("S08", "MODEL_D"): 0.50,   # residential store under-sells the family model
    ("S10", "MODEL_A"): 0.45,   # mall store under-sells the same light model (gift angle, not study angle)
}
STOCKOUT = {("S02", "MODEL_A")}  # shows the stock filter: high fit, but nothing to sell
# Recommender thresholds (MIN_FIT, MAX_INDEX, ...) are imported from agent/recommend/scoring.py.

# Fake POI layout per intended type: category -> (count range, distance range in m)
POI_LAYOUT = {
    "campus": {"university": ((1, 2), (500, 1400)), "middle_school": ((1, 1), (300, 1400)),
               "primary_school": ((1, 1), (300, 1400)), "residential": ((3, 5), (200, 1400)),
               "office": ((1, 2), (300, 1400)), "mall": ((0, 1), (600, 1400))},
    "office": {"office": ((10, 16), (100, 1400)), "industrial_park": ((1, 2), (300, 1400)),
               "residential": ((2, 3), (400, 1400)), "primary_school": ((1, 1), (500, 1400)),
               "mall": ((1, 1), (300, 1400))},
    "residential": {"residential": ((8, 12), (100, 1400)), "primary_school": ((2, 2), (200, 1200)),
                    "middle_school": ((1, 1), (300, 1400)), "mall": ((0, 1), (600, 1400)),
                    "office": ((1, 1), (500, 1400))},
    "mall": {"mall": ((1, 1), (500, 1400)), "office": ((4, 6), (200, 1400)),
             "residential": ((3, 4), (300, 1400)), "middle_school": ((1, 1), (400, 1400)),
             "university": ((0, 1), (900, 1400))},
}
ANCHOR_DISTANCE = {"university": 300, "mall": 50, "office": 200, "industrial_park": 200, "residential": 150}


# ---------------------------------------------------------------- helpers
def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:  # normal approximation for large lambda
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


# ---------------------------------------------------------------- POI
def fake_pois(store: dict, rng: random.Random, seg_cfg: dict) -> list[dict]:
    cats = seg_cfg["categories"]
    pois = [{
        "name": store["anchor_poi"], "category": store["anchor_category"],
        "typecode": cats[store["anchor_category"]]["typecodes"][0],
        "distance_m": ANCHOR_DISTANCE[store["anchor_category"]], "is_anchor": True, "is_demo": True,
    }]
    for cat, ((lo, hi), (dmin, dmax)) in POI_LAYOUT[store["intended_type"]].items():
        for i in range(rng.randint(lo, hi)):
            pois.append({
                "name": f"（模拟）{cats[cat]['label']}{i + 1}", "category": cat,
                "typecode": cats[cat]["typecodes"][0],
                "distance_m": rng.randint(dmin, dmax), "is_anchor": False, "is_demo": True,
            })
    return pois


# ---------------------------------------------------------------- sales
def seasonal_factor(week: dt.date) -> float:
    if dt.date(week.year, 8, 25) <= week <= dt.date(week.year, 9, 21):   # 开学季
        return 1.3
    return 1.0


def gen_sales(stores, models, today, rng) -> list[dict]:
    rows = []
    weeks = sales_mod.week_starts(today)
    sellable = [m for m in models if parse_date(m["launch_date"]) <= weeks[0]]
    for st in stores:
        gw = GEN_WEIGHTS[st["intended_type"]]
        demand = {m["model_id"]: sum(gw[s] * a for s, a in affinity(m).items()) * float(m["base_popularity"])
                  for m in sellable}
        tot = sum(demand.values())
        for wi, wk in enumerate(weeks):
            expected_total = TOTAL_UNITS[int(st["traffic_tier"])] * seasonal_factor(wk)
            for mid, d in demand.items():
                lam = expected_total * d / tot * PLANTED.get((st["store_id"], mid), 1.0)
                units = poisson(rng, lam * rng.lognormvariate(0, 0.15))
                stock = rng.randint(3, 20)
                if (st["store_id"], mid) in STOCKOUT and wi == len(weeks) - 1:
                    stock = 0
                rows.append({"store_id": st["store_id"], "model_id": mid, "week_start": wk.isoformat(),
                             "units": units, "stock_on_hand": stock, "is_demo": "true"})
    return rows


# ---------------------------------------------------------------- other fake logs
def gen_publish_log(stores, models, quota, today, rng):
    rows = []
    regular = [m["model_id"] for m in models if m["is_new_release"] != "true"]
    for st in stores:
        propensity = rng.uniform(0.35, 0.95)        # some stores are lazy - that's pain #1
        banned = {m for (s, m) in PLANTED if s == st["store_id"]}
        choices = [m for m in regular if m not in banned]
        for back in range(14, 0, -1):
            d = today - dt.timedelta(days=back)
            posted = rng.random() < propensity
            rows.append({"date": d.isoformat(), "store_id": st["store_id"],
                         "platform": quota["rotation"][d.weekday()], "posted": str(posted).lower(),
                         "model_id": rng.choice(choices) if posted else "", "is_demo": "true"})
    return rows


def gen_engagement(publish_rows, rng):
    base = {"朋友圈": (60, 300), "小红书": (150, 2500), "公众号": (200, 1200)}
    rows = []
    for r in publish_rows:
        if r["posted"] != "true":
            continue
        views = rng.randint(*base[r["platform"]])
        rows.append({"date": r["date"], "store_id": r["store_id"], "platform": r["platform"],
                     "model_id": r["model_id"], "views": views,
                     "likes": int(views * rng.uniform(0.02, 0.08)), "saves": int(views * rng.uniform(0.005, 0.04)),
                     "comments": int(views * rng.uniform(0.002, 0.015)), "inquiries": rng.randint(0, 4),
                     "is_demo": "true"})
    return rows


def gen_questions(stores, signals, pool, today, rng):
    rows = []
    for st in stores:
        dom = signals[st["store_id"]]["dominant"]
        fit_chips = [cid for cid, c in pool["chips"].items() if dom in c["segments"]]
        other = [cid for cid in pool["chips"] if cid not in fit_chips]
        for _ in range(rng.randint(3, 8)):
            cid = rng.choice(fit_chips) if rng.random() < 0.8 or not other else rng.choice(other)
            d = today - dt.timedelta(days=rng.randint(1, 7))
            rows.append({"store_id": st["store_id"], "chip_id": cid, "text": pool["chips"][cid]["text"],
                         "date": d.isoformat(), "is_demo": True})
    return rows


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default="2026-10-21")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    today = parse_date(args.today)
    rng = random.Random(args.seed)

    stores = load_csv(INPUTS / "stores.csv")
    models = load_csv(INPUTS / "models.csv")
    seg_cfg = load_json(INPUTS / "segments.json")
    promos = load_json(INPUTS / "promotions.json")
    calendar = load_json(INPUTS / "calendar.json")
    quota = load_json(INPUTS / "platform_quota.json")
    angles = load_json(INPUTS / "angles.json")
    pool = load_json(INPUTS / "question_pool.json")
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. location -> audience (real Amap cache wins; else a fake fixture is built and written here)
    signals = poi.store_signals(stores, seg_cfg, INPUTS, OUT,
                                make_fixture=lambda st: fake_pois(st, rng, seg_cfg))
    write_json(OUT / "store_signals.json", signals)

    # 2. sales + under-index
    sales = gen_sales(stores, models, today, rng)
    write_csv(OUT / "sales_weekly.csv", sales)
    idx = sales_mod.under_index(sales, signals, today)

    # 3. other logs
    overrides = {k: v for k, v in load_json(INPUTS / "store_profile_overrides.json").items() if not k.startswith("_")}
    profiles = build_profiles(stores, signals, angles, overrides)
    write_json(OUT / "store_profiles.json", profiles)
    publish = gen_publish_log(stores, models, quota, today, rng)
    write_csv(OUT / "publish_log.csv", publish)
    write_json(OUT / "post_history.json",
               [r for r in publish if r["posted"] == "true"
                and (today - parse_date(r["date"])).days <= RECENT_POST_DAYS])
    write_csv(OUT / "engagement_log.csv", gen_engagement(publish, rng))
    questions = gen_questions(stores, signals, pool, today, rng)
    write_json(OUT / "customer_questions.json", questions)

    # 4. today's cards (what the store screen shows)
    cards = slots.build_cards(stores, models, signals, idx, promos, calendar, quota, angles, profiles,
                              questions, publish, seg_cfg, pool, today)
    write_json(OUT / "today_cards.json", {"date": today.isoformat(), "seed": args.seed, "cards": cards})

    # 5. sanity table
    lines = [f"pbw gemoy demo data · today={today} · seed={args.seed} · platform today="
             f"{quota['rotation'][today.weekday()]}", ""]
    lines.append(f"{'store':<5}{'type':<12}{'POI':<9}{'dominant':<9}{'w':<6}{'潜力款':<9}{'index':<7}{'default card':<14}")
    problems = []
    for st in stores:
        sid = st["store_id"]
        sig = signals[sid]
        pot = next((c for c in cards[sid] if c["slot"] == "potential"), None)
        default = next((c for c in cards[sid] if c["is_default"]), None)
        lines.append(f"{sid:<5}{st['intended_type']:<12}{sig['poi_source']:<9}{sig['dominant']:<9}"
                     f"{sig['weights'][sig['dominant']]:<6}{(pot['model_id'] if pot else '-'):<9}"
                     f"{(str(pot['scores']['index']) if pot else '-'):<7}"
                     f"{(default['slot_label'] + ' ' + (default['model_id'] or '')) if default else '-':<14}")
    for (sid, mid) in PLANTED:
        pot = next((c for c in cards[sid] if c["slot"] == "potential"), None)
        if not pot or pot["model_id"] != mid:
            problems.append(f"planted story {sid}/{mid} did NOT surface as 潜力款 - try another seed")
    best_seller = max(models, key=lambda m: float(m["base_popularity"]))["model_id"]
    bs_idx = [idx[(s["store_id"], best_seller)]["index"] for s in stores if (s["store_id"], best_seller) in idx]
    lines += ["", f"best-seller {best_seller} index range: {min(bs_idx):.2f}-{max(bs_idx):.2f} (should hover ~1.0)"]
    if any(c["model_id"] == best_seller for cs in cards.values() for c in cs if c["slot"] == "potential"):
        problems.append(f"best-seller {best_seller} was picked as 潜力款 somewhere - check noise/thresholds")
    for (sid, mid) in STOCKOUT:
        lines.append(f"stock-out check: {sid}/{mid} stock={idx[(sid, mid)]['stock']} (must not be 潜力款)")
    lines += ["", "PROBLEMS:" if problems else "All checks passed."] + [f"  - {p}" for p in problems]
    summary = "\n".join(lines)
    (OUT / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
