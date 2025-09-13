from decimal import Decimal
from typing import List, Dict, Any


async def _mock_batch_quotes(symbols: List[str]) -> List[Dict[str, Any]]:
    out = []
    # Timestamp is arbitrary; we only assert fields presence
    for s in symbols:
        out.append({
            "code": s,
            "close": 100.0,
            "open": 100.0,
            "timestamp": 1_700_000_000,
            "currency": "USD",
        })
    return out


async def _fx_rate(self):
    return Decimal("1.00")


def test_quote_includes_freshness_fields(client, monkeypatch):
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    monkeypatch.setattr(eod_mod.EodhdClient, "batch_quotes", lambda self, syms: _mock_batch_quotes(syms))
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", _fx_rate)

    r = client.get("/quote", params={"symbols": "AAPL"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    q = js["data"]["quotes"][0]
    # Ensure freshness fields present for router formatting
    assert "freshness" in q
    assert ("fresh_time" in q) or ("freshness_note" in q)

