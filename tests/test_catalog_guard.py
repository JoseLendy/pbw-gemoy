"""Task 8: every model_id in data/demo/inputs/models.csv must resolve in agent/catalog.py.

Skips (with a reason) while the IDs are still MODEL_* placeholders; starts enforcing as soon as a teammate
maps a real model. Offline: reads the cached catalog index (.cache/, gitignored), never calls ima.
"""
from __future__ import annotations

import csv
import json
import re

import pytest

from agent.recommend.common import INPUTS

PLACEHOLDER = re.compile(r"^MODEL_[A-Z0-9]+$")


def _rows() -> list[dict]:
    with (INPUTS / "models.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _catalog():
    from agent.catalog import INDEX_PATH, LOCAL_INDEX_PATH, Catalog
    for path in (INDEX_PATH, LOCAL_INDEX_PATH):
        if path.exists():
            return Catalog(json.loads(path.read_text("utf-8")))
    return None


def test_demo_models_resolve_in_catalog():
    rows = _rows()
    mapped = [r for r in rows if not PLACEHOLDER.match(r["model_id"])]
    if not mapped:
        pytest.skip(f"models.csv still uses placeholder IDs ({', '.join(r['model_id'] for r in rows)}); "
                    "this guard enforces itself once WS-A maps real catalog model_ids")
    cat = _catalog()
    if cat is None:
        pytest.skip("no cached catalog index in .cache/ (run scripts/build_index.py on a machine with KB access)")
    missing = [r["model_id"] for r in mapped if r["model_id"] not in cat.models]
    assert not missing, f"models.csv model_ids not in the catalog: {missing}"
    unfilled = [r["model_id"] for r in mapped if "<" in r["display_name"]]
    assert not unfilled, f"mapped models still have placeholder display names: {unfilled}"


def test_placeholder_pattern():
    assert PLACEHOLDER.match("MODEL_A") and PLACEHOLDER.match("MODEL_N")
    assert not PLACEHOLDER.match("matebook-14-harmonyos")
