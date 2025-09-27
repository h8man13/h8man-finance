from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .base import BaseHandler


class TradingHandler(BaseHandler):
    """Handle trading commands such as /buy and /sell."""

    async def handle_buy(self, *, chat_id: int, values: Dict[str, Any], resp: Dict[str, Any]) -> List[str]:
        """Render /buy success screen with resolved price."""
        _ = resp
        formatter = self.formatting
        symbol = (values.get("symbol") or "").upper()
        qty_text = formatter.format_quantity(values.get("qty")) if formatter else str(values.get("qty"))
        price_display = await self._resolve_price_display(symbol, values.get("price_eur"))
        pages = self.render_response(
            "buy_success",
            {"symbol": symbol, "qty": qty_text, "price_ccy": price_display},
        )
        self.clear_session(chat_id)
        return pages

    async def handle_sell(self, *, chat_id: int, values: Dict[str, Any], resp: Dict[str, Any]) -> List[str]:
        """Render /sell success screen with resolved price."""
        _ = resp
        formatter = self.formatting
        symbol = (values.get("symbol") or "").upper()
        qty_text = formatter.format_quantity(values.get("qty")) if formatter else str(values.get("qty"))
        price_display = await self._resolve_price_display(symbol, values.get("price_eur"))
        pages = self.render_response(
            "sell_success",
            {"symbol": symbol, "qty": qty_text, "price_ccy": price_display},
        )
        self.clear_session(chat_id)
        return pages

    async def _resolve_price_display(self, symbol: str, provided_price: Any) -> str:
        """Return formatted price for trading success messages."""
        formatter = self.formatting
        if provided_price not in (None, ""):
            return formatter.format_eur(provided_price) if formatter else str(provided_price)
        quote_price = await self._fetch_quote_price(symbol)
        if quote_price is not None:
            return formatter.format_eur(quote_price) if formatter else str(quote_price)
        return "market"

    async def _fetch_quote_price(self, symbol: str) -> Optional[float]:
        if not symbol:
            return None
        base = symbol.strip().upper()
        candidates: List[str] = []
        if base:
            candidates.append(base)
            if "." not in base:
                candidates.append(f"{base}.US")
        seen: set[str] = set()
        spec = {"service": "market_data", "method": "GET", "path": "/quote", "args_map": {"symbols": "symbols"}}
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            result = await self.dispatcher.dispatch(spec, {"symbols": [candidate]})
            if not isinstance(result, dict) or not result.get("ok"):
                continue
            quotes = ((result.get("data") or {}).get("quotes") or [])
            if not isinstance(quotes, list):
                continue
            price = self._extract_quote_price(quotes, candidate)
            if price is not None:
                return price
        return None

    def _extract_quote_price(self, quotes: Iterable[Dict[str, Any]], target: str) -> Optional[float]:
        target_upper = target.upper()
        fallback_price = None
        for quote in quotes or []:
            symbol = str(quote.get("symbol") or "").upper()
            price_value = quote.get("price_eur") or quote.get("price")
            if price_value in (None, ""):
                continue
            try:
                price_float = float(price_value)
            except (TypeError, ValueError):
                continue
            if symbol == target_upper:
                return price_float
            if fallback_price is None:
                fallback_price = price_float
        return fallback_price


