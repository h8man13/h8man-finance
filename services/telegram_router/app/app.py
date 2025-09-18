from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
import time
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal, InvalidOperation

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse

from .settings import get_settings, Settings
from .models import TelegramUpdate, TestRouteIn
from .core.parser import parse_text, normalize_command
from .core.registry import Registry
from .core.validator import validate_args
from .core.sessions import SessionStore
from .core.idempotency import IdempotencyStore
from .core.dispatcher import Dispatcher
from .core.templates import escape_mdv2, paginate, euro, monotable, safe_escape_mdv2_with_fences, convert_markdown_to_html, mdv2_blockquote, mdv2_expandable_blockquote
from .connectors.http import HTTPClient
from .ui.loader import load_ui, render_screen


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.ROUTER_LOG_LEVEL)
    # ensure data dirs
    os.makedirs(os.path.dirname(s.IDEMPOTENCY_PATH), exist_ok=True)
    os.makedirs(s.SESSIONS_DIR, exist_ok=True)
    # Warm UI cache (load once if present)
    try:
        _ = load_ui(s.UI_PATH)
    except Exception:
        pass
    # optional polling loop
    poll_task = None
    if s.TELEGRAM_MODE == "polling" and s.TELEGRAM_BOT_TOKEN:
        poll_task = asyncio.create_task(_poll_updates())
    try:
        yield
    finally:
        if poll_task is not None:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Telegram Router", lifespan=lifespan)


def setup_logging(level: str):
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")


def json_log(**kwargs):
    print(json.dumps(kwargs, ensure_ascii=False))

def _decimal_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except Exception:
        return None


def _prepare_portfolio_payload(command: str, values: Dict[str, Any]) -> Dict[str, Any]:
    prepared: Dict[str, Any] = {}
    name = command.lower()
    if name in ("/add", "/buy", "/sell"):
        qty = _decimal_str(values.get("qty"))
        if qty is not None:
            prepared["qty"] = qty
            values["qty"] = qty
        symbol = values.get("symbol")
        if symbol:
            prepared["symbol"] = str(symbol).strip().upper()
            values["symbol"] = prepared["symbol"]
        if name == "/add":
            asset_class = values.get("asset_class")
            if asset_class:
                prepared["asset_class"] = str(asset_class).lower()
        if name in ("/buy", "/sell"):
            price = values.get("price_eur")
            price_str = _decimal_str(price)
            if price_str is not None:
                prepared["price_eur"] = price_str
                values["price_eur"] = price_str
            fees = values.get("fees_eur")
            fees_str = _decimal_str(fees)
            if fees_str is not None:
                prepared["fees_eur"] = fees_str
                values["fees_eur"] = fees_str
        return prepared
    if name in ("/remove", "/rename"):
        symbol = values.get("symbol")
        if symbol:
            prepared["symbol"] = str(symbol).strip().upper()
            values["symbol"] = prepared["symbol"]
        if name == "/rename":
            display_name = values.get("display_name")
            if display_name:
                prepared["display_name"] = str(display_name).strip()
                values["display_name"] = prepared["display_name"]
        return prepared
    if name in ("/cash_add", "/cash_remove"):
        amount = _decimal_str(values.get("amount_eur"))
        if amount is not None:
            prepared["amount_eur"] = amount
            values["amount_eur"] = amount
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
            prepared["scope"] = str(scope).strip()
            values["scope"] = prepared["scope"]
        delta = values.get("delta_pct")
        delta_str = _decimal_str(delta)
        if delta_str is not None:
            prepared["delta_pct"] = delta_str
            values["delta_pct"] = delta_str
        return prepared
    return {k: v for k, v in values.items() if v is not None}


def _to_decimal(value: Any, default: Decimal | None = None) -> Decimal:
    if default is None:
        default = Decimal("0")
    try:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default

