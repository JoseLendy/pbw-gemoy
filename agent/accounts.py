"""
Accounts and HQ product approvals, stored in a small SQLite database (stdlib only).

    accounts.init_db()                       # create tables (idempotent)
    accounts.seed_demo_accounts(stores)      # staff-<store> / manager-<store> / dev, once
    accounts.authenticate("staff-s01", pw)   # -> user dict | None
    accounts.approve_product(model_id, store_id, by)

Passwords are stored as PBKDF2-SHA256 hashes with a per-user random salt; the plain password is never
written to disk or logged. The database lives at `data/app.db` (gitignored) unless APP_DB_PATH points
somewhere else. Demo accounts share one password: DEMO_PASSWORD from the environment, or the default
below when it is not set. `demo_password()` only reveals the default (for the demo login page), never
an operator-supplied value.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("staff", "manager", "developer")
ROLE_LABELS = {"staff": "店员", "manager": "店长", "developer": "开发者"}
ROLE_RANK = {"staff": 1, "manager": 2, "developer": 3}
DEMO_PASSWORD_DEFAULT = "hwpc2026"
_PBKDF2_ITERATIONS = 120_000


# ---------------------------------------------------------------- paths + schema
def db_path(path: Optional[str | Path] = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.getenv("APP_DB_PATH") or (ROOT / "data" / "app.db"))


def _connect(path: Optional[str | Path] = None) -> sqlite3.Connection:
    p = db_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Optional[str | Path] = None) -> None:
    """Create the two tables if they are not there yet. Safe to call on every operation."""
    with _connect(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('staff','manager','developer')),
                store_id TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS product_approvals (
                model_id TEXT NOT NULL,
                store_id TEXT NOT NULL,
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL,
                PRIMARY KEY (model_id, store_id)
            );
            """
        )


# ---------------------------------------------------------------- passwords + users
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt),
                               _PBKDF2_ITERATIONS).hex()


def create_user(username: str, password: str, role: str, store_id: str = "",
                display_name: str = "", path: Optional[str | Path] = None) -> bool:
    """Add one account. Returns False when the username already exists (never overwrites a password)."""
    username = (username or "").strip().lower()
    if not username or not password:
        raise ValueError("username and password are required")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    init_db(path)
    salt = os.urandom(16).hex()
    with _connect(path) as c:
        try:
            c.execute(
                "INSERT INTO users (username, password_hash, salt, role, store_id, display_name, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, _hash_password(password, salt), salt, role, store_id or "",
                 display_name or "", _now()),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def _row_to_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "store_id": row["store_id"] or "", "display_name": row["display_name"] or ""}


def authenticate(username: str, password: str, path: Optional[str | Path] = None) -> Optional[dict]:
    """The user dict for a correct username + password, else None. Constant-time hash comparison."""
    username = (username or "").strip().lower()
    if not username or not password:
        return None
    init_db(path)
    with _connect(path) as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    expected = row["password_hash"]
    actual = _hash_password(password, row["salt"])
    return _row_to_user(row) if hmac.compare_digest(actual, expected) else None


def get_user(username: str, path: Optional[str | Path] = None) -> Optional[dict]:
    init_db(path)
    with _connect(path) as c:
        row = c.execute("SELECT * FROM users WHERE username = ?",
                        ((username or "").strip().lower(),)).fetchone()
    return _row_to_user(row) if row else None


def list_users(path: Optional[str | Path] = None) -> list[dict]:
    """Every account, without hashes or salts (the login page's demo-account shortcuts)."""
    init_db(path)
    with _connect(path) as c:
        rows = c.execute("SELECT id, username, role, store_id, display_name FROM users"
                         " ORDER BY id").fetchall()
    return [_row_to_user(r) for r in rows]


def can_create(creator_role: str, target_role: str) -> bool:
    """A higher role may create a lower one; the developer may also create another developer."""
    if creator_role == "developer" and target_role == "developer":
        return True
    return ROLE_RANK.get(creator_role, 0) > ROLE_RANK.get(target_role, 0)


def change_password(username: str, old_password: str, new_password: str,
                    path: Optional[str | Path] = None) -> bool:
    """Change a user's own password after verifying the old one. False on wrong old password / no user."""
    username = (username or "").strip().lower()
    if not new_password:
        return False
    init_db(path)
    with _connect(path) as c:
        row = c.execute("SELECT password_hash, salt FROM users WHERE username = ?",
                        (username,)).fetchone()
    if row is None:
        return False
    if not hmac.compare_digest(_hash_password(old_password, row["salt"]), row["password_hash"]):
        return False
    salt = os.urandom(16).hex()
    with _connect(path) as c:
        c.execute("UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                  (_hash_password(new_password, salt), salt, username))
    return True


def delete_user(username: str, path: Optional[str | Path] = None) -> bool:
    """Remove an account. False when the username does not exist."""
    username = (username or "").strip().lower()
    init_db(path)
    with _connect(path) as c:
        cur = c.execute("DELETE FROM users WHERE username = ?", (username,))
        return cur.rowcount > 0


# ---------------------------------------------------------------- demo accounts
def seed_password() -> str:
    """The password assigned to seeded demo accounts at creation time."""
    return os.getenv("DEMO_PASSWORD") or DEMO_PASSWORD_DEFAULT


def demo_password() -> str:
    """For the demo login page only: the default password when the operator has not overridden it."""
    return "" if os.getenv("DEMO_PASSWORD") else DEMO_PASSWORD_DEFAULT


def seed_demo_accounts(stores: Iterable[dict], password: Optional[str] = None,
                       path: Optional[str | Path] = None) -> int:
    """Create staff/manager accounts for every store plus one developer account. Existing usernames are
    left untouched, so restarting the server never resets a changed password. Returns how many were added."""
    pw = password if password is not None else seed_password()
    created = 0
    for store in stores:
        store_id = str(store.get("store_id") or "")
        name = str(store.get("store_name") or store_id)
        if not store_id:
            continue
        key = store_id.lower()
        for role in ("staff", "manager"):
            if create_user(f"{role}-{key}", pw, role, store_id=store_id,
                           display_name=f"{name} {ROLE_LABELS[role]}", path=path):
                created += 1
    if create_user("dev", pw, "developer", display_name="开发者", path=path):
        created += 1
    return created


# ---------------------------------------------------------------- product approvals (store-scoped)
def approve_product(model_id: str, store_id: str, approved_by: str = "",
                    path: Optional[str | Path] = None) -> None:
    """HQ / a store manager confirms one new product for one store."""
    if not model_id or not store_id:
        raise ValueError("model_id and store_id are required")
    init_db(path)
    with _connect(path) as c:
        c.execute(
            "INSERT INTO product_approvals (model_id, store_id, approved_by, approved_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(model_id, store_id) DO UPDATE SET"
            " approved_by = excluded.approved_by, approved_at = excluded.approved_at",
            (model_id, store_id, approved_by or "", _now()),
        )


def all_approvals(path: Optional[str | Path] = None) -> list[tuple[str, str]]:
    """[(model_id, store_id)] for hydrating the in-process recommender gate at startup."""
    init_db(path)
    with _connect(path) as c:
        rows = c.execute("SELECT model_id, store_id FROM product_approvals").fetchall()
    return [(r["model_id"], r["store_id"]) for r in rows]


def approved_stores(model_id: str, path: Optional[str | Path] = None) -> list[str]:
    init_db(path)
    with _connect(path) as c:
        rows = c.execute("SELECT store_id FROM product_approvals WHERE model_id = ?"
                         " ORDER BY store_id", (model_id,)).fetchall()
    return [r["store_id"] for r in rows]


def clear_approvals(path: Optional[str | Path] = None) -> int:
    """重置演示: drop every store approval (accounts are kept). Returns the number removed."""
    init_db(path)
    with _connect(path) as c:
        cur = c.execute("DELETE FROM product_approvals")
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
