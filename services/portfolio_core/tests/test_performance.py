"""Tests for portfolio performance calculations."""
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.services.portfolio import PortfolioService


@pytest.mark.asyncio
async def test_snapshot_creation(portfolio_service, test_user):
    """Test taking a portfolio snapshot."""
    # Setup initial portfolio state
    await portfolio_service.update_cash(Decimal("1000"))
    await portfolio_service.record_transaction(
        type="buy",
        symbol="AAPL",
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    
    # Take snapshot
    snapshot = await portfolio_service.take_snapshot()
    
    assert "value_eur" in snapshot
    assert "net_external_flows_eur" in snapshot
    assert snapshot["net_external_flows_eur"] == Decimal("1000")
    
    # Take another snapshot tomorrow and verify daily return
    pytest.freeze_time("2025-09-16").start()
    snapshot = await portfolio_service.take_snapshot()
    assert snapshot.get("daily_r_t") is not None


@pytest.mark.asyncio
async def test_performance_periods(portfolio_service, test_user):
    """Test performance data for different periods."""
    # Setup portfolio and take daily snapshots
    await portfolio_service.update_cash(Decimal("1000"))
    await portfolio_service.record_transaction(
        type="buy",
        symbol="AAPL",
        qty=Decimal("5"),
        price_ccy=Decimal("175.50")
    )
    
    # Take initial snapshot
    await portfolio_service.take_snapshot()
    
    # Get performance for different periods
    for period in ["d", "w", "m", "y"]:
        perf = await portfolio_service.get_performance(period)
        assert "snapshots" in perf
        assert "spx" in perf
        assert "gold" in perf
        assert "holdings" in perf


@pytest.mark.asyncio
async def test_movers_ranking(portfolio_service, test_user):
    """Test getting best/worst movers."""
    # Setup multiple positions
    symbols = [
        ("AAPL", Decimal("175.50"), Decimal("5")),
        ("MSFT", Decimal("250.00"), Decimal("3")),
        ("NVDA", Decimal("400.00"), Decimal("2"))
    ]
    
    for symbol, price, qty in symbols:
        await portfolio_service.record_transaction(
            type="buy",
            symbol=symbol,
            qty=qty,
            price_ccy=price
        )
        
    # Get movers for different periods
    for period in ["d", "w", "m", "y"]:
        movers = await portfolio_service.get_movers(period)
        # Should have all positions with performance data
        assert len(movers) == len(symbols)
        # Should be sorted by return percentage
        for m in movers[1:]:
            assert m["return_pct"] <= movers[0]["return_pct"]


@pytest.mark.asyncio
async def test_allocation_calculation(portfolio_service, test_user):
    """Test allocation breakdown and target comparison."""
    # Setup positions of different types
    positions = [
        ("SPY", "etf", Decimal("400.00"), Decimal("5")),
        ("AAPL", "stock", Decimal("175.50"), Decimal("10")),
        ("BTC", "crypto", Decimal("30000.00"), Decimal("0.1"))
    ]
    
    for symbol, type_, price, qty in positions:
        await portfolio_service.record_transaction(
            type="buy",
            symbol=symbol,
            qty=qty,
            price_ccy=price
        )
        
    # Get allocation without targets
    alloc = await portfolio_service.get_allocation()
    assert "current" in alloc
    assert "target" in alloc
    
    # Set targets
    await portfolio_service.set_allocation_targets(60, 30, 10)
    
    # Get updated allocation
    alloc = await portfolio_service.get_allocation()
    assert alloc["target"]["etf_pct"] == 60
    assert alloc["target"]["stock_pct"] == 30
    assert alloc["target"]["crypto_pct"] == 10