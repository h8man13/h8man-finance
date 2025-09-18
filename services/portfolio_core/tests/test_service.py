from __future__ import annotations

from decimal import Decimal

import pytest
pytest.importorskip("respx")
import respx
from httpx import Response

from app.clients import market_data_client
from app.models import (
    AddPositionRequest,
    CashMutationRequest,
    TradeRequest,
    UserContext,
)
from app.services import PortfolioService


@pytest.mark.asyncio
@respx.mock
async def test_buy_updates_cost_basis_and_cash(conn):
    user = UserContext(user_id=1)
    service = PortfolioService(conn, market_data_client)

    # Seed cash
    await service.cash_add(user, CashMutationRequest(op_id="cash1", amount_eur=Decimal("1000")))

    # Mock market data responses
    respx.get("http://market-data.test/meta").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "meta": [
                    {"symbol": "AMZN", "asset_class": "stock", "market": "US", "currency": "USD"}
                ]
            }
        })
    )
    respx.get("http://market-data.test/quote").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "quotes": [
                    {"symbol": "AMZN", "price_eur": 95, "currency": "USD", "market": "US", "freshness": "live"}
                ]
            }
        })
    )

    result = await service.buy(user, TradeRequest(op_id="buy1", symbol="amzn", qty=Decimal("5")))
    assert "portfolio" in result

    snapshot = await service.portfolio(user)
    assert snapshot.cash_eur == Decimal("525.00")
    assert snapshot.holdings[0].qty_total == Decimal("5.0000")
    assert snapshot.holdings[0].price_eur == Decimal("95.00")


@pytest.mark.asyncio
@respx.mock
async def test_sell_partially_reduces_position(conn):
    user = UserContext(user_id=2)
    service = PortfolioService(conn, market_data_client)

    await service.cash_add(user, CashMutationRequest(op_id="cash1", amount_eur=Decimal("1000")))

    respx.get("http://market-data.test/meta").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "meta": [
                    {"symbol": "NVDA", "asset_class": "stock", "market": "US", "currency": "USD"}
                ]
            }
        })
    )
    respx.get("http://market-data.test/quote").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "quotes": [
                    {"symbol": "NVDA", "price_eur": 100, "currency": "USD", "market": "US"}
                ]
            }
        })
    )

    await service.buy(user, TradeRequest(op_id="buy1", symbol="nvda", qty=Decimal("4")))

    # new quote for sell
    respx.get("http://market-data.test/quote").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "quotes": [
                    {"symbol": "NVDA", "price_eur": 110, "currency": "USD", "market": "US"}
                ]
            }
        })
    )

    await service.sell(user, TradeRequest(op_id="sell1", symbol="NVDA", qty=Decimal("1")))
    snapshot = await service.portfolio(user)

    assert snapshot.holdings[0].qty_total == Decimal("3.0000")
    # Cash should be 1000 - (4*100) + 110 = 510
    assert snapshot.cash_eur == Decimal("510.00")


@pytest.mark.asyncio
@respx.mock
async def test_idempotency_returns_cached_result(conn):
    user = UserContext(user_id=3)
    service = PortfolioService(conn, market_data_client)

    respx.get("http://market-data.test/meta").mock(
        return_value=Response(200, json={
            "ok": True,
            "data": {
                "meta": [
                    {"symbol": "BTC", "asset_class": "crypto", "market": "CRYPTO", "currency": "EUR"}
                ]
            }
        })
    )

    request = AddPositionRequest(op_id="add1", symbol="btc", qty=Decimal("1"), asset_class="crypto")
    first = await service.add(user, request)
    second = await service.add(user, request)
    assert first == second
