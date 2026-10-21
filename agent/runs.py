"""Real-run log (Phase 4, Task 4): append the full result of every real card/baseline run.

    runs/<card date>/<timestamp>-<store>-<slot>.json

The directory is gitignored. Fake/demo runs are never logged. `latest_run(card_id)` lets the UI show
the most recent real output if the API fails during recording. Logs are real outputs; never hand-edit.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

from agent.llm import temperatures

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"

__all__ = ["RUNS_DIR", "log_run", "latest_run"]


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
