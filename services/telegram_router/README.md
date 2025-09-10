# Telegram Router Service

A FastAPI service that bridges Telegram to your internal microservices. It handles parsing, validation, short‑lived conversational sessions, idempotency, and formats human replies in MarkdownV2. External services return JSON only; this router renders user‑facing text.

## Features
- Webhook (Cloudflare) or long‑polling (dev)
- File‑driven configuration: commands, copies, help ranking
- Conversational UX with partial arguments and `/cancel`
- Idempotency per chat/update
- Owner gating via `ROUTER_OWNER_IDS`
- MarkdownV2 rendering helpers (escape, code, monospaced tables, pagination)

## Layout
```
services/telegram_router/
  app/
    app.py                # FastAPI app (webhook, health, dev polling)
    settings.py           # env via pydantic BaseSettings
    models.py             # pydantic DTOs (Telegram update)
    core/
      parser.py           # Telegram parse + tokenization
      registry.py         # mtime-cached loader for commands.json
      validator.py        # schema-driven coercion (EU decimals, %, enums)
      sessions.py         # per-chat sessions (TTL)
      idempotency.py      # dedupe by update_id
      dispatcher.py       # map dispatch.service → connector
      templates.py        # MarkdownV2 helpers
    connectors/
      http.py             # httpx client (timeouts, retries)
      market_data.py      # market_data client
      portfolio_core.py   # portfolio_core client
      fx.py               # fx client
  config/
    commands.json         # registry (names, aliases, args schemas, dispatch)
    router_copies.yaml    # UX copies/templates
    help_ranking.yaml     # /help sections & order
  data/                   # sessions, idempotency (mounted writable)
  Dockerfile
  requirements.txt
  .env.example
```

## Environment
Copy `.env.example` → `.env` and set values (keep out of git):
- `TELEGRAM_BOT_TOKEN`: Bot token
- `TELEGRAM_WEBHOOK_SECRET`: 64‑char secret (for webhook header)
- `TELEGRAM_MODE`: `webhook` or `polling`
- `ROUTER_OWNER_IDS`: comma‑separated Telegram user IDs
- `REGISTRY_PATH`, `COPIES_PATH`, `RANKING_PATH`: point to mounted `/config` files
- Upstreams: `MARKET_DATA_URL`, `PORTFOLIO_CORE_URL`, `FX_URL`

## Run (local)
Option A — Dev server
- Set `TELEGRAM_MODE=polling` and `TELEGRAM_BOT_TOKEN`.
- Start: `uvicorn app.app:app --reload --port 8010` in `services/telegram_router`.
- Send yourself a DM like `/help`.

Option B — Docker Compose
- Copy `.env.example` to `.env` in `services/telegram_router` and set values.
- Start stack: `docker compose up --build`.
- Services:
  - Router: http://localhost:8010 (polling) or webhook mode if configured
  - Market Data: http://localhost:8000
  - FX: http://localhost:8020

## Webhook behind Cloudflare
- Deploy container; expose `8010` (or behind reverse proxy)
- Set webhook:
```
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d url="https://n8n.hooman.com/telegram/webhook" \
  -d secret_token="$TELEGRAM_WEBHOOK_SECRET"
```
- Cloudflare: proxy enabled, no caching on `/telegram/*`
- Router validates `X-Telegram-Bot-Api-Secret-Token` header

## Message formatting (MarkdownV2)
- All replies use `parse_mode=MarkdownV2`
- Escape special chars: `_ * [ ] ( ) ~ ` + - = | { } . ! > #`
- Use templates in `router_copies.yaml` to keep strings out of code
- Router auto‑paginates replies >4096 chars
- Quotes (`/price`) render as a compact monospaced table for readability.

## Config files
- `commands.json`: authoritative registry; no hardcoding
- `router_copies.yaml`: generic + per‑command copies
- `help_ranking.yaml`: sections + order; unknown commands fall back to alpha

## Endpoints
- `GET /health` → `{ ok: true, ts }`
- `POST /telegram/webhook` (prod): validates header, processes, and sends messages via Telegram
- `POST /telegram/test` (dev): `{ chat_id, text }` → routes through same pipeline and sends a real Telegram message

## Services and envelopes
Upstreams must return envelopes:
- Success: `{ ok: true, data: {...}, ts }`
- Error: `{ ok: false, error: { code, message, ... }, ts }`

Router converts these into MarkdownV2 using templates. No external providers are called from the router.

## Docker
- Build: `docker build -t telegram_router .`
- Run: mount data and config; pass `.env`

## Testing ideas (not included)
- Parser: quoted args, `/cmd@bot`
- Validator: EU decimals, percent
- Sessions: TTL behavior
- Templates: escaping, table layout
- Dispatcher: mapping correctness

## Notes
- `/fx` and `/price` are implemented against `FX_URL` and `MARKET_DATA_URL` respectively.
- Trading `/buy` and `/sell` POST to `PORTFOLIO_CORE_URL`.
- Extend by editing `config/commands.json` and adding a matching connector path.
