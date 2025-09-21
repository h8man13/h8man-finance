from __future__ import annotations

from typing import Any, Dict, List

from ..core.registry import CommandSpec
from ..core.templates import mdv2_blockquote, mdv2_expandable_blockquote
from ..services import market_label, freshness_label
from .base import BaseHandler


class MarketHandler(BaseHandler):
    """Handle market oriented commands such as /price and /fx."""

    async def handle_price(
        self,
        *,
        chat_id: int,
        spec: CommandSpec,
        values: Dict[str, Any],
        resp: Dict[str, Any],
        clear_after: bool,
    ) -> list[str]:
        formatter = self.formatting
        data = resp.get("data", {})
        quotes = data.get("quotes") or []
        ttl_min = self.ttl_minutes()

        if not quotes:
            self.create_session(chat_id, spec, values={}, missing=[])
            requested = [str(x).upper() for x in (values.get("symbols") or [])]
            if requested:
                payload = {"ttl_min": ttl_min, "not_found_symbols": requested}
                pages = self.render_response("price_not_found", payload)
                if not pages:
                    return []
                note = (
                    formatter.format_error_note("Tickers couldn't be found.")
                    if formatter
                    else mdv2_blockquote(["Tickers couldn't be found."])
                )
                first_page = f"{pages[0]}\n\n{note}"
                return [first_page] + list(pages[1:])
            return self.render_response("price_prompt", {"ttl_min": ttl_min})

        rows: List[List[str]] = [["TICKER", "NOW", "OPEN", "%", "MARKET", "FRESHNESS"]]
        for q in quotes:
            sym = str(q.get("symbol") or "").upper()
            disp = q.get("display") or sym
            market = q.get("market") or ""
            star = "*" if market and market != "US" else ""
            try:
                now_eur = float(q.get("price_eur")) if q.get("price_eur") is not None else None
                open_eur = float(q.get("open_eur")) if q.get("open_eur") is not None else None
            except Exception:
                now_eur = None
                open_eur = None
            pct = None
            if now_eur is not None and open_eur is not None and open_eur != 0:
                pct = (now_eur - open_eur) / open_eur * 100.0
            if formatter:
                now_txt = formatter.format_optional_eur(now_eur)
                open_txt = formatter.format_optional_eur(open_eur)
                pct_txt = formatter.format_signed_percent(pct, default="n/a")
            else:
                now_txt = str(now_eur) if now_eur is not None else "n/a"
                open_txt = str(open_eur) if open_eur is not None else "n/a"
                pct_txt = f"{pct:+.1f}%" if pct is not None else "n/a"
            market_display = market_label(sym, market)
            freshness_display = freshness_label(str(q.get("freshness") or ""))
            rows.append([f"{disp}{star}", now_txt, open_txt, pct_txt, market_display, freshness_display])

        partial = bool(resp.get("partial"))
        details = resp.get("error", {}).get("details", {}) if isinstance(resp.get("error"), dict) else {}
        failed = details.get("symbols_failed") or []
        requested = [str(x).upper() for x in (values.get("symbols") or [])] if isinstance(values.get("symbols"), list) else []
        present = [str(q.get("symbol") or "").upper() for q in quotes]
        derived_missing = [s for s in requested if not any(p.startswith(s) for p in present)] if requested else []
        effective_failed = failed or derived_missing
        has_missing = isinstance(effective_failed, list) and len(effective_failed) > 0

        base_screen = "price_partial_error" if has_missing else "price_partial_note" if partial else "price_result"
        screen_payload = {
            "table_rows": rows,
            "not_found_symbols": effective_failed or [],
            "ttl_min": ttl_min,
        }
        pages = self.render_response(base_screen, screen_payload)
        if not pages:
            return []
        text = pages[0]
        interactive_hint_needed = (not clear_after) or has_missing or partial

        if has_missing:
            note = (
                formatter.format_error_note("Tickers couldn't be found.")
                if formatter
                else mdv2_blockquote(["Tickers couldn't be found."])
            )
            text = f"{text}\n\n{note}"

        if partial or has_missing:
            self.create_session(chat_id, spec, values={}, missing=[])
        elif not clear_after:
            self.create_session(chat_id, spec, values={}, missing=[])
        else:
            self.clear_session(chat_id)

        footnotes = ""
        if not has_missing:
            if resp.get("partial") or (isinstance(resp.get("error"), dict) and resp.get("error", {}).get("details")):
                details = resp.get("error", {}).get("details", {}) if isinstance(resp.get("error"), dict) else {}
                failed_symbols = details.get("symbols_failed") or effective_failed or []
                message = "Tickers couldn't be found."
                if failed_symbols:
                    head = message
                    body = [" ".join(str(sym) for sym in failed_symbols)] if isinstance(failed_symbols, list) else [str(failed_symbols)]
                    footnotes = (
                        formatter.format_error_details(head, body)
                        if formatter
                        else mdv2_expandable_blockquote([head], body)
                    )
                else:
                    footnotes = (
                        formatter.format_error_note(message)
                        if formatter
                        else mdv2_blockquote([message])
                    )

        if clear_after and footnotes:
            text = f"{text}\n\n{footnotes}"

        if interactive_hint_needed:
            text = text.replace("Session ends after", "Session auto-closes after")

        return [text]

    async def handle_fx(
        self,
        *,
        chat_id: int,
        spec: CommandSpec,
        values: Dict[str, Any],
        resp: Dict[str, Any],
    ) -> list[str]:
        formatter = self.formatting
        data = resp.get("data", {})
        ttl_min = self.ttl_minutes()

        if data.get("fx_prompt"):
            self.create_session(chat_id, spec, values={}, missing=[])
            return self.render_response("fx_prompt", {"ttl_min": ttl_min})

        existing = self.session_service.get(chat_id)
        clear_after = True
        if self.is_sticky(spec) and existing and existing.get("cmd") == spec.name and existing.get("sticky"):
            clear_after = False

        rate = data.get("rate") or data.get("close") or data.get("price")
        pair = (str(data.get("pair")) or "").upper()
        base = (values.get("base", "") or data.get("base") or "").upper()
        quote = (values.get("quote", "") or data.get("quote") or "").upper()
        if (not base or not quote) and pair:
            parts = pair.replace("-", "_").split("_")
            if len(parts) == 2:
                base = base or parts[0]
                quote = quote or parts[1]

        rate_display = rate
        try:
            rate_num = float(rate)
        except Exception:
            rate_num = None
        if pair == "USD_EUR" and base == "EUR" and quote == "USD" and rate_num and rate_num != 0.0:
            rate_display = 1.0 / rate_num

        default_rate = str(rate_display) if rate_display not in (None, "") else "?"
        if formatter:
            rate_str = formatter.format_float(rate_display, precision=4, default=default_rate)
        else:
            rate_str = default_rate

        pages = self.render_response(
            "fx_result",
            {"base": base or "?", "quote": quote or "?", "rate": rate_str, "ttl_min": ttl_min},
        )

        if not clear_after:
            self.create_session(chat_id, spec, values={}, missing=[])
        else:
            self.clear_session(chat_id)

        return pages

    def handle_fx_error(
        self,
        *,
        spec: CommandSpec,
        values: Dict[str, Any],
        usage: str,
        example: str,
    ) -> list[str]:
        base = (values.get("base", "") or "").upper()
        quote = (values.get("quote", "") or "").upper()
        payload = {"base": base or "?", "quote": quote or "?", "usage": usage, "example": example}
        pages = self.render_response("fx_error", payload)
        if pages:
            return pages
        fallback = self.render_response(
            "service_error",
            {"message": "Service error", "usage": usage, "example": example},
        )
        return fallback if fallback else ["Service error"]
