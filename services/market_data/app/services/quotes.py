import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict
from ..clients.eodhd import EodhdClient
from ..clients.fx import FxClient
from ..db import cache_get, cache_set
from ..settings import settings
from ..utils.symbols import normalize_symbol, infer_market_currency
from ..utils.time import classify_freshness

def qd(x: Decimal, q: str = "0.01") -> str:
    return str(x.quantize(Decimal(q), rounding=ROUND_HALF_UP))

async def get_quotes(conn, symbols: List[str]) -> Dict:
    # Normalize symbols per spec
    symbols_n = [normalize_symbol(s) for s in symbols]
    key = f"quotes:{','.join(symbols_n)}"
    now_iso = datetime.now(timezone.utc).isoformat()

    cached = await cache_get(conn, "quotes_cache", key, now_iso)
    if cached:
        return json.loads(cached)

    eod = EodhdClient()
    fx = FxClient()

    # Fetch quotes in batch
    data = await eod.batch_quotes(symbols_n)

    # Prepare FX rate once
    usd_eur = await fx.usd_to_eur()

    out = []
    for item in data:
        # EODHD real-time fields expected: code, close (last), timestamp, open, currency
        code = item.get("code") or item.get("symbol")
        symbol = normalize_symbol(code)
        # Determine market via suffix (for display), but prefer provider-reported currency when available
        market, inferred_ccy = infer_market_currency(symbol)
        reported_ccy_raw = item.get("currency")
        reported_ccy = str(reported_ccy_raw).strip().upper() if reported_ccy_raw is not None else ""
        # Use provider currency for conversion when it is USD or EUR; otherwise fall back to inferred
        ccy = reported_ccy if reported_ccy in {"USD", "EUR"} else inferred_ccy

        # Last and open in native (robust against bad provider values)
        try:
            last = Decimal(str(item.get("close")))
        except Exception:
            # Skip items without a valid last price
            continue
        o = item.get("open")
        try:
            open_px = Decimal(str(o)) if o is not None else None
        except Exception:
            open_px = None

        # EUR conversion rules: convert only when priced in USD; EUR (and others) pass through
        if ccy == "USD":
            price_eur = last * usd_eur
            open_eur = (open_px * usd_eur) if open_px is not None else None
        else:
            price_eur = last
            open_eur = open_px

        try:
            ts = datetime.fromtimestamp(int(item.get("timestamp")), tz=timezone.utc)
        except Exception:
            # Fallback to current time if timestamp is missing or invalid
            ts = datetime.now(timezone.utc)
        # Freshness classification (best-effort)
        fres_label, fres_note, fres_time = classify_freshness(symbol, ts, {
            "eod": item.get("is_eod") or item.get("eod"),
            "delayed": item.get("is_delayed") or item.get("delayed"),
        })

        out.append({
            "symbol": symbol,
            "market": market,
            # Expose the provider currency if present; otherwise the effective one used above
            "currency": (reported_ccy or ccy),
            "price": qd(last),
            "price_eur": qd(price_eur),
            "open": qd(open_px) if open_px is not None else None,
            "open_eur": qd(open_eur) if open_eur is not None else None,
            "ts": ts.isoformat(),
            "provider": "EODHD",
            "freshness": fres_label,
            "freshness_note": fres_note,
            "fresh_time": fres_time,
        })

    payload = {"quotes": out}
    await cache_set(conn, "quotes_cache", key, json.dumps(payload), settings.QUOTES_TTL_SEC, now_iso)
    return payload
