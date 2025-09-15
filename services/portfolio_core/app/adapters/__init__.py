"""
External service adapters for portfolio_core.
"""
from .fx_client import fx_client, FxClient, FxRate
from .market_data_client import market_data_client, MarketDataClient, Quote, SymbolMeta

__all__ = [
    "fx_client",
    "FxClient",
    "FxRate",
    "market_data_client",
    "MarketDataClient",
    "Quote",
    "SymbolMeta"
]