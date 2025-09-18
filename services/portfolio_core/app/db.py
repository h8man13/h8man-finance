"""Database helpers for portfolio_core."""
from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

import aiosqlite
import sqlite3

from .settings import settings


sqlite3.register_adapter(Decimal, lambda d: str(d))


def _convert_decimal(value: bytes | str) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return Decimal(value)


sqlite3.register_converter("DECIMAL", _convert_decimal)
sqlite3.register_converter("NUMERIC", _convert_decimal)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    username TEXT,
    language_code TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_ts TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    market TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    avg_cost_eur NUMERIC NOT NULL,
    avg_cost_ccy NUMERIC NOT NULL,
    ccy TEXT NOT NULL,
    display_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, symbol),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS cash_balances (
    user_id INTEGER PRIMARY KEY,
    amount_eur NUMERIC NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    op_id TEXT,
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    type TEXT NOT NULL,
    symbol TEXT,
    asset_class TEXT,
    qty NUMERIC,
    price_eur NUMERIC,
    amount_eur NUMERIC,
    cash_delta_eur NUMERIC,
    fees_eur NUMERIC DEFAULT 0,
    note TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_ts ON transactions(user_id, ts DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_op ON transactions(user_id, op_id) WHERE op_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS operations (
    user_id INTEGER NOT NULL,
    op_id TEXT NOT NULL,
    command TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, op_id)
);

CREATE TABLE IF NOT EXISTS allocations (
    user_id INTEGER PRIMARY KEY,
    stock_pct INTEGER NOT NULL,
    etf_pct INTEGER NOT NULL,
    crypto_pct INTEGER NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    value_eur NUMERIC NOT NULL,
    net_external_flows_eur NUMERIC NOT NULL DEFAULT 0,
    daily_r_t NUMERIC,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    params_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""


async def init_db(db_path: str | None = None) -> None:
    path = db_path or settings.DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def open_db(db_path: str | None = None) -> aiosqlite.Connection:
    path = db_path or settings.DB_PATH
    conn = await aiosqlite.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = aiosqlite.Row
    return conn


async def upsert_user(conn: aiosqlite.Connection, user: Dict[str, Any]) -> None:
    user_id = user.get("user_id")
    if not user_id:
        return
    await conn.execute(
        """
        INSERT INTO users (user_id, first_name, last_name, username, language_code, updated_at, last_seen_ts)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = COALESCE(EXCLUDED.first_name, first_name),
            last_name = COALESCE(EXCLUDED.last_name, last_name),
            username = COALESCE(EXCLUDED.username, username),
            language_code = COALESCE(EXCLUDED.language_code, language_code),
            updated_at = CURRENT_TIMESTAMP,
            last_seen_ts = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            user.get("first_name"),
            user.get("last_name", ""),
            user.get("username"),
            user.get("language_code"),
        ),
    )
    await conn.commit()


async def ensure_user_state(conn: aiosqlite.Connection, user_id: int, *, defaults: Dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO cash_balances (user_id, amount_eur, updated_at)
        VALUES (?, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id,),
    )
    await conn.execute(
        """
        INSERT INTO allocations (user_id, stock_pct, etf_pct, crypto_pct, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (
            user_id,
            defaults["stock_pct"],
            defaults["etf_pct"],
            defaults["crypto_pct"],
        ),
    )
    await conn.commit()


async def record_operation(
    conn: aiosqlite.Connection,
    *,
    user_id: int,
    op_id: str,
    command: str,
    result: Dict[str, Any],
) -> None:
    payload = json.dumps(result, default=_json_default)
    await conn.execute(
        """
        INSERT OR REPLACE INTO operations (user_id, op_id, command, result_json, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (user_id, op_id, command, payload),
    )
    await conn.commit()


async def get_operation(conn: aiosqlite.Connection, *, user_id: int, op_id: str) -> Dict[str, Any] | None:
    async with conn.execute(
        "SELECT result_json FROM operations WHERE user_id = ? AND op_id = ?",
        (user_id, op_id),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return json.loads(row["result_json"])


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serialisable")