"""
In-process per-store new-product approvals.

An HQ confirmation now belongs to a store: when a manager confirms a new product for their store, only
that store's staff can generate it. `agent.recommend.slots` consults this module while building the
cards; `agent.recommend.store_data` clears it on 重置演示 / reload. It imports nothing (slots imports it,
store_data imports slots) and keeps no I/O of its own — `agent.accounts` persists the same rows.
"""
from __future__ import annotations

_APPROVALS: dict[str, set[str]] = {}


def set_approval(model_id: str, store_id: str, approved: bool = True) -> None:
    if not model_id or not store_id:
        return
    if approved:
        _APPROVALS.setdefault(model_id, set()).add(store_id)
    else:
        stores = _APPROVALS.get(model_id)
        if stores is not None:
            stores.discard(store_id)
            if not stores:
                _APPROVALS.pop(model_id, None)


def is_approved(model_id: str, store_id: str) -> bool:
    return bool(store_id) and store_id in _APPROVALS.get(model_id, ())


def stores_for(model_id: str) -> list[str]:
    return sorted(_APPROVALS.get(model_id, ()))


def snapshot() -> dict[str, list[str]]:
    return {model_id: sorted(stores) for model_id, stores in _APPROVALS.items() if stores}


def clear() -> None:
    _APPROVALS.clear()
