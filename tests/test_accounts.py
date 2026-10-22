"""Accounts (SQLite) and store-scoped new-product approvals. Fakes/tmp_path only; never the real data/app.db."""
from __future__ import annotations

import sqlite3

from agent import accounts
from agent.recommend.store_data import cards_for, reload, set_store_approval

TODAY = "2026-10-21"
NEW_MODEL = "matebook-pro-s"
STORES = [{"store_id": "S01", "store_name": "一号店"}, {"store_id": "S02", "store_name": "二号店"}]


def _db(tmp_path):
    return tmp_path / "app.db"


# ---------------------------------------------------------------- accounts
def test_seed_demo_accounts_is_idempotent_and_authenticates(tmp_path):
    db = _db(tmp_path)
    assert accounts.seed_demo_accounts(STORES, password="pw-test", path=db) == 5   # 2 stores × 2 + dev
    assert accounts.seed_demo_accounts(STORES, password="pw-test", path=db) == 0   # never overwrites

    staff = accounts.authenticate("staff-s01", "pw-test", path=db)
    assert staff and staff["role"] == "staff" and staff["store_id"] == "S01"
    assert accounts.authenticate("MANAGER-S02", "pw-test", path=db)["role"] == "manager"
    assert accounts.authenticate("dev", "pw-test", path=db)["role"] == "developer"
    assert accounts.authenticate("staff-s01", "wrong", path=db) is None
    assert accounts.authenticate("nobody", "pw-test", path=db) is None


def test_accounts_are_listed_without_secrets_and_passwords_are_hashed(tmp_path):
    db = _db(tmp_path)
    accounts.seed_demo_accounts(STORES, password="pw-test", path=db)
    users = accounts.list_users(path=db)
    assert {u["username"] for u in users} == {"staff-s01", "manager-s01", "staff-s02", "manager-s02", "dev"}
    assert all("password_hash" not in u and "salt" not in u for u in users)

    with sqlite3.connect(db) as c:
        stored = c.execute("SELECT password_hash, salt FROM users WHERE username = 'staff-s01'").fetchone()
    assert stored and "pw-test" not in stored[0] and len(stored[0]) == 64


def test_demo_password_is_only_revealed_when_not_overridden(monkeypatch):
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    assert accounts.demo_password() == accounts.DEMO_PASSWORD_DEFAULT
    monkeypatch.setenv("DEMO_PASSWORD", "operator-secret")
    assert accounts.demo_password() == ""
    assert accounts.seed_password() == "operator-secret"


def test_role_must_be_known(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        accounts.create_user("x", "pw", "owner", path=_db(tmp_path))


# ---------------------------------------------------------------- approvals (persisted, per store)
def test_approvals_are_per_store_and_clearable(tmp_path):
    db = _db(tmp_path)
    accounts.approve_product(NEW_MODEL, "S01", "manager-s01", path=db)
    assert accounts.approved_stores(NEW_MODEL, path=db) == ["S01"]
    assert ("matebook-pro-s", "S01") in accounts.all_approvals(path=db)

    accounts.approve_product(NEW_MODEL, "S01", "manager-s01", path=db)   # upsert, no duplicate row
    assert accounts.approved_stores(NEW_MODEL, path=db) == ["S01"]

    accounts.approve_product(NEW_MODEL, "S02", "dev", path=db)
    assert accounts.approved_stores(NEW_MODEL, path=db) == ["S01", "S02"]
    assert accounts.clear_approvals(path=db) >= 1
    assert accounts.all_approvals(path=db) == []


def test_store_approval_unlocks_only_that_store():
    reload()
    before = {sid: next(c for c in cards_for(sid, TODAY) if c.slot == "new_release")
              for sid in ("S01", "S02")}
    assert before["S01"].locked and before["S02"].locked

    set_store_approval(NEW_MODEL, "S01")
    after = {sid: next(c for c in cards_for(sid, TODAY) if c.slot == "new_release")
             for sid in ("S01", "S02")}
    assert not after["S01"].locked and after["S01"].locked_reason is None
    assert after["S02"].locked and after["S02"].locked_reason == "fact_card_draft"

    reload()   # 重置演示 drops the in-memory approvals too
    restored = next(c for c in cards_for("S01", TODAY) if c.slot == "new_release")
    assert restored.locked
