"""
Recommender tests (PROACTIVE_AGENT_PLAN §5, §10). Everything runs on the committed demo data kit and
tests/fakes.py: no ima, no LLM, no network, scripts/fetch_poi.py is never run.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import shutil
from collections import defaultdict

import pytest

from agent.pipeline import Deps, run_from_card
from agent.recommend import card_to_task
from agent.recommend.common import GENERATED, INPUTS
from agent.recommend.poi import segment_weights
from agent.recommend.scoring import MAX_INDEX, MIN_FIT, MIN_PEER_UNITS, RECENT_POST_DAYS
from agent.recommend.store_data import (
    all_cards, cards_for, default_card, load_store_data, reload, set_fact_card_status,
)
from agent.schemas import LockedResult, RecommendationCard, RunResult, StaffContext, Task

TODAY = dt.date(2026, 10, 21)
PLANTED = {("S01", "matebook-14-harmonyos"), ("S04", "matebook-pro-s"),
           ("S08", "matebook-d-16-se-2024"), ("S10", "matebook-14-harmonyos")}
BEST_SELLER = "matebook-14-2024"


@pytest.fixture(scope="module")
def data():
    reload()
    return load_store_data()


@pytest.fixture(scope="module")
def cards(data):
    return all_cards(data, TODAY)


def _potential(cards, sid):
    return next((c for c in cards[sid] if c["slot"] == "potential"), None)


# ---------------------------------------------------------------- planted stories + filters
@pytest.mark.parametrize("sid,mid", sorted(PLANTED))
def test_planted_stories_surface_as_potential(cards, sid, mid):
    pot = _potential(cards, sid)
    assert pot is not None and pot["model_id"] == mid
    s = pot["scores"]
    assert s["fit"] >= MIN_FIT and s["index"] <= MAX_INDEX
    assert s["potential"] == pytest.approx(s["fit"] * (1 - s["index"]), abs=1e-3)


def test_best_seller_is_never_potential(cards):
    for sid, cs in cards.items():
        pot = _potential(cards, sid)
        assert pot is None or pot["model_id"] != BEST_SELLER, sid


def test_stock_out_store_has_no_potential_for_that_model(cards, data):
    pot = _potential(cards, "S02")
    assert pot is None or pot["model_id"] != "matebook-14-harmonyos"
    # and the reason is really the stock filter: high fit, nothing to sell
    from agent.recommend.sales import under_index
    idx = under_index(data.sales, data.signals, TODAY)
    assert idx[("S02", "matebook-14-harmonyos")]["stock"] == 0


def test_thresholds_are_the_single_source_of_truth():
    import scripts.gen_fake_data as gen  # the script must import, not redefine, the constants
    from agent.recommend import scoring
    for name in ("MIN_FIT", "MAX_INDEX", "MIN_PEER_UNITS", "RECENT_POST_DAYS", "CALENDAR_LOOKAHEAD_DAYS",
                 "NEW_RELEASE_PRIORITY_DAYS"):
        assert hasattr(scoring, name)
    assert gen.RECENT_POST_DAYS is scoring.RECENT_POST_DAYS
    assert (MIN_FIT, MAX_INDEX, MIN_PEER_UNITS, RECENT_POST_DAYS) == (0.50, 0.70, 10, 7)


# ---------------------------------------------------------------- live == generated
def test_live_cards_equal_generated_today_cards(cards):
    gen = json.loads((GENERATED / "today_cards.json").read_text(encoding="utf-8"))
    assert gen["date"] == TODAY.isoformat() and gen["seed"] == 42
    assert cards == gen["cards"]


def test_cards_for_returns_typed_cards_matching_the_template(data):
    tpl = json.loads((INPUTS.parent / "templates" / "recommendation_card.example.json").read_text(encoding="utf-8"))
    cs = cards_for("S01", TODAY, data)
    assert cs and all(isinstance(c, RecommendationCard) for c in cs)
    assert sum(c.is_default for c in cs) == 1
    d = next(c for c in cs if c.is_default).to_dict()
    assert list(d) == list(tpl)                       # same field names, same order
    assert d == tpl                                   # the template IS the S01 default card
    assert default_card("S01", TODAY, data).card_id == tpl["card_id"]
    with pytest.raises(KeyError):
        cards_for("S99", TODAY, data)


def test_reasons_are_ordered_where_why_when(cards):
    for sid, cs in cards.items():
        for c in cs:
            srcs = [r["source"] for r in c["reasons"]]
            order = {"poi": 0, "sales": 1, "promo": 1, "release": 1, "questions": 1, "calendar": 2}
            assert srcs == sorted(srcs, key=order.get), (sid, c["slot"], srcs)
            assert srcs[0] == "poi"


def test_same_model_gets_different_angles_at_campus_and_mall(cards):
    s01, s10 = _potential(cards, "S01"), _potential(cards, "S10")
    assert s01["model_id"] == s10["model_id"] == "matebook-14-harmonyos"
    assert s01["segment"] == "student" and s10["segment"] == "shopper"
    assert s01["angle"] != s10["angle"]


def test_peer_group_hooks_and_angles_are_distinct(cards, data):
    """Within a peer group and the same slot, stores get distinct non-customer hooks and angles while
    the segment's pool allows it; the customer hook is reserved for 顾客问答 cards."""
    groups = defaultdict(list)
    for st in data.stores:
        groups[data.signals[st["store_id"]]["dominant"]].append(st["store_id"])
    hooks = [h["id"] for h in data.angles["hooks"] if not h.get("requires_logged_question")]
    for seg, sids in groups.items():
        angles = data.angles["segment_angles"][seg]
        for slot in ("potential", "promo", "new_release", "customer_question"):
            picked = [(sid, c) for sid in sids for c in cards[sid] if c["slot"] == slot]
            if not picked:
                continue
            if slot == "customer_question":
                assert all(c["hook"]["id"] == "customer" for _, c in picked)
                continue
            hook_ids = [c["hook"]["id"] for _, c in picked]
            assert "customer" not in hook_ids
            if len(picked) <= len(hooks):
                assert len(hook_ids) == len(set(hook_ids)), (seg, slot, hook_ids)
            angle_values = [c["angle"] for _, c in picked]
            if len(picked) <= len(angles):
                assert len(angle_values) == len(set(angle_values)), (seg, slot, angle_values)


