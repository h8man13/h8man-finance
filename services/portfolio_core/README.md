# Portfolio Core Service 🚧

> **Status**: Phase 1 complete, Phase 2 (Analytics) in progress
> **See**: `PROJECT_STATUS_AND_ROADMAP.md` for complete project context

FastAPI service that owns portfolio state: users, positions, cash, transactions, targets, and snapshots. Exposes JSON-only endpoints for Telegram router and Mini App.

## Current Status
- ✅ **Phase 1**: All CRUD operations (portfolio, cash, trading, transactions)
- 🚧 **Phase 2**: Analytics engine implementation in progress
- 🎯 **Missing**: TWR analytics endpoints (`/portfolio_snapshot`, `/portfolio_summary`, etc.)

## Key Features (Phase 1 Complete)
- SQLite persistence with Decimal precision
- User management and authentication
- Position tracking with WAC cost basis
- Cash operations and transaction logging
- Target allocation management

Environment
- PORT=8000
- DB_PATH=/app/data/portfolio.db
- MARKET_DATA_BASE_URL=http://market_data:8000
- FX_BASE_URL=http://fx:8000
- TZ=Europe/Berlin
- TELEGRAM_BOT_TOKEN=... (for /auth/telegram)

Run locally
  uvicorn app.main:app --reload --port 8000

