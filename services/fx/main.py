import os
import json
import time
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(title="fx")

# ---------------- config ----------------
# Accept both FX_CACHE_PATH and DB_PATH. Persist under /app/data by default.
FX_TTL_SEC = int(os.getenv("FX_TTL_SEC", "82800"))  # 23h default from your .env
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8.0"))
EODHD_KEY = os.getenv("EODHD_KEY", "").strip()

_data_dir = Path(os.getenv("DATA_DIR", "/app/data"))
_data_dir.mkdir(parents=True, exist_ok=True)

_raw_db_path = os.getenv("FX_CACHE_PATH") or os.getenv("DB_PATH") or "cache.db"
DB_PATH = _data_dir / Path(_raw_db_path).name  # final persisted path, e.g. /app/data/cache.db

# ---------------- sqlite cache ----------------
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache(
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL,
            ts INTEGER NOT NULL
        )
        """
    )
    return conn

def cache_get(key: str, ttl: int) -> Optional[dict]:
    conn = _db()
    try:
        row = conn.execute("SELECT v, ts FROM cache WHERE k=?", (key,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    v, ts = row
    if int(time.time()) - int(ts) > ttl:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None

def cache_put(key: str, payload: dict):
    conn = _db()
    try:
        conn.execute(
            "REPLACE INTO cache(k, v, ts) VALUES(?,?,?)",
            (key, json.dumps(payload), int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()

# ---------------- models ----------------
class FxResp(BaseModel):
    pair: str          # e.g. USD_EUR
    rate: float        # EUR per 1 USD
    source: str
    fetched_at: int    # unix seconds
    ttl_sec: int

# ---------------- providers ----------------
async def fetch_usdeur_from_eodhd(client: httpx.AsyncClient) -> Tuple[Optional[float], Optional[str]]:
    """
    EODHD real-time for EURUSD.FOREX returns USD per 1 EUR (EURUSD).
    We need USD_EUR, so return 1 / EURUSD.
    """
    if not EODHD_KEY:
        return None, "missing_eodhd_key"
    url = "https://eodhd.com/api/real-time/EURUSD.FOREX"
    params = {"api_token": EODHD_KEY, "fmt": "json"}
    try:
        r = await client.get(url, params=params, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None, f"eodhd_http_{r.status_code}"
        data = r.json()
        if isinstance(data, list) and data:
            data = data[0]
        close = data.get("close") or data.get("price") or data.get("last")
        eurusd = float(close) if close is not None else 0.0
        if eurusd <= 0:
            return None, "eodhd_bad_price"
        usd_eur = 1.0 / eurusd
        return usd_eur, "eodhd"
    except Exception:
        return None, "eodhd_exception"

async def fetch_usdeur_from_ecb(client: httpx.AsyncClient) -> Tuple[Optional[float], Optional[str]]:
    """
    exchangerate.host (ECB based). Base USD, symbol EUR already gives USD->EUR.
    """
    try:
        r = await client.get("https://api.exchangerate.host/latest?base=USD&symbols=EUR", timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None, "ecb_http"
        js = r.json()
        rate = js.get("rates", {}).get("EUR")
        if rate is None:
            return None, "ecb_no_rate"
        rate = float(rate)
        if rate <= 0:
            return None, "ecb_bad_rate"
        return rate, "exchangerate.host-ecb"
    except Exception:
        return None, "ecb_exception"

async def get_usd_eur(force: bool) -> FxResp:
    key = "fx:USD_EUR"
    if not force:
        cached = cache_get(key, FX_TTL_SEC)
        if cached:
            return FxResp(**cached)

    async with httpx.AsyncClient() as client:
        rate, src = await fetch_usdeur_from_eodhd(client)
        if rate is None:
            rate, src = await fetch_usdeur_from_ecb(client)

    if rate is None:
        raise HTTPException(status_code=502, detail="Failed to fetch USD_EUR from providers")

    payload = FxResp(
        pair="USD_EUR",
        rate=rate,
        source=src or "unknown",
        fetched_at=int(time.time()),
        ttl_sec=FX_TTL_SEC,
    ).dict()
    cache_put(key, payload)
    return FxResp(**payload)

async def fetch_pair_generic(client: httpx.AsyncClient, base: str, quote: str) -> Tuple[Optional[float], Optional[str]]:
    """Fetch arbitrary BASE->QUOTE from exchangerate.host. Returns rate (QUOTE per 1 BASE)."""
    try:
        url = f"https://api.exchangerate.host/latest?base={base}&symbols={quote}"
        r = await client.get(url, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None, "exchangerate_http"
        js = r.json()
        rate = js.get("rates", {}).get(quote)
        if rate is None:
            return None, "exchangerate_no_rate"
        rate = float(rate)
        if rate <= 0:
            return None, "exchangerate_bad_rate"
        return rate, "exchangerate.host"
    except Exception:
        return None, "exchangerate_exception"

async def fetch_pair_eodhd(client: httpx.AsyncClient, base: str, quote: str) -> Tuple[Optional[float], Optional[str]]:
    """Fetch BASE->QUOTE via EODHD, symbol pattern like XAUUSD.FOREX or EURUSD.FOREX."""
    if not EODHD_KEY:
        return None, "missing_eodhd_key"
    sym = f"{base}{quote}.FOREX"
    url = f"https://eodhd.com/api/real-time/{sym}"
    params = {"api_token": EODHD_KEY, "fmt": "json"}
    try:
        r = await client.get(url, params=params, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None, f"eodhd_http_{r.status_code}"
        data = r.json()
        # EODHD sometimes returns list
        if isinstance(data, list) and data:
            data = data[0]
        close = data.get("close") or data.get("price") or data.get("last")
        if close is None:
            return None, "eodhd_no_rate"
        rate = float(close)
        if rate <= 0:
            return None, "eodhd_bad_rate"
        return rate, "eodhd"
    except Exception:
        return None, "eodhd_exception"

async def get_pair(base: str, quote: str, force: bool) -> FxResp:
    b = base.upper()
    q = quote.upper()
    if b == q:
        # Identity rate
        now = int(time.time())
        return FxResp(pair=f"{b}_{q}", rate=1.0, source="identity", fetched_at=now, ttl_sec=FX_TTL_SEC)

    # Prefer dedicated USD_EUR path for better sources
    if b == "USD" and q == "EUR":
        return await get_usd_eur(force)

    key = f"fx:{b}_{q}"
    if not force:
        cached = cache_get(key, FX_TTL_SEC)
        if cached:
            return FxResp(**cached)

    async with httpx.AsyncClient() as client:
        rate, src = await fetch_pair_generic(client, b, q)
        # If generic provider didn't have a rate, try EODHD as a fallback for common pairs (e.g., XAUUSD)
        if rate is None:
            r2, src2 = await fetch_pair_eodhd(client, b, q)
            if r2 is not None:
                rate, src = r2, src2

    if rate is None:
        # Provide a clearer reason for common failure modes
        hint = " (market may be closed or symbol unsupported)"
        raise HTTPException(status_code=502, detail=f"Failed to fetch {b}_{q}{hint}")

    payload = FxResp(
        pair=f"{b}_{q}",
        rate=rate,
        source=src or "unknown",
        fetched_at=int(time.time()),
        ttl_sec=FX_TTL_SEC,
    ).dict()
    cache_put(key, payload)
    return FxResp(**payload)

# ---------------- endpoints ----------------
@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.get("/fx/usd-eur", response_model=FxResp)
async def fx_usd_eur_last_cached():
    """
    Shortcut that returns the last cached USD_EUR.
    If cache is empty on first run, it fetches once and stores it.
    """
    return await get_usd_eur(force=False)

@app.get("/fx", response_model=FxResp)
async def fx(pair: str = Query(..., description="Format: BASE_QUOTE, e.g. USD_EUR"),
             force: bool = Query(False, description="Force refresh")):
    """
    Generic endpoint supporting arbitrary pairs.
    Examples:
      /fx?pair=USD_EUR&force=true
      /fx?pair=XAU_USD
      /fx?pair=XAU_EUR
    """
    p = (pair or "").strip().upper()
    if "_" not in p:
        raise HTTPException(status_code=400, detail="pair must be BASE_QUOTE with underscore")
    base, quote = p.split("_", 1)
    base = base.strip()
    quote = quote.strip()
    if not base or not quote:
        raise HTTPException(status_code=400, detail="pair must be BASE_QUOTE with underscore")
    return await get_pair(base, quote, force=bool(force))

@app.get("/fx/cache/{key}")
def cache_inspect(key: str):
    """
    Inspect a cache entry, e.g. /fx/cache/USD_EUR
    """
    value = cache_get(f"fx:{key.upper()}", FX_TTL_SEC)
    return {"key": key.upper(), "cached": value is not None, "value": value}