# ---------------------------------------------------------------- voice profile
def test_s01_voice_is_senior_override_and_s02_is_not(data):
    assert data.profiles["S01"]["voice"] == "senior" and data.profiles["S01"]["voice_label"] == "学长学姐风"
    assert data.profiles["S01"]["landmark"] == "紫金港校区东门对面"
    assert data.profiles["S02"]["voice"] != "senior" or data.profiles["S02"]["landmark"] != data.profiles["S01"]["landmark"]


def test_invalid_override_voice_raises(data):
    from agent.recommend.profiles import build_profiles
    with pytest.raises(ValueError, match="senior"):
        build_profiles(data.stores, data.signals, data.angles, {"S04": {"voice": "senior"}})   # office store
    with pytest.raises(ValueError):
        build_profiles(data.stores, data.signals, data.angles, {"S01": {"voice": "no_such_voice"}})


# ---------------------------------------------------------------- POI cache beats the fixture
def test_poi_cache_overrides_fixture_and_can_flip_dominant_segment(tmp_path, data):
    inputs = tmp_path / "inputs"
    shutil.copytree(INPUTS, inputs)
    (inputs / "poi_cache").mkdir(exist_ok=True)
    # S07 is residential (family) by fixture; a cache with a university next door flips it to student.
    (inputs / "poi_cache" / "S07.json").write_text(json.dumps({
        "store_id": "S07", "source": "amap_v3_place_around", "pois": [
            {"name": "测试大学", "typecode": "141201", "distance_m": 200},
            {"name": "测试小区", "typecode": "120302", "distance_m": 900},
            {"name": "无关类型", "typecode": "999999", "distance_m": 100},     # unknown typecode is ignored
        ]}, ensure_ascii=False), encoding="utf-8")
    d2 = load_store_data(inputs, GENERATED)
    assert data.signals["S07"]["dominant"] == "family" and data.signals["S07"]["poi_source"] == "fixture"
    assert d2.signals["S07"]["dominant"] == "student" and d2.signals["S07"]["poi_source"] == "amap"
    assert d2.signals["S07"]["top_category_example"] == "测试大学"
    # other stores untouched
    assert d2.signals["S01"] == data.signals["S01"]
    # the card reflects it: POI reason is now real data (no 模拟 badge) and the segment is student
    c = cards_for("S07", TODAY, d2)[0]
    assert c.segment == "student" and c.reasons[0].source == "poi" and c.reasons[0].is_demo is False


def test_segment_weights_math(data):
    import math
    cfg = data.seg_cfg
    pois = [{"name": "U", "category": "university", "distance_m": 500},
            {"name": "O", "category": "office", "distance_m": 500},
            {"name": "M", "category": "mall", "distance_m": 5000}]   # beyond radius → ignored
    sig = segment_weights(pois, cfg)
    u, o = 5.0 * math.exp(-1), 1.0 * math.exp(-1)
    assert sig["weights"]["student"] == round(u / (u + o), 3)
    assert sig["weights"]["shopper"] == 0.0 and sig["dominant"] == "student"
    assert sum(sig["weights"].values()) == pytest.approx(1.0, abs=0.002)


# ---------------------------------------------------------------- card → task
def test_card_to_task_fills_the_intake_fields(data):
    card = default_card("S01", TODAY, data)
    t = card_to_task(card)
    assert isinstance(t, Task)
    assert t.model_id == card.model_id and t.platform == "moments" and t.scenario == "campus_daily"
    assert t.audience and t.raw_text and t.source == "card" and t.card_id == card.card_id
    assert (t.hook, t.voice, t.landmark, t.nickname) == (card.hook.id, "senior", "紫金港校区东门对面", card.nickname)
    assert t.angle == card.angle and t.calendar_theme == "购物节前做功课"
    assert t.promo is None and t.question is None and t.staff is None
    # the manual-flow defaults are untouched
    assert Task(raw_text="x").source == "manual" and Task(raw_text="x").voice is None


def test_card_to_task_carries_promo_and_question(data):
    promo = next(c for c in cards_for("S02", TODAY, data) if c.slot == "promo")
    t = card_to_task(promo)
    assert t.promo["campaign_id"] == "DEMO-1111-PRE" and t.promo["price_info"]["value"] == "4999"
    q = next(c for c in cards_for("S01", TODAY, data) if c.slot == "customer_question")
    t = card_to_task(q)
    assert t.question["count"] >= 1 and t.hook == "customer" and t.angle == q.question.text


def test_staff_context_overrides_voice_and_nickname(data):
    card = default_card("S01", TODAY, data)
    staff = StaffContext(staff_id="u1", display_name="小张", role="staff", voice="techie", nickname="小张")
    t = card_to_task(card, staff)
    assert (t.voice, t.nickname) == ("techie", "小张") and t.staff["staff_id"] == "u1"
    # no override → card values kept
    t2 = card_to_task(card, StaffContext(staff_id="u2", display_name="店长", role="manager"))
    assert (t2.voice, t2.nickname) == ("senior", card.nickname)


def test_invalid_staff_voice_raises(data):
    office_card = default_card("S04", TODAY, data)          # office segment: 学长学姐风 not allowed
    with pytest.raises(ValueError, match="senior"):
        card_to_task(office_card, StaffContext(staff_id="u3", display_name="x", voice="senior"))
    with pytest.raises(ValueError):
        card_to_task(office_card, StaffContext(staff_id="u3", display_name="x", voice="no_such_voice"))


def test_new_release_card_maps_to_new_launch_scenario(data):
    card = next(c for c in cards_for("S01", TODAY, data) if c.slot == "new_release")
    assert card.scenario == "new_launch" and card_to_task(card).scenario == "new_launch"


# ---------------------------------------------------------------- scenario (decision A): calendar-aware
def test_scenario_is_on_the_card_and_never_back_to_school_outside_the_window(data):
    s01 = default_card("S01", TODAY, data)
    assert s01.scenario == "campus_daily" and s01.scenario != "back_to_school"
    assert default_card("S04", TODAY, data).scenario == "office"
    # 双十一 within 30 days of Oct 21 → shopper and family stores get holiday
    assert default_card("S10", TODAY, data).scenario == "holiday"
    assert default_card("S08", TODAY, data).scenario == "holiday"


def test_scenario_by_date(data):
    from agent.recommend.slots import scenario_for
    cal = data.calendar
    inside = dt.date(2027, 2, 20)          # 开学季 2027-02-15 .. 03-10
    assert scenario_for("potential", "student", cal, inside) == "back_to_school"
    assert scenario_for("potential", "family", cal, inside) == "back_to_school"
    assert scenario_for("new_release", "student", cal, inside) == "new_launch"
    quiet = dt.date(2026, 7, 15)           # no event within 30 days
    assert scenario_for("potential", "student", cal, quiet) == "campus_daily"
    assert scenario_for("potential", "shopper", cal, quiet) == "store_visit"
    assert scenario_for("potential", "family", cal, quiet) == "family_upgrade"
    assert scenario_for("potential", "office", cal, dt.date(2026, 11, 5)) == "office"   # office never holiday
    # a campus store in 开学季 really yields back_to_school through cards_for
    card = default_card("S01", inside, data)
    assert card.scenario == "back_to_school"


def test_card_with_unknown_scenario_is_rejected(data):
    bad = dataclasses.replace(default_card("S01", TODAY, data), scenario="no_such_key")
    with pytest.raises(ValueError, match="scenario"):
        card_to_task(bad)


# ---------------------------------------------------------------- cache + HQ fact-card override (decision E)
def test_load_store_data_is_cached_process_wide():
    reload()
    a, b = load_store_data(), load_store_data()
    assert a is b
    assert load_store_data(use_cache=False) is not a


def test_set_fact_card_status_unlocks_new_release_and_reload_restores():
    reload()
    locked = next(c for c in cards_for("S01", TODAY) if c.slot == "new_release")
    assert locked.locked and locked.locked_reason == "fact_card_draft"
    set_fact_card_status("matebook-fold-ultimate-design", "verified")
    unlocked = next(c for c in cards_for("S01", TODAY) if c.slot == "new_release")
    assert not unlocked.locked and unlocked.locked_reason is None
    # the demo launch_date only schedules the card: the KB does not state it, so no date is shown
    assert unlocked.reasons[1].text == "总部新品推送（演示流程）" and unlocked.reasons[1].is_demo
    # within ±7 days of launch (Oct 23) the verified release becomes every store's 今日一条
    for sid in ("S01", "S04", "S08"):
        assert default_card(sid, dt.date(2026, 10, 23)).slot == "new_release"
    # the file on disk was never touched
    import csv
    rows = list(csv.DictReader((INPUTS / "models.csv").open(encoding="utf-8")))
    assert next(r for r in rows if r["model_id"] == "matebook-fold-ultimate-design")["fact_card_status"] == "draft"
    with pytest.raises(ValueError):
        set_fact_card_status("matebook-fold-ultimate-design", "published")
    reload()
    assert next(c for c in cards_for("S01", TODAY) if c.slot == "new_release").locked


# ---------------------------------------------------------------- pipeline entry
def _demo_card(card: RecommendationCard) -> RecommendationCard:
    """The fake catalog only knows the synthetic DemoBook models; product facts stay synthetic."""
    return dataclasses.replace(card, model_id="demobook-14", display_name="DemoBook 14（演示版）")


def test_run_from_card_end_to_end_on_fakes(data):
    deps = Deps.fake()
    card = _demo_card(default_card("S01", TODAY, data))
    lines = []
    r = run_from_card(card, deps, on_progress=lambda s, m: lines.append((s, m)))
    assert isinstance(r, RunResult)
    assert r.task.source == "card" and r.task.model_id == "demobook-14"
    assert r.post.platform == "moments" and r.task.scenario == "campus_daily"
    assert r.task.voice == "senior" and r.task.landmark == "紫金港校区东门对面"
    assert "intake" not in [s for s, _ in lines]          # no intake stage ran
    assert set(r.timings) >= {"retrieval", "ledger", "analyze", "reconcile", "plan", "write", "check", "total"}
    assert r.report.passed


def test_run_from_card_with_staff_override(data):
    deps = Deps.fake()
    card = _demo_card(default_card("S01", TODAY, data))
    r = run_from_card(card, deps, staff=StaffContext("u1", "小张", voice="manager", nickname="小张"))
    assert isinstance(r, RunResult) and r.task.voice == "manager" and r.task.nickname == "小张"
    with pytest.raises(ValueError):
        run_from_card(card, deps, staff=StaffContext("u1", "x", voice="no_such_voice"))


def test_locked_card_returns_without_calling_llm_or_ima(data):
    locked = next(c for c in cards_for("S01", TODAY, data) if c.slot == "new_release")
    assert locked.locked and locked.locked_reason == "fact_card_draft"

    def boom(*a, **k):
        raise AssertionError("locked card must not reach this stage")

    deps = Deps.fake()
    for fld in ("get_bundle", "build_ledger", "plan_images", "parse_task", "analyze", "reconcile",
                "write_post", "rewrite", "run_checks"):
        setattr(deps, fld, boom)
    deps.llm = type("NoLLM", (), {"chat_json": boom, "chat_text": boom})()
    res = run_from_card(locked, deps)
    assert isinstance(res, LockedResult)
    assert res.message == "新品资料待总部确认，暂不可生成" and res.reason == "fact_card_draft"
    assert res.card is locked
