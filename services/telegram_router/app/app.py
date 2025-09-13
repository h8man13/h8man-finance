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
from .core.templates import escape_mdv2, paginate, euro, monotable, safe_escape_mdv2_with_fences, convert_markdown_to_html, mdv2_blockquote, mdv2_expandable_blockquote, render_blocks
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


def _render_prompt(data) -> str:
    """Render a prompt from copies.prompts.* supporting either:
    - string (multi-line): 1st line header + blockquoted rest
    - blocks (list[dict]): rendered via render_blocks
    """
    if not data:
        return ""
    # Structured blocks
    if isinstance(data, list):
        return render_blocks(data)
    # Fallback: multi-line string
    text = str(data)
    lines = [ln.rstrip() for ln in text.splitlines()]
    head = lines[0] if lines else ""
    rest = [ln for ln in lines[1:] if ln.strip()]
    msg = escape_mdv2(head)
    if rest:
        msg = f"{msg}\n\n" + mdv2_blockquote(rest)
    return msg


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


def build_help_text(registry: Registry, copies: Dict[str, Any], ranking: Dict[str, Any]) -> str:
    # Main header from copies, but format as bold+underline per spec
    raw_header = copies.get("generic", {}).get("header_help", "Commands")
    # Strip common MDV2 markers if present in copies
    for ch in "*_":
        raw_header = raw_header.replace(ch, "")
    lines: List[str] = [f"*__{escape_mdv2(raw_header.strip())}__*"]

    by_name = {c.name: c for c in registry.all()}
    used = set()

    def _render_cmd(c) -> List[str]:
        usage = c.help.get("usage", "")
        example = c.help.get("example", "")
        head = f"{c.name} {usage}".strip()
        bq_lines = [head]
        if example:
            bq_lines.append(f"Example: {example}")
        return [mdv2_blockquote(bq_lines)]

    # Ranked sections
    for sec in ranking.get("sections", []):
        title = (sec.get("title", "") or "").strip()
        cmds = sec.get("commands", [])
        if title:
            lines.append(f"\n*__{escape_mdv2(title)}__*")
        for name in cmds:
            c = by_name.get(name)
            if not c:
                continue
            lines.extend(_render_cmd(c))
            used.add(name)

    # Other commands sorted alpha
    remaining = [c for c in registry.all() if c.name not in used]
    remaining.sort(key=lambda c: c.name)
    if remaining:
        other_hdr = copies.get("generic", {}).get("other_header", "Other")
        lines.append(f"\n*__{escape_mdv2(other_hdr)}__*")
    for c in remaining:
        lines.extend(_render_cmd(c))

    return "\n".join([ln for ln in lines if ln is not None])


async def process_text(chat_id: int, sender_id: int, text: str, ctx):
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx
    # owner gate (only if configured)
    if s.owner_ids and sender_id not in s.owner_ids:
        return [escape_mdv2(copies.get("generic", {}).get("not_authorized", "Not authorized."))]

    # parse
    cmd, tokens = parse_text(text)
    if cmd is None:
        # If ongoing session, treat as input-only
        session = sessions.get(chat_id)
        if not session:
            # Structured unknown input with a hint
            header = copies.get("generic", {}).get("unknown_input", "Unknown input.")
            txt = escape_mdv2(header)
            txt = f"{txt}\n\n" + mdv2_blockquote(["Try: /help"])
            return [txt]
        cmd = session.get("cmd")
        tokens = [t for t in tokens if t]

    # handle /cancel
    if cmd == "/cancel":
        sessions.clear(chat_id)
        return [escape_mdv2(copies.get("generic", {}).get("canceled", "Canceled."))]

    # handle /exit (alias for closing any sticky session)
    if cmd == "/exit":
        sessions.clear(chat_id)
        return [escape_mdv2(copies.get("generic", {}).get("canceled", "Canceled."))]

    # handle /help
    if cmd == "/help":
        # End any existing sticky session when a new root command arrives
        existing = sessions.get(chat_id) or {}
        if existing.get("sticky"):
            sessions.clear(chat_id)
        return [build_help_text(registry, copies, ranking)]

    spec = registry.get(cmd)
    if not spec:
        # Highlight unknown command with a hint
        tmpl = copies.get("generic", {}).get("unknown_command", "Unknown command: {cmd}")
        header = tmpl.format(cmd=cmd)
        txt = escape_mdv2(header)
        txt = f"{txt}\n\n" + mdv2_blockquote(["Try: /help"])
        return [txt]

    # If switching away from a sticky session to a different command, clear it
    existing = sessions.get(chat_id) or {}
    if existing and existing.get("cmd") != spec.name and existing.get("sticky"):
        sessions.clear(chat_id)

    # session merge
    got = existing.get("got") if existing.get("cmd") == spec.name else {}

    values, missing, err = validate_args(spec.args_schema, tokens, got=got, cmd_name=spec.name)
    if err:
        tpl = copies.get("generic", {}).get("invalid_template", "Invalid\nTry: {usage}\nExample: {example}")
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        rendered = tpl.format(error=err, usage=usage, example=example)
        parts = rendered.split("\n")
        header = parts[0]
        bq_lines: List[str] = []
        for line in parts[1:]:
            if line.strip():
                bq_lines.append(line)
        text = escape_mdv2(header)
        if bq_lines:
            text = f"{text}\n\n" + mdv2_blockquote(bq_lines)
        return [text]
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
        # Prefer per-command blocks, then prompts.*, otherwise fall back
        msg = None
        cmd_cfg = copies.get(spec.name, {}) or {}
        if isinstance(cmd_cfg.get("prompt_blocks"), list):
            msg = _render_prompt(cmd_cfg.get("prompt_blocks"))
        if msg is None and spec.name == "/price":
            prompts_cfg = (copies.get("prompts", {}) or {})
            prompt_blocks = prompts_cfg.get("ask_symbols_price_blocks")
            if isinstance(prompt_blocks, list):
                msg = _render_prompt(prompt_blocks)
            else:
                prompt = prompts_cfg.get("ask_symbols_price")
                if prompt:
                    msg = _render_prompt(prompt)
        if not msg:
            usage = spec.help.get("usage", "")
            example = spec.help.get("example", "")
            tpl = copies.get(spec.name, {}).get("prompt_usage") or copies.get("generic", {}).get("missing_template", "Use: {usage}\nMissing: {missing}\nTry: {usage}\nExample: {example}")
            rendered = tpl.format(usage=usage, missing=", ".join(missing), example=example)
            parts = rendered.split("\n")
            header = parts[0]
            bq_lines: List[str] = []
            for line in parts[1:]:
                if line.strip():
                    bq_lines.append(line)
            msg = escape_mdv2(header)
            if bq_lines:
                msg = f"{msg}\n\n" + mdv2_blockquote(bq_lines)
        # In interactive /price mode, add sticky footnote with TTL
        if sticky:
            ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
            hint = f"You can send more symbols now. This session auto-closes after {ttl_min} minute(s) of inactivity or when you run a new command."
            msg = f"{msg}\n\n{escape_mdv2(hint)}"
        return [msg]

    # ready to dispatch
    # For sticky /price sessions, keep the session alive after each success
    clear_after = True
    if spec.name == "/price" and existing and existing.get("cmd") == "/price" and existing.get("sticky"):
        clear_after = False
    resp = await dispatcher.dispatch(spec.dispatch, values)
    if not isinstance(resp, dict) or not resp.get("ok", False):
        err = (resp or {}).get("error", {})
        message = err.get("message", "Service error")
        # Add usage + example to help recover from errors
        usage = spec.help.get("usage", "")
        example = spec.help.get("example", "")
        if usage or example:
            message = f"{message}\nTry: {usage}\nExample: {example}".strip()
        prefix = copies.get("generic", {}).get("error_prefix", "�?-")
        return [escape_mdv2(f"{prefix} {message}")]

    # success mapping by command
    if spec.name == "/price":
        data = resp.get("data", {})
        quotes = data.get("quotes") or []
        # If no quotes, prompt again (keep session open if sticky)
        if not quotes:
            # keep sticky session alive
            sessions.set(chat_id, {
                "chat_id": chat_id,
                "cmd": "/price",
                "expected": [f["name"] for f in spec.args_schema],
                "got": {},
                "missing_from": [],
                "sticky": True,
            })
            # Prefer per-command blocks, then prompts.*, otherwise fall back
            cmd_cfg = copies.get("/price", {}) or {}
            if isinstance(cmd_cfg.get("prompt_blocks"), list):
                msg = _render_prompt(cmd_cfg.get("prompt_blocks"))
                return [msg]
            prompts_cfg = (copies.get("prompts", {}) or {})
            prompt_blocks = prompts_cfg.get("ask_symbols_price_blocks")
            if isinstance(prompt_blocks, list):
                msg = _render_prompt(prompt_blocks)
                return [msg]
            prompt = prompts_cfg.get("ask_symbols_price")
            if prompt:
                msg = _render_prompt(prompt)
                return [msg]
            usage = spec.help.get("usage", "")
            example = spec.help.get("example", "")
            tpl = copies.get(spec.name, {}).get("prompt_usage") or copies.get("generic", {}).get("missing_template", "Use: {usage}\nMissing: {missing}")
            msg = tpl.format(usage=usage, missing="symbols", example=example)
            return [escape_mdv2(msg)]

        # Tabular view for clean readability
        rows: List[List[str]] = [["SYMBOL", "NOW", "OPEN", "%", "MARKET", "FRESHNESS"]]
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
            market_col = market or ("US" if sym.endswith(".US") else "-")
            freshness = str(q.get("freshness") or "").strip() or "n/a"
            ftime = str(q.get("fresh_time") or "").strip()
            fcol = f"{freshness} ({ftime})".strip() if ftime else freshness
            rows.append([f"{disp}{star}", n_txt, o_txt, pct_txt, market_col, fcol])
        text = monotable(rows) if rows else escape_mdv2("No quotes")
        # Refresh sticky session TTL if applicable
        if not clear_after:
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
        # Common footnotes (partial failures) in all modes -> use blockquote
        footnotes_common_str = ""
        if resp.get("partial") or (isinstance(resp.get("error"), dict) and resp.get("error", {}).get("details")):
            details = resp.get("error", {}).get("details", {}) if isinstance(resp.get("error"), dict) else {}
            failed = details.get("symbols_failed") or []
            if failed:
                head = "Some symbols were not found:"
                body = [" ".join(failed)] if isinstance(failed, list) else [str(failed)]
                footnotes_common_str = mdv2_expandable_blockquote([head], body)

        # Footnotes only in interactive mode (sticky)
        if not clear_after:
            # Provider-hour caveat and sticky hint from copies
            ttl_min = int(get_settings().ROUTER_SESSION_TTL_SEC // 60)
            caveat = copies.get("/price", {}).get("caveat") or "Note: Provider limitations may apply."
            hint_tpl = copies.get("/price", {}).get("sticky_hint") or "You can send more symbols now. This session auto-closes after {ttl_min} minute(s) of inactivity or when you run a new command."
            hint = hint_tpl.format(ttl_min=ttl_min)
            blk1 = mdv2_blockquote([caveat])
            blk2 = mdv2_blockquote([hint])
            foot = "\n\n".join([blk1, blk2] + ([footnotes_common_str] if footnotes_common_str else []))
            text = f"{text}\n\n{foot}"
        elif footnotes_common_str:
            text = f"{text}\n\n{footnotes_common_str}"
        return [text]
    if spec.name == "/fx":
        data = resp.get("data", {})
        rate = data.get("rate") or data.get("close") or data.get("price")
        pair = (str(data.get("pair")) or "").upper()
        # fx upstream returns pair sometimes; keep inputs for clarity
        base = (values.get("base", "") or "USD").upper()
        quote = (values.get("quote", "") or "EUR").upper()
        # Invert if user requested EUR/USD but upstream pair is USD_EUR
        rate_disp = rate
        try:
            rnum = float(rate)
        except Exception:
            rnum = None
        if pair == "USD_EUR" and base == "EUR" and quote == "USD" and rnum and rnum != 0.0:
            rate_disp = 1.0 / rnum
        tpl = copies.get("/fx", {}).get("success", "{base}/{quote}: {rate}")
        # Clear session by default for /fx (stateless)
        sessions.clear(chat_id)
        # Display: round to 4 decimals for communication purposes,
        # but leave upstream data untouched for any calculations elsewhere.
        try:
            rate_str = f"{float(rate_disp):.4f}"
        except Exception:
            rate_str = str(rate_disp)
        return [escape_mdv2(tpl.format(base=base, quote=quote, rate=rate_str))]
    if spec.name in ("/buy", "/sell"):
        tpl = copies.get(spec.name, {}).get("success")
        if tpl:
            msg = tpl.format(**values)
            sessions.clear(chat_id)
            return [escape_mdv2(msg)]
        else:
            sessions.clear(chat_id)
            return [escape_mdv2("Done.")]

    # default success
    done = copies.get("generic", {}).get("done", "Done.")
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




