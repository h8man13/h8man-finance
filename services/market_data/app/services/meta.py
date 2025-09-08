import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict
from ..db import cache_get, cache_set
from ..settings import settings
from ..utils.symbols import normalize_symbol, infer_market_currency

async def get_meta(conn, raw_symbol: str) -> Dict:
    symbol = normalize_symbol(raw_symbol)
    key = f"meta:{symbol}"
    now_iso = datetime.now(timezone.utc).isoformat()

    cached = await cache_get(conn, "meta_cache", key, now_iso)
    if cached:
        return json.loads(cached)

    market, currency = infer_market_currency(symbol)
    asset_class = "Crypto" if market == "CRYPTO" else ("ETF" if symbol.endswith(".XETRA") or symbol.endswith(".MI") else "Stock")

    payload = {
        "symbol": symbol,
        "asset_class": asset_class,
        "market": market,
        "currency": currency,
    }

    await cache_set(conn, "meta_cache", key, json.dumps(payload), settings.META_TTL_SEC, now_iso)
    return payload
