"""
Core database models using SQLite with aiosqlite for async support.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
import json
import sqlite3
import aiosqlite


# Decimal adapters for SQLite
def adapt_decimal(d):
    """Convert Decimal to string for SQLite storage."""
    return str(d)


def convert_decimal(s):
    """Convert string back to Decimal from SQLite."""
    if isinstance(s, bytes):
        s = s.decode('utf-8')
    return Decimal(s)


# Register adapters
sqlite3.register_adapter(Decimal, adapt_decimal)
sqlite3.register_converter("DECIMAL", convert_decimal)
sqlite3.register_converter("NUMERIC", convert_decimal)


SCHEMA = """
-- Users table (from Telegram)
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    username TEXT,
    language_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Positions table (active holdings)
CREATE TABLE IF NOT EXISTS positions (
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    avg_cost_ccy NUMERIC NOT NULL,
    avg_cost_eur NUMERIC NOT NULL,
    ccy TEXT NOT NULL,
    nickname TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, symbol),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Cash balances (EUR only)
CREATE TABLE IF NOT EXISTS cash_balances (
    user_id INTEGER PRIMARY KEY,
    amount_eur NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Transactions log
CREATE TABLE IF NOT EXISTS transactions (
    tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    type TEXT NOT NULL,
    symbol TEXT,
    qty NUMERIC,
    price_ccy NUMERIC,
    ccy TEXT,
    amount_eur NUMERIC NOT NULL,
    fx_rate_used NUMERIC,
    note TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Portfolio snapshots
CREATE TABLE IF NOT EXISTS snapshots (
    user_id INTEGER NOT NULL,
    date DATE NOT NULL,
    value_eur DECIMAL NOT NULL,
    net_external_flows_eur DECIMAL NOT NULL,
    daily_r_t DECIMAL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Target allocations
CREATE TABLE IF NOT EXISTS targets (
    user_id INTEGER PRIMARY KEY,
    etf_target_pct INTEGER NOT NULL,
    stock_target_pct INTEGER NOT NULL,
    crypto_target_pct INTEGER NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    params_json TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Indexes for common queries
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_transactions_user_ts ON transactions (user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_positions_user_class ON positions (user_id, asset_class);
CREATE INDEX IF NOT EXISTS idx_alerts_user_kind ON alerts (user_id, kind);
CREATE INDEX IF NOT EXISTS idx_transactions_user_type ON transactions (user_id, type);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_date ON snapshots (user_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_positions_user_qty ON positions (user_id) WHERE qty > 0;

-- Drop old tables that are no longer used
DROP TABLE IF EXISTS portfolios;
DROP TABLE IF EXISTS portfolio_positions;
DROP TABLE IF EXISTS portfolio_transactions;

-- Migrate data if needed (this will run once during update)
-- Create temp table for positions migration
CREATE TABLE IF NOT EXISTS positions_new (
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    qty NUMERIC NOT NULL,
    avg_cost_ccy NUMERIC NOT NULL,
    avg_cost_eur NUMERIC NOT NULL,
    ccy TEXT NOT NULL,
    nickname TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, symbol),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Migrate existing positions data if old table exists
INSERT OR IGNORE INTO positions_new (user_id, symbol, market, asset_class, qty, avg_cost_ccy, avg_cost_eur, ccy, nickname, updated_at)
SELECT user_id, symbol,
       COALESCE(market, 'US') as market,
       COALESCE(asset_class, 'stock') as asset_class,
       qty, avg_cost_ccy, avg_cost_eur, ccy, nickname, updated_at
FROM positions
WHERE EXISTS (SELECT name FROM sqlite_master WHERE type='table' AND name='positions');

-- Drop old positions table and rename new one
DROP TABLE IF EXISTS positions;
ALTER TABLE positions_new RENAME TO positions;

-- Same for cash_balances
CREATE TABLE IF NOT EXISTS cash_balances_new (
    user_id INTEGER PRIMARY KEY,
    amount_eur NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

-- Migrate cash balances
INSERT OR IGNORE INTO cash_balances_new (user_id, amount_eur, updated_at)
SELECT user_id, amount_eur, updated_at
FROM cash_balances
WHERE EXISTS (SELECT name FROM sqlite_master WHERE type='table' AND name='cash_balances');

DROP TABLE IF EXISTS cash_balances;
ALTER TABLE cash_balances_new RENAME TO cash_balances;
"""


async def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database schema."""
    from .settings import settings
    import os

    path = db_path or settings.DB_PATH

    # Ensure directory exists
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def open_db(db_path: Optional[str] = None):
    """Open database connection with Decimal support."""
    from .settings import settings

    path = db_path or settings.DB_PATH
    # aiosqlite uses sqlite3 under the hood, so the adapters will be used
    db = await aiosqlite.connect(path,
                                detect_types=sqlite3.PARSE_DECLTYPES)
    db.row_factory = aiosqlite.Row
    return db


# User operations
async def upsert_user(db: aiosqlite.Connection, user: Dict[str, Any]) -> None:
    """Update or insert user record."""
    user_id = user.get("user_id")
    if not user_id:
        return

    async with db.execute(
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
    ):
        await db.commit()