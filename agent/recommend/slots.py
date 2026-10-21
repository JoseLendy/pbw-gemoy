"""
Daily slots (plan §5.3): 潜力款 / 活动款 / 新品款 / 顾客问答, the default card ("今日一条"),
and the deterministic hook / angle / voice assignment (md5, never hash()).

build_cards() returns plain dicts in exactly the shape of templates/recommendation_card.example.json;
store_data.cards_for() wraps them in schemas.RecommendationCard.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from agent.recommend import explain
from agent.recommend.common import parse_date
from agent.recommend.scoring import (
    CALENDAR_LOOKAHEAD_DAYS, NEW_RELEASE_PRIORITY_DAYS, NEW_RELEASE_WINDOW_DAYS, RECENT_POST_DAYS, eligible,
    fit_table, potential,
)

SLOT_LABELS = {"potential": "潜力款", "promo": "活动款", "new_release": "新品款", "customer_question": "顾客问答"}
SLOT_ORDER = ("potential", "promo", "new_release", "customer_question")
HOOK_EPOCH = dt.date(2026, 1, 1)      # fixed epoch for the peer-aware daily rotation

# Scenario keys (agent/schemas.Scenario) by segment outside any calendar window.
SEGMENT_SCENARIO = {"student": "campus_daily", "office": "office", "family": "family_upgrade",
                    "shopper": "store_visit"}
SHOPPING_FESTIVALS = ("双十一", "双十二", "春节")
BACK_TO_SCHOOL_EVENT = "开学季"


def _active_or_soon(ev: dict, today: dt.date, lookahead: int) -> bool:
    start, end = parse_date(ev["start"]), parse_date(ev["end"])
    return start <= today <= end or 0 < (start - today).days <= lookahead


def scenario_for(slot: str, segment: str, calendar: list[dict], today: dt.date) -> str:
    """Calendar-aware scenario key for a card (plan decision A, Phase 2):
    new_release → new_launch; 开学季 active and segment ∈ {student, family} → back_to_school;
    a shopping festival active or within CALENDAR_LOOKAHEAD_DAYS and segment ∈ {shopper, family} → holiday;
    otherwise by segment: student → campus_daily (never back_to_school outside 开学季), office → office,
    family → family_upgrade, shopper → store_visit."""
    if slot == "new_release":
        return "new_launch"
    for ev in calendar:
        if ev["event"] == BACK_TO_SCHOOL_EVENT and segment in ("student", "family") \
                and parse_date(ev["start"]) <= today <= parse_date(ev["end"]):
            return "back_to_school"
    if segment in ("shopper", "family"):
        for ev in calendar:
            if ev["event"] in SHOPPING_FESTIVALS and _active_or_soon(ev, today, CALENDAR_LOOKAHEAD_DAYS):
                return "holiday"
    return SEGMENT_SCENARIO[segment]
# Default-card priority after the "verified release near launch" rule (which is 0).
_SLOT_PRIORITY = {"potential": 1, "promo": 2, "customer_question": 3, "new_release": 4}


def pick_hook(angles: dict, store_id: str, today: dt.date, slot: str,
              peer_rank: int = 0, day_offset: int = 0) -> dict:
    """A logged question always opens with the customer hook; other slots rotate by peer rank + date + slot.
    Stores in the same peer group get distinct non-customer hooks while the pool allows it."""
    if slot == "customer_question":
        return next(h for h in angles["hooks"] if h.get("requires_logged_question"))
    hooks = [h for h in angles["hooks"] if not h.get("requires_logged_question")]
    idx = (peer_rank + day_offset + SLOT_ORDER.index(slot)) % len(hooks)
    return hooks[idx]


def pick_angle(angles: dict, segment: str, store_id: str, today: dt.date, slot: str,
               peer_rank: int = 0, day_offset: int = 0) -> str:
    """Peer-aware angle assignment: distinct within a peer group while the segment's angle list allows."""
    seg_angles = angles["segment_angles"][segment]
    idx = (peer_rank + day_offset + SLOT_ORDER.index(slot)) % len(seg_angles)
    return seg_angles[idx]


def recent_models(publish_rows: list[dict], today: dt.date) -> dict[str, set]:
    recent = defaultdict(set)
    for r in publish_rows:
        if r["posted"] == "true" and (today - parse_date(r["date"])).days <= RECENT_POST_DAYS:
            recent[r["store_id"]].add(r["model_id"])
    return recent


def question_counts(questions: list[dict]) -> dict[str, dict[str, int]]:
    q_counts = defaultdict(lambda: defaultdict(int))
    for q in questions:
        q_counts[q["store_id"]][q["chip_id"]] += 1
    return q_counts


