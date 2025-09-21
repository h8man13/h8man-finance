from __future__ import annotations

from typing import Any, Callable, Dict, List

from .base import BaseHandler

SnapshotBuilder = Callable[[Dict[str, Any], Dict[str, Any] | None], List[str]]
AllocationBuilder = Callable[[Dict[str, Any], tuple[str, Dict[str, Any] | None], tuple[str, Dict[str, Any] | None]], List[str]]


class PortfolioHandler(BaseHandler):
    """Handle portfolio related commands such as /portfolio and /add."""

    def __init__(
        self,
        ui: Dict[str, Any],
        session_service,
        dispatcher,
        settings,
        *,
        sticky_commands=None,
        snapshot_builder: SnapshotBuilder,
        allocation_builder: AllocationBuilder,
        formatting_service=None,
    ) -> None:
        super().__init__(
            ui,
            session_service,
            dispatcher,
            settings,
            sticky_commands=sticky_commands,
            formatting_service=formatting_service,
        )
        self._snapshot_builder = snapshot_builder
        self._allocation_builder = allocation_builder

    async def handle_portfolio(
        self,
        *,
        resp: Dict[str, Any],
    ) -> List[str]:
        return self._snapshot_builder(self.ui, resp.get("data", {})) or []

    async def handle_add(
        self,
        *,
        chat_id: int,
        values: Dict[str, Any],
        resp: Dict[str, Any],
    ) -> List[str]:
        formatter = self.formatting
        symbol = (values.get("symbol") or "").upper()
        qty_text = formatter.format_quantity(values.get("qty")) if formatter else str(values.get("qty"))
        success_payload = {"symbol": symbol, "qty": qty_text}
        success_pages = self.render_response("add_success", success_payload) or []
        snapshot_pages = self._snapshot_builder(self.ui, resp.get("data", {})) or []
        self.clear_session(chat_id)
        return success_pages + snapshot_pages

    async def handle_remove(
        self,
        *,
        chat_id: int,
        values: Dict[str, Any],
        resp: Dict[str, Any],
    ) -> List[str]:
        symbol = (values.get("symbol") or "").upper()
        success_pages = self.render_response("remove_success", {"symbol": symbol}) or []
        snapshot_pages = self._snapshot_builder(self.ui, resp.get("data", {})) or []
        self.clear_session(chat_id)
        return success_pages + snapshot_pages

    def handle_remove_confirmation(
        self,
        *,
        chat_id: int,
        spec,
        values: Dict[str, Any],
    ) -> List[str]:
        """Create confirmation session for remove command."""
        symbol = (values.get("symbol") or "").upper()
        if not symbol:
            return self.render_response("invalid_template", {
                "error": "symbol is required",
                "usage": spec.help.get("usage", ""),
                "example": spec.help.get("example", "")
            })

        ui_payload = {"symbol": symbol}
        self.create_session(
            chat_id,
            spec,
            values=values,
            missing=[],
            extra={
                "expected": [],
                "confirm": {
                    "payload": dict(values),
                    "values": dict(values),
                    "ui": ui_payload,
                },
            },
        )
        return self.render_response("remove_confirm", ui_payload)

    def handle_remove_cancelled(
        self,
        *,
        chat_id: int,
        confirm_state: Dict[str, Any],
    ) -> List[str]:
        """Handle remove cancellation."""
        self.clear_session(chat_id)
        return self.render_response("remove_cancelled", confirm_state.get("ui", {}))

    async def handle_cash_add(
        self,
        *,
        chat_id: int,
        values: Dict[str, Any],
    ) -> List[str]:
        formatter = self.formatting
        ui_values = dict(values)
        if formatter and values.get("amount_eur") is not None:
            ui_values["amount"] = formatter.format_eur(values.get("amount_eur"))
        pages = self.render_response("cash_add_success", ui_values)
        self.clear_session(chat_id)
        return pages

    async def handle_cash_remove(
        self,
        *,
        chat_id: int,
        values: Dict[str, Any],
        resp: Dict[str, Any],
    ) -> List[str]:
        formatter = self.formatting
        amount_display = formatter.format_eur(values.get("amount_eur")) if formatter else str(values.get("amount_eur"))
        success_pages = self.render_response("cash_remove_success", {"amount_display": amount_display}) or []
        snapshot_pages = self._snapshot_builder(self.ui, resp.get("data", {})) or []
        self.clear_session(chat_id)
        return success_pages + snapshot_pages

    def handle_cash_remove_confirmation(
        self,
        *,
        chat_id: int,
        spec,
        values: Dict[str, Any],
    ) -> List[str]:
        """Create confirmation session for cash_remove command."""
        formatter = self.formatting
        amount_dec = formatter.to_decimal(values.get("amount_eur")) if formatter else None

        if not amount_dec or amount_dec <= 0:
            return self.render_response("invalid_template", {
                "error": "amount must be greater than 0",
                "usage": spec.help.get("usage", ""),
                "example": spec.help.get("example", "")
            })

        amount_display = formatter.format_eur(amount_dec) if formatter else str(amount_dec)
        ui_payload = {"amount_display": amount_display}

        self.create_session(
            chat_id,
            spec,
            values=values,
            missing=[],
            extra={
                "expected": [],
                "confirm": {
                    "payload": dict(values),
                    "values": dict(values),
                    "ui": ui_payload,
                },
            },
        )
        return self.render_response("cash_remove_confirm", ui_payload)

    def handle_cash_remove_cancelled(
        self,
        *,
        chat_id: int,
        confirm_state: Dict[str, Any],
    ) -> List[str]:
        """Handle cash_remove cancellation."""
        self.clear_session(chat_id)
        return self.render_response("cash_remove_cancelled", confirm_state.get("ui", {}))

    def handle_confirmation_response(
        self,
        *,
        chat_id: int,
        spec,
        text: str,
        tokens: List[str],
        confirm_state: Dict[str, Any],
    ) -> tuple[bool, Dict[str, Any] | None, List[str] | None]:
        """
        Handle Y/N confirmation responses.
        Returns: (should_proceed, dispatch_values, response_pages)
        """
        if not confirm_state or text.strip().startswith("/"):
            return False, None, None

        answer_raw = (tokens[0] if tokens else text or "").strip().lower()

        if answer_raw in ("y", "yes"):
            # User confirmed - proceed with the action
            values = dict(confirm_state.get("values", {}))
            dispatch_values = dict(confirm_state.get("payload", {}))
            return True, dispatch_values, None

        elif answer_raw in ("n", "no"):
            # User cancelled - show cancellation message
            if spec.name == "/remove":
                pages = self.handle_remove_cancelled(chat_id=chat_id, confirm_state=confirm_state)
            elif spec.name == "/cash_remove":
                pages = self.handle_cash_remove_cancelled(chat_id=chat_id, confirm_state=confirm_state)
            else:
                self.clear_session(chat_id)
                pages = self.render_response("service_error", {"message": "Cancelled", "usage": "", "example": ""})
            return False, None, pages

        else:
            # Invalid response - re-show confirmation
            ui_data = confirm_state.get("ui", {})
            if spec.name == "/remove":
                pages = self.render_response("remove_confirm", ui_data)
            elif spec.name == "/cash_remove":
                pages = self.render_response("cash_remove_confirm", ui_data)
            else:
                pages = self.render_response("service_error", {"message": "Please reply Y or N", "usage": "", "example": ""})
            return False, None, pages

    async def handle_cash_overview(
        self,
        *,
        resp: Dict[str, Any] = None,
        user_context: Dict[str, Any] = None,
        return_formatted_only: bool = False,
    ) -> List[str] | str:
        # If no resp provided, fetch cash data ourselves
        if resp is None and user_context is not None:
            cash_dispatch_spec = {
                "service": "portfolio_core",
                "method": "GET",
                "path": "/cash"
            }
            resp = await self.dispatcher.dispatch(cash_dispatch_spec, {}, user_context)
            if not resp.get("ok"):
                return "0€" if return_formatted_only else self.render_response("cash_zero", {})

        formatter = self.formatting
        if not formatter:
            return "0€" if return_formatted_only else self.render_response("cash_zero", {})

        cash_dec = formatter.to_decimal(resp.get("data", {}).get("cash_eur"))
        formatted_balance = formatter.format_eur(cash_dec)

        # Return just the formatted balance for prompts
        if return_formatted_only:
            return formatted_balance

        # Return rendered response for normal cash command
        if cash_dec == 0:
            return self.render_response("cash_zero", {})
        return self.render_response("cash_result", {"cash_balance": formatted_balance})

    async def handle_transactions(
        self,
        *,
        resp: Dict[str, Any],
    ) -> List[str]:
        formatter = self.formatting
        payload = resp.get("data", {})
        transactions = payload.get("transactions", []) or []
        if not transactions:
            return self.render_response("tx_empty", {})
        rows: List[List[str]] = [["DATE", "TYPE", "SYMBOL", "QTY", "AMOUNT"]]
        for tx in transactions:
            ts_raw = tx.get("ts")
            timestamp = ts_raw.replace("T", " ")[:16] if isinstance(ts_raw, str) and ts_raw else ""
            tx_type = str(tx.get("type") or "").upper()
            symbol = str(tx.get("symbol") or "CASH")
            qty = formatter.format_quantity(tx.get("qty")) if formatter and tx.get("qty") is not None else ""
            amount = formatter.format_eur(tx.get("amount_eur")) if formatter and tx.get("amount_eur") is not None else ""
            rows.append([timestamp, tx_type, symbol, qty, amount])
        count = payload.get("count")
        total = count if isinstance(count, int) else len(transactions)
        summary = f"Showing {total} transaction{'s' if total != 1 else ''}"
        return self.render_response(
            "tx_result",
            {"transaction_summary": summary, "table_rows": rows},
        )

    async def handle_allocation_view(
        self,
        *,
        resp: Dict[str, Any],
    ) -> List[str]:
        allocation = resp.get("data", {}) or {}
        return self._allocation_builder(
            self.ui,
            ("Current", allocation.get("current")),
            ("Target", allocation.get("target")),
        )

    async def handle_allocation_edit(
        self,
        *,
        chat_id: int,
        values: Dict[str, Any],
        resp: Dict[str, Any],
    ) -> List[str]:
        allocation = resp.get("data", {}) or {}
        target = allocation.get("target", {})
        success_data = {
            "stock_target_pct": target.get("stock_pct", values.get("stock_pct", 0)),
            "etf_target_pct": target.get("etf_pct", values.get("etf_pct", 0)),
            "crypto_target_pct": target.get("crypto_pct", values.get("crypto_pct", 0)),
        }
        pages = self.render_response("allocation_edit_success", success_data)
        self.clear_session(chat_id)
        return pages

    async def handle_rename(
        self,
        *,
        chat_id: int,
        values: Dict[str, Any],
        resp: Dict[str, Any],
    ) -> List[str]:
        rename_payload = resp.get("data", {}).get("rename", {}) or {}
        symbol = (rename_payload.get("symbol") or values.get("symbol") or "").upper()
        nickname_raw = rename_payload.get("display_name") or values.get("display_name") or ""
        nickname = nickname_raw.strip()
        pages = self.render_response("rename_success", {"symbol": symbol, "nickname": nickname})
        self.clear_session(chat_id)
        return pages


