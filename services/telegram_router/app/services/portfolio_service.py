from __future__ import annotations

from decimal import Decimal
from functools import partial
from typing import Any, Dict, List, Tuple

from ..ui.loader import render_screen
from .formatting_service import FormattingService


def prepare_portfolio_payload(
    command: str,
    values: Dict[str, Any],
    formatter: FormattingService,
) -> Dict[str, Any]:
    prepared: Dict[str, Any] = {}
    name = command.lower()
    if name in ("/add", "/buy", "/sell"):
        qty_str = formatter.decimal_str(values.get("qty"))
        if qty_str is not None:
            prepared["qty"] = qty_str
            values["qty"] = qty_str
        symbol = values.get("symbol")
        if symbol:
            prepared["symbol"] = str(symbol).strip().upper()
            values["symbol"] = prepared["symbol"]
        if name == "/add":
            asset_class = values.get("asset_class")
            if asset_class:
                prepared["asset_class"] = str(asset_class).lower()
        if name in ("/buy", "/sell"):
            for key in ("price_eur", "fees_eur"):
                normalized = formatter.decimal_str(values.get(key))
                if normalized is not None:
                    prepared[key] = normalized
                    values[key] = prepared[key]
        return prepared
    if name in ("/remove", "/rename"):
        symbol = values.get("symbol")
        if symbol:
            prepared["symbol"] = str(symbol).strip().upper()
            values["symbol"] = prepared["symbol"]
        if name == "/rename":
            display_name = values.get("display_name")
            if display_name:
                normalized = str(display_name).strip()
                prepared["display_name"] = normalized
                values["display_name"] = normalized
        return prepared
    if name in ("/cash_add", "/cash_remove"):
        normalized = formatter.decimal_str(values.get("amount_eur"))
        if normalized is not None:
            prepared["amount_eur"] = normalized
            values["amount_eur"] = normalized
        return prepared
    if name == "/allocation_edit":
        for key in ("stock_pct", "etf_pct", "crypto_pct"):
            if values.get(key) is not None:
                prepared[key] = int(values[key])
                values[key] = prepared[key]
        return prepared
    if name == "/tx":
        if values.get("limit") is not None:
            prepared["limit"] = int(values["limit"])
            values["limit"] = prepared["limit"]
        return prepared
    if name == "/po_if":
        scope = values.get("scope")
        if scope:
            normalized_scope = str(scope).strip()
            prepared["scope"] = normalized_scope
            values["scope"] = normalized_scope
        delta_str = formatter.decimal_str(values.get("delta_pct"))
        if delta_str is not None:
            prepared["delta_pct"] = delta_str
            values["delta_pct"] = delta_str
        return prepared
    return {k: v for k, v in values.items() if v is not None}


def portfolio_table_pages(
    ui: Dict[str, Any],
    portfolio: Dict[str, Any] | None,
    formatter: FormattingService,
) -> List[str]:
    if not ui or portfolio is None:
        return []

    holdings = portfolio.get("holdings") or []
    cash_dec = formatter.to_decimal(portfolio.get("cash_eur"))

    if not holdings and cash_dec == 0:
        pages = render_screen(ui, "portfolio_empty", {})
        return [p for p in pages] if pages else []

    rows: List[List[str]] = [["TICKER", "CLASS", "QTY", "PRICE", "TOTAL"]]

    holdings_total = Decimal("0")
    for holding in holdings:
        symbol = str(holding.get("symbol") or "").upper()
        display_symbol = symbol.replace(".US", "") if symbol.endswith(".US") else symbol
        display_name = holding.get("display_name")
        ticker = display_symbol if not display_name else f"{display_symbol} ({display_name})"
        asset_class = (holding.get("asset_class") or "-").lower()
        market = (holding.get("market") or "-").upper()
        qty = formatter.format_quantity(holding.get("qty_total"))
        price = "-" if holding.get("price_eur") is None else formatter.format_eur(holding.get("price_eur"))
        value_dec = formatter.to_decimal(holding.get("value_eur"))
        value = formatter.format_eur(value_dec)
        holdings_total += value_dec
        rows.append([ticker, asset_class, qty, price, value])

    if cash_dec > 0:
        cash_display = formatter.format_eur(cash_dec)
        rows.append(["Cash", "cash", "-", cash_display, cash_display])

    total_dec = formatter.to_decimal(portfolio.get("total_value_eur"), default=holdings_total + cash_dec)
    data = {"total_value": formatter.format_eur(total_dec), "table_rows": rows}
    pages = render_screen(ui, "portfolio_result", data)
    return [p for p in pages] if pages else []


def portfolio_pages_with_fallback(
    ui: Dict[str, Any],
    portfolio: Dict[str, Any] | None,
    formatter: FormattingService,
) -> List[str]:
    pages = portfolio_table_pages(ui, portfolio, formatter)
    if pages:
        return pages
    fallback = render_screen(ui, "portfolio_empty", {})
    return [p for p in fallback] if fallback else []


def allocation_rows(entries: List[Tuple[str, Dict[str, Any]]], formatter: FormattingService) -> List[List[str]]:
    rows: List[List[str]] = [["", "STOCK", "ETF", "CRYPTO"]]
    for label, payload in entries:
        payload = payload or {}
        rows.append([
            label,
            formatter.format_percent(payload.get("stock_pct")),
            formatter.format_percent(payload.get("etf_pct")),
            formatter.format_percent(payload.get("crypto_pct")),
        ])
    return rows


def allocation_table_pages(
    ui: Dict[str, Any],
    formatter: FormattingService,
    *entries: Tuple[str, Dict[str, Any]],
) -> List[str]:
    if not ui or not entries:
        return []
    rows = allocation_rows(list(entries), formatter)
    pages = render_screen(ui, "allocation_result", {"table_rows": rows})
    return [p for p in pages] if pages else []


def analytic_json_pages(ui: Dict[str, Any], resp: Dict[str, Any]) -> List[str]:
    data = resp.get("data", {})
    if data:
        import json

        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        return [f"```json\n{formatted}\n```"]
    return ["No data available"]
