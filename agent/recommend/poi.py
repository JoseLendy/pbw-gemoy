"""
Location → audience (plan §4.1).

raw[s]  = Σ over POIs within radius_m in segment s: importance × exp(-distance / decay_m)
w[s]    = raw[s] / Σ raw            (sums to 1)
dominant_segment = argmax w[s]

POI wins over the label: stores.csv's intended_type is never read here.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from agent.recommend.common import GENERATED, INPUTS, load_json, write_json

FixtureFactory = Callable[[dict], list[dict]]   # store row -> fake POI list (gen_fake_data.fake_pois)


def category_of(typecode: str, seg_cfg: dict) -> Optional[str]:
    """Amap typecode (possibly several joined by '|') → category key in segments.json, or None."""
    for cat, c in seg_cfg["categories"].items():
        for code in typecode.split("|"):
            if code in c["typecodes"]:
                return cat
    return None


def cache_path(store_id: str, inputs_dir: Path = INPUTS) -> Path:
    return Path(inputs_dir) / "poi_cache" / f"{store_id}.json"


def fixture_path(store_id: str, generated_dir: Path = GENERATED) -> Path:
    return Path(generated_dir) / "poi_fixtures" / f"{store_id}.json"


def load_pois(store: dict, seg_cfg: dict, inputs_dir: Path = INPUTS, generated_dir: Path = GENERATED,
              make_fixture: FixtureFactory | None = None) -> tuple[list[dict], str]:
    """(pois, source). A real Amap cache (scripts/fetch_poi.py) always wins → "amap".
    Otherwise the generated fixture → "fixture": the generator passes `make_fixture` to build and
    write it; the app leaves it None and reads the file the generator wrote."""
    sid = store["store_id"]
    cache = cache_path(sid, inputs_dir)
    if cache.exists():
        raw = load_json(cache)
        pois = []
        for p in raw["pois"]:
            cat = category_of(p["typecode"], seg_cfg)
            if cat:
                pois.append({**p, "category": cat, "is_demo": False})
        return pois, "amap"
    fixture = fixture_path(sid, generated_dir)
    if make_fixture is not None:
        pois = make_fixture(store)
        write_json(fixture, {"store_id": sid, "pois": pois})
        return pois, "fixture"
    if fixture.exists():
        return load_json(fixture)["pois"], "fixture"
    raise FileNotFoundError(f"no POI data for {sid}: neither {cache} nor {fixture} exists "
                            f"(run scripts/gen_fake_data.py)")


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


def store_signals(stores: list[dict], seg_cfg: dict, inputs_dir: Path = INPUTS,
                  generated_dir: Path = GENERATED, make_fixture: FixtureFactory | None = None) -> dict:
    """{store_id: segment_weights(...) + poi_source} for every store, in stores.csv order."""
    signals = {}
    for st in stores:
        pois, src = load_pois(st, seg_cfg, inputs_dir, generated_dir, make_fixture)
        sig = segment_weights(pois, seg_cfg)
        sig["poi_source"] = src
        signals[st["store_id"]] = sig
    return signals
