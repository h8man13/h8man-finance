from __future__ import annotations

from typing import Any, Dict

from .base import BaseHandler


class TradingHandler(BaseHandler):
    """Handle trading commands such as /buy and /sell."""

    async def handle_buy(self, *, chat_id: int, values: Dict[str, Any]) -> list[str]:
        formatter = self.formatting
        symbol = (values.get("symbol") or "").upper()
        qty_text = formatter.format_quantity(values.get("qty")) if formatter else str(values.get("qty"))
        price_display = "market"
        if formatter and values.get("price_eur") not in (None, ""):
            price_display = formatter.format_eur(values.get("price_eur"))
        pages = self.render_response(
            "buy_success",
            {"symbol": symbol, "qty": qty_text, "price_ccy": price_display},
        )
        self.clear_session(chat_id)
        return pages

    async def handle_sell(self, *, chat_id: int, values: Dict[str, Any]) -> list[str]:
        formatter = self.formatting
        symbol = (values.get("symbol") or "").upper()
        qty_text = formatter.format_quantity(values.get("qty")) if formatter else str(values.get("qty"))
        price_display = "market"
        if formatter and values.get("price_eur") not in (None, ""):
            price_display = formatter.format_eur(values.get("price_eur"))
        pages = self.render_response(
            "sell_success",
            {"symbol": symbol, "qty": qty_text, "price_ccy": price_display},
        )
        self.clear_session(chat_id)
        return pages
