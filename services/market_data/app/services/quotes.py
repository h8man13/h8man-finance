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
        market, ccy = infer_market_currency(symbol)

        # Last and open in native
        last = Decimal(str(item.get("close")))
        o = item.get("open")
        open_px = Decimal(str(o)) if o is not None else None

        # EUR conversion rules
        if ccy == "USD":
            price_eur = last * usd_eur
            open_eur = (open_px * usd_eur) if open_px is not None else None
        else:
            price_eur = last
            open_eur = open_px

        ts = datetime.fromtimestamp(int(item.get("timestamp")), tz=timezone.utc)
        # Freshness classification (best-effort)
        fres_label, fres_note = classify_freshness(symbol, ts, {
            "eod": item.get("is_eod") or item.get("eod"),
            "delayed": item.get("is_delayed") or item.get("delayed"),
        })

        out.append({
            "symbol": symbol,
            "market": market,
            "currency": ccy,
            "price": qd(last),
            "price_eur": qd(price_eur),
            "open": qd(open_px) if open_px is not None else None,
            "open_eur": qd(open_eur) if open_eur is not None else None,
            "ts": ts.isoformat(),
            "provider": "EODHD",
            "freshness": fres_label,
            "freshness_note": fres_note,
        })

    payload = {"quotes": out}
    await cache_set(conn, "quotes_cache", key, json.dumps(payload), settings.QUOTES_TTL_SEC, now_iso)
    return payload
