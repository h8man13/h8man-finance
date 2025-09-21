from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
import time
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from contextlib import asynccontextmanager
import inspect
from functools import partial
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
from .handlers.market import MarketHandler
from .handlers.portfolio import PortfolioHandler
from .handlers.trading import TradingHandler
from .handlers.system import SystemHandler
from .services import (
    FormattingService,
    SessionService,
    prepare_portfolio_payload,
    portfolio_pages_with_fallback,
    allocation_table_pages,
)
from .connectors.http import HTTPClient
from .connectors.telegram import TelegramConnector
from .ui.loader import load_ui, load_router_config, render_screen


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
    telegram_connector = None
    poll_task = None
    if s.TELEGRAM_MODE == "polling" and s.TELEGRAM_BOT_TOKEN:
        telegram_connector = TelegramConnector(s.TELEGRAM_BOT_TOKEN, _process_telegram_update)
        poll_task = asyncio.create_task(telegram_connector.start_polling())
    try:
        yield
    finally:
        if telegram_connector is not None:
            telegram_connector.stop_polling()
        if poll_task is not None:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Telegram Router", lifespan=lifespan)
formatting_service = FormattingService()


def setup_logging(level: str):
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")


def json_log(**kwargs):
    print(json.dumps(kwargs, ensure_ascii=False))


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


async def _process_telegram_update(update: TelegramUpdate):
    """Process a single Telegram update."""
    s, registry, sessions, idemp, dispatcher, http = deps()

    msg = update.get_message()
    if not msg:
        return

    chat_id = msg.chat.id
    sender_id = (msg.from_.id if msg.from_ else 0) or 0
    text = msg.text or msg.caption or ""

    if idemp.seen(chat_id, update.update_id):
        return

    user_context = {}
    if msg.from_:
        user_context = {
            "user_id": msg.from_.id,
            "first_name": getattr(msg.from_, 'first_name', ''),
            "last_name": getattr(msg.from_, 'last_name', ''),
            "username": msg.from_.username,
            "language_code": getattr(msg.from_, 'language_code', 'en'),
        }

    replies = await process_text(chat_id, sender_id, text, (s, registry, sessions, idemp, dispatcher, http), user_context)
    for rtxt in replies:
        for chunk in paginate(rtxt):
            await send_telegram_message(s.TELEGRAM_BOT_TOKEN, chat_id, chunk, s.REPLY_PARSE_MODE)


# Legacy help builder removed; /help is rendered via UI screens.









HandlerFunction = Callable[[], Awaitable | list[str]]

def build_success_handlers(
    market_handler,
    portfolio_handler,
    trading_handler,
    ui,
    resp,
    chat_id,
    spec,
    values,
    clear_after,
) -> tuple[dict[str, HandlerFunction], set[str]]:
    handlers: dict[str, HandlerFunction] = {
        "/price": lambda: market_handler.handle_price(
            chat_id=chat_id,
            spec=spec,
            values=values,
            resp=resp,
            clear_after=clear_after,
        ),
        "/fx": lambda: market_handler.handle_fx(
            chat_id=chat_id,
            spec=spec,
            values=values,
            resp=resp,
        ),
        "/portfolio": lambda: portfolio_handler.handle_portfolio(resp=resp),
        "/add": lambda: portfolio_handler.handle_add(
            chat_id=chat_id,
            values=values,
            resp=resp,
        ),
        "/remove": lambda: portfolio_handler.handle_remove(
            chat_id=chat_id,
            values=values,
            resp=resp,
        ),
        "/buy": lambda: trading_handler.handle_buy(
            chat_id=chat_id,
            values=values,
        ),
        "/sell": lambda: trading_handler.handle_sell(
            chat_id=chat_id,
            values=values,
        ),
        "/cash_add": lambda: portfolio_handler.handle_cash_add(
            chat_id=chat_id,
            values=values,
        ),
        "/cash_remove": lambda: portfolio_handler.handle_cash_remove(
            chat_id=chat_id,
            values=values,
            resp=resp,
        ),
        "/cash": lambda: portfolio_handler.handle_cash_overview(resp=resp),
        "/tx": lambda: portfolio_handler.handle_transactions(resp=resp),
        "/allocation": lambda: portfolio_handler.handle_allocation_view(resp=resp),
        "/allocation_edit": lambda: portfolio_handler.handle_allocation_edit(
            chat_id=chat_id,
            values=values,
            resp=resp,
        ),
        "/rename": lambda: portfolio_handler.handle_rename(
            chat_id=chat_id,
            values=values,
            resp=resp,
        ),
    }

    analytic_commands = {
        "/portfolio_snapshot",
        "/portfolio_summary",
        "/portfolio_breakdown",
        "/portfolio_digest",
        "/portfolio_movers",
        "/po_if",
    }

    for command in analytic_commands:
        handlers.setdefault(command, lambda cmd=command: analytic_json_pages(ui, resp))

    return handlers, analytic_commands



def build_handlers(
    ui,
    session_service,
    dispatcher,
    settings,
    formatting_service,
    sticky_commands,
):
    market_handler = MarketHandler(
        ui,
        session_service,
        dispatcher,
        settings,
        sticky_commands=sticky_commands,
        formatting_service=formatting_service,
    )

    portfolio_snapshot_builder = partial(
        portfolio_pages_with_fallback,
        formatter=formatting_service,
    )
    allocation_builder = partial(
        allocation_table_pages,
        formatter=formatting_service,
    )
    portfolio_handler = PortfolioHandler(
        ui,
        session_service,
        dispatcher,
        settings,
        sticky_commands=sticky_commands,
        snapshot_builder=portfolio_snapshot_builder,
        allocation_builder=allocation_builder,
        formatting_service=formatting_service,
    )

    trading_handler = TradingHandler(
        ui,
        session_service,
        dispatcher,
        settings,
        sticky_commands=sticky_commands,
        formatting_service=formatting_service,
    )

    system_handler = SystemHandler(
        ui,
        session_service,
        dispatcher,
        settings,
        sticky_commands=sticky_commands,
    )

    return market_handler, portfolio_handler, trading_handler, system_handler

async def process_text(chat_id: int, sender_id: int, text: str, ctx, user_context: Dict[str, Any] = None):
    s, registry, sessions, idemp, dispatcher, http = ctx
    ui = load_ui(get_settings().UI_PATH)
    if not ui:
        raise HTTPException(status_code=500, detail="UI config missing")

    session_service = SessionService(sessions, s)
    sticky_commands = session_service.get_sticky_commands()
    market_handler = MarketHandler(
        ui,
        session_service,
        dispatcher,
        s,
        sticky_commands=sticky_commands,
        formatting_service=formatting_service,
    )
    portfolio_snapshot_builder = partial(portfolio_pages_with_fallback, formatter=formatting_service)
    allocation_builder = partial(allocation_table_pages, formatter=formatting_service)
    portfolio_handler = PortfolioHandler(
        ui,
        session_service,
        dispatcher,
        s,
        sticky_commands=sticky_commands,
        snapshot_builder=portfolio_snapshot_builder,
        allocation_builder=allocation_builder,
        formatting_service=formatting_service,
    )
    trading_handler = TradingHandler(
        ui,
        session_service,
        dispatcher,
        s,
        sticky_commands=sticky_commands,
        formatting_service=formatting_service,
    )
    system_handler = SystemHandler(
        ui,
        session_service,
        dispatcher,
        s,
        sticky_commands=sticky_commands,
    )
    if user_context is None:
        user_context = {}
    elif not isinstance(user_context, dict):
        user_context = dict(user_context)
    if sender_id and not user_context.get("user_id"):
        user_context["user_id"] = sender_id
    # owner gate (only if configured)
    if s.owner_ids and sender_id not in s.owner_ids:
        pages = render_screen(ui, "not_authorized", {})
        return [p for p in pages]

    # parse
    cmd, tokens = parse_text(text)
    if cmd is None:
        # If ongoing session, treat as input-only
        session = session_service.get(chat_id)
        if not session:
            pages = render_screen(ui, "unknown_input", {})
            return [p for p in pages]
        cmd = session.get("cmd")
        tokens = [t for t in tokens if t]

    # handle /cancel
    if cmd == "/cancel":
        return await system_handler.handle_cancel(chat_id=chat_id)

    # handle /exit (alias for closing any sticky session)
    if cmd == "/exit":
        return await system_handler.handle_exit(chat_id=chat_id)

    # handle /help
    if cmd == "/help":
        return await system_handler.handle_help(chat_id=chat_id)

    spec = registry.get(cmd)
    if not spec:
        # Unknown command via UI, fallback minimal
        pages = render_screen(ui, "unknown_command", {"cmd": cmd})
        return [p for p in pages]

    # If switching away from a sticky session to a different command, clear it
    existing = session_service.get(chat_id) or {}
    if session_service.should_clear_session(spec, existing):
        session_service.clear(chat_id)
        existing = {}

    # session merge
    got = existing.get("got") if existing.get("cmd") == spec.name else {}
    dispatch_override = None

    if spec.name in ("/buy", "/sell") and tokens:
        tokens = [tok for tok in tokens if tok.lower() not in ("at", "@")]

    if spec.name == "/cash_remove":
        confirm_state = existing.get("confirm")
        if confirm_state and not (text or "").strip().startswith("/"):
            should_proceed, dispatch_values, response_pages = portfolio_handler.handle_confirmation_response(
                chat_id=chat_id,
                spec=spec,
                text=text,
                tokens=tokens,
                confirm_state=confirm_state
            )
            if response_pages:
                return response_pages
            if should_proceed:
                dispatch_override = dispatch_values
                values = dict(confirm_state.get("values", {}))
                missing = []
                err = None

    if spec.name == "/remove":
        confirm_state = existing.get("confirm")
        if confirm_state and not (text or "").strip().startswith("/"):
            should_proceed, dispatch_values, response_pages = portfolio_handler.handle_confirmation_response(
                chat_id=chat_id,
                spec=spec,
                text=text,
                tokens=tokens,
                confirm_state=confirm_state
            )
            if response_pages:
                return response_pages
            if should_proceed:
                dispatch_override = dispatch_values
                values = dict(confirm_state.get("values", {}))
                missing = []
                err = None

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
    should_prompt_when_empty = spec.args_schema and spec.name not in ["/help", "/cancel", "/exit", "/portfolio", "/cash", "/allocation", "/tx", "/fx", "/portfolio_snapshot", "/portfolio_summary", "/portfolio_breakdown", "/portfolio_digest", "/portfolio_movers"]
    user_provided_no_args = not tokens and not (existing and existing.get("got"))


    if missing or (should_prompt_when_empty and user_provided_no_args):
        # Start a sticky session if command is configured as sticky
        session_service.create_session(
            chat_id,
            spec,
            values=values,
            missing=missing,
        )
        # Prefer UI screens first; otherwise minimal fallback
        msg = None
        # UI generic command prompt mapping: /cmd -> cmd_prompt
        screen_key = spec.name.lstrip("/") + "_prompt"
        ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
        prompt_data = {"ttl_min": ttl_min}

        # For /cash_remove, get current cash balance for prompt
        if spec.name == "/cash_remove":
            cash_balance = await portfolio_handler.handle_cash_overview(
                user_context=user_context,
                return_formatted_only=True
            )
            prompt_data.update({"cash_balance": cash_balance})

        # For /allocation_edit, fetch current allocation data to show in prompt
        if spec.name == "/allocation_edit":
            try:
                # Make API call to get current allocation using same pattern as dispatcher
                user_id = (user_context or {}).get("user_id")
                if user_id:
                    import httpx
                    base = get_settings().PORTFOLIO_CORE_URL.rstrip("/")
                    url = f"{base}/allocation"
                    timeout = get_settings().HTTP_TIMEOUT_SEC

                    # Use same params pattern as dispatcher: user_context in query params
                    params = {k: v for k, v in (user_context or {}).items() if v is not None}

                    # Use sync httpx client with same timeout/retry as main http client
                    with httpx.Client(timeout=timeout) as client:
                        resp = client.get(url, params=params)
                        if resp.status_code == 200:
                            allocation_data = resp.json().get("data", {})
                            target = allocation_data.get("target", {})
                            prompt_data.update({
                                "stock_target_pct": target.get("stock_pct", 0),
                                "etf_target_pct": target.get("etf_pct", 0),
                                "crypto_target_pct": target.get("crypto_pct", 0),
                            })
                        else:
                            # Default values if API call fails
                            prompt_data.update({
                                "stock_target_pct": 0,
                                "etf_target_pct": 0,
                                "crypto_target_pct": 0,
                            })
                else:
                    # Default values if no user_id
                    prompt_data.update({
                        "stock_target_pct": 0,
                        "etf_target_pct": 0,
                        "crypto_target_pct": 0,
                    })
            except Exception:
                # Default values if any error occurs
                prompt_data.update({
                    "stock_target_pct": 0,
                    "etf_target_pct": 0,
                    "crypto_target_pct": 0,
                })

        pages = render_screen(ui, screen_key, prompt_data)
        return [p for p in pages]

    # ready to dispatch
    # For sticky sessions, keep the session alive after each success
    clear_after = True
    if session_service.is_sticky(spec.name) and existing and existing.get("cmd") == spec.name and existing.get("sticky"):
        clear_after = False
    dispatch_values = dispatch_override or values
    if spec.dispatch.get("service") == "portfolio_core":
        user_id = (user_context or {}).get("user_id")
        if not user_id:
            usage = spec.help.get("usage", "")
            example = spec.help.get("example", "")
            pages = render_screen(ui, "service_error", {"message": "User context unavailable. Please retry.", "usage": usage, "example": example})
            return [p for p in pages] if pages else []
        if dispatch_override is None:
            dispatch_values = prepare_portfolio_payload(spec.name, dict(values), formatting_service)
            method = spec.dispatch.get("method", "GET").upper()
            if method == "POST":
                op_id = dispatch_values.get("op_id")
                if not op_id:
                    op_id = uuid.uuid4().hex
                    dispatch_values["op_id"] = op_id
                values["op_id"] = op_id
            if spec.name == "/cash_remove":
                return portfolio_handler.handle_cash_remove_confirmation(
                    chat_id=chat_id,
                    spec=spec,
                    values=values
                )
            if spec.name == "/remove":
                return portfolio_handler.handle_remove_confirmation(
                    chat_id=chat_id,
                    spec=spec,
                    values=values
                )
    resp = await dispatcher.dispatch(spec.dispatch, dispatch_values, user_context)
    if not isinstance(resp, dict) or not resp.get("ok", False):
        err = (resp or {}).get("error", {})
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        code = err.get("code") if isinstance(err, dict) else None
        if spec.name == "/fx":
            return market_handler.handle_fx_error(
                spec=spec,
                values=values,
                usage=usage,
                example=example,
            )
        if spec.name == "/remove" and code == "NOT_FOUND":
            symbol = (values.get("symbol") or "").upper()
            pages = render_screen(ui, "remove_not_owned", {"symbol": symbol})
            session_service.clear(chat_id)
            return [p for p in pages] if pages else []
        if spec.name == "/cash_remove":
            session_service.clear(chat_id)
        if spec.name == "/remove":
            session_service.clear(chat_id)
        message = err.get("message") if isinstance(err, dict) else None
        pages = render_screen(ui, "service_error", {"message": message or "Internal error", "usage": usage, "example": example})
        return [p for p in pages]

    # success mapping by command
    handlers, analytic_commands = build_success_handlers(
        market_handler,
        portfolio_handler,
        trading_handler,
        ui,
        resp,
        chat_id,
        spec,
        values,
        clear_after,
    )

    handler_fn = handlers.get(spec.name)
    if handler_fn is not None:
        result = handler_fn()
        if inspect.isawaitable(result):
            return await result
        return result

    if spec.name in analytic_commands:
        return analytic_json_pages(ui, resp)


def analytic_json_pages(ui, resp):
    """Handle analytic commands that return JSON data."""
    data = resp.get("data", {})
    if not data:
        return [render_screen(ui, "service_error", {"message": "No data available", "usage": "", "example": ""})[0]]

    # For analytic commands, render the JSON data as a simple table or formatted text
    # This is a fallback implementation - specific handlers should be used for better formatting
    if isinstance(data, dict) and "table_rows" in data:
        return render_screen(ui, "portfolio_result", data)
    else:
        # Simple text representation for other data
        import json
        formatted_data = json.dumps(data, indent=2, ensure_ascii=False)
        return [f"```json\n{formatted_data}\n```"]




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
                "language_code": getattr(msg.from_, 'language_code', 'en'),
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
        "language_code": "en",
    }
    replies = await process_text(chat_id, sender_id, text, (s, registry, sessions, idemp, dispatcher, http), user_context)
    # Also send via Telegram for parity
    for r in replies:
        for chunk in paginate(r):
            await send_telegram_message(s.TELEGRAM_BOT_TOKEN, chat_id, chunk, s.REPLY_PARSE_MODE)
    return {"ok": True}
