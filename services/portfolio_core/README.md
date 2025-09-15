portfolio_core
================

FastAPI service that owns portfolio state: users, positions, cash, transactions, targets, alerts, and daily snapshots. It exposes JSON-only endpoints for both the Telegram router and the Mini App.

Key features
- SQLite for persistence (aiosqlite)
- Decimal for money/FX math
- CORS enabled for Mini App
- Telegram WebApp auth endpoint (/auth/telegram)
- Endpoints: portfolio snapshot, add/remove positions, cash ops, buy/sell, tx list, allocation, rename, what-if, snapshots runner

Environment
- PORT=8000
- DB_PATH=/app/data/portfolio.db
- MARKET_DATA_BASE_URL=http://market_data:8000
- FX_BASE_URL=http://fx:8000
- TZ=Europe/Berlin
- TELEGRAM_BOT_TOKEN=... (for /auth/telegram)

Run locally
  uvicorn app.main:app --reload --port 8000

