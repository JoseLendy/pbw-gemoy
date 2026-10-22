"""Small shared helpers: paths, deterministic hashing, CSV/JSON io, dates."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEMO = ROOT / "data" / "demo"
INPUTS = DEMO / "inputs"
GENERATED = DEMO / "generated"

SEGMENTS: tuple[str, ...] = ("student", "office", "family", "shopper")


def stable_hash(*parts: str) -> int:
    """Deterministic across runs and machines (Python's hash() is salted - never use it)."""
    return int(hashlib.md5("|".join(parts).encode("utf-8")).hexdigest(), 16)


def parse_date(s: str | dt.date) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(s)


def load_csv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(path: Path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def write_csv(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
