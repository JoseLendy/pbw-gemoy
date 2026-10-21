#!/usr/bin/env python3
"""
pbw gemoy - demo data generator (复赛).

Reads the editable templates in data/demo/inputs/ and writes everything else to
data/demo/generated/. Deterministic: same seed + same inputs = same output.

    python scripts/gen_fake_data.py                    # today = 2026-10-21, seed = 42
    python scripts/gen_fake_data.py --today 2026-10-23 --seed 7

Standard library only. The scoring functions here (segment_weights, under_index,
build_cards) are the reference implementation for agent/recommend/ - copy them,
don't re-invent them, so the app and the demo data agree.

Everything written is marked is_demo. Real product facts are NOT generated here:
they come from the ima knowledge base through the existing fact ledger.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "data" / "demo" / "inputs"
OUT = ROOT / "data" / "demo" / "generated"

# ---------------------------------------------------------------- generation-only knobs
# Used ONLY to synthesize sales. The app must derive audience from POI, never from these.
GEN_WEIGHTS = {
    "campus":      {"student": .65, "family": .15, "office": .05, "shopper": .15},
    "office":      {"student": .05, "family": .15, "office": .65, "shopper": .15},
    "residential": {"student": .10, "family": .65, "office": .10, "shopper": .15},
    "mall":        {"student": .15, "family": .25, "office": .10, "shopper": .50},
}
TOTAL_UNITS = {1: 15, 2: 30, 3: 50}          # avg weekly units per store tier
HISTORY_WEEKS = 12
SCORE_WINDOW_WEEKS = 8                        # weeks used for under-index

# Planted stories: (store, model) -> sales multiplier. These make the demo surface
# clear, explainable 潜力款 picks. Change freely, then re-run and read the sanity table.
PLANTED = {
    ("S01", "MODEL_A"): 0.40,   # campus store under-sells the light/long-battery model
    ("S04", "MODEL_B"): 0.45,   # CBD store under-sells the business model
    ("S08", "MODEL_D"): 0.50,   # residential store under-sells the family model
    ("S10", "MODEL_A"): 0.45,   # mall store under-sells the same light model (gift angle, not study angle)
}
STOCKOUT = {("S02", "MODEL_A")}  # shows the stock filter: high fit, but nothing to sell

# Recommender thresholds (keep identical in agent/recommend/scoring.py)
MIN_FIT = 0.50
MAX_INDEX = 0.70                 # only "clearly under-selling" counts
MIN_PEER_UNITS = 10
RECENT_POST_DAYS = 7
CALENDAR_LOOKAHEAD_DAYS = 30
NEW_RELEASE_PRIORITY_DAYS = 7    # verified release within ±7 days of launch -> default card

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
def stable_hash(*parts: str) -> int:
    """Deterministic across runs and machines (Python's hash() is salted - never use it)."""
    return int(hashlib.md5("|".join(parts).encode("utf-8")).hexdigest(), 16)


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


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


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


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


def category_of(typecode: str, seg_cfg: dict) -> str | None:
    for cat, c in seg_cfg["categories"].items():
        for code in typecode.split("|"):
            if code in c["typecodes"]:
                return cat
    return None


def load_pois(store: dict, rng: random.Random, seg_cfg: dict) -> tuple[list[dict], str]:
    """Real Amap cache wins (written by scripts/fetch_poi.py); otherwise a fake fixture."""
    cache = INPUTS / "poi_cache" / f"{store['store_id']}.json"
    if cache.exists():
        raw = load_json(cache)
        pois = []
        for p in raw["pois"]:
            cat = category_of(p["typecode"], seg_cfg)
            if cat:
                pois.append({**p, "category": cat, "is_demo": False})
        return pois, "amap"
    pois = fake_pois(store, rng, seg_cfg)
    write_json(OUT / "poi_fixtures" / f"{store['store_id']}.json", {"store_id": store["store_id"], "pois": pois})
    return pois, "fixture"


def segment_weights(pois: list[dict], seg_cfg: dict) -> dict:
    """raw[s] = sum importance * exp(-d/decay); normalized. Reference implementation."""
    cats, decay = seg_cfg["categories"], seg_cfg["decay_m"]
    raw = {s: 0.0 for s in seg_cfg["segments"]}
    by_cat = defaultdict(list)
    contrib = defaultdict(float)
    for p in pois:
        if p["distance_m"] > seg_cfg["radius_m"]:
            continue
        c = cats[p["category"]]
        v = c["importance"] * math.exp(-p["distance_m"] / decay)
        raw[c["segment"]] += v
        contrib[p["category"]] += v
        by_cat[p["category"]].append(p)
    total = sum(raw.values()) or 1.0
    weights = {s: round(v / total, 3) for s, v in raw.items()}
    dominant = max(weights, key=weights.get)
    # strongest category inside the dominant segment -> used in the explanation card
    dom_cats = [c for c in contrib if cats[c]["segment"] == dominant]
    top_cat = max(dom_cats, key=contrib.get) if dom_cats else None
    examples = sorted(by_cat.get(top_cat, []), key=lambda p: (not p.get("is_anchor"), p["distance_m"]))
    return {
        "weights": weights, "dominant": dominant, "top_category": top_cat,
        "top_category_count": len(by_cat.get(top_cat, [])),
        "top_category_example": examples[0]["name"] if examples else None,
        "category_counts": {c: len(v) for c, v in by_cat.items()},
    }


# ---------------------------------------------------------------- sales
def week_starts(today: dt.date) -> list[dt.date]:
    this_monday = today - dt.timedelta(days=today.weekday())
    last_full = this_monday - dt.timedelta(weeks=1)
    return [last_full - dt.timedelta(weeks=i) for i in reversed(range(HISTORY_WEEKS))]


def seasonal_factor(week: dt.date) -> float:
    if dt.date(week.year, 8, 25) <= week <= dt.date(week.year, 9, 21):   # 开学季
        return 1.3
    return 1.0


def affinity(model: dict) -> dict:
    return {s: float(model[f"aff_{s}"]) for s in ("student", "office", "family", "shopper")}


def gen_sales(stores, models, today, rng) -> list[dict]:
    rows = []
    weeks = week_starts(today)
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


def under_index(sales, signals, today) -> dict:
    """share vs peer share (same dominant segment). Reference implementation."""
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


def build_profiles(stores, signals, angles, overrides):
    voices = {v["id"]: v for v in angles["voices"]}
    profiles = {}
    for st in stores:
        dom = signals[st["store_id"]]["dominant"]
        allowed = [v for v in angles["voices"] if dom in v["allowed_segments"]]
        voice = allowed[stable_hash(st["store_id"], "voice") % len(allowed)]
        profiles[st["store_id"]] = {
            "store_id": st["store_id"], "store_name": st["store_name"],
            "landmark": f"{st['anchor_poi']}附近", "landmark_source": "auto_from_poi",
            "voice": voice["id"], "voice_label": voice["label"],
            "nickname": angles["nicknames"][stable_hash(st["store_id"], "nick") % len(angles["nicknames"])],
            "editable_by_store": True, "is_demo": True,
        }
        ov = overrides.get(st["store_id"], {})
        if "voice" in ov:
            if dom not in voices[ov["voice"]]["allowed_segments"]:
                raise ValueError(f"{st['store_id']}: voice {ov['voice']} not allowed for segment {dom}")
            profiles[st["store_id"]].update(voice=ov["voice"], voice_label=voices[ov["voice"]]["label"])
        if "landmark" in ov:
            profiles[st["store_id"]].update(landmark=ov["landmark"], landmark_source="edited_by_store")
        if "nickname" in ov:
            profiles[st["store_id"]]["nickname"] = ov["nickname"]
    return profiles


# ---------------------------------------------------------------- cards
def calendar_reason(calendar, segment, today):
    best = None
    for ev in calendar:
        if segment not in ev["segments"]:
            continue
        start, end = parse_date(ev["start"]), parse_date(ev["end"])
        if start <= today <= end:
            return {"event": ev["event"], "theme": ev["theme"], "text": f"正值{ev['event']}（{ev['theme']}）"}
        days = (parse_date(ev["end"]) - today).days if ev["event"] in ("双十一", "双十二") else (start - today).days
        if 0 < days <= CALENDAR_LOOKAHEAD_DAYS and (best is None or days < best[0]):
            best = (days, ev)
    if best:
        d, ev = best
        return {"event": ev["event"], "theme": ev["theme"], "text": f"距{ev['event']}还有 {d} 天"}
    return None


def poi_reason(sig, seg_cfg):
    cat = sig["top_category"]
    if not cat:
        return None
    label = seg_cfg["categories"][cat]["label"]
    unit = "所" if cat in ("university", "middle_school", "primary_school") else "个"
    return (f"门店{seg_cfg['radius_m'] / 1000:g}km内有{sig['top_category_count']}{unit}{label}"
            f"（{sig['top_category_example']}等）→ {seg_cfg['segment_labels'][sig['dominant']]}为主")


def build_cards(stores, models, signals, idx, promos, calendar, quota, angles, profiles,
                questions, publish_rows, seg_cfg, pool, today):
    mby = {m["model_id"]: m for m in models}
    platform = quota["rotation"][today.weekday()]
    recent = defaultdict(set)
    for r in publish_rows:
        if r["posted"] == "true" and (today - parse_date(r["date"])).days <= RECENT_POST_DAYS:
            recent[r["store_id"]].add(r["model_id"])
    q_counts = defaultdict(lambda: defaultdict(int))
    for q in questions:
        q_counts[q["store_id"]][q["chip_id"]] += 1

    all_cards = {}
    for st in stores:
        sid = st["store_id"]
        sig, prof = signals[sid], profiles[sid]
        dom = sig["dominant"]
        fit = {m["model_id"]: round(sum(sig["weights"][s] * a for s, a in affinity(m).items()), 3) for m in models}
        cal = calendar_reason(calendar, dom, today)
        poi_r = [{"text": poi_reason(sig, seg_cfg), "source": "poi", "is_demo": sig["poi_source"] != "amap"}]
        cal_r = [{"text": cal["text"], "source": "calendar", "is_demo": False}] if cal else []

        def card(slot, label, model_id, reasons, **extra):
            seg_angles = angles["segment_angles"][dom]
            if slot == "customer_question":   # a logged question always opens with the customer hook
                hook = next(h for h in angles["hooks"] if h.get("requires_logged_question"))
            else:
                hooks = [h for h in angles["hooks"] if not h.get("requires_logged_question")]
                hook = hooks[stable_hash(sid, today.isoformat(), slot) % len(hooks)]
            c = {
                "card_id": f"{sid}-{today.isoformat()}-{slot}", "store_id": sid, "store_name": st["store_name"],
                "date": today.isoformat(), "slot": slot, "slot_label": label,
                "model_id": model_id, "display_name": mby[model_id]["display_name"] if model_id else None,
                "platform": platform, "segment": dom, "segment_label": seg_cfg["segment_labels"][dom],
                "angle": seg_angles[stable_hash(sid, today.isoformat(), slot, "angle") % len(seg_angles)],
                "calendar_theme": cal["theme"] if cal else None,
                "hook": {"id": hook["id"], "label": hook["label"]},
                "voice": {"id": prof["voice"], "label": prof["voice_label"]},
                "landmark": prof["landmark"], "nickname": prof["nickname"],
                "reasons": [r for r in poi_r + reasons + cal_r if r["text"]],  # where → why this → when
                "locked": False, "locked_reason": None, "promo": None, "question": None,
                "scores": {"fit": fit.get(model_id)} if model_id else {}, "is_default": False, "is_demo": True,
            }
            c.update(extra)
            return c

        cards = []
        # 潜力款
        cands = []
        for mid, f in fit.items():
            s = idx.get((sid, mid))
            if not s or s["index"] is None:
                continue
            ok = (f >= MIN_FIT and s["index"] <= MAX_INDEX and s["stock"] > 0
                  and s["peer_units"] >= MIN_PEER_UNITS and mid not in recent[sid])
            if ok:
                cands.append((f * (1 - s["index"]), mid, s))
        if cands:
            pot, mid, s = max(cands)
            peer_word = "同类商圈门店" if s["peer_basis"] == "same_segment" else "其他门店"
            c = card("potential", "潜力款", mid, [{
                "text": f"该型号本店销量占比低于{peer_word} {round((1 - s['index']) * 100)}%",
                "source": "sales", "is_demo": True}])
            c["scores"].update({"index": s["index"], "potential": round(pot, 3),
                                "share": s["share"], "peer_share": s["peer_share"]})
            cards.append(c)
        # 活动款
        active = [p for p in promos if parse_date(p["start"]) <= today <= parse_date(p["end"])]
        if active:
            best = max(((fit[m], m, p) for p in active for m in p["models"] if m in fit), default=None)
            if best:
                _, mid, p = best
                price = (p.get("price_info") or {}).get(mid)
                cards.append(card("promo", "活动款", mid, [{
                    "text": f"全国活动「{p['name']}」进行中（{p['start']} 至 {p['end']}）",
                    "source": "promo", "is_demo": p["source"] == "DEMO"}],
                    promo={"campaign_id": p["campaign_id"], "name": p["name"], "mechanic": p["mechanic"],
                           "price_info": price, "source": p["source"]}))
        # 新品款
        for m in models:
            if m["is_new_release"] != "true":
                continue
            launch = parse_date(m["launch_date"])
            if abs((launch - today).days) > 30:
                continue
            verified = m["fact_card_status"] == "verified"
            cards.append(card("new_release", "新品款", m["model_id"], [{
                "text": f"新品 {launch.isoformat()} 上市" if verified else "新品资料待总部确认，暂不可生成",
                "source": "release", "is_demo": False}],
                locked=not verified, locked_reason=None if verified else "fact_card_draft"))
        # 顾客问答
        if q_counts[sid]:
            # most asked; ties go to questions that fit this store's audience
            cid, n = max(q_counts[sid].items(),
                         key=lambda kv: (kv[1], dom in pool["chips"][kv[0]]["segments"], kv[0]))
            text = next(q["text"] for q in questions if q["chip_id"] == cid)
            best_model = max(fit, key=lambda m: (fit[m] if mby[m]["is_new_release"] != "true" else -1))
            c = card("customer_question", "顾客问答", best_model, [{
                "text": f"本店近7天顾客问「{text}」{n} 次", "source": "questions", "is_demo": True}],
                question={"chip_id": cid, "text": text, "count": n})
            c["angle"] = text
            cards.append(c)

        # default card: verified new release near launch > 潜力款 > 活动款 > 顾客问答
        def prio(c):
            if c["slot"] == "new_release" and not c["locked"] and \
                    abs((parse_date(mby[c["model_id"]]["launch_date"]) - today).days) <= NEW_RELEASE_PRIORITY_DAYS:
                return 0
            return {"potential": 1, "promo": 2, "customer_question": 3, "new_release": 4}[c["slot"]]
        unlocked = [c for c in cards if not c["locked"]]
        if unlocked:
            min(unlocked, key=prio)["is_default"] = True
        all_cards[sid] = cards
    return all_cards


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

    # 1. location -> audience
    signals = {}
    for st in stores:
        pois, src = load_pois(st, rng, seg_cfg)
        sig = segment_weights(pois, seg_cfg)
        sig["poi_source"] = src
        signals[st["store_id"]] = sig
    write_json(OUT / "store_signals.json", signals)

    # 2. sales + under-index
    sales = gen_sales(stores, models, today, rng)
    write_csv(OUT / "sales_weekly.csv", sales)
    idx = under_index(sales, signals, today)

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
    cards = build_cards(stores, models, signals, idx, promos, calendar, quota, angles, profiles,
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
