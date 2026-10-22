"""
Recommender core (WS-B, PROACTIVE_AGENT_PLAN §3 / §5).

Ported from scripts/gen_fake_data.py, which now imports these functions, so the demo data and
the app can never drift. Everything here is deterministic and offline: it reads data/demo/inputs/
and data/demo/generated/ and never calls ima, the LLM or the network.

    poi.py        POI → segment weights (real Amap cache first, else the generated fixture)
    sales.py      weekly windows, under-index vs peer stores
    scoring.py    fit + every threshold (single source of truth)
    explain.py    "为什么推这条" reason lines (templates, never the LLM)
    slots.py      the four daily slots + default card + hook/angle/voice assignment
    profiles.py   store voice profile (auto landmark / voice + store overrides)
    store_data.py loads everything and computes cards live: cards_for(store_id, date)
    to_task.py    RecommendationCard (+ optional StaffContext) → Task for the existing pipeline
"""
from agent.recommend.store_data import (  # noqa: F401
    StoreData, cards_for, default_card, load_store_data, reload, reset_demo_state, set_fact_card_status,
)
from agent.recommend.to_task import card_to_task  # noqa: F401
