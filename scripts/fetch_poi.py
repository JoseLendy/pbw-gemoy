#!/usr/bin/env python3
"""
Optional: replace fake POI fixtures with REAL Amap (高德) nearby-search results.

    export AMAP_KEY=...            # Web服务 key from console.amap.com - never commit it
    python scripts/fetch_poi.py            # all stores
    python scripts/fetch_poi.py S01 S04    # some stores

Writes data/demo/inputs/poi_cache/<store_id>.json. gen_fake_data.py automatically
prefers these files over fake fixtures; re-run it afterwards.

Uses Amap Web Service v3: /v3/geocode/geo and /v3/place/around.
Standard library only. NOTE: written without a key to test against - run it once on
one store first and check the output file before running all 12.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "data" / "demo" / "inputs"
API = "https://restapi.amap.com/v3"
MAX_PAGES = 4          # 25 POIs per page
SLEEP_S = 0.35         # stay under the free-tier QPS limit


def get(path: str, **params) -> dict:
    params["key"] = os.environ["AMAP_KEY"]
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    time.sleep(SLEEP_S)
    if data.get("status") != "1":
        # never print the URL: it contains the key
        raise RuntimeError(f"Amap error on {path}: {data.get('info')} ({data.get('infocode')})")
    return data


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> int:
    lng1, lat1, lng2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return round(2 * 6371000 * math.asin(math.sqrt(h)))


def fetch_store(store: dict, typecodes: list[str], radius: int) -> dict:
    if store.get("lat") and store.get("lng"):
        center = (float(store["lng"]), float(store["lat"]))
    else:
        geo = get("geocode/geo", address=store["address"], city="杭州")
        if not geo.get("geocodes"):
            raise RuntimeError(f"{store['store_id']}: address not found, edit stores.csv address")
        center = tuple(map(float, geo["geocodes"][0]["location"].split(",")))
    pois, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        res = get("place/around", location=f"{center[0]},{center[1]}", types="|".join(typecodes),
                  radius=radius, offset=25, page=page, extensions="base", sortrule="distance")
        batch = res.get("pois", [])
        for p in batch:
            if p.get("id") in seen:
                continue
            seen.add(p.get("id"))
            loc = tuple(map(float, p["location"].split(",")))
            dist = p.get("distance")
            pois.append({"name": p["name"], "typecode": p["typecode"],
                         "distance_m": int(float(dist)) if dist not in (None, "", []) else haversine_m(center, loc),
                         "location": p["location"]})
        if len(batch) < 25:
            break
    return {"store_id": store["store_id"], "lng": center[0], "lat": center[1],
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"), "source": "amap_v3_place_around",
            "pois": pois}


def main():
    if not os.environ.get("AMAP_KEY"):
        sys.exit("Set AMAP_KEY first (Amap Web服务 key). The demo also works without it, using fake fixtures.")
    seg = json.load((INPUTS / "segments.json").open(encoding="utf-8"))
    typecodes = sorted({c for cat in seg["categories"].values() for c in cat["typecodes"]})
    with (INPUTS / "stores.csv").open(encoding="utf-8") as f:
        stores = list(csv.DictReader(f))
    wanted = set(sys.argv[1:])
    (INPUTS / "poi_cache").mkdir(exist_ok=True)
    for st in stores:
        if wanted and st["store_id"] not in wanted:
            continue
        out = fetch_store(st, typecodes, seg["radius_m"])
        path = INPUTS / "poi_cache" / f"{st['store_id']}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{st['store_id']} {st['store_name']}: {len(out['pois'])} POIs -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
