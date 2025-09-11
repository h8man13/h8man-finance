from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml
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
from .core.templates import escape_mdv2, paginate, euro, monotable
from .connectors.http import HTTPClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.ROUTER_LOG_LEVEL)
    # ensure data dirs
    os.makedirs(os.path.dirname(s.IDEMPOTENCY_PATH), exist_ok=True)
    os.makedirs(s.SESSIONS_DIR, exist_ok=True)
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


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# startup handled by lifespan


def deps() -> Tuple[Settings, Registry, Dict[str, Any], Dict[str, Any], SessionStore, IdempotencyStore, Dispatcher, HTTPClient]:
    s = get_settings()
    registry = Registry(s.REGISTRY_PATH)
    copies = load_yaml(s.COPIES_PATH)
    ranking = load_yaml(s.RANKING_PATH)
    sessions = SessionStore(s.SESSIONS_DIR, ttl_sec=s.ROUTER_SESSION_TTL_SEC)
    idemp = IdempotencyStore(s.IDEMPOTENCY_PATH)
    http = HTTPClient(timeout=s.HTTP_TIMEOUT_SEC, retries=s.HTTP_RETRIES)
    dispatch = Dispatcher(http)
    return s, registry, copies, ranking, sessions, idemp, dispatch, http


async def send_telegram_message(token: str, chat_id: int, text: str, parse_mode: str = "MarkdownV2"):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=8.0) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })


def build_help_text(registry: Registry, copies: Dict[str, Any], ranking: Dict[str, Any]) -> str:
    header = copies.get("generic", {}).get("header_help", "*Commands*")
    lines: List[str] = [header]
    by_name = {c.name: c for c in registry.all()}

    used = set()
    for sec in ranking.get("sections", []):
        title = sec.get("title", "")
        cmds = sec.get("commands", [])
        if title:
            lines.append(escape_mdv2(f"\n{title}"))
        for name in cmds:
            if name in by_name:
                c = by_name[name]
                usage = c.help.get("usage", "")
                lines.append(f"{escape_mdv2(c.name)} {escape_mdv2(usage)}".strip())
                used.add(name)

    # other commands sorted alpha
    remaining = [c for c in registry.all() if c.name not in used]
    remaining.sort(key=lambda c: c.name)
    if remaining:
        lines.append(escape_mdv2("\nOther"))
    for c in remaining:
        usage = c.help.get("usage", "")
        lines.append(f"{escape_mdv2(c.name)} {escape_mdv2(usage)}".strip())

    return "\n".join(lines)


async def process_text(chat_id: int, sender_id: int, text: str, ctx):
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx
    # owner gate
    if sender_id not in s.owner_ids:
        return [escape_mdv2("Not authorized.")]

    # parse
    cmd, tokens = parse_text(text)
    if cmd is None:
        # If ongoing session, treat as input-only
        session = sessions.get(chat_id)
        if not session:
            return [escape_mdv2("Unknown input. Try /help")]
        cmd = session.get("cmd")
        tokens = [t for t in tokens if t]

    # handle /cancel
    if cmd == "/cancel":
        sessions.clear(chat_id)
        return [escape_mdv2(copies.get("generic", {}).get("canceled", "Canceled."))]

    # handle /help
    if cmd == "/help":
        return [build_help_text(registry, copies, ranking)]

    spec = registry.get(cmd)
    if not spec:
        return [escape_mdv2("Unknown command. Try /help")]

    # session merge
    existing = sessions.get(chat_id) or {}
    got = existing.get("got") if existing.get("cmd") == spec.name else {}

    values, missing, err = validate_args(spec.args_schema, tokens, got=got, cmd_name=spec.name)
    if err:
        tpl = copies.get("generic", {}).get("invalid_template", "Invalid")
        return [escape_mdv2(tpl.format(error=err))]
    if missing:
        sessions.set(chat_id, {
            "chat_id": chat_id,
            "cmd": spec.name,
            "expected": [f["name"] for f in spec.args_schema],
            "got": values,
            "missing_from": missing,
        })
        usage = spec.help.get("usage", "")
        tpl = copies.get(spec.name, {}).get("prompt_usage") or copies.get("generic", {}).get("missing_template", "Use: {usage}\nMissing: {missing}")
        msg = tpl.format(usage=usage, missing=", ".join(missing))
        return [escape_mdv2(msg)]

    # ready to dispatch
    sessions.clear(chat_id)
    resp = await dispatcher.dispatch(spec.dispatch, values)
    if not isinstance(resp, dict) or not resp.get("ok", False):
        err = (resp or {}).get("error", {})
        message = err.get("message", "Service error")
        prefix = copies.get("generic", {}).get("error_prefix", "�?-")
        return [escape_mdv2(f"{prefix} {message}")]

    # success mapping by command
    if spec.name == "/price":
        data = resp.get("data", {})
        quotes = data.get("quotes") or []
        # Tabular view for clean readability
        rows: List[List[str]] = [["SYMBOL", "NOW", "OPEN", "%"]]
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
            rows.append([f"{disp}{star}", n_txt, o_txt, pct_txt])
        text = monotable(rows) if rows else escape_mdv2("No quotes")
        return [text]
    if spec.name == "/fx":
        data = resp.get("data", {})
        rate = data.get("rate") or data.get("close") or data.get("price")
        # fx upstream returns pair sometimes; keep inputs for clarity
        base = (values.get("base", "")).upper()
        quote = (values.get("quote", "")).upper()
        tpl = copies.get("/fx", {}).get("success", "{base}/{quote}: {rate}")
        return [escape_mdv2(tpl.format(base=base, quote=quote, rate=str(rate)))]
    if spec.name in ("/buy", "/sell"):
        tpl = copies.get(spec.name, {}).get("success")
        if tpl:
            return [escape_mdv2(tpl.format(**values))]
        else:
            return [escape_mdv2("Done.")]

    # default success
    done = copies.get("generic", {}).get("done", "�o. Done")
    return [escape_mdv2(done)]


async def _poll_updates():
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = deps()
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
                    replies = await process_text(chat_id, sender_id, text, (s, registry, copies, ranking, sessions, idemp, dispatcher, http))
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
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = deps()
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
        replies = await process_text(chat_id, sender_id, text, (s, registry, copies, ranking, sessions, idemp, dispatcher, http))
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
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = deps()
    chat_id = body.chat_id
    text = body.text
    sender_id = s.owner_ids[0] if s.owner_ids else 0
    replies = await process_text(chat_id, sender_id, text, (s, registry, copies, ranking, sessions, idemp, dispatcher, http))
    # Also send via Telegram for parity
    for r in replies:
        for chunk in paginate(r):
            await send_telegram_message(s.TELEGRAM_BOT_TOKEN, chat_id, chunk, s.REPLY_PARSE_MODE)
    return {"ok": True}
