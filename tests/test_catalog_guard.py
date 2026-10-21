"""Task 8: every model_id in data/demo/inputs/models.csv must resolve in agent/catalog.py.

Skips (with a reason) while the IDs are still MODEL_* placeholders; starts enforcing as soon as a teammate
maps a real model. Offline: reads the cached catalog index (.cache/, gitignored), never calls ima.
"""
from __future__ import annotations

import csv
import json
import pathlib
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
            cat = Catalog(json.loads(path.read_text("utf-8")))
            return {mid: m.canonical_name for mid, m in cat.models.items()}
    # Clean checkouts have no .cache/ (it is gitignored). This committed fixture is the demo catalog
    # snapshot, so the guard still enforces IDs and canonical names instead of skipping.
    fixture = pathlib.Path(__file__).resolve().parent / "fixtures" / "catalog_ids.json"
    if fixture.exists():
        return json.loads(fixture.read_text("utf-8"))
    return None


def test_demo_models_resolve_in_catalog():
    rows = _rows()
    mapped = [r for r in rows if not PLACEHOLDER.match(r["model_id"])]
    if not mapped:
        pytest.skip(f"models.csv still uses placeholder IDs ({', '.join(r['model_id'] for r in rows)}); "
                    "this guard enforces itself once WS-A maps real catalog model_ids")
    catalog = _catalog()
    if catalog is None:
        pytest.skip("no cached catalog index or committed catalog fixture")
    missing = [r["model_id"] for r in mapped if r["model_id"] not in catalog]
    assert not missing, f"models.csv model_ids not in the catalog: {missing}"
    wrong = [r["model_id"] for r in mapped if r["display_name"] != catalog[r["model_id"]]]
    assert not wrong, f"models.csv display_name does not match the catalog canonical name: {wrong}"


def test_why_columns_are_references_not_values():
    for row in _rows():
        for col in ("why_student", "why_office", "why_family", "why_shopper"):
            cell = row[col]
            assert "—" in cell and "P1-产品参数库/" in cell, (row["model_id"], col, cell)
            assert not any(ch in cell for ch in ('"', "“", "「", "」")), (row["model_id"], col, cell)


def test_no_placeholders_anywhere_under_data_demo():
    root = pathlib.Path(__file__).resolve().parents[1] / "data" / "demo"
    bad = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".csv", ".json", ".md", ".txt"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "<" in text or "MODEL_" in text:
            bad.append(str(p.relative_to(root)))
    assert bad == []


def test_placeholder_pattern():
    assert PLACEHOLDER.match("MODEL_A") and PLACEHOLDER.match("MODEL_N")
    assert not PLACEHOLDER.match("matebook-14-harmonyos")
