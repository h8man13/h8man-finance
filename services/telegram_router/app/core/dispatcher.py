from __future__ import annotations

from typing import Any, Dict

from ..connectors.http import HTTPClient
from ..connectors.market_data import MarketDataClient
from ..connectors.portfolio_core import PortfolioCoreClient
from ..connectors.fx import FXClient


class Dispatcher:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.market_data = MarketDataClient(http)
        self.portfolio = PortfolioCoreClient(http)
        self.fx = FXClient(http)

    async def dispatch(self, spec: Dict[str, Any], args: Dict[str, Any], user_context: Dict[str, Any] = None) -> Dict[str, Any]:
        service = spec.get("service")
        method = spec.get("method", "GET").upper()
        path = spec.get("path", "/")
        args_map: Dict[str, str] = spec.get("args_map", {})
        payload: Dict[str, Any] = {to: args.get(frm) for frm, to in args_map.items()}

        # Market data
        if service == "market_data":
            if path == "/quote" and method == "GET":
                symbols = payload.get("symbols") or []
                if isinstance(symbols, str):
                    symbols = [symbols]
                try:
                    return await self.market_data.get_quotes(symbols=symbols)
                except Exception as e:
                    return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": str(e), "source": "market_data", "retriable": True}}

        # FX
        if service == "fx":
            if path == "/fx" and method == "GET":
                base = (payload.get("base") or "").strip()
                quote = (payload.get("quote") or "").strip()
                if not base or not quote:
                    return {"ok": True, "data": {"fx_prompt": True}}
                try:
                    data = await self.fx.get_fx(base=base, quote=quote, force=True)
                    return {"ok": True, "data": data}
                except Exception as e:
                    return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": str(e), "source": "fx", "retriable": True}}

        if service == "portfolio_core":
            base = self.portfolio.base
            url = f"{base}{path}"
            query_params = {k: v for k, v in (user_context or {}).items() if v is not None}
            body = {k: v for k, v in payload.items() if v is not None}
            try:
                if method == "GET":
                    params = {**body, **query_params}
                    return (await self.http.request("GET", url, params=params)).json()
                if method == "POST":
                    return (await self.http.request("POST", url, params=query_params, json=body)).json()
            except Exception as e:
                return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": str(e), "source": "portfolio_core", "retriable": True}}

        return {"ok": False, "error": {"code": "unknown_dispatch", "message": f"No route for {service} {method} {path}"}}