def _format_quantity(value: Any) -> str:
    dec = _to_decimal(value)
    if dec == 0:
        return "0"
    s = format(dec.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"

def _format_percent(value: Any) -> str:
    dec = _to_decimal(value)
    try:
        return f"{int(dec)}%"
    except (ValueError, TypeError):
        return f"{dec}%"

def _format_eur(value: Any) -> str:
    dec = _to_decimal(value)
    return euro(float(dec))


def _portfolio_table_pages(ui: Dict[str, Any], portfolio: Dict[str, Any] | None) -> List[str]:
    if not ui or portfolio is None:
        return []

    holdings = portfolio.get("holdings") or []
    cash_dec = _to_decimal(portfolio.get("cash_eur"))

    if not holdings and cash_dec == 0:
        pages = render_screen(ui, "portfolio_empty", {})
        return [p for p in pages] if pages else []

    rows: List[List[str]] = [[
        "Ticker",
        "Asset class",
        "Market",
        "Quantity",
        "Price EUR",
        "Value EUR",
    ]]

    holdings_total = Decimal("0")
    for holding in holdings:
        symbol = str(holding.get("symbol") or "").upper()
        display_name = holding.get("display_name")
        ticker = symbol if not display_name else f"{symbol} ({display_name})"
        asset_class = (holding.get("asset_class") or "-").lower()
        market = (holding.get("market") or "-").upper()
        qty = _format_quantity(holding.get("qty_total"))
        price = "-" if holding.get("price_eur") is None else _format_eur(holding.get("price_eur"))
        value_dec = _to_decimal(holding.get("value_eur"))
        value = _format_eur(value_dec)
        holdings_total += value_dec
        rows.append([ticker, asset_class, market, qty, price, value])

    if cash_dec > 0:
        cash_display = _format_eur(cash_dec)
        rows.append(["Cash", "cash", "-", "-", cash_display, cash_display])

    total_dec = _to_decimal(portfolio.get("total_value_eur"), default=holdings_total + cash_dec)
    data = {"total_value": _format_eur(total_dec), "table_rows": rows}
    pages = render_screen(ui, "portfolio_result", data)
    return [p for p in pages] if pages else []


def _portfolio_pages_with_fallback(ui: Dict[str, Any], portfolio: Dict[str, Any] | None) -> List[str]:
    pages = _portfolio_table_pages(ui, portfolio)
    if pages:
        return pages
    fallback = render_screen(ui, "portfolio_empty", {})
    return [p for p in fallback] if fallback else []


def _allocation_rows(entries: List[Tuple[str, Dict[str, Any]]]) -> List[List[str]]:
    rows: List[List[str]] = [["", "stock", "etf", "crypto"]]
    for label, payload in entries:
        payload = payload or {}
        rows.append([
            label,
            _format_percent(payload.get("stock_pct")),
            _format_percent(payload.get("etf_pct")),
            _format_percent(payload.get("crypto_pct")),
        ])
    return rows


def _allocation_table_pages(ui: Dict[str, Any], *entries: Tuple[str, Dict[str, Any]]) -> List[str]:
    if not ui or not entries:
        return []
    rows = _allocation_rows(list(entries))
    pages = render_screen(ui, "allocation_result", {"table_rows": rows})
    return [p for p in pages] if pages else []

# UI (ui.yml) is the single source of truth for rendering.


# startup handled by lifespan


def deps() -> Tuple[Settings, Registry, SessionStore, IdempotencyStore, Dispatcher, HTTPClient]:
    s = get_settings()
    registry = Registry(s.REGISTRY_PATH)
    sessions = SessionStore(s.SESSIONS_DIR, ttl_sec=s.ROUTER_SESSION_TTL_SEC)
    idemp = IdempotencyStore(s.IDEMPOTENCY_PATH)
    http = HTTPClient(timeout=s.HTTP_TIMEOUT_SEC, retries=s.HTTP_RETRIES)
    dispatch = Dispatcher(http)
    return s, registry, sessions, idemp, dispatch, http


async def send_telegram_message(token: str, chat_id: int, text: str, parse_mode: str = "MarkdownV2"):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=8.0) as client:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            # 1) Try MarkdownV2 as-is
            r = await client.post(url, json=payload)
            ok = False
            try:
                js = r.json()
                ok = bool(js.get("ok"))
                if not ok:
                    json_log(action="send_telegram", status="api_error", chat_id=chat_id, code=js.get("error_code"), description=js.get("description"))
            except Exception:
                json_log(action="send_telegram", status="bad_response", chat_id=chat_id, http_status=r.status_code)

            # 2) Retry with stricter MarkdownV2 escaping (outside code fences)
            if not ok:
                text2 = safe_escape_mdv2_with_fences(text, strict=True)
                payload2 = dict(payload)
                payload2["text"] = text2
                r2 = await client.post(url, json=payload2)
                try:
                    js2 = r2.json()
                    ok = bool(js2.get("ok"))
                    if not ok:
                        json_log(action="send_telegram", status="api_error_strict", chat_id=chat_id, code=js2.get("error_code"), description=js2.get("description"))
                except Exception:
                    json_log(action="send_telegram", status="bad_response_strict", chat_id=chat_id, http_status=r2.status_code)

            # 3) Fallback to HTML parse_mode
            if not ok:
                html = convert_markdown_to_html(text)
                payload_html = dict(payload)
                payload_html["text"] = html
                payload_html["parse_mode"] = "HTML"
                r3 = await client.post(url, json=payload_html)
                try:
                    js3 = r3.json()
                    ok = bool(js3.get("ok"))
                    if not ok:
                        json_log(action="send_telegram", status="api_error_html", chat_id=chat_id, code=js3.get("error_code"), description=js3.get("description"))
                except Exception:
                    json_log(action="send_telegram", status="bad_response_html", chat_id=chat_id, http_status=r3.status_code)

            # 4) Last resort: plain text
            if not ok:
                payload_plain = dict(payload)
                payload_plain.pop("parse_mode", None)
                payload_plain["text"] = text
                rr = await client.post(url, json=payload_plain)
                try:
                    js4 = rr.json()
                    if not bool(js4.get("ok")):
                        json_log(action="send_telegram", status="fallback_failed", chat_id=chat_id, code=js4.get("error_code"), description=js4.get("description"))
                except Exception:
                    json_log(action="send_telegram", status="fallback_bad_response", chat_id=chat_id, http_status=rr.status_code)
        except Exception as e:
            json_log(action="send_telegram", status="exception", error=str(e), chat_id=chat_id)