def build_cards(stores, models, signals, idx, promos, calendar, quota, angles, profiles,
                questions, publish_rows, seg_cfg, pool, today: dt.date) -> dict[str, list[dict]]:
    """{store_id: [card dict, ...]} for every store. Reference implementation (plan §10.5 step 5)."""
    mby = {m["model_id"]: m for m in models}
    platform = quota["rotation"][today.weekday()]
    recent = recent_models(publish_rows, today)
    q_counts = question_counts(questions)
    peers = defaultdict(list)
    for st in stores:
        peers[signals[st["store_id"]]["dominant"]].append(st["store_id"])
    for group in peers.values():
        group.sort()
    day_offset = (today - HOOK_EPOCH).days

    all_cards = {}
    for st in stores:
        sid = st["store_id"]
        sig, prof = signals[sid], profiles[sid]
        dom = sig["dominant"]
        fit = fit_table(models, sig["weights"])
        cal = explain.calendar_reason(calendar, dom, today)
        poi_r = [explain.reason(explain.poi_reason(sig, seg_cfg), "poi", sig["poi_source"] != "amap")]
        cal_r = [explain.reason(cal["text"], "calendar", False)] if cal else []
        rank = peers[dom].index(sid)

        def card(slot, model_id, reasons, **extra):
            hook = pick_hook(angles, sid, today, slot, peer_rank=rank, day_offset=day_offset)
            c = {
                "card_id": f"{sid}-{today.isoformat()}-{slot}", "store_id": sid, "store_name": st["store_name"],
                "date": today.isoformat(), "slot": slot, "slot_label": SLOT_LABELS[slot],
                "model_id": model_id, "display_name": mby[model_id]["display_name"] if model_id else None,
                "platform": platform, "segment": dom, "segment_label": seg_cfg["segment_labels"][dom],
                "angle": pick_angle(angles, dom, sid, today, slot, peer_rank=rank, day_offset=day_offset),
                "scenario": scenario_for(slot, dom, calendar, today),
                "calendar_theme": cal["theme"] if cal else None,
                "hook": {"id": hook["id"], "label": hook["label"]},
                "voice": {"id": prof["voice"], "label": prof["voice_label"]},
                "landmark": prof["landmark"], "nickname": prof["nickname"],
                "reasons": explain.order_reasons(poi_r, reasons, cal_r),  # where → why this → when
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
            if s and eligible(f, s, mid in recent[sid]):
                cands.append((potential(f, s["index"]), mid, s))
        if cands:
            pot, mid, s = max(cands)
            c = card("potential", mid, [explain.reason(explain.sales_reason(s), "sales", True)])
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
                cards.append(card("promo", mid, [explain.reason(explain.promo_reason(p), "promo", p["source"] == "DEMO")],
                                  promo={"campaign_id": p["campaign_id"], "name": p["name"], "mechanic": p["mechanic"],
                                         "price_info": price, "source": p["source"]}))
        # 新品款
        for m in models:
            if m["is_new_release"] != "true":
                continue
            launch = parse_date(m["launch_date"])
            if abs((launch - today).days) > NEW_RELEASE_WINDOW_DAYS:
                continue
            verified = m["fact_card_status"] == "verified"
            cards.append(card("new_release", m["model_id"],
                              [explain.reason(explain.release_reason(launch, verified), "release", False)],
                              locked=not verified, locked_reason=None if verified else "fact_card_draft"))
        # 顾客问答
        if q_counts[sid]:
            # most asked; ties go to questions that fit this store's audience
            cid, n = max(q_counts[sid].items(),
                         key=lambda kv: (kv[1], dom in pool["chips"][kv[0]]["segments"], kv[0]))
            text = next(q["text"] for q in questions if q["chip_id"] == cid)
            best_model = max(fit, key=lambda m: (fit[m] if mby[m]["is_new_release"] != "true" else -1))
            c = card("customer_question", best_model,
                     [explain.reason(explain.question_reason(text, n), "questions", True)],
                     question={"chip_id": cid, "text": text, "count": n})
            c["angle"] = text
            cards.append(c)

        # default card: verified new release near launch > 潜力款 > 活动款 > 顾客问答
        def prio(c):
            if c["slot"] == "new_release" and not c["locked"] and \
                    abs((parse_date(mby[c["model_id"]]["launch_date"]) - today).days) <= NEW_RELEASE_PRIORITY_DAYS:
                return 0
            return _SLOT_PRIORITY[c["slot"]]
        unlocked = [c for c in cards if not c["locked"]]
        if unlocked:
            min(unlocked, key=prio)["is_default"] = True
        all_cards[sid] = cards
    return all_cards
