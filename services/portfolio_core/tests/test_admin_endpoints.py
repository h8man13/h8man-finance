"""
Tests for admin endpoints.
"""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

from app.main import app
from app.db import init_db


@pytest.fixture
def client():
    """Test client fixture with database initialization."""
    return TestClient(app)


def test_admin_health_endpoint(client):
    """Test admin health endpoint."""
    with patch('app.api.fx_client') as mock_fx, \
         patch('app.api.market_data_client') as mock_md:

        # Mock healthy services
        mock_fx.health_check.return_value = True
        mock_fx.cache = {}
        mock_md.health_check.return_value = True
        mock_md.get_cache_stats.return_value = {
            "quotes_cached": 0,
            "meta_cached": 0,
            "quotes_valid": 0,
            "meta_valid": 0
        }

        response = client.get("/admin/health")
        assert response.status_code == 200

        data = response.json()
        print(f"Response data: {data}")  # Debug output
        assert data.get("ok") is True
        assert "database" in data.get("data", {})
        assert "fx_service" in data.get("data", {})
        assert "market_data_service" in data.get("data", {})
        assert data.get("data", {}).get("database", {}).get("healthy") is True


def test_run_snapshots_endpoint_no_users(client):
    """Test snapshot run endpoint when no users exist."""
    response = client.post("/admin/snapshots/run")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["data"]["processed_users"] == 0
    assert data["data"]["results"] == []


def test_run_snapshots_endpoint_specific_user(client):
    """Test snapshot run endpoint for specific user."""
    # This test would need a user with positions, but for now just test the endpoint structure
    response = client.post("/admin/snapshots/run?user_id=12345")
    assert response.status_code == 200

    data = response.json()
    # This will likely fail with no snapshot data, but endpoint should be reachable
    # In a real test environment, we'd set up test data first


def test_get_snapshots_status_endpoint(client):
    """Test snapshot status endpoint."""
    response = client.get("/admin/snapshots/status")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert "users" in data["data"]
    assert "total_users" in data["data"]
    assert data["data"]["total_users"] == 0  # No users in test DB


def test_get_snapshots_status_specific_user(client):
    """Test snapshot status endpoint for specific user."""
    response = client.get("/admin/snapshots/status?user_id=12345")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert "user_id" in data["data"]
    assert "recent_snapshots" in data["data"]
    assert data["data"]["user_id"] == 12345
    assert data["data"]["recent_snapshots"] == []  # No snapshots for test user


def test_cleanup_snapshots_endpoint(client):
    """Test snapshot cleanup endpoint."""
    response = client.delete("/admin/snapshots/cleanup?days_to_keep=30")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert "deleted_snapshots" in data["data"]
    assert "cutoff_date" in data["data"]
    assert data["data"]["deleted_snapshots"] == 0  # No snapshots to delete


def test_cleanup_snapshots_specific_user(client):
    """Test snapshot cleanup endpoint for specific user."""
    response = client.delete("/admin/snapshots/cleanup?user_id=12345&days_to_keep=30")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert "user_id" in data["data"]
    assert "deleted_snapshots" in data["data"]
    assert data["data"]["user_id"] == 12345
    assert data["data"]["deleted_snapshots"] == 0  # No snapshots to delete


@pytest.mark.asyncio
async def test_admin_endpoints_with_mock_data():
    """Test admin endpoints with mocked data for comprehensive testing."""
    from app.db import open_db
    from app.models import UserContext
    from app.services.analytics import AnalyticsService

    # This would be a more comprehensive test with actual database setup
    # For now, just ensure the endpoints are properly structured
    pass


def test_admin_endpoints_error_handling():
    """Test error handling in admin endpoints."""
    # Test with invalid parameters
    client = TestClient(app)

    # Invalid days_to_keep
    response = client.delete("/admin/snapshots/cleanup?days_to_keep=-1")
    # Should handle validation errors gracefully

    # Invalid user_id
    response = client.get("/admin/snapshots/status?user_id=invalid")
    # Should handle type conversion errors gracefully


@pytest.mark.asyncio
async def test_snapshot_cron_integration():
    """Test that admin endpoints work as expected for cron job integration."""
    # This test would verify that the admin endpoints respond correctly
    # to the snapshot cron job calls

    client = TestClient(app)

    # Test the sequence that the cron job would follow:
    # 1. Health check
    response = client.get("/admin/health")
    assert response.status_code == 200

    # 2. Get status before
    response = client.get("/admin/snapshots/status")
    assert response.status_code == 200

    # 3. Run snapshots
    response = client.post("/admin/snapshots/run")
    assert response.status_code == 200

    # 4. Cleanup old snapshots
    response = client.delete("/admin/snapshots/cleanup")
    assert response.status_code == 200

    # 5. Get status after
    response = client.get("/admin/snapshots/status")
    assert response.status_code == 200