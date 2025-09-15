"""Tests for portfolio service."""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, date

from app.services.portfolio import PortfolioService


@pytest.mark.asyncio
async def test_portfolio_snapshot(portfolio_service, test_user):
    """Test getting portfolio snapshot."""
    # 1. Start with empty portfolio
    snapshot = await portfolio_service.get_portfolio_snapshot()
    assert snapshot["total_eur"] == 0
    assert snapshot["cash_eur"] == 0
    assert len(snapshot["positions"]) == 0

    # 2. Add cash
    await portfolio_service.update_cash(Decimal("1000.00"))
    snapshot = await portfolio_service.get_portfolio_snapshot()
    assert snapshot["total_eur"] == Decimal("1000.00")
    assert snapshot["cash_eur"] == Decimal("1000.00")

    # 3. Add position
    await portfolio_service.record_transaction(
        type="buy",
        symbol="AAPL",
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )

    snapshot = await portfolio_service.get_portfolio_snapshot()
    assert len(snapshot["positions"]) == 1
    pos = snapshot["positions"][0]
    assert pos["symbol"] == "AAPL"
    assert pos["qty"] == Decimal("5")
    assert pos["price_ccy"] == Decimal("175.50")
    assert pos["asset_class"] == "stock"
    assert pos["weight_pct"] > 0


@pytest.mark.asyncio
async def test_cash_operations(portfolio_service, test_user):
    """Test cash deposit and withdrawal."""
    # Initial state
    balance = await portfolio_service.get_cash_balance()
    assert balance == 0

    # Deposit
    await portfolio_service.update_cash(Decimal("1000.00"))
    balance = await portfolio_service.get_cash_balance()
    assert balance == Decimal("1000.00")

    # Withdrawal
    await portfolio_service.update_cash(Decimal("-500.00"))
    balance = await portfolio_service.get_cash_balance()
    assert balance == Decimal("500.00")


@pytest.mark.asyncio
async def test_position_transactions(portfolio_service, test_user, market_data_mock):
    """Test position operations through transactions."""
    # Buy position
    tx = await portfolio_service.record_transaction(
        type="buy",
        symbol="AAPL",
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    assert tx["type"] == "buy"
    assert tx["qty"] == Decimal("5")
    assert tx["price_ccy"] == Decimal("175.50")

    # Check position
    positions = await portfolio_service._get_active_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == "AAPL"
    assert pos["qty"] == Decimal("5")
    assert pos["avg_cost_ccy"] == Decimal("175.50")

    # Sell partial
    tx = await portfolio_service.record_transaction(
        type="sell",
        symbol="AAPL",
        qty=Decimal("-2"),
        price_ccy=Decimal("180.00")
    )
    assert tx["type"] == "sell"
    assert tx["qty"] == Decimal("-2")

    # Check position again
    positions = await portfolio_service._get_active_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos["qty"] == Decimal("3")  # 5 - 2


@pytest.mark.asyncio 
async def test_transaction_history(portfolio_service, test_user):
    """Test transaction history retrieval."""
    # Record some transactions
    await portfolio_service.update_cash(Decimal("1000.00"))
    await portfolio_service.record_transaction(
        type="buy",
        symbol="AAPL",
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    await portfolio_service.record_transaction(
        type="sell",
        symbol="AAPL",
        qty=Decimal("-2"),
        price_ccy=Decimal("180.00")
    )

    # Get history
    history = await portfolio_service.get_recent_transactions(limit=10)
    assert len(history) == 3  # deposit, buy, sell
    
    # Check order
    assert history[0]["type"] == "sell"
    assert history[1]["type"] == "buy"
    assert history[2]["type"] == "deposit"