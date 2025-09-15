"""Tests for portfolio simulation and what-if analysis."""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.services.portfolio import PortfolioService


@pytest.mark.asyncio
async def test_symbol_simulation(portfolio_service, test_user):
    """Test simulating price change for a specific symbol."""
    # Setup position
    symbol = "AAPL"
    await portfolio_service.record_transaction(
        type="buy",
        symbol=symbol,
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    
    # Simulate 5% increase
    change = Decimal("5")
    result = await portfolio_service.simulate_price_change(
        symbol=symbol,
        pct_change=change
    )
    
    # Verify results
    assert "current" in result
    assert "simulated" in result
    assert "delta_eur" in result
    assert "delta_pct" in result
    assert result["delta_pct"] > 0


@pytest.mark.asyncio
async def test_asset_class_simulation(portfolio_service, test_user):
    """Test simulating price change for an asset class."""
    # Setup positions
    stocks = [
        ("AAPL", Decimal("175.50"), Decimal("5")),
        ("MSFT", Decimal("250.00"), Decimal("3"))
    ]
    for symbol, price, qty in stocks:
        await portfolio_service.record_transaction(
            type="buy",
            symbol=symbol,
            qty=qty,
            price_ccy=price
        )
        
    # Add non-stock position
    await portfolio_service.record_transaction(
        type="buy",
        symbol="BTC",
        qty=Decimal("0.1"),
        price_ccy=Decimal("30000.00")
    )
    
    # Simulate 5% drop in stocks
    change = Decimal("-5")
    result = await portfolio_service.simulate_price_change(
        asset_class="stock",
        pct_change=change
    )
    
    # Verify results
    assert result["delta_pct"] < 0  # Portfolio value should decrease
    
    # Get current portfolio
    portfolio = await portfolio_service.get_portfolio_snapshot()
    assert len(portfolio["positions"]) > len(stocks)  # Should include BTC


@pytest.mark.asyncio
async def test_nickname_management(portfolio_service, test_user):
    """Test setting and getting symbol nicknames."""
    # Setup position
    symbol = "AAPL"
    nickname = "iPhone Maker"
    await portfolio_service.record_transaction(
        type="buy",
        symbol=symbol,
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    
    # Set nickname
    pos = await portfolio_service.set_symbol_nickname(symbol, nickname)
    assert pos["nickname"] == nickname
    
    # Get nickname
    saved = await portfolio_service.get_symbol_nickname(symbol)
    assert saved == nickname
    
    # Clear nickname
    pos = await portfolio_service.set_symbol_nickname(symbol, None)
    assert pos["nickname"] is None
    
    # Check portfolio view includes nicknames
    portfolio = await portfolio_service.get_portfolio_snapshot()
    symbol_pos = next(p for p in portfolio["positions"] if p["symbol"] == symbol)
    assert "nickname" in symbol_pos