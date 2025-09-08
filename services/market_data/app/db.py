import aiosqlite
from typing import Optional, Tuple, Any, Dict
from datetime import datetime, timezone
from .settings import settings

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  first_name TEXT, last_name TEXT, username TEXT, language_code TEXT,
  created_at TEXT, updated_at TEXT, last_seen_ts TEXT
);

CREATE TABLE IF NOT EXISTS quotes_cache(
  key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  ts TEXT NOT NULL,
  ttl_sec INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmarks_cache(
  key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  ts TEXT NOT NULL,
  ttl_sec INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta_cache(
  key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  ts TEXT NOT NULL,
  ttl_sec INTEGER NOT NULL
);
"""

async def open_db():
    conn = await aiosqlite.connect(settings.DB_PATH)
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn

async def cache_get(conn: aiosqlite.Connection, table: str, key: str, now_iso: str) -> Optional[str]:
    # Expire in read
    await conn.execute(f"DELETE FROM {table} WHERE (strftime('%s', ?) - strftime('%s', ts)) > ttl_sec", (now_iso,))
    await conn.commit()
    cur = await conn.execute(f"SELECT payload FROM {table} WHERE key=?", (key,))
    row = await cur.fetchone()
    return row[0] if row else None

async def cache_set(conn: aiosqlite.Connection, table: str, key: str, payload: str, ttl: int, now_iso: str):
    await conn.execute(
        f"INSERT INTO {table}(key,payload,ts,ttl_sec) VALUES(?,?,?,?) "
        f"ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, ts=excluded.ts, ttl_sec=excluded.ttl_sec",
        (key, payload, now_iso, ttl),
    )
    await conn.commit()

async def upsert_user(conn: aiosqlite.Connection, u: Dict[str, Any]):
    if not u or not u.get("user_id"):
        return
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        """
        INSERT INTO users(user_id, first_name, last_name, username, language_code, created_at, updated_at, last_seen_ts)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
          first_name=excluded.first_name,
          last_name=excluded.last_name,
          username=excluded.username,
          language_code=excluded.language_code,
          updated_at=excluded.updated_at,
          last_seen_ts=excluded.last_seen_ts
        """,
        (
            u.get("user_id"),
            u.get("first_name"),
            u.get("last_name","") or "",
            u.get("username"),
            u.get("language_code"),
            now, now, now,
        ),
    )
    await conn.commit()
