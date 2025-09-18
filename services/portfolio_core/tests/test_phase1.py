"""Comprehensive tests for Phase 1 portfolio_core functionality."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from app.clients import market_data_client, Meta, Quote


@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    """Test health check endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_cash_operations(async_client):
    """Test cash add, remove, and query operations."""
    user_params = {"user_id": 1001}

    # Add cash
    resp = await async_client.post(
        "/cash_add",
        params=user_params,
        json={"op_id": "cash-add-1", "amount_eur": "1000"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert Decimal(data["data"]["cash_eur"]) == Decimal("1000")

    # Query cash
    resp = await async_client.get("/cash", params=user_params)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert Decimal(data["data"]["cash_eur"]) == Decimal("1000")

    # Remove cash
    resp = await async_client.post(
        "/cash_remove",
        params=user_params,
        json={"op_id": "cash-rem-1", "amount_eur": "200"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert Decimal(data["data"]["cash_eur"]) == Decimal("800")


@pytest.mark.asyncio
async def test_cash_insufficient_funds(async_client):
    """Test cash removal with insufficient funds."""
    user_params = {"user_id": 1002}

    resp = await async_client.post(
        "/cash_remove",
        params=user_params,
        json={"op_id": "cash-rem-fail", "amount_eur": "100"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert not data["ok"]
    assert data["error"]["code"] == "INSUFFICIENT"


@pytest.mark.asyncio
async def test_portfolio_positions_flow(async_client):
    """Test complete portfolio position management flow."""
    # Mock market data
    meta = Meta(symbol="AAPL.US", asset_class="stock", market="US", currency="USD")
    quote = Quote(symbol="AAPL.US", price_eur=Decimal("150"), currency="USD", market="US", freshness="eod")

    orig_get_meta = market_data_client.get_meta
    orig_get_quotes = market_data_client.get_quotes
    market_data_client.get_meta = AsyncMock(return_value={"AAPL.US": meta})
    market_data_client.get_quotes = AsyncMock(return_value={"AAPL.US": quote})

    try:
        user_params = {"user_id": 1003}

        # Add position
        resp = await async_client.post(
            "/add",
            params=user_params,
            json={"op_id": "add-aapl", "symbol": "AAPL", "qty": "10", "asset_class": "stock"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert len(data["data"]["holdings"]) == 1
        assert data["data"]["holdings"][0]["symbol"] == "AAPL.US"
        assert Decimal(data["data"]["holdings"][0]["qty_total"]) == Decimal("10")

        # Get portfolio
        resp = await async_client.get("/portfolio", params=user_params)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert len(data["data"]["holdings"]) == 1
        assert data["data"]["holdings"][0]["symbol"] == "AAPL.US"

        # Remove position
        resp = await async_client.post(
            "/remove",
            params=user_params,
            json={"op_id": "remove-aapl", "symbol": "AAPL"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert data["data"]["holdings"] == []

    finally:
        market_data_client.get_meta = orig_get_meta
        market_data_client.get_quotes = orig_get_quotes


@pytest.mark.asyncio
async def test_remove_nonexistent_position(async_client):
    """Test removing a position that doesn't exist."""
    resp = await async_client.post(
        "/remove",
        params={"user_id": 1004},
        json={"op_id": "remove-missing", "symbol": "XYZ"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert not data["ok"]
    assert data["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_trading_operations(async_client):
    """Test buy and sell operations."""
    # Mock market data
    meta = Meta(symbol="TSLA.US", asset_class="stock", market="US", currency="USD")
    quote = Quote(symbol="TSLA.US", price_eur=Decimal("200"), currency="USD", market="US", freshness="eod")

    orig_get_meta = market_data_client.get_meta
    orig_get_quotes = market_data_client.get_quotes
    market_data_client.get_meta = AsyncMock(return_value={"TSLA.US": meta})
    market_data_client.get_quotes = AsyncMock(return_value={"TSLA.US": quote})

    try:
        user_params = {"user_id": 1005}

        # Add cash first
        await async_client.post(
            "/cash_add",
            params=user_params,
            json={"op_id": "cash-for-trading", "amount_eur": "5000"},
        )

        # Buy
        resp = await async_client.post(
            "/buy",
            params=user_params,
            json={"op_id": "buy-tsla", "symbol": "TSLA", "qty": "5", "price_eur": "200", "fees_eur": "10"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        expected_cash = Decimal("5000") - (Decimal("200") * 5) - Decimal("10")
        assert Decimal(data["data"]["cash_eur"]) == expected_cash

        # Sell
        resp = await async_client.post(
            "/sell",
            params=user_params,
            json={"op_id": "sell-tsla", "symbol": "TSLA", "qty": "2", "price_eur": "210", "fees_eur": "5"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        expected_cash += Decimal("210") * 2 - Decimal("5")
        assert Decimal(data["data"]["cash_eur"]) == expected_cash

    finally:
        market_data_client.get_meta = orig_get_meta
        market_data_client.get_quotes = orig_get_quotes


@pytest.mark.asyncio
async def test_transactions_history(async_client):
    """Test transaction history retrieval."""
    # Mock market data
    meta = Meta(symbol="BTC.US", asset_class="crypto", market="US", currency="USD")
    quote = Quote(symbol="BTC.US", price_eur=Decimal("30000"), currency="USD", market="US", freshness="eod")

    orig_get_meta = market_data_client.get_meta
    orig_get_quotes = market_data_client.get_quotes
    market_data_client.get_meta = AsyncMock(return_value={"BTC.US": meta})
    market_data_client.get_quotes = AsyncMock(return_value={"BTC.US": quote})

    try:
        user_params = {"user_id": 1006}

        # Create some transactions
        await async_client.post(
            "/cash_add",
            params=user_params,
            json={"op_id": "cash-tx-1", "amount_eur": "50000"},
        )

        await async_client.post(
            "/add",
            params=user_params,
            json={"op_id": "add-btc", "symbol": "BTC", "qty": "1", "asset_class": "crypto"},
        )

        # Get transaction history
        resp = await async_client.get("/tx", params={**user_params, "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert "transactions" in data["data"]
        assert len(data["data"]["transactions"]) >= 2
        assert "count" in data["data"]

    finally:
        market_data_client.get_meta = orig_get_meta
        market_data_client.get_quotes = orig_get_quotes


@pytest.mark.asyncio
async def test_allocation_management(async_client):
    """Test allocation target management."""
    user_params = {"user_id": 1007}

    # Get default allocation
    resp = await async_client.get("/allocation", params=user_params)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert "target" in data["data"]
    target = data["data"]["target"]
    assert target["stock_pct"] + target["etf_pct"] + target["crypto_pct"] == 100

    # Edit allocation
    resp = await async_client.post(
        "/allocation_edit",
        params=user_params,
        json={"op_id": "alloc-edit", "stock_pct": 60, "etf_pct": 30, "crypto_pct": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert data["data"]["target"]["stock_pct"] == 60
    assert data["data"]["target"]["etf_pct"] == 30
    assert data["data"]["target"]["crypto_pct"] == 10


@pytest.mark.asyncio
async def test_allocation_validation(async_client):
    """Test allocation validation."""
    user_params = {"user_id": 1008}

    # Invalid allocation (doesn't sum to 100)
    resp = await async_client.post(
        "/allocation_edit",
        params=user_params,
        json={"op_id": "alloc-bad", "stock_pct": 50, "etf_pct": 30, "crypto_pct": 10},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert not data["ok"]
    assert data["error"]["code"] == "BAD_INPUT"


@pytest.mark.asyncio
async def test_rename_functionality(async_client):
    """Test position renaming."""
    # Mock market data
    meta = Meta(symbol="NVDA.US", asset_class="stock", market="US", currency="USD")
    quote = Quote(symbol="NVDA.US", price_eur=Decimal("800"), currency="USD", market="US", freshness="eod")

    orig_get_meta = market_data_client.get_meta
    orig_get_quotes = market_data_client.get_quotes
    market_data_client.get_meta = AsyncMock(return_value={"NVDA.US": meta})
    market_data_client.get_quotes = AsyncMock(return_value={"NVDA.US": quote})

    try:
        user_params = {"user_id": 1009}

        # Add position
        await async_client.post(
            "/add",
            params=user_params,
            json={"op_id": "add-nvda", "symbol": "NVDA", "qty": "5", "asset_class": "stock"},
        )

        # Rename position
        resp = await async_client.post(
            "/rename",
            params=user_params,
            json={"op_id": "rename-nvda", "symbol": "NVDA", "display_name": "NVIDIA Corp"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"]
        assert data["data"]["rename"]["symbol"] == "NVDA.US"
        assert data["data"]["rename"]["display_name"] == "NVIDIA Corp"

    finally:
        market_data_client.get_meta = orig_get_meta
        market_data_client.get_quotes = orig_get_quotes


@pytest.mark.asyncio
async def test_portfolio_analytics_endpoints(async_client):
    """Test portfolio analytics endpoints."""
    user_params = {"user_id": 1010}

    # Test portfolio snapshot
    resp = await async_client.get("/portfolio_snapshot", params={**user_params, "period": "d"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert "snapshot" in data["data"]

    # Test portfolio summary
    resp = await async_client.get("/portfolio_summary", params={**user_params, "period": "m"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]

    # Test portfolio breakdown
    resp = await async_client.get("/portfolio_breakdown", params={**user_params, "period": "y"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]

    # Test portfolio digest
    resp = await async_client.get("/portfolio_digest", params={**user_params, "period": "m"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]

    # Test portfolio movers
    resp = await async_client.get("/portfolio_movers", params={**user_params, "period": "d"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]


@pytest.mark.asyncio
async def test_what_if_scenario(async_client):
    """Test what-if scenario endpoint."""
    user_params = {"user_id": 1011}

    resp = await async_client.get("/po_if", params={**user_params, "scope": "stocks", "delta_pct": "5"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]


@pytest.mark.asyncio
async def test_help_endpoint(async_client):
    """Test help endpoint."""
    user_params = {"user_id": 1012}

    resp = await async_client.get("/help", params=user_params)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"]
    assert "help" in data["data"]


@pytest.mark.asyncio
async def test_idempotency(async_client):
    """Test operation idempotency."""
    # Mock market data
    meta = Meta(symbol="ETH.US", asset_class="crypto", market="US", currency="USD")
    quote = Quote(symbol="ETH.US", price_eur=Decimal("2000"), currency="USD", market="US", freshness="eod")

    orig_get_meta = market_data_client.get_meta
    orig_get_quotes = market_data_client.get_quotes
    market_data_client.get_meta = AsyncMock(return_value={"ETH.US": meta})
    market_data_client.get_quotes = AsyncMock(return_value={"ETH.US": quote})

    try:
        user_params = {"user_id": 1013}

        # Same operation twice should be idempotent
        op_data = {"op_id": "add-eth-once", "symbol": "ETH", "qty": "2", "asset_class": "crypto"}

        resp1 = await async_client.post("/add", params=user_params, json=op_data)
        assert resp1.status_code == 200

        resp2 = await async_client.post("/add", params=user_params, json=op_data)
        assert resp2.status_code == 200

        # Should only create one position
        resp = await async_client.get("/portfolio", params=user_params)
        holdings = resp.json()["data"]["holdings"]
        eth_holdings = [h for h in holdings if h["symbol"] == "ETH.US"]
        assert len(eth_holdings) == 1
        assert Decimal(eth_holdings[0]["qty_total"]) == Decimal("2")

    finally:
        market_data_client.get_meta = orig_get_meta
        market_data_client.get_quotes = orig_get_quotes