# Legacy help builder removed; /help is rendered via UI screens.


async def process_text(chat_id: int, sender_id: int, text: str, ctx, user_context: Dict[str, Any] = None):
    s, registry, sessions, idemp, dispatcher, http = ctx
    ui = load_ui(get_settings().UI_PATH)
    if not ui:
        raise HTTPException(status_code=500, detail="UI config missing")
    # owner gate (only if configured)
    if s.owner_ids and sender_id not in s.owner_ids:
        pages = render_screen(ui, "not_authorized", {})
        return [p for p in pages]

    # parse
    cmd, tokens = parse_text(text)
    if cmd is None:
        # If ongoing session, treat as input-only
        session = sessions.get(chat_id)
        if not session:
            pages = render_screen(ui, "unknown_input", {})
            return [p for p in pages]
        cmd = session.get("cmd")
        tokens = [t for t in tokens if t]

    # handle /cancel
    if cmd == "/cancel":
        sessions.clear(chat_id)
        pages = render_screen(ui, "canceled", {})
        return [p for p in pages]

    # handle /exit (alias for closing any sticky session)
    if cmd == "/exit":
        sessions.clear(chat_id)
        pages = render_screen(ui, "canceled", {})
        return [p for p in pages]

    # handle /help
    if cmd == "/help":
        # End any existing sticky session when a new root command arrives
        existing = sessions.get(chat_id) or {}
        if existing.get("sticky"):
            sessions.clear(chat_id)
        # Prefer ui.yml help screen, fallback to dynamic builder
        pages = render_screen(ui, "help", {})
        return [p for p in pages]

    spec = registry.get(cmd)
    if not spec:
        # Unknown command via UI, fallback minimal
        pages = render_screen(ui, "unknown_command", {"cmd": cmd})
        return [p for p in pages]

    # If switching away from a sticky session to a different command, clear it
    existing = sessions.get(chat_id) or {}
    if existing and existing.get("cmd") != spec.name and existing.get("sticky"):
        sessions.clear(chat_id)

    # session merge
    got = existing.get("got") if existing.get("cmd") == spec.name else {}
    dispatch_override = None

    if spec.name in ("/buy", "/sell") and tokens:
        tokens = [tok for tok in tokens if tok.lower() not in ("at", "@")]

    if spec.name == "/cash_remove":
        confirm_state = existing.get("confirm")
        if confirm_state and not (text or "").strip().startswith("/"):
            answer_raw = (tokens[0] if tokens else (text or "")).strip().lower()
            if answer_raw in ("y", "yes"):
                values = dict(confirm_state.get("values", {}))
                missing = []
                err = None
                dispatch_override = dict(confirm_state.get("payload", {}))
            elif answer_raw in ("n", "no"):
                sessions.clear(chat_id)
                pages = render_screen(ui, "cash_remove_cancelled", confirm_state.get("ui", {}))
                return [p for p in pages] if pages else []
            else:
                pages = render_screen(ui, "cash_remove_confirm", confirm_state.get("ui", {}))
                return [p for p in pages] if pages else []

    if dispatch_override is None:
        values, missing, err = validate_args(spec.args_schema, tokens, got=got, cmd_name=spec.name)
    else:
        tokens = []
    if err:
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        pages = render_screen(ui, "invalid_template", {"error": err, "usage": usage, "example": example})
        return [p for p in pages]

    if spec.name == "/rename" and values.get("display_name"):
        if len(tokens) >= 2:
            values["display_name"] = " ".join(tokens[1:]).strip()

    # Check if this command should prompt when no user arguments provided
    should_prompt_when_empty = spec.args_schema and spec.name not in ["/tx", "/fx", "/portfolio_snapshot", "/portfolio_summary", "/portfolio_breakdown", "/portfolio_digest", "/portfolio_movers"]
    user_provided_no_args = not tokens and not (existing and existing.get("got"))


    if missing or (should_prompt_when_empty and user_provided_no_args):
        # For /price, start a sticky session so user can keep sending symbols
        sticky = (spec.name == "/price")
        sessions.set(chat_id, {
            "chat_id": chat_id,
            "cmd": spec.name,
            "expected": [f["name"] for f in spec.args_schema],
            "got": values,
            "missing_from": missing,
            "sticky": sticky,
        })
        # Prefer UI screens first; otherwise minimal fallback
        msg = None
        # UI generic command prompt mapping: /cmd -> cmd_prompt
        screen_key = spec.name.lstrip("/") + "_prompt"
        ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
        pages = render_screen(ui, screen_key, {"ttl_min": ttl_min})
        return [p for p in pages]

    # ready to dispatch
    # For sticky /price sessions, keep the session alive after each success
    clear_after = True
    if spec.name == "/price" and existing and existing.get("cmd") == "/price" and existing.get("sticky"):
        clear_after = False
    dispatch_values = dispatch_override or values
    if spec.dispatch.get("service") == "portfolio_core" and dispatch_override is None:
        dispatch_values = _prepare_portfolio_payload(spec.name, dict(values))
        method = spec.dispatch.get("method", "GET").upper()
        if method == "POST":
            op_id = dispatch_values.get("op_id")
            if not op_id:
                op_id = uuid.uuid4().hex
                dispatch_values["op_id"] = op_id
            values["op_id"] = op_id
        if spec.name == "/cash_remove":
            amount_dec = _to_decimal(dispatch_values.get("amount_eur"))
            if amount_dec <= 0:
                usage = spec.help.get("usage", "")
                example = spec.help.get("example", "")
                pages = render_screen(ui, "invalid_template", {"error": "amount must be greater than 0", "usage": usage, "example": example})
                return [p for p in pages] if pages else []
            ui_payload = {"amount_display": _format_eur(dispatch_values.get("amount_eur"))}
            session_data = {
                "chat_id": chat_id,
                "cmd": spec.name,
                "expected": [],
                "got": values,
                "missing_from": [],
                "sticky": True,
                "confirm": {
                    "payload": dict(dispatch_values),
                    "values": dict(values),
                    "ui": ui_payload,
                },
            }
            sessions.set(chat_id, session_data)
            pages = render_screen(ui, "cash_remove_confirm", ui_payload)
            return [p for p in pages] if pages else []
    resp = await dispatcher.dispatch(spec.dispatch, dispatch_values, user_context)
    if not isinstance(resp, dict) or not resp.get("ok", False):
        err = (resp or {}).get("error", {})
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        code = err.get("code") if isinstance(err, dict) else None
        if spec.name == "/fx":
            # Build a UI-driven message; do not leak backend text
            base = (values.get("base", "") or "").upper()
            quote = (values.get("quote", "") or "").upper()
            pages = render_screen(ui, "fx_error", {"base": base or "?", "quote": quote or "?", "usage": usage, "example": example})
            return [p for p in pages]
        if spec.name == "/remove" and code == "NOT_FOUND":
            symbol = (values.get("symbol") or "").upper()
            pages = render_screen(ui, "remove_not_owned", {"symbol": symbol})
            sessions.clear(chat_id)
            return [p for p in pages] if pages else []
        if spec.name == "/cash_remove":
            sessions.clear(chat_id)
        message = err.get("message") if isinstance(err, dict) else None
        pages = render_screen(ui, "service_error", {"message": message or "Internal error", "usage": usage, "example": example})
        return [p for p in pages]

    # success mapping by command
    if spec.name == "/price":
        data = resp.get("data", {})
        quotes = data.get("quotes") or []
        # If no quotes, prompt again (keep session open if sticky)
        if not quotes:
            # Always keep session open on errors (fully invalid input)
            sessions.set(chat_id, {
                "chat_id": chat_id,
                "cmd": "/price",
                "expected": [f["name"] for f in spec.args_schema],
                "got": {},
                "missing_from": [],
                "sticky": True,
            })
            # Prefer UI screens showing missing symbols when available.
            # For no-quotes responses, treat all requested as missing.
            ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
            req_syms = [str(x).upper() for x in (values.get("symbols") or [])]
            if req_syms:
                pages = render_screen(ui, "price_not_found", {"ttl_min": ttl_min, "not_found_symbols": req_syms})
            else:
                pages = render_screen(ui, "price_prompt", {"ttl_min": ttl_min})
            return [p for p in pages]

        # Build rows for table (compact for mobile); keep headers short and uppercase
        rows: List[List[str]] = [["TICKER", "NOW", "OPEN", "%", "MARKET", "FRESHNESS"]]

        def _market_label(sym: str, market_code: str) -> str:
            sfx = ""
            if "." in sym:
                sfx = sym.split(".")[-1].upper()
            code = (market_code or "").upper()
            # Prefer a specific suffix over generic country codes
            cand = [sfx, code]
            m = {
                # US
                "US": "US", "NYSE": "NYS", "NASDAQ": "NAS", "NSDQ": "NAS",
                # Germany / Xetra
                "XETRA": "XET", "DE": "XET", "FWB": "XET",
                # UK
                "LSE": "LSE", "LON": "LSE",
                # Canada
                "TSX": "TSX", "TSXV": "TSV",
                # Japan
                "TSE": "TYO", "JPX": "TYO",
                # Australia
                "ASX": "ASX",
                # Switzerland
                "SIX": "SIX", "SWX": "SIX",
                # France / Euronext Paris
                "PAR": "PAR", "EPA": "PAR",
                # Netherlands / Euronext Amsterdam
                "AMS": "AMS", "AEX": "AMS",
                # Spain
                "BME": "MAD", "MCE": "MAD",
                # Hong Kong
                "HK": "HK", "HKEX": "HK",
                # Singapore
                "SGX": "SG",
            }
            for k in cand:
                if k and k in m:
                    return m[k]
            # Fallback to suffix or code or '-'
            return sfx or code or "-"

        def _freshness_label(fresh: str) -> str:
            f = (fresh or "").lower()
            if "live" in f:
                return "L"
            if "prev" in f:
                return "P"
            if "eod" in f or "end of day" in f:
                return "E"
            if "delay" in f:
                return "D"
            return f.upper()[:3] if f else "n/a"
        for q in quotes:
            sym = str(q.get("symbol") or "").upper()
            disp = sym.replace(".US", "")
            market = (q.get("market") or "").upper()
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
            n_txt = euro(now_eur) if now_eur is not None else "n/a"
            o_txt = euro(open_eur) if open_eur is not None else "n/a"
            pct_txt = f"{pct:+.1f}%" if pct is not None else "n/a"
            market_col = _market_label(sym, market)
            freshness = _freshness_label(str(q.get("freshness") or ""))
            rows.append([f"{disp}{star}", n_txt, o_txt, pct_txt, market_col, freshness])
        # Choose UI screen
        partial = bool(resp.get("partial"))
        details = resp.get("error", {}).get("details", {}) if isinstance(resp.get("error"), dict) else {}
        failed = details.get("symbols_failed") or []
        # Compute effective missing list: use upstream details if present; otherwise derive from request vs response
        requested = [str(x).upper() for x in (values.get("symbols") or [])] if isinstance(values.get("symbols"), list) else []
        present = [str(q.get("symbol") or "").upper() for q in quotes]
        derived_missing = [s for s in requested if not any(p.startswith(s) for p in present)] if requested else []
        eff_failed = failed or derived_missing
        data_ui = {"table_rows": rows, "not_found_symbols": (eff_failed or [])}
        has_missing = isinstance(eff_failed, list) and len(eff_failed) > 0
        base_screen = "price_partial_error" if has_missing else "price_partial_note" if partial else "price_result"
        screen = base_screen
        screen_payload = dict(data_ui)
        if not clear_after:
            ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
            screen_payload["ttl_min"] = ttl_min
            sticky_map = {
                "price_result": "price_result_sticky",
                "price_partial_error": "price_partial_error_sticky",
                "price_partial_note": "price_partial_note_sticky",
            }
            screen = sticky_map.get(screen, screen)
        pages = render_screen(ui, screen, screen_payload)
        text = pages[0]
        # Session handling: keep session open for any error cases (partial or missing list)
        if partial or has_missing:
            sessions.set(chat_id, {
                "chat_id": chat_id,
                "cmd": "/price",
                "expected": [f["name"] for f in spec.args_schema],
                "got": {},
                "missing_from": [],
                "sticky": True,
            })
        elif not clear_after:
            # Already an interactive session -> refresh TTL
            sessions.set(chat_id, {
                "chat_id": chat_id,
                "cmd": "/price",
                "expected": [f["name"] for f in spec.args_schema],
                "got": {},
                "missing_from": [],
                "sticky": True,
            })
        else:
            sessions.clear(chat_id)
        # Common footnotes (partial failures) if we didn't already render a partial-error screen
        footnotes_common_str = ""
        if not has_missing:
            if resp.get("partial") or (isinstance(resp.get("error"), dict) and resp.get("error", {}).get("details")):
                details = resp.get("error", {}).get("details", {}) if isinstance(resp.get("error"), dict) else {}
                failed2 = details.get("symbols_failed") or eff_failed or []
                # Use copies for message text, avoid hard-coded strings
                msg_nf = "Some symbols were not found."
                if failed2:
                    head = msg_nf
                    body = [" ".join(failed2)] if isinstance(failed2, list) else [str(failed2)]
                    footnotes_common_str = mdv2_expandable_blockquote([head], body)
                else:
                    # Partial without explicit details: still inform the user
                    footnotes_common_str = mdv2_blockquote([msg_nf])

        # Append partial-footnote hints only when the session closes
        if clear_after and footnotes_common_str:
            text = f"{text}\n\n{footnotes_common_str}"

        return [text]
    if spec.name == "/fx":
        data = resp.get("data", {})
        # Prompt flow when no args provided
        if data.get("fx_prompt"):
            # Open a sticky session to accept base/quote next
            sessions.set(chat_id, {
                "chat_id": chat_id,
                "cmd": "/fx",
                "expected": [f["name"] for f in spec.args_schema],
                "got": {},
                "missing_from": [],
                "sticky": True,
            })
            pages = render_screen(ui, "fx_prompt", {})
            return [p for p in pages]
        rate = data.get("rate") or data.get("close") or data.get("price")
        pair = (str(data.get("pair")) or "").upper()
        # fx upstream returns pair sometimes; keep inputs for clarity
        base = (values.get("base", "") or data.get("base") or "").upper()
        quote = (values.get("quote", "") or data.get("quote") or "").upper()
        if (not base or not quote) and pair:
            parts = pair.replace("-", "_").split("_")
            if len(parts) == 2:
                base = base or parts[0]
                quote = quote or parts[1]
        # Invert if user requested EUR/USD but upstream pair is USD_EUR
        rate_disp = rate
        try:
            rnum = float(rate)
        except Exception:
            rnum = None
        if pair == "USD_EUR" and base == "EUR" and quote == "USD" and rnum and rnum != 0.0:
            rate_disp = 1.0 / rnum
        # Clear session after success
        sessions.clear(chat_id)
        # Display: round to 4 decimals for communication purposes,
        # but leave upstream data untouched for any calculations elsewhere.
        try:
            rate_str = f"{float(rate_disp):.4f}"
        except Exception:
            rate_str = str(rate_disp)
        pages = render_screen(ui, "fx_result", {"base": base or "?", "quote": quote or "?", "rate": rate_str})
        return [p for p in pages]
    # Portfolio command success screens
    if spec.name in ("/buy", "/sell"):
        key = "buy_success" if spec.name == "/buy" else "sell_success"
        pages = render_screen(ui, key, values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/add":
        pages = render_screen(ui, "add_success", values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/remove":
        pages = render_screen(ui, "remove_success", values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/cash_add":
        ui_values = dict(values)
        if values.get("amount_eur") is not None:
            ui_values["amount"] = _format_eur(values.get("amount_eur"))
        pages = render_screen(ui, "cash_add_success", ui_values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/allocation_edit":
        pages = render_screen(ui, "allocation_edit_success", values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/rename":
        rename_payload = resp.get("data", {}).get("rename", {}) or {}
        symbol = (rename_payload.get("symbol") or values.get("symbol") or "").upper()
        nickname_raw = rename_payload.get("display_name") or values.get("display_name") or ""
        nickname = nickname_raw.strip()
        pages = render_screen(ui, "rename_success", {"symbol": symbol, "nickname": nickname})
        sessions.clear(chat_id)
        return [p for p in pages]


    # Portfolio read commands with table formatting
    elif spec.name == "/portfolio":
        return _portfolio_pages_with_fallback(ui, resp.get("data", {}))

    elif spec.name == "/add":
        symbol = (values.get("symbol") or "").upper()
        qty_text = _format_quantity(values.get("qty"))
        success_pages = render_screen(ui, "add_success", {"symbol": symbol, "qty": qty_text}) or []
        snapshot_pages = _portfolio_pages_with_fallback(ui, resp.get("data", {}))
        sessions.clear(chat_id)
        return success_pages + snapshot_pages

    elif spec.name == "/remove":
        symbol = (values.get("symbol") or "").upper()
        success_pages = render_screen(ui, "remove_success", {"symbol": symbol}) or []
        snapshot_pages = _portfolio_pages_with_fallback(ui, resp.get("data", {}))
        sessions.clear(chat_id)
        return success_pages + snapshot_pages

    elif spec.name == "/cash_add":
        amount_display = _format_eur(values.get("amount_eur"))
        success_pages = render_screen(ui, "cash_add_success", {"amount_display": amount_display}) or []
        snapshot_pages = _portfolio_pages_with_fallback(ui, resp.get("data", {}))
        sessions.clear(chat_id)
        return success_pages + snapshot_pages

    elif spec.name == "/cash_remove":
        amount_display = _format_eur(values.get("amount_eur"))
        success_pages = render_screen(ui, "cash_remove_success", {"amount_display": amount_display}) or []
        snapshot_pages = _portfolio_pages_with_fallback(ui, resp.get("data", {}))
        sessions.clear(chat_id)
        return success_pages + snapshot_pages

    elif spec.name == "/buy":
        symbol = (values.get("symbol") or "").upper()
        qty_text = _format_quantity(values.get("qty"))
        price_display = "market"
        if values.get("price_eur") not in (None, ""):
            price_display = _format_eur(values.get("price_eur"))
        success_pages = render_screen(ui, "buy_success", {"symbol": symbol, "qty": qty_text, "price_ccy": price_display}) or []
        snapshot_pages = _portfolio_pages_with_fallback(ui, resp.get("data", {}))
        sessions.clear(chat_id)
        return success_pages + snapshot_pages

    elif spec.name == "/sell":
        symbol = (values.get("symbol") or "").upper()
        qty_text = _format_quantity(values.get("qty"))
        price_display = "market"
        if values.get("price_eur") not in (None, ""):
            price_display = _format_eur(values.get("price_eur"))
        success_pages = render_screen(ui, "sell_success", {"symbol": symbol, "qty": qty_text, "price_ccy": price_display}) or []
        snapshot_pages = _portfolio_pages_with_fallback(ui, resp.get("data", {}))
        sessions.clear(chat_id)
        return success_pages + snapshot_pages

    elif spec.name == "/cash":
        cash_dec = _to_decimal(resp.get("data", {}).get("cash_eur"))
        if cash_dec == 0:
            pages = render_screen(ui, "cash_zero", {})
            return [p for p in pages] if pages else []
        pages = render_screen(ui, "cash_result", {"cash_balance": _format_eur(cash_dec)})
        return [p for p in pages] if pages else []

    elif spec.name == "/tx":
        payload = resp.get("data", {})
        transactions = payload.get("transactions", []) or []
        if not transactions:
            pages = render_screen(ui, "tx_empty", {})
            return [p for p in pages] if pages else []
        rows: List[List[str]] = [["DATE", "TYPE", "SYMBOL", "QTY", "AMOUNT"]]
        for tx in transactions:
            ts_raw = tx.get("ts")
            timestamp = ts_raw.replace("T", " ")[:16] if isinstance(ts_raw, str) and ts_raw else ""
            tx_type = str(tx.get("type") or "").upper()
            symbol = str(tx.get("symbol") or "CASH")
            qty = _format_quantity(tx.get("qty")) if tx.get("qty") is not None else ""
            amount = _format_eur(tx.get("amount_eur")) if tx.get("amount_eur") is not None else ""
            rows.append([timestamp, tx_type, symbol, qty, amount])
        count = payload.get("count")
        total = count if isinstance(count, int) else len(transactions)
        summary = f"Showing {total} transaction{'s' if total != 1 else ''}"
        pages = render_screen(ui, "tx_result", {"transaction_summary": summary, "table_rows": rows})
        return [p for p in pages] if pages else []
    elif spec.name == "/allocation":
        allocation = resp.get("data", {}) or {}
        pages = _allocation_table_pages(ui, ("Current", allocation.get("current")), ("Target", allocation.get("target")))
        return pages

    elif spec.name == "/allocation_edit":
        allocation = resp.get("data", {}) or {}
        rows = _allocation_rows([
            ("Previous", allocation.get("previous")),
            ("Current", allocation.get("current")),
            ("Target", allocation.get("target")),
        ])
        pages = render_screen(ui, "allocation_edit_success", {"table_rows": rows})
        sessions.clear(chat_id)
        return [p for p in pages] if pages else []

    elif spec.name == "/rename":
        rename_payload = resp.get("data", {}).get("rename", {}) or {}
        symbol = (rename_payload.get("symbol") or values.get("symbol") or "").upper()
        nickname_raw = rename_payload.get("display_name") or values.get("display_name") or ""
        nickname = nickname_raw.strip()
        pages = render_screen(ui, "rename_success", {"symbol": symbol, "nickname": nickname})
        sessions.clear(chat_id)
        return [p for p in pages] if pages else []
    # For other read-only portfolio commands, display the service response as formatted JSON (temporary)
    elif spec.name in ["/portfolio_snapshot", "/portfolio_summary",
                       "/portfolio_breakdown", "/portfolio_digest", "/portfolio_movers", "/po_if"]:
        # Format the JSON response nicely for display
        import json
        data = resp.get("data", {})
        if data:
            formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
            return [f"```json\n{formatted_json}\n```"]
        else:
            return ["No data available"]

    # Default success (only for modification commands without specific screens)
    pages = render_screen(ui, "done", {})
    return [p for p in pages]


async def _poll_updates():
    s, registry, sessions, idemp, dispatcher, http = deps()
    token = s.TELEGRAM_BOT_TOKEN
    base = f"https://api.telegram.org/bot{token}"
    offset = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                params = {"timeout": 25}
                if offset is not None:
                    params["offset"] = offset
                r = await client.get(f"{base}/getUpdates", params=params)
                j = r.json()
                if not j.get("ok"):
                    await asyncio.sleep(1.0)
                    continue
                for upd in j.get("result", []):
                    update = TelegramUpdate.model_validate(upd)
                    msg = update.get_message()
                    if not msg:
                        offset = update.update_id + 1
                        continue
                    chat_id = msg.chat.id
                    sender_id = (msg.from_.id if msg.from_ else 0) or 0
                    text = msg.text or msg.caption or ""
                    if idemp.seen(chat_id, update.update_id):
                        offset = update.update_id + 1
                        continue
                    replies = await process_text(chat_id, sender_id, text, (s, registry, sessions, idemp, dispatcher, http))
                    for rtxt in replies:
                        for chunk in paginate(rtxt):
                            await send_telegram_message(s.TELEGRAM_BOT_TOKEN, chat_id, chunk, s.REPLY_PARSE_MODE)
                    offset = update.update_id + 1
            except Exception as e:
                json_log(action="poll", status="error", error=str(e))
                await asyncio.sleep(1.0)


@app.get("/health")
async def health():
    return {"ok": True, "ts": int(time.time())}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(None)):
    s, registry, sessions, idemp, dispatcher, http = deps()
    if s.TELEGRAM_MODE != "webhook":
        raise HTTPException(status_code=400, detail="Not in webhook mode")
    if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != s.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    # Be lenient: if payload is missing required fields, just ack ok
    try:
        update = TelegramUpdate.model_validate(payload)
    except Exception:
        return {"ok": True}
    msg = update.get_message()
    if not msg:
        return {"ok": True}
    chat_id = msg.chat.id
    sender_id = (msg.from_.id if msg.from_ else 0) or 0
    text = msg.text or msg.caption or ""

    if idemp.seen(chat_id, update.update_id):
        return {"ok": True}

    try:
        # Extract user context from Telegram message
        user_context = {}
        if msg.from_:
            user_context = {
                "user_id": msg.from_.id,
                "first_name": getattr(msg.from_, 'first_name', ''),
                "last_name": getattr(msg.from_, 'last_name', ''),
                "username": msg.from_.username,
                "language_code": getattr(msg.from_, 'language_code', 'en')
            }

        replies = await process_text(chat_id, sender_id, text, (s, registry, sessions, idemp, dispatcher, http), user_context)
    except Exception as e:
        json_log(action="process", status="error", error=str(e), chat_id=chat_id)
        replies = [escape_mdv2("Internal error")]

    # Send replies out-of-band and return quickly
    async def _send_all():
        for r in replies:
            for chunk in paginate(r):
                await send_telegram_message(s.TELEGRAM_BOT_TOKEN, chat_id, chunk, s.REPLY_PARSE_MODE)

    asyncio.create_task(_send_all())
    return {"ok": True}


@app.post("/telegram/test")
async def telegram_test(body: TestRouteIn):
    s, registry, sessions, idemp, dispatcher, http = deps()
    chat_id = body.chat_id
    text = body.text
    sender_id = s.owner_ids[0] if s.owner_ids else 0
    # Create mock user context for test
    user_context = {
        "user_id": sender_id,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en"
    }
    replies = await process_text(chat_id, sender_id, text, (s, registry, sessions, idemp, dispatcher, http), user_context)
    # Also send via Telegram for parity
    for r in replies:
        for chunk in paginate(r):
            await send_telegram_message(s.TELEGRAM_BOT_TOKEN, chat_id, chunk, s.REPLY_PARSE_MODE)
    return {"ok": True}


