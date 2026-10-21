"""
Per-product fact cache (Phase 5, L2; plan §7 "HQ verifies once, stores generate many").

Retrieval + ledger depend only on the model (and the KB), never on the store, so one (bundle, ledger) per
(model_id, date) is reused by every store's run: prepare_today, generate_batch, eval and live 重新生成.

    get_facts(deps, model_id, day) -> (bundle, ledger)
    clear_fact_cache(day=None)     -> number of entries dropped (memory + disk)

- Real deps: one process-wide cache, plus runs/cache/<day>/<model_id>.pkl (gitignored; FACT_CACHE_DISK=0
  turns the disk copy off). Pickles are our own objects written by this module; nothing else is loaded.
- Fake deps (tests): the cache lives on the Deps object, so tests that swap fake ledgers never share entries.
- Misses are filled one at a time (one lock): the KB client and the ledger disk cache stay single-threaded,
  and two stores of the same model in a parallel batch fetch it once.
- reset_demo_state() does not touch this cache. A card's lock (fact-card status) is checked before any of it.
"""
from __future__ import annotations

import copy
import logging
import os
import pickle
import shutil
import threading
from pathlib import Path

log = logging.getLogger("agent.fact_cache")

_REAL: dict[tuple[str, str], tuple] = {}
_LOCK = threading.RLock()


def disk_dir() -> Path:
    from agent.runs import RUNS_DIR
    return RUNS_DIR / "cache"


def _store(deps) -> dict:
    if getattr(deps, "is_dev_mode", True):
        cache = getattr(deps, "_fact_cache", None)
        if cache is None:
            cache = {}
            deps._fact_cache = cache
        return cache
    return _REAL


def _disk_on(deps) -> bool:
    return not getattr(deps, "is_dev_mode", True) and os.getenv("FACT_CACHE_DISK", "1") != "0"


def _path(model_id: str, day: str) -> Path:
    return disk_dir() / str(day) / f"{model_id}.pkl"


def get_facts(deps, model_id: str, day: str):
    """(bundle, ledger) for the model on that day; built once, then copied out of the cache."""
    key = (model_id, str(day))
    cache = _store(deps)
    with _LOCK:
        entry = cache.get(key)
        if entry is None and _disk_on(deps) and _path(*key).exists():
            try:
                entry = pickle.loads(_path(*key).read_bytes())
                cache[key] = entry
            except Exception as e:  # noqa: BLE001 - a bad cache file is rebuilt, never fatal
                log.warning("fact cache file for %s unreadable (%s); rebuilding", model_id, type(e).__name__)
                entry = None
        if entry is None:
            bundle = deps.get_bundle(model_id, deps.catalog)
            ledger = deps.build_ledger(bundle, deps.llm)
            entry = (bundle, ledger)
            cache[key] = entry
            if _disk_on(deps):
                try:
                    _path(*key).parent.mkdir(parents=True, exist_ok=True)
                    _path(*key).write_bytes(pickle.dumps(entry))
                except Exception as e:  # noqa: BLE001
                    log.warning("fact cache write failed for %s: %s", model_id, e)
    return copy.deepcopy(entry[0]), copy.deepcopy(entry[1])


def clear_fact_cache(day: str | None = None) -> int:
    """Drop cached facts (all days, or one day) from memory and disk. Fake-deps caches die with their Deps."""
    with _LOCK:
        keys = [k for k in _REAL if day is None or k[1] == str(day)]
        for k in keys:
            del _REAL[k]
        root = disk_dir()
        target = root if day is None else root / str(day)
        n_disk = len(list(target.rglob("*.pkl"))) if target.exists() else 0
        if target.exists():
            shutil.rmtree(target)
    return max(len(keys), n_disk)


__all__ = ["get_facts", "clear_fact_cache", "disk_dir"]
