"""Tests for transaction operations."""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.services.portfolio import PortfolioService


@pytest.mark.asyncio
async def test_buy_transaction(portfolio_service, test_user):
    """Test recording a buy transaction."""
    symbol = "AAPL"
    qty = Decimal("5")
    price = Decimal("175.50")
    
    # Record buy transaction
    tx = await portfolio_service.record_transaction(
        type="buy",
        symbol=symbol,
        qty=qty,
        price_ccy=price
    )
    
    assert tx["type"] == "buy"
    assert tx["symbol"] == symbol
    assert tx["qty"] == qty
    assert tx["price_ccy"] == price
    
    # Verify position updated
    pos = await portfolio_service._get_active_positions()
    assert len(pos) == 1
    assert pos[0]["symbol"] == symbol
    assert pos[0]["qty"] == qty
    assert pos[0]["avg_cost_ccy"] == price


@pytest.mark.asyncio
async def test_sell_transaction(portfolio_service, test_user):
    """Test recording a sell transaction."""
    # Setup initial position
    symbol = "AAPL"
    buy_qty = Decimal("10")
    buy_price = Decimal("175.50")
    await portfolio_service.record_transaction(
        type="buy",
        symbol=symbol,
        qty=buy_qty,
        price_ccy=buy_price
    )
    
    # Sell half
    sell_qty = Decimal("5")
    sell_price = Decimal("180.00")
    tx = await portfolio_service.record_transaction(
        type="sell",
        symbol=symbol,
        qty=-sell_qty,  # Negative for sell
        price_ccy=sell_price
    )
    
    assert tx["type"] == "sell"
    assert tx["symbol"] == symbol
    assert tx["qty"] == -sell_qty
    assert tx["price_ccy"] == sell_price
    
    # Verify position updated
    pos = await portfolio_service._get_active_positions()
    assert len(pos) == 1
    assert pos[0]["qty"] == buy_qty - sell_qty


@pytest.mark.asyncio
async def test_cash_transaction(portfolio_service, test_user):
    """Test cash deposit/withdrawal."""
    deposit = Decimal("1000")
    tx = await portfolio_service.update_cash(deposit)
    
    assert tx["type"] == "deposit"
    assert tx["amount_eur"] == deposit
    
    # Verify cash balance
    balance = await portfolio_service.get_cash_balance()
    assert balance == deposit
    
    # Test withdrawal
    withdraw = Decimal("-500")
    tx = await portfolio_service.update_cash(withdraw)
    
    assert tx["type"] == "withdraw"
    assert tx["amount_eur"] == withdraw
    
    # Verify updated balance
    balance = await portfolio_service.get_cash_balance()
    assert balance == deposit + withdraw


@pytest.mark.asyncio
async def test_transaction_history(portfolio_service, test_user):
    """Test getting transaction history."""
    # Create some transactions
    await portfolio_service.update_cash(Decimal("1000"))
    await portfolio_service.record_transaction(
        type="buy",
        symbol="AAPL",
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    await portfolio_service.record_transaction(
        type="buy",
        symbol="MSFT",
        qty=Decimal("3"),
        price_ccy=Decimal("250.00")
    )
    
    # Get history with default limit
    history = await portfolio_service.get_recent_transactions()
    assert len(history) == 3
    assert history[0]["type"] == "buy"  # Most recent first
    assert history[0]["symbol"] == "MSFT"
    
    # Test with custom limit
    history = await portfolio_service.get_recent_transactions(limit=2)
    assert len(history) == 2