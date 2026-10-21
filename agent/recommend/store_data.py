"""
Load the demo data kit and compute recommendation cards LIVE (plan §3, §10).

    data = load_store_data()                       # inputs/ + generated/ (no network, no LLM)
    cards = cards_for("S01", "2026-10-21")          # list[RecommendationCard]

With the committed generated/ files and seed 42 this equals generated/today_cards.json byte for byte
in content; the UI can swap from the file to this function without changing anything else.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent.recommend import poi, sales, slots
from agent.recommend.common import GENERATED, INPUTS, load_csv, load_json, parse_date
from agent.recommend.profiles import build_profiles
from agent.schemas import RecommendationCard


@dataclass
class StoreData:
    """Everything the recommender reads, already parsed. Build with load_store_data()."""
    stores: list[dict]
    models: list[dict]
    seg_cfg: dict
    promos: list[dict]
    calendar: list[dict]
    quota: dict
    angles: dict
    pool: dict
    overrides: dict
    sales: list[dict]
    publish: list[dict]
    questions: list[dict]
    signals: dict = field(default_factory=dict)      # store_id -> segment weights (+ poi_source)
    profiles: dict = field(default_factory=dict)     # store_id -> landmark / voice / nickname
    inputs_dir: Path = INPUTS
    generated_dir: Path = GENERATED

    def store(self, store_id: str) -> dict:
        return next(s for s in self.stores if s["store_id"] == store_id)

    def model(self, model_id: str) -> dict:
        return next(m for m in self.models if m["model_id"] == model_id)


# ---------------------------------------------------------------- process-wide cache + HQ overrides
_CACHE: dict[tuple[str, str], StoreData] = {}
_FACT_CARD_STATUS: dict[str, str] = {}      # model_id -> status set by HQ in this process; never written to disk
FACT_CARD_STATUSES = ("draft", "verified")


def set_fact_card_status(model_id: str, status: str) -> None:
    """HQ "确认发布" (plan §7): in-memory override of models.csv's fact_card_status for this process.
    Invalidates the cache so the next cards_for() reflects it. Never writes a file."""
    if status not in FACT_CARD_STATUSES:
        raise ValueError(f"status must be one of {FACT_CARD_STATUSES}, got {status!r}")
    _FACT_CARD_STATUS[model_id] = status
    _CACHE.clear()


def fact_card_overrides() -> dict[str, str]:
    return dict(_FACT_CARD_STATUS)


def reload() -> None:
    """Drop the cache and every in-memory override; the next load reads the files again."""
    _FACT_CARD_STATUS.clear()
    _CACHE.clear()


def load_store_data(inputs_dir: Path = INPUTS, generated_dir: Path = GENERATED, use_cache: bool = True) -> StoreData:
    """Reads inputs/ (templates) and generated/ (sales + logs). POI: real cache first, else the fixture.
    Cached per (inputs_dir, generated_dir) for the process; HQ fact-card overrides are applied on load."""
    key = (str(Path(inputs_dir).resolve()), str(Path(generated_dir).resolve()))
    if use_cache and key in _CACHE:
        return _CACHE[key]
    data = _read_store_data(Path(inputs_dir), Path(generated_dir))
    for m in data.models:
        if m["model_id"] in _FACT_CARD_STATUS:
            m["fact_card_status"] = _FACT_CARD_STATUS[m["model_id"]]
    if use_cache:
        _CACHE[key] = data
    return data


def _read_store_data(inputs_dir: Path, generated_dir: Path) -> StoreData:
    stores = load_csv(inputs_dir / "stores.csv")
    seg_cfg = load_json(inputs_dir / "segments.json")
    overrides = {k: v for k, v in load_json(inputs_dir / "store_profile_overrides.json").items()
                 if not k.startswith("_")}
    data = StoreData(
        stores=stores, models=load_csv(inputs_dir / "models.csv"), seg_cfg=seg_cfg,
        promos=load_json(inputs_dir / "promotions.json"), calendar=load_json(inputs_dir / "calendar.json"),
        quota=load_json(inputs_dir / "platform_quota.json"), angles=load_json(inputs_dir / "angles.json"),
        pool=load_json(inputs_dir / "question_pool.json"), overrides=overrides,
        sales=load_csv(generated_dir / "sales_weekly.csv"),
        publish=load_csv(generated_dir / "publish_log.csv"),
        questions=load_json(generated_dir / "customer_questions.json"),
        inputs_dir=inputs_dir, generated_dir=generated_dir,
    )
    data.signals = poi.store_signals(stores, seg_cfg, inputs_dir, generated_dir)
    data.profiles = build_profiles(stores, data.signals, data.angles, overrides)
    return data


def all_cards(data: StoreData, today: dt.date | str) -> dict[str, list[dict]]:
    """Plain card dicts for every store (same shape as generated/today_cards.json["cards"])."""
    today = parse_date(today)
    idx = sales.under_index(data.sales, data.signals, today)
    return slots.build_cards(data.stores, data.models, data.signals, idx, data.promos, data.calendar,
                             data.quota, data.angles, data.profiles, data.questions, data.publish,
                             data.seg_cfg, data.pool, today)


def cards_for(store_id: str, today: dt.date | str, data: Optional[StoreData] = None) -> list[RecommendationCard]:
    """Today's cards for one store, computed live. The default card ("今日一条") has is_default=True."""
    data = data or load_store_data()
    if store_id not in {s["store_id"] for s in data.stores}:
        raise KeyError(f"unknown store {store_id!r}")
    return [RecommendationCard.from_dict(c) for c in all_cards(data, today).get(store_id, [])]


def default_card(store_id: str, today: dt.date | str, data: Optional[StoreData] = None) -> Optional[RecommendationCard]:
    return next((c for c in cards_for(store_id, today, data) if c.is_default), None)
