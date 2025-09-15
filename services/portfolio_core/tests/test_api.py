"""Tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from app.main import app


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


@pytest.fixture
def mock_auth_header():
    """Mock auth header for test user."""
    return {"Authorization": "Bearer test_token"}


def test_create_portfolio(client, mock_auth_header):
    """Test portfolio creation endpoint."""
    portfolio_data = {
        "name": "Test Portfolio",
        "description": "Test description",
        "base_currency": "USD"
    }
    
    response = client.post("/portfolios/", json=portfolio_data, headers=mock_auth_header)
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == portfolio_data["name"]
    assert data["description"] == portfolio_data["description"]
    assert data["base_currency"] == portfolio_data["base_currency"]


def test_get_portfolios(client, mock_auth_header):
    """Test getting user portfolios endpoint."""
    # Create test portfolios first
    portfolio_data = [
        {"name": "Portfolio 1", "description": "Test 1", "base_currency": "USD"},
        {"name": "Portfolio 2", "description": "Test 2", "base_currency": "EUR"}
    ]
    
    for data in portfolio_data:
        client.post("/portfolios/", json=data, headers=mock_auth_header)
    
    # Get portfolios
    response = client.get("/portfolios/", headers=mock_auth_header)
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == len(portfolio_data)
    for portfolio, expected in zip(data, portfolio_data):
        assert portfolio["name"] == expected["name"]


def test_add_position(client, mock_auth_header):
    """Test adding position endpoint."""
    # Create portfolio first
    portfolio = client.post(
        "/portfolios/",
        json={"name": "Test", "description": "Test", "base_currency": "USD"},
        headers=mock_auth_header
    ).json()
    
    # Add position
    position_data = {
        "symbol": "AAPL",
        "quantity": 10,
        "avg_price": 150.0,
        "currency": "USD"
    }
    
    response = client.post(
        f"/portfolios/{portfolio['id']}/positions/",
        json=position_data,
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == position_data["symbol"]
    assert data["quantity"] == position_data["quantity"]


def test_add_transaction(client, mock_auth_header):
    """Test adding transaction endpoint."""
    # Create portfolio and position first
    portfolio = client.post(
        "/portfolios/",
        json={"name": "Test", "description": "Test", "base_currency": "USD"},
        headers=mock_auth_header
    ).json()
    
    position = client.post(
        f"/portfolios/{portfolio['id']}/positions/",
        json={"symbol": "AAPL", "quantity": 0, "avg_price": 0, "currency": "USD"},
        headers=mock_auth_header
    ).json()
    
    # Add transaction
    transaction_data = {
        "quantity": 5,
        "price": 150.0,
        "date": datetime.now(timezone.utc).isoformat()
    }
    
    response = client.post(
        f"/portfolios/{portfolio['id']}/positions/{position['id']}/transactions/",
        json=transaction_data,
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["quantity"] == transaction_data["quantity"]
    assert data["price"] == transaction_data["price"]


def test_get_portfolio_performance(client, mock_auth_header):
    """Test getting portfolio performance endpoint."""
    # Create portfolio with position and transaction
    portfolio = client.post(
        "/portfolios/",
        json={"name": "Test", "description": "Test", "base_currency": "USD"},
        headers=mock_auth_header
    ).json()
    
    # Get performance
    params = {
        "start_date": (datetime.now(timezone.utc).isoformat()),
        "end_date": (datetime.now(timezone.utc).isoformat())
    }
    
    response = client.get(
        f"/portfolios/{portfolio['id']}/performance/",
        params=params,
        headers=mock_auth_header
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "return_pct" in data