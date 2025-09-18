from __future__ import annotations

from decimal import Decimal

import pytest
pytest.importorskip("respx")
import respx
from httpx import Response

from app.clients import MarketDataClient


@pytest.mark.asyncio
@respx.mock
async def test_market_data_client_fetches_and_caches_quotes():
    client = MarketDataClient()

    route = respx.get("http://market-data.test/quote").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "quotes": [
                    {"symbol": "AAPL", "price_eur": 150, "currency": "USD", "market": "US"}
                ]
            }
        })
    )

    quotes = await client.get_quotes(["aapl"])
    assert "AAPL" in quotes
    assert quotes["AAPL"].price_eur == Decimal("150")
    assert route.called

    route.calls.reset()
    quotes = await client.get_quotes(["AAPL"])
    assert not route.called  # served from cache


@pytest.mark.asyncio
@respx.mock
async def test_market_data_client_fetches_meta():
    client = MarketDataClient()

    route = respx.get("http://market-data.test/meta").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "meta": [
                    {"symbol": "MSFT", "asset_class": "stock", "market": "US", "currency": "USD"}
                ]
            }
        })
    )

    meta = await client.get_meta(["msft"])
    assert "MSFT" in meta
    assert meta["MSFT"].asset_class == "stock"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_market_data_client_fetches_benchmarks():
    client = MarketDataClient()

    route = respx.get("http://market-data.test/benchmarks").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {"series": {"GSPC.INDX": [0.1, 0.2]}}
        })
    )

    data = await client.get_benchmarks(["GSPC.INDX"], "d")
    assert "series" in data
    assert route.called

    route.calls.reset()
    await client.get_benchmarks(["GSPC.INDX"], "d")
    assert not route.called



