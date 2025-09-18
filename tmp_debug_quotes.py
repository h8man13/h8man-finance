import asyncio
from services.portfolio_core.app.clients import MarketDataClient
from services.portfolio_core.app.settings import settings
import respx
from httpx import Response

async def main():
    settings.MARKET_DATA_BASE_URL = "http://market-data.test"
    client = MarketDataClient()
    client._base_url = settings.MARKET_DATA_BASE_URL.rstrip('/')
    with respx.mock:
        route = respx.get("http://market-data.test/quote").mock(return_value=Response(200, json={
            "ok": True,
            "data": {"quotes": [{"symbol": "AAPL", "price_eur": 150, "currency": "USD", "market": "US"}]}
        }))
        await client.get_quotes(["aapl"])
        print('call count after first', route.call_count)
        route.calls.reset()
        print('call count after reset', route.call_count)
        print('route.called after reset', route.called)
        await client.get_quotes(["AAPL"])
        print('call count after second', route.call_count)
        print('route.called final', route.called)

asyncio.run(main())
