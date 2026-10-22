"""Real-run log (Phase 4, Task 4): append the full result of every real card/baseline run.

    runs/<card date>/<timestamp>-<store>-<slot>.json
    runs/<card date>/prepared/<store>.json          # Phase 5: the morning's prepared post per store

The directory is gitignored. Fake/demo runs are never logged. `latest_run(card_id)` lets the UI show
the most recent real output if the API fails during recording. Logs are real outputs; never hand-edit.

Prepared posts (pipeline.prepare_today) are real run logs too: reset_demo_state() never touches them;
only clear_prepared(date) deletes them. A --fake rehearsal writes to REHEARSAL_DIR, never to RUNS_DIR.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any, Optional

from agent.llm import temperatures

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
REHEARSAL_DIR = RUNS_DIR / "_rehearsal"
PREPARED = "prepared"

__all__ = ["RUNS_DIR", "REHEARSAL_DIR", "log_run", "log_batch", "latest_run",
           "log_prepared", "prepared_post", "clear_prepared", "log_version", "stored_version", "log_stored",
           "stored"]


def _payload(result: Any) -> Any:
    if hasattr(result, "to_dict"):
        try:
            return result.to_dict()
        except Exception:  # noqa: BLE001
            pass
    if dataclasses.is_dataclass(result):
        return dataclasses.asdict(result)
    return {"repr": repr(result)}


def log_run(card, result, staff=None, kind: str = "run_from_card",
            runs_dir: Path | None = None) -> Path:
    """Append one JSON record. Callers must only invoke this for real (non-fake) results."""
    out_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    now = dt.datetime.now(dt.timezone.utc)
    day = getattr(card, "date", None) or now.date().isoformat()
    folder = out_dir / str(day)
    folder.mkdir(parents=True, exist_ok=True)
    store = getattr(card, "store_id", "store")
    slot = getattr(card, "slot", "slot")
    name = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{store}-{slot}.json"
    task = getattr(result, "task", None)
    model = getattr(result, "model", None)
    post = getattr(result, "post", None)
    payload = {
        "card_id": getattr(card, "card_id", None),
        "store_id": store,
        "store_name": getattr(card, "store_name", None),
        "staff": staff.to_dict() if hasattr(staff, "to_dict") else staff,
        "scenario": getattr(task, "scenario", getattr(card, "scenario", None)),
        "model": getattr(model, "model_id", getattr(card, "model_id", None)),
        "platform": getattr(post, "platform", getattr(card, "platform", None)),
        "temperatures": temperatures(),
        "kind": kind,
        "timestamp": now.isoformat(timespec="seconds"),
        "result": _payload(result),
    }
    path = folder / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def log_batch(cards, batch, runs_dir: Path | None = None) -> Path:
    """One record per real generate_batch call. Individual run results are already logged by
    run_from_card; this record keeps the 8E similarity report and the store set."""
    out_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    now = dt.datetime.now(dt.timezone.utc)
    cards = list(cards)
    day = getattr(cards[0], "date", None) if cards else None
    day = day or now.date().isoformat()
    folder = out_dir / str(day)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-batch.json"
    payload = {
        "kind": "generate_batch",
        "date": str(day),
        "store_ids": [getattr(c, "store_id", None) for c in cards],
        "similarity": [dataclasses.asdict(p) if dataclasses.is_dataclass(p) else p
                       for p in getattr(batch, "similarity", [])],
        "regenerated": list(getattr(batch, "regenerated", [])),
        "timestamp": now.isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def latest_run(card_id: str, runs_dir: Path | None = None) -> Optional[dict]:
    """Newest logged record for a card id, or None. Reads JSON; never touches the network."""
    root = Path(runs_dir) if runs_dir else RUNS_DIR
    if not root.exists():
        return None
    best = None
    for path in root.glob("*/*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("card_id") != card_id:
            continue
        key = (data.get("timestamp") or "", path.stat().st_mtime)
        if best is None or key > best[0]:
            best = (key, data)
    return best[1] if best else None


# ---------------------------------------------------------------- prepared posts (Phase 5)
def _prepared_dir(day, runs_dir: Path | None) -> Path:
    return (Path(runs_dir) if runs_dir else RUNS_DIR) / str(day) / PREPARED


def _prepared_payload(card, result, seconds, similarity, regenerated, dev_mode) -> dict:
    report = getattr(result, "report", None)
    payload = {
        "kind": "prepared",
        "card_id": card.card_id,
        "store_id": card.store_id,
        "store_name": card.store_name,
        "date": str(card.date),
        "slot": card.slot,
        "model": card.model_id,
        "card": card.to_dict(),
        "status": type(result).__name__,
        "passed": bool(report.passed) if report is not None else False,
        "rewrites": getattr(result, "loops", None),
        "seconds": seconds,
        "similarity": similarity or [],
        "regenerated": regenerated,
        "dev_mode": dev_mode,
        "temperatures": temperatures(),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "result": _payload(result) if not isinstance(result, Exception) else {"error": repr(result)},
    }
    return payload


def log_prepared(card, result, *, seconds: float | None = None, similarity: list | None = None,
                 regenerated: bool = False, dev_mode: bool = False, runs_dir: Path | None = None) -> Path:
    """Write (overwrite) the prepared post for the card's store and date (the 朋友圈 version of the default
    card; every other version goes through log_version)."""
    folder = _prepared_dir(card.date, runs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    payload = _prepared_payload(card, result, seconds, similarity, regenerated, dev_mode)
    path = folder / f"{card.store_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# ---------------------------------------------------------------- stored versions + demo sets (precompute)
# runs/<date>/prepared/versions/<card_id>__<platform>.json   one card on one platform (any slot)
# runs/<date>/prepared/compare/<model_id>__<platform>.json   三店对比 set (results + similarity pairs)
# runs/<date>/prepared/baseline/<card_id>.json              对照组 pair (baseline + ours)
# Written by prepare_today / prepare_demo; read by the UI before it generates anything. Never deleted by
# reset_demo_state; clear_prepared(date) removes them with the rest of the date's prepared posts.
def _platform_key(platform: str) -> str:
    from agent.recommend.to_task import platform_key
    return platform_key(platform)


def _stored_path(day, kind: str, key: str, runs_dir: Path | None) -> Path:
    return _prepared_dir(day, runs_dir) / kind / f"{re.sub(r'[^0-9A-Za-z_.-]+', '_', key)}.json"


def log_stored(day, kind: str, key: str, payload: dict, runs_dir: Path | None = None) -> Path:
    path = _stored_path(day, kind, key, runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "kind": kind if kind != "versions" else "version",
               "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def stored(day, kind: str, key: str, runs_dir: Path | None = None) -> Optional[dict]:
    path = _stored_path(day, kind, key, runs_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def log_version(card, result, *, seconds: float | None = None, similarity: list | None = None,
                regenerated: bool = False, dev_mode: bool = False, runs_dir: Path | None = None) -> Path:
    """One card on one platform (card.platform), stored like a prepared post."""
    payload = _prepared_payload(card, result, seconds, similarity, regenerated, dev_mode)
    payload["platform"] = card.platform
    return log_stored(card.date, "versions", f"{card.card_id}__{_platform_key(card.platform)}", payload, runs_dir)


def stored_version(card, platform: str | None = None, runs_dir: Path | None = None) -> Optional[dict]:
    """The stored version of this card on `platform` (default: card.platform), or None. A record made for
    another model under the same card id (e.g. the card changed after HQ verified a release) is ignored."""
    platform = platform or card.platform
    data = stored(card.date, "versions", f"{card.card_id}__{_platform_key(platform)}", runs_dir)
    if data is None or data.get("model") != card.model_id or data.get("card_id") != card.card_id:
        return None
    return data


def prepared_post(store_id: str, date, card_id: str | None = None, model_id: str | None = None,
                  runs_dir: Path | None = None) -> Optional[dict]:
    """The stored prepared post for the store on that date, or None.

    If card_id / model_id are not given, they are taken from the store's CURRENT default card, so a
    prepared post for a card that is no longer the default (e.g. HQ verified a new release after the
    morning run) is not returned; the UI then generates live."""
    path = _prepared_dir(date, runs_dir) / f"{store_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if card_id is None and model_id is None:
        from agent.recommend.store_data import default_card
        card = default_card(store_id, date)
        if card is None:
            return None
        card_id, model_id = card.card_id, card.model_id
    if card_id is not None and data.get("card_id") != card_id:
        return None
    if model_id is not None and data.get("model") != model_id:
        return None
    return data


def clear_prepared(date, runs_dir: Path | None = None) -> int:
    """Delete the prepared posts of one date (explicit; reset_demo_state never does this). Returns count."""
    folder = _prepared_dir(date, runs_dir)
    if not folder.exists():
        return 0
    n = len(list(folder.rglob("*.json")))
    shutil.rmtree(folder)
    return n
