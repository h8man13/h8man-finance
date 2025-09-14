from decimal import Decimal
from typing import List, Dict, Any


async def _mock_batch_quotes_ok(symbols: List[str]) -> List[Dict[str, Any]]:
    out = []
    for s in symbols:
        code = s
        if s == "AAPL.US":
            out.append({
                "code": code,
                "close": 100.0,
                "open": 95.0,
                "timestamp": 1_700_000_000,
                "currency": "USD",
            })
        elif s == "SAP.XETRA":
            out.append({
                "code": code,
                "close": 120.0,
                "open": 115.0,
                "timestamp": 1_700_000_100,
                "currency": "EUR",
            })
        else:
            out.append({
                "code": code,
                "close": 10.0,
                "open": 10.0,
                "timestamp": 1_700_000_200,
                "currency": "USD",
            })
    return out


async def _fx_rate(self):
    return Decimal("0.90")


def test_quote_happy_path(client, monkeypatch):
    # Patch EODHD and FX
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    monkeypatch.setattr(eod_mod.EodhdClient, "batch_quotes", lambda self, syms: _mock_batch_quotes_ok(syms))
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", _fx_rate)

    r = client.get("/quote", params={"symbols": "AAPL,SAP.XETRA"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    quotes = js["data"]["quotes"]
    # Middleware normalizes items
    aapl = next(q for q in quotes if q["symbol"] == "AAPL.US")
    sap = next(q for q in quotes if q["symbol"] == "SAP.XETRA")

    # USD converted using 0.90
    assert aapl["price_ccy"] == 100.0
    assert aapl["price_eur"] == 90.0
    # pct since open: (100/95 - 1) * 100 = ~5.26 -> rounded 2dp
    assert aapl["pct_since_open"] == 5.26

    # EUR stays as-is
    assert sap["price_ccy"] == 120.0
    assert sap["price_eur"] == 120.0
    assert sap["pct_since_open"] == 4.35


def test_quote_partial_success(client, monkeypatch):
    # First batch call fails, then per-symbol: AAPL ok, BAD.ONE fails
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    async def flaky_batch(self, syms):
        # Simulate upstream error on initial batch
        raise RuntimeError("eodhd down")

    async def per_symbol(self, syms):
        s = syms[0]
        if s == "AAPL.US":
            return await _mock_batch_quotes_ok([s])
        raise RuntimeError("symbol not found")

    monkeypatch.setattr(eod_mod.EodhdClient, "batch_quotes", flaky_batch)
    # For subsequent single symbol calls
    # We patch the function back on the class used inside the service via a wrapper that inspects args length
    # But easier: monkeypatch within services.quotes to use our per_symbol for that module's EodhdClient
    from app.services import quotes as quotes_mod  # type: ignore
    monkeypatch.setattr(quotes_mod.EodhdClient, "batch_quotes", per_symbol)
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", _fx_rate)

    r = client.get("/quote", params={"symbols": "AAPL,BAD.ONE"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    assert js.get("partial") is True or js["data"]  # envelope may carry partial flag or error inside
    # When partial, error field can be included; ensure at least one quote present
    quotes = js["data"]["quotes"]
    assert any(q["symbol"] == "AAPL.US" for q in quotes)


def test_quote_too_many_symbols(client):
    # 11 symbols should trigger BAD_INPUT
    syms = ",".join([f"S{i}" for i in range(11)])
    r = client.get("/quote", params={"symbols": syms})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is False
    assert js["error"]["code"] == "BAD_INPUT"


def test_quote_crypto_and_sanitization(client, monkeypatch):
    # BTC-USD (crypto, stays without .US) and sanitation when close is missing but price is present
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    async def batch(self, syms):
        out = []
        for s in syms:
            if s == "BTC-USD":
                out.append({
                    "code": s,
                    "close": 20000.0,
                    "open": 19000.0,
                    "timestamp": 1_700_000_300,
                    "currency": "USD",
                })
            else:
                out.append({
                    "code": s,
                    # sanitized path would ensure close exists; open=0 to trigger pct=None
                    "close": 10.0,
                    "open": 0,
                    "timestamp": 1_700_000_400,
                    "currency": "USD",
                })
        return out

    async def fx(self):
        return Decimal("0.90")

    monkeypatch.setattr(eod_mod.EodhdClient, "batch_quotes", batch)
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", fx)

    r = client.get("/quote", params={"symbols": "BTC-USD,SANITIZE"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    quotes = js["data"]["quotes"]
    btc = next(q for q in quotes if q["symbol"] == "BTC-USD")
    san = next(q for q in quotes if q["symbol"] == "SANITIZE.US")
    assert btc["price_ccy"] == 20000.0 and btc["price_eur"] == 18000.0
    # open=0 -> pct_since_open should be None
    assert san["price_ccy"] == 10.0 and san["pct_since_open"] is None


def test_quote_provider_currency_and_suffix_fallback(client, monkeypatch):
    """
    Provider-reported currency should drive conversion when available (USD/EUR),
    falling back to suffix inference when missing.
    - BMW.F with currency EUR -> no conversion
    - FOO.F with missing currency -> suffix .F implies EUR -> no conversion
    - BAR.AS with currency USD -> convert using USD_EUR
    - AAPL.US with provider currency EUR -> no conversion (provider takes precedence)
    """
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    async def batch(self, syms):
        out = []
        for s in syms:
            if s == "BMW.F":
                out.append({
                    "code": s,
                    "close": 50.0,
                    "open": 40.0,
                    "timestamp": 1_700_000_500,
                    "currency": "EUR",
                })
            elif s == "FOO.F":
                out.append({
                    "code": s,
                    "close": 10.0,
                    "open": 10.0,
                    "timestamp": 1_700_000_600,
                    # currency missing -> fallback to suffix
                })
            elif s == "BAR.AS":
                out.append({
                    "code": s,
                    "close": 20.0,
                    "open": 10.0,
                    "timestamp": 1_700_000_700,
                    "currency": "USD",
                })
            elif s == "AAPL.US":
                out.append({
                    "code": s,
                    "close": 100.0,
                    "open": 95.0,
                    "timestamp": 1_700_000_800,
                    # provider says EUR even for .US -> prefer provider
                    "currency": "EUR",
                })
        return out

    async def fx(self):
        return Decimal("0.90")

    monkeypatch.setattr(eod_mod.EodhdClient, "batch_quotes", batch)
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", fx)

    r = client.get("/quote", params={"symbols": "BMW.F,FOO.F,BAR.AS,AAPL.US"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    quotes = js["data"]["quotes"]

    bmw = next(q for q in quotes if q["symbol"] == "BMW.F")
    foo = next(q for q in quotes if q["symbol"] == "FOO.F")
    bar = next(q for q in quotes if q["symbol"] == "BAR.AS")
    aapl = next(q for q in quotes if q["symbol"] == "AAPL.US")

    # EUR cases: no conversion
    assert bmw["price_eur"] == 50.0
    assert foo["price_eur"] == 10.0
    # USD case: convert using 0.90
    assert bar["price_eur"] == 18.0
    # Provider EUR precedence over suffix
    assert aapl["price_eur"] == 100.0
