from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

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

    values, missing, err = validate_args(spec.args_schema, tokens, got=got, cmd_name=spec.name)
    if err:
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        pages = render_screen(ui, "invalid_template", {"error": err, "usage": usage, "example": example})
        return [p for p in pages]
    if missing:
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
    resp = await dispatcher.dispatch(spec.dispatch, values, user_context)
    if not isinstance(resp, dict) or not resp.get("ok", False):
        err = (resp or {}).get("error", {})
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        if spec.name == "/fx":
            # Build a UI-driven message; do not leak backend text
            base = (values.get("base", "") or "").upper()
            quote = (values.get("quote", "") or "").upper()
            pages = render_screen(ui, "fx_error", {"base": base or "?", "quote": quote or "?", "usage": usage, "example": example})
            return [p for p in pages]
        else:
            message = err.get("message") or "Internal error"
            pages = render_screen(ui, "service_error", {"message": message, "usage": usage, "example": example})
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

        # Build rows for table (compact for mobile): MKT and AGE are short
        rows: List[List[str]] = [["TICKER", "NOW", "OPEN", "%", "MARKET", "AGE"]]

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

        def _age_label(fresh: str) -> str:
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
            age = _age_label(str(q.get("freshness") or ""))
            rows.append([f"{disp}{star}", n_txt, o_txt, pct_txt, market_col, age])
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
        if has_missing:
            pages = render_screen(ui, "price_partial_error", data_ui)
        elif partial:
            pages = render_screen(ui, "price_partial_note", data_ui)
        else:
            pages = render_screen(ui, "price_result", data_ui)
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

        # Footnotes only in interactive mode (sticky)
        if not clear_after:
            # Re-render using the same base screens (they include footers)
            ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
            data_ui = {"table_rows": rows, "not_found_symbols": (eff_failed or []), "ttl_min": ttl_min}
            if has_missing:
                pages2 = render_screen(ui, "price_partial_error", data_ui)
            elif partial:
                pages2 = render_screen(ui, "price_partial_note", data_ui)
            else:
                pages2 = render_screen(ui, "price_result", data_ui)
            text = pages2[0]
        elif footnotes_common_str:
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
        base = (values.get("base", "") or "").upper()
        quote = (values.get("quote", "") or "").upper()
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
        pages = render_screen(ui, "fx_result", {"base": base, "quote": quote, "rate": rate_str})
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
        pages = render_screen(ui, "cash_add_success", values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/allocation_edit":
        pages = render_screen(ui, "allocation_edit_success", values)
        sessions.clear(chat_id)
        return [p for p in pages]
    elif spec.name == "/rename":
        pages = render_screen(ui, "rename_success", values)
        sessions.clear(chat_id)
        return [p for p in pages]

    # Special handling for /portfolio when empty
    elif spec.name == "/portfolio":
        # Check if portfolio is empty by looking at the response data
        portfolio_data = resp.get("data", {}).get("portfolio", {})
        positions = portfolio_data.get("positions", [])
        cash_balance = portfolio_data.get("cash_balance_eur", 0)

        # If no positions and no cash, show guidance for new users
        if not positions and (cash_balance == 0 or cash_balance is None):
            pages = render_screen(ui, "portfolio_empty", {})
            return [p for p in pages]
        # Otherwise let the portfolio data display normally
        pages = render_screen(ui, "done", {})
        return [p for p in pages]

    # default success (for other read-only commands like /cash, /allocation, etc.)
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




