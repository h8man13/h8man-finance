"""Tests for analytics service."""
import pytest
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

from app.services.analytics import AnalyticsService


@pytest.mark.asyncio
async def test_bucket_boundaries(analytics_service):
    """Test bucket boundary calculation."""
    ref_date = date(2023, 6, 15)  # A Thursday

    # Daily boundaries
    d_boundaries = analytics_service._get_bucket_boundaries("d", ref_date)
    assert len(d_boundaries) == 1
    assert d_boundaries[0] == ref_date

    # Weekly boundaries
    w_boundaries = analytics_service._get_bucket_boundaries("w", ref_date)
    assert len(w_boundaries) == 7

    # Monthly boundaries (4 weekly Friday closes)
    m_boundaries = analytics_service._get_bucket_boundaries("m", ref_date)
    assert len(m_boundaries) == 4

    # Yearly boundaries (YTD monthly)
    y_boundaries = analytics_service._get_bucket_boundaries("y", ref_date)
    assert len(y_boundaries) == 6  # Jan through Jun


@pytest.mark.asyncio
async def test_calculate_twr(analytics_service):
    """Test TWR calculation logic."""
    # Mock snapshots and flows
    snapshots = [
        {"date": "2023-01-01", "value_eur": 10000},
        {"date": "2023-01-02", "value_eur": 10200},
        {"date": "2023-01-03", "value_eur": 10100},
    ]

    flows = [
        {"date": "2023-01-02", "amount_eur": 0},  # No flows
    ]

    twr_pct, daily_returns = await analytics_service.calculate_twr(
        date(2023, 1, 1), date(2023, 1, 3), snapshots, flows
    )

    # TWR should be calculated correctly
    assert isinstance(twr_pct, Decimal)
    assert len(daily_returns) > 0


@pytest.mark.asyncio
async def test_get_portfolio_snapshot(analytics_service):
    """Test portfolio snapshot for period."""
    # This will test the endpoint integration
    snapshot = await analytics_service.get_portfolio_snapshot("d")

    # Should return a snapshot even with no data
    assert "bucket_performance" in snapshot
    assert "bucket_end_date" in snapshot
    assert "bucket_start_date" in snapshot