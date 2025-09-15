"""
Client for interacting with the market_data service.
"""
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime
from decimal import Decimal

from ..settings import settings


class MarketDataClient:
    def __init__(self):
        self.base_url = settings.MARKET_DATA_URL
        self.timeout = httpx.Timeout(30.0)
        # Flag set by tests to indicate mock mode
        self._mock_mode = False
        self._mock_data = {}

    def enable_mock_mode(self, mock_data: Dict[str, Any] = None):
        """Enable mock mode for testing."""
        self._mock_mode = True
        self._mock_data = mock_data or {}

    def disable_mock_mode(self):
        """Disable mock mode."""
        self._mock_mode = False
        self._mock_data = {}

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make a request to market_data service."""
        if self._mock_mode:
            # Handle mock data based on endpoint and parameters
            mock_data = self._mock_data.get(path, {})
            
            # Handle specific endpoint parameter processing
            if path == "/quote":
                # Filter quotes by requested symbols
                if "params" in kwargs and "symbols" in kwargs["params"]:
                    requested_symbols = set(kwargs["params"]["symbols"].split(","))
                    mock_data["quotes"] = [
                        q for q in mock_data.get("quotes", [])
                        if q["symbol"] in requested_symbols
                    ]
            elif path == "/meta":
                # Return specific symbol metadata
                if "params" in kwargs and "symbol" in kwargs["params"]:
                    symbol = kwargs["params"]["symbol"]
                    mock_data = mock_data.get(symbol, {
                        "symbol": symbol,
                        "market": "US",  # Default values
                        "currency": "USD",
                        "asset_class": "stock"
                    })
            elif path == "/benchmarks":
                # Filter benchmarks by requested symbols
                if "params" in kwargs and "symbols" in kwargs["params"]:
                    requested_symbols = set(kwargs["params"]["symbols"].split(","))
                    mock_data = {
                        symbol: mock_data[symbol]
                        for symbol in mock_data
                        if symbol in requested_symbols
                    }
            
            return mock_data
            
        url = f"{self.base_url}{path}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, **kwargs)
            data = response.json()
            
            if not isinstance(data, dict):
                raise ValueError("Invalid response from market_data")
                
            if not data.get("ok", False):
                error = data.get("error", {})
                raise ValueError(f"market_data error: {error.get('message', 'Unknown error')}")
                
            return data.get("data", {})

    async def get_quote(self, symbols: List[str]) -> Dict[str, Any]:
        """Get quotes for multiple symbols."""
        params = {"symbols": ",".join(symbols)}
        return await self._request("GET", "/quote", params=params)

    async def get_meta(self, symbol: str) -> Dict[str, Any]:
        """Get metadata for a symbol."""
        params = {"symbol": symbol}
        return await self._request("GET", "/meta", params=params)

    async def get_benchmarks(self, period: str, symbols: List[str]) -> Dict[str, Any]:
        """Get benchmark data for symbols."""
        params = {
            "period": period,
            "symbols": ",".join(symbols)
        }
        return await self._request("GET", "/benchmarks", params=params)

    async def get_performance(self, symbols: List[str], period: str) -> Dict[str, Any]:
        """Get performance data for symbols."""
        params = {
            "symbols": ",".join(symbols),
            "period": period
        }
        return await self._request("GET", "/performance", params=params)


# Singleton instance
market_data = MarketDataClient()