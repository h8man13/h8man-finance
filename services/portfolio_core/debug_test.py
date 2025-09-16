#!/usr/bin/env python3
import os
import asyncio
os.environ["DB_PATH"] = "/tmp/portfolio_debug.db"

from fastapi.testclient import TestClient
import json
from app.main import app
from app.db import init_db

# Initialize database manually for testing
asyncio.run(init_db("/tmp/portfolio_debug.db"))

client = TestClient(app)

# Test health endpoint first
health_response = client.get("/health")
print("Health Response:")
print(f"Status: {health_response.status_code}")
print(f"Body: {health_response.text}")
print()

# Test portfolio endpoint
portfolio_params = {
    "user_id": 12345,
    "first_name": "Test",
    "last_name": "User",
    "username": "testuser",
    "language_code": "en"
}

portfolio_response = client.get("/portfolio", params=portfolio_params)
print("Portfolio Response:")
print(f"Status: {portfolio_response.status_code}")
print(f"Body: {portfolio_response.text}")

try:
    portfolio_data = portfolio_response.json()
    print(f"JSON: {json.dumps(portfolio_data, indent=2)}")
except:
    print("Failed to parse JSON")