# H8man Finance - Project Status and Roadmap

## 🎯 Architecture Overview

### Microservices Stack (Current State)
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   fx (✅ DONE)   │    │ market_data (✅) │    │ telegram_router │
│   Port: 8000    │    │   Port: 8001     │    │   Port: 8010    │
│                 │    │                  │    │   (✅ PHASE 1)  │
│ USD/EUR rates   │    │ EODHD + cache    │    │ Telegram Bridge │
│ 23h cache       │    │ EUR conversion   │    │ FastAPI + UI    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  │
                    ┌─────────────────────────┐
                    │   portfolio_core        │
                    │     Port: 8002          │
                    │   (🔄 PHASE 1 DONE)     │
                    │   (🚧 PHASE 2 IN PROG)  │
                    │                         │
                    │ SQLite → Postgres       │
                    │ Positions, Transactions │
                    │ TWR Analytics (pending) │
                    └─────────────────────────┘

Development Utilities:
• SQLite Web: 8081 (fx), 8082 (market_data), 8094 (portfolio)
• Cron Service: portfolio_core snapshots & maintenance
```

## ?? Phase 1 Status - Config Fixes Pending

Phase 1 functionality is roughly 95% complete; configuration and response payload alignment from the September 2025 assessment remain outstanding before we can describe the phase as done.

### Outstanding Issues (Phase 1 Assessment Follow-up)

- `commands.json` parameter mappings: align `/add` (`type` -> `asset_class`), `/buy` + `/sell` (`price_ccy` -> `price_eur`), and reorder `/allocation_edit` arguments to `[stock_pct, etf_pct, crypto_pct]` so `portfolio_core` receives the expected field names.
- Response payload alignment between `portfolio_core` and `telegram_router`: adjust the portfolio snapshot, allocation, and transaction list payloads (including the `count` field) so router templates render correctly.
- UX polish and data quality: ensure zero cash balances prompt `/cash_add`, review market data caching to avoid stale pricing, and populate `fees_eur` when fees are supplied (or document the limitation).

### Immediate Next Actions

1. Update `services/telegram_router/config/commands.json` with the parameter map fixes above.
2. Choose and implement the response alignment approach (`portfolio_core` vs router expectations), then update templates/clients accordingly.
3. Re-run Phase 1 end-to-end tests (`tests/test_phase1_commands.py`) to confirm parsing and rendering once the configuration fixes land.

### ✅ What's Working (Telegram Commands)
All basic portfolio management commands are functional:

**Portfolio Management:**
- `/portfolio` - Shows position table with live pricing
- `/add [qty] [symbol] [type?]` - Add positions with asset class validation
- `/remove [symbol]` - Remove positions with confirmation
- `/rename [symbol] [nickname]` - Set position nicknames

**Cash Operations:**
- `/cash` - Show EUR cash balance
- `/cash_add [amount]` - Add cash with confirmation
- `/cash_remove [amount]` - Remove cash with Y/N confirmation loop

**Trading:**
- `/buy [qty] [symbol] [at price?]` - Buy with WAC cost basis
- `/sell [qty] [symbol] [at price?]` - Sell with WAC cost basis

**Reporting:**
- `/tx [n?]` - Transaction history (defaults to 10)
- `/allocation` - Current allocation table (ETF/Stock/Crypto)
- `/allocation_edit [etf%] [stock%] [crypto%]` - Edit target allocations

### ✅ Infrastructure Completed
- **telegram_router**: Full FastAPI service with n8n integration
- **portfolio_core**: Basic CRUD operations with SQLite
- **Database Schema**: Users, positions, cash_balances, transactions, targets
- **User Management**: Telegram user context extraction and persistence
- **Error Handling**: Common envelope format `{ok, data/error, ts}`
- **UI System**: Clean ui.yml-driven response formatting
- **Integration**: End-to-end Telegram → portfolio_core → response flow

### ✅ Technical Fixes Applied
**Endpoint Path Corrections**:
- Fixed commands.json mappings: `/buy` and `/sell` (not `/tx/buy`, `/tx/sell`)
- Updated PortfolioCoreClient connector URLs in `connectors/portfolio_core.py`
- Fixed Dispatcher path matching logic in `core/dispatcher.py`

**Parameter Mapping Fixes**:
- `/tx` command: Fixed `n` → `limit` parameter mapping in commands.json
- `/allocation_edit`: Changed from `weights` array to individual `etf_pct`, `stock_pct`, `crypto_pct` parameters

**User Context Implementation**:
- Extended TelegramUser model with first_name, last_name, language_code fields
- Added user context extraction in app.py from Telegram message objects
- Implemented user context passing to portfolio_core via dispatcher payload

**Architecture Cleanup**:
- Removed overlapping files (parsers.py, handlers/, router_copies.yaml)
- Consolidated around existing patterns (ui.yml, templates.py, validator.py)
- Updated UI configuration to match new parameter structures

### ✅ Testing
- Comprehensive Phase 1 test suite in `tests/test_phase1_commands.py`
- Integration tests validating Telegram → portfolio_core flow
- All basic command workflows verified

## 📋 Command Specifications (Ideal Behavior)

### 1. `/portfolio` - Portfolio Overview
**Router Parsing**: No parameters required
**portfolio_core Endpoint**: `GET /portfolio`
**Expected Response**:
```json
{
  "ok": true,
  "data": {
    "total_value_eur": "decimal_value",
    "cash_eur": "decimal_value",
    "holdings": [
      {
        "symbol": "AMZN.US",
        "asset_class": "Stock",
        "market": "US",
        "qty_total": "decimal_qty",
        "price_eur": "decimal_price",
        "value_eur": "decimal_value"
      }
    ]
  }
}
```
**Router Output**:
- Header: "Total Portfolio Value: {total_value_eur}"
- Table: Ticker | Asset class | Market | Quantity total | Price EUR | Value EUR
- Cash row only if cash_eur > 0

### 2. `/add [qty] [symbol] [asset_class?]` - Add Position
**Router Parsing**: Extract qty, symbol, optional asset_class ("stock"|"etf"|"crypto")
**Examples**: `/add 10 amzn stock`, `/add 10 sxr8.xetra etf`, `/add 1 btc crypto`
**portfolio_core Endpoint**: `POST /add`
**Request**:
```json
{
  "op_id": "unique_id",
  "symbol": "AMZN.US",
  "asset_class": "Stock",
  "qty": "decimal_qty"
}
```
**Expected Response**: Updated portfolio snapshot (same as `/portfolio`)
**Router Output**: Success message + portfolio snapshot (no benchmarks)

### 3. `/remove [symbol]` - Remove Position
**Router Parsing**: Extract symbol, handle suffixes
**portfolio_core Endpoint**: `POST /remove`
**Request**:
```json
{
  "op_id": "unique_id",
  "symbol": "AMZN.US"
}
```
**Expected Response**: Updated portfolio snapshot OR error if position doesn't exist
**Router Output**: Success message + portfolio snapshot OR "You do not own this symbol"

### 4. `/cash` - Show Cash Balance
**Router Parsing**: No parameters
**portfolio_core Endpoint**: `GET /cash`
**Expected Response**:
```json
{
  "ok": true,
  "data": {
    "cash_eur": "decimal_value"
  }
}
```
**Router Output**: If cash_eur = 0, encourage user to try `/cash_add`

### 5. `/cash_add [amount]` - Add Cash
**Router Parsing**: Extract decimal amount, support sticky/one-shot
**Example**: `/cash_add 1000`
**portfolio_core Endpoint**: `POST /cash_add`
**Request**:
```json
{
  "op_id": "unique_id",
  "amount_eur": "decimal_amount"
}
```
**Expected Response**: Updated portfolio snapshot
**Router Output**: Clear success message + portfolio snapshot

### 6. `/cash_remove [amount]` - Remove Cash (with confirmation)
**Router Parsing**: Extract decimal amount
**Router Flow**:
- One-shot `/cash_remove 500` → "Remove 500 EUR from cash. Confirm Y or N"
- Accept y/yes/n/no → Call portfolio_core OR cancel gracefully
**portfolio_core Endpoint**: `POST /cash_remove`
**Request**:
```json
{
  "op_id": "unique_id",
  "amount_eur": "decimal_amount"
}
```
**Expected Response**: Updated portfolio snapshot

### 7. `/buy [qty] [symbol] [at price?]` - Buy Position
**Router Parsing**: Extract qty, symbol, optional price after "at"
**Examples**: `/buy 3 amzn at 120`, `/buy 3 amzn`
**portfolio_core Endpoint**: `POST /buy`
**Request**:
```json
{
  "op_id": "unique_id",
  "symbol": "AMZN.US",
  "qty": "decimal_qty",
  "price_eur": "decimal_price?"
}
```
**Expected Response**: Updated portfolio snapshot
**Router Output**: Success message + portfolio snapshot

### 8. `/sell [qty] [symbol] [at price?]` - Sell Position
**Router Parsing**: Extract qty, symbol, optional price after "at"
**Examples**: `/sell 1 sxr8.xetra`, `/sell 1 btc`
**portfolio_core Endpoint**: `POST /sell`
**Request**:
```json
{
  "op_id": "unique_id",
  "symbol": "SXR8.XETRA",
  "qty": "decimal_qty",
  "price_eur": "decimal_price?"
}
```
**Expected Response**: Updated portfolio snapshot
**Business Rules**: Prevent negative positions, apply WAC cost basis

### 9. `/tx [n?]` - Transaction History
**Router Parsing**: Extract optional integer limit (default 10)
**Examples**: `/tx 5`, `/tx`
**portfolio_core Endpoint**: `GET /tx?limit=int`
**Expected Response**:
```json
{
  "ok": true,
  "data": {
    "transactions": [
      {
        "ts": "2025-01-01T12:00:00Z",
        "type": "buy|sell|deposit|withdraw",
        "symbol": "AMZN.US",
        "qty": "decimal_qty",
        "price_eur": "decimal_price",
        "fees_eur": "decimal_fees",
        "cash_delta_eur": "decimal_delta"
      }
    ],
    "count": 5
  }
}
```
**Router Output**: "Showing N transactions" + table
**Error Handling**: If no transactions, suggest `/add`, `/buy`, `/cash_add`

### 10. `/allocation` - Allocation Overview
**Router Parsing**: No parameters
**portfolio_core Endpoint**: `GET /allocation`
**Expected Response**:
```json
{
  "ok": true,
  "data": {
    "current": {
      "stock_pct": 60,
      "etf_pct": 30,
      "crypto_pct": 10
    },
    "target": {
      "stock_pct": 60,
      "etf_pct": 30,
      "crypto_pct": 10
    }
  }
}
```
**Router Output**: Table with header "stock | etf | crypto", current row, target row

### 11. `/allocation_edit [stock_pct] [etf_pct] [crypto_pct]` - Edit Allocation
**Router Parsing**: Extract three numeric arguments
**Example**: `/allocation_edit 60 25 15`
**portfolio_core Endpoint**: `POST /allocation_edit`
**Request**:
```json
{
  "op_id": "unique_id",
  "stock_pct": 60,
  "etf_pct": 25,
  "crypto_pct": 15
}
```
**Validation**: Sum must equal 100
**Expected Response**: Before and after allocation snapshots
**Router Output**: Table with 4 rows (titles, previous, current, target)

### 12. `/rename [symbol] [display_name]` - Rename Position
**Router Parsing**: Extract symbol and multi-word display name
**Example**: `/rename amzn Amazon Inc`
**portfolio_core Endpoint**: `POST /rename`
**Request**:
```json
{
  "op_id": "unique_id",
  "symbol": "AMZN.US",
  "display_name": "Amazon Inc"
}
```
**Expected Response**: Success confirmation
**Router Output**: Clear success message with symbol and new name

## 🚧 Phase 2 - IN PROGRESS (Analytics Engine)

### 🎯 Current Priority: Portfolio Analytics Implementation

**Required Analytics Endpoints:**
```
/portfolio_snapshot [d|w|m|y]  - Bucketed performance series
/portfolio_summary [d|w|m|y]   - Total portfolio with benchmarks
/portfolio_breakdown [d|w|m|y] - Holding-level performance
/portfolio_digest [d|w|m|y]    - Compact digest with movers
/portfolio_movers [d|w|m|y]    - Best/worst performers
/po_if [symbol] [±%]           - What-if simulation
```

### 🔧 Implementation Requirements

#### Time-Weighted Return (TWR) Engine
```python
# Daily return formula (neutralizes deposits/withdrawals)
r_t = ((V_t - F_t) / max(V_{t-1}, 0.01)) - 1

# Multi-day chaining
TWR_{a..b} = Π_{t=a..b} (1 + r_t) - 1
```

#### Period Bucket System (Europe/Berlin timezone)
- **d bucket**: Today only (O=open, N=now)
- **w bucket**: Last 7 daily closes (labeled by weekday)
- **m bucket**: 4 weekly buckets keyed to Friday (W0, W-1, W-2, W-3)
- **y bucket**: YTD monthly buckets (January through current month)

#### Benchmark Integration
- S&P 500 (GSPC.INDX) and Gold (XAUUSD.FOREX) from market_data
- EUR conversion at contemporaneous FX rates (avoid FX drift)
- Same bucket boundaries as portfolio for alignment

#### Database Extensions Needed
```sql
-- Add to existing schema
snapshots(
  user_id, date, value_eur,
  net_external_flows_eur, daily_r_t,
  PRIMARY KEY(user_id, date)
)

-- Extend transactions table
ALTER TABLE transactions ADD COLUMN fx_rate_used DECIMAL;
```

### 🚧 Phase 2 Scope Breakdown

1. **TWR Calculation Engine**
   - Daily return computation with flow handling
   - Multi-period chaining logic
   - Inception date handling

2. **Bucket System Implementation**
   - Europe/Berlin timezone normalization
   - DST-aware bucket boundaries
   - Trading day vs calendar day logic

3. **Benchmark Data Pipeline**
   - market_data integration for S&P 500 and Gold
   - Contemporaneous FX conversion
   - Bucket-aligned benchmark series

4. **Analytics Endpoints**
   - All 6 analytics commands with proper JSON responses
   - ui.yml integration for Telegram formatting
   - Error handling for insufficient data

5. **Snapshot Management**
   - Daily snapshot storage for TWR calculation
   - Historical data backfill capability
   - Performance optimization for large time series

### 📋 Command API Examples (Phase 2 Target Output)

#### /portfolio_snapshot [d|w|m|y] (alias /po_snapshot)
Returns per-bucket performance series with benchmarks

**Example**: `/po_snapshot d`
**Human Output**: `today | portfolio: N: €58.900 - O: €58.750 - +0,3% | S&P 500: N: +0,3% - O: +0,0% | gold: N: +0,1% - O: +0,0%`
**JSON Output**:
```json
{
  "ok": true,
  "data": {
    "snapshot": {
      "today": {
        "portfolio_n": 58900,
        "portfolio_o": 58750,
        "portfolio_pct": 0.3,
        "spx_pct": 0.3,
        "gold_pct": 0.1
      }
    }
  },
  "ts": "2025-09-04T12:13:00Z"
}
```

#### /portfolio_summary [d|w|m|y] (alias /po_summary)
**Example**: `/portfolio_summary m`
**Human Output**: `MtD (Fridays closes) | W0 portfolio: €59.000 (+0,4%) | W-1 portfolio: €58.750 (+0,6%) | W-2 portfolio: €58.400 (+0,7%) | W-3 portfolio: €58.000 (+0,8%) | S&P 500: W0 +0,3% | W-1 +0,7% | W-2 +0,6% | W-3 +0,5% | gold: W0 +0,0% | W-1 +0,4% | W-2 +0,1% | W-3 +0,2%`

#### /portfolio_breakdown [d|w|m|y] (alias /po_breakdown)
**Example**: `/portfolio_breakdown y`
**Human Output**: `YTD (monthly closes) | AMZN: Jan +2,1% | Feb +1,0% | Mar -0,5% | Apr +1,8% | May +0,9% | Jun +2,2% | Jul -0,4% | Aug +0,7% | NVDA: Jan +3,0% | Feb +2,2% | Mar -1,1% | … | S&P 500: Jan +1,5% | Feb +0,9% | … | gold: Jan +0,8% | Feb +0,3% | …`

#### /portfolio_digest [d|w|m|y] (alias /po_digest)
**Example**: `/portfolio_digest m`
**Human Output**: `MtD (Fridays closes) | portfolio: W0 €59,000 (+0.4%) | W-1 €58,750 (+0.6%) | movers: AMZN +3.2% (€+340), NVDA -1.4% (€-96) | cash: +€500 | allocation: now 60/30/10 vs prev 59/31/10`

#### /portfolio_movers [d|w|m|y] (alias /po_movers)
**Example**: `/portfolio_movers w`
**Human Output**: `week (7 daily closes) | AMZN: +3,2% | SXR8*: +1,1% | BTC: -0,5% | NVDA: -1,4%`

#### /po_if [symbol] [Δ%]
**Example**: `/po_if AMZN +5%`
**Human Output**: `what-if AMZN: +5% | portfolio: €59.280 | Δ +€530 (+0,9%)`
**JSON Output**:
```json
{
  "ok": true,
  "data": {
    "whatif": {
      "portfolio": 59280,
      "delta_pct": 0.9,
      "delta_eur": 530
    }
  },
  "ts": "2025-09-04T12:19:00Z"
}
```

## 🎯 Phase 3 - PLANNED (Integration & Polish)

### Router Integration
- Replace temporary JSON dumps with dedicated ui.yml screens
- Add analytics command configurations to commands.json
- Implement proper error screens for analytics edge cases

### Schema Alignment
- Ensure all database fields match long-term spec
- Add missing indexes for performance
- Migrate from SQLite to Postgres when ready

### End-to-End Testing
- Analytics command test coverage
- DST handling validation
- Inception date edge cases
- Non-trading day carry-forward logic
- Full Telegram integration tests

### Production Readiness
- Cache optimization for analytics queries
- Database connection pooling
- Performance monitoring
- Error rate tracking

## 🔍 Service Specifications

### fx Service ✅
**Role**: USD/EUR currency conversion service with 23h cache

- **Status**: Production ready
- **Port**: 8000 (external) → 8000 (internal)
- **Dependencies**: None

**Endpoints**:
- `GET /fx?pair=USD_EUR` → `{ ok, data: { base, quote, rate }, ts }`
- `GET /fx/usd-eur` → shorthand for USD/EUR
- `GET /fx/cache/{key}` → inspect cache entry

**Features**:
- Generic BASE_QUOTE pair format (uppercase)
- 23 hours cache for cost optimization
- JSON envelope format only, no human formatting

**Environment Variables**:
- `PORT=8000` - Service port
- `LOG_LEVEL=info` - Logging level
- `FX_CACHE_PATH=/app/data/cache.db` - Cache database path
- `EODHD_KEY=<secret>` - EODHD API key
- `FX_TTL_SEC=82800` - Cache TTL (23 hours)
- `HTTP_TIMEOUT=8.0` - HTTP timeout for external calls

### market_data Service ✅
**Role**: Single source of truth for EODHD data with EUR conversion

- **Status**: Production ready
- **Port**: 8001 (external) → 8000 (internal)
- **Dependencies**: fx service for USD→EUR conversion

**Endpoints**:
- `GET /quote?symbols=AMZN.US,SXR8.XETRA,BTC-USD`
  - Returns: `symbol`, `market`, `currency`, `price`, `price_eur`, `open`, `open_eur`, `ts`
  - Batch processing for multiple symbols
  - EUR conversion via fx service for USD markets
  - Cached responses to minimize costs
- `GET /benchmarks?period=d|w|m|y&symbols=GSPC.INDX,XAUUSD.FOREX`
  - EUR-converted benchmark data
  - Same bucket rules as portfolio_core
  - Period-aligned responses
- `GET /meta?symbol=AMZN.US`
  - Symbol metadata and classification
  - Asset class: ETF|Stock|Crypto
  - Market: US|XETRA|CRYPTO
  - Currency information
  - No fundamentals (excluded from current plan)

**Implementation Rules**:
- **Ticker Format**: SYMBOL.US (default), SYMBOL.XETRA (explicit), BTC-USD (crypto)
- **Currency Handling**: USD prices converted via fx, EUR prices direct
- **Caching**: QUOTES_TTL_SEC=90, BENCH_TTL_SEC=900, META_TTL_SEC=86400
- **Error Handling**: Common envelope `{ ok: false, error: { code, message, source, retriable } }`
- **Crypto Mapping**: BTC-USD → Crypto, market=CRYPTO, ccy=USD

**Environment Variables**:
- `APP_NAME=market_data` - Application name
- `ENV=prod` - Environment
- `LOG_LEVEL=info` - Logging level
- `HOST=0.0.0.0` - Bind host
- `PORT=8000` - Service port
- `CORS_ALLOW_ORIGINS=[]` - CORS origins for Mini App
- `EODHD_BASE_URL=https://eodhd.com/api` - EODHD API base URL
- `EODHD_API_TOKEN=<secret>` - EODHD API token
- `FX_BASE_URL=http://fx:8000` - FX service URL
- `DB_PATH=/app/data/cache.db` - Cache database path
- `QUOTES_TTL_SEC=90` - Quote cache TTL
- `BENCH_TTL_SEC=900` - Benchmark cache TTL
- `META_TTL_SEC=86400` - Metadata cache TTL
- `TELEGRAM_BOT_TOKEN=<secret>` - Telegram bot token

### portfolio_core Service 🚧
**Role**: Core portfolio management and analytics engine

- **Status**: Phase 1 complete, Phase 2 in progress
- **Port**: 8002 (external) → 8000 (internal)
- **Database**: SQLite (migrate to Postgres later)
- **Dependencies**: market_data, fx

**Phase 1 Complete Endpoints**:
- Portfolio CRUD operations
- Cash management
- Trading with WAC cost basis
- Transaction logging
- Allocation management

**Phase 2 Missing Analytics Endpoints**:
- `/portfolio_snapshot [d|w|m|y]` - Bucketed performance series
- `/portfolio_summary [d|w|m|y]` - Total portfolio with benchmarks
- `/portfolio_breakdown [d|w|m|y]` - Holding-level performance
- `/portfolio_digest [d|w|m|y]` - Compact digest with movers
- `/portfolio_movers [d|w|m|y]` - Best/worst performers
- `/po_if [symbol] [±%]` - What-if simulation

**Environment Variables**:
- `APP_NAME=portfolio_core` - Application name
- `ENV=prod` - Environment
- `LOG_LEVEL=info` - Logging level
- `HOST=0.0.0.0` - Bind host
- `PORT=8000` - Service port
- `CORS_ALLOW_ORIGINS=""` - CORS origins for Mini App (CSV)
- `DB_PATH=/app/data/portfolio.db` - Database path
- `MARKET_DATA_URL=http://market_data:8000` - Market data service URL
- `FX_URL=http://fx:8000` - FX service URL
- `TELEGRAM_BOT_TOKEN=<secret>` - Telegram bot token
- `INITDATA_MAX_AGE_SEC=3600` - Mini App auth max age
- `DEFAULT_ETF_TARGET=60` - Default ETF allocation %
- `DEFAULT_STOCK_TARGET=30` - Default stock allocation %
- `DEFAULT_CRYPTO_TARGET=10` - Default crypto allocation %
- `ENABLE_SNAPSHOT_MAINTENANCE=true` - Enable snapshot maintenance
- `ENABLE_PERFORMANCE_ANALYTICS=true` - Enable performance analytics
- `CACHE_PATH=/app/data/cache` - Cache directory
- `CACHE_TTL_SEC=300` - Cache TTL

**Snapshot Cron Service** (Phase 2 requirement):
- Separate container for daily portfolio snapshots
- Cron schedule for TWR calculation
- Environment: `PORTFOLIO_CORE_HOST`, `CLEANUP_DAYS=90`, `LOG_LEVEL=INFO`

### telegram_router Service ✅
**Role**: FastAPI bridge between Telegram and internal microservices

- **Status**: Phase 1 complete
- **Port**: 8010 (external) → 8010 (internal)
- **Mode**: Webhook (Cloudflare prod) or polling (dev)
- **Dependencies**: portfolio_core, market_data, fx

**Features**:
- File-driven configuration (commands.json, ui.yml)
- MarkdownV2 formatting and auto-pagination
- Session management with TTL
- Idempotency per chat/update
- Owner gating via ROUTER_OWNER_IDS

**Environment Variables**:
- `TELEGRAM_BOT_TOKEN=<secret>` - Bot token from @BotFather
- `TELEGRAM_WEBHOOK_SECRET=<secret>` - 64-char webhook validation secret
- `TELEGRAM_MODE=polling|webhook` - Operation mode (polling for dev)
- `REPLY_PARSE_MODE=MarkdownV2` - Telegram message format
- `ROUTER_PORT=8010` - Service port
- `ROUTER_LOG_LEVEL=info` - Logging level
- `ROUTER_SESSION_TTL_SEC=300` - Session TTL (5 minutes)
- `ROUTER_OWNER_IDS=<csv>` - Allowed Telegram user IDs
- `IDEMPOTENCY_PATH=/app/data/idempotency.json` - Idempotency storage
- `SESSIONS_DIR=/app/data/sessions` - Session storage directory
- `REGISTRY_PATH=/config/commands.json` - Commands configuration
- `UI_PATH=/config/ui.yml` - UI templates
- `MARKET_DATA_URL=http://market_data:8000` - Market data service
- `PORTFOLIO_CORE_URL=http://portfolio_core:8000` - Portfolio service
- `FX_URL=http://fx:8000` - FX service
- `HTTP_TIMEOUT_SEC=8.0` - HTTP client timeout
- `HTTP_RETRIES=2` - HTTP client retries

**Integration**:
- Services expose REST endpoints only
- Router handles all Telegram formatting
- HTTP-based communication between services
- User context passed in request headers/body

## 🐳 Docker Deployment

### Main Stack (compose.yml)
**Services and Ports**:
- `fx`: 8000 → 8000 (external port corrected from docs)
- `market_data`: 8001 → 8000 (depends on fx)
- `telegram_router`: 8010 → 8010 (depends on portfolio_core, market_data, fx)
- `portfolio_core`: 8002 → 8000 (depends on market_data)

**Development Utilities**:
- `sqliteweb_fx`: http://127.0.0.1:8081 - FX cache database browser
- `sqliteweb_market_data`: http://127.0.0.1:8082 - Market data cache browser
- `sqliteweb_portfolio`: http://127.0.0.1:8094 - Portfolio database browser

**Health Checks**:
- All services have health checks with 20s intervals
- Dependencies wait for healthy status before starting

**Volumes**:
- `market_data_data` - Market data cache persistence
- `portfolio_core_data` - Portfolio database persistence
- Service-specific data directories mounted

### Portfolio Cron Stack (portfolio_core/docker-compose.cron.yml)
**Additional Services**:
- `portfolio_cron` - Sidecar for daily snapshot maintenance
- Separate cron schedule for TWR calculations
- Shared portfolio_data volume for database access

## 🏗️ Development Guidelines

### Code Organization
- **No hardcoded strings**: Use ui.yml for all user-facing text
- **Common envelopes**: `{ok, data/error, ts}` for all service responses
- **Timezone consistency**: Europe/Berlin for all timestamp operations
- **Error handling**: Retriable flags and proper HTTP status codes

### Testing Strategy
- Unit tests for TWR calculations and bucket logic
- Integration tests for service communication
- End-to-end tests via Telegram API
- Edge case coverage (DST, holidays, inception dates)

### Database Guidelines
- Decimal type for all monetary values
- UTC storage with timezone conversion at query time
- Proper indexing for analytics queries
- Foreign key constraints when migrating to Postgres

## 📊 Current Gaps and Next Steps

### Immediate (Phase 2)
1. Implement TWR calculation engine in portfolio_core
2. Add snapshot table and daily value tracking
3. Build period bucket system with Europe/Berlin timezone
4. Integrate benchmark data from market_data
5. Create analytics endpoints with proper JSON responses

### Short-term (Phase 3)
1. Add ui.yml screens for analytics commands
2. Complete telegram_router integration
3. Add comprehensive test coverage
4. Performance optimization and caching

### Long-term (Future Phases)
1. Migrate to Postgres with proper scaling
2. Add alert system (daily digest, allocation warnings)
3. Mini App frontend integration
4. Advanced analytics (Sharpe ratio, drawdown analysis)

## 🤔 Architecture Decisions & Open Questions

### Service Communication Pattern (Phase 2 Key Decision)
**Current Implementation**: portfolio_core operates independently with stored position costs
**Phase 2 Requirement**: Real-time analytics require external data integration

**Data Flow Options**:
1. `telegram_router -> [market_data + fx] -> portfolio_core` (preferred)
2. Direct portfolio_core → market_data calls (cleaner but breaks current boundaries)

### Critical Open Questions for Phase 2:
1. **Real-time vs Stored Values**: Should analytics use real-time prices or stored costs?
2. **Snapshot Maintenance**: How to trigger daily snapshots for TWR calculations? (Cron service exists)
3. **Service Dependencies**: Should portfolio_core directly call market_data for analytics?
4. **Error Handling**: How to handle missing external data in analytics calculations?
5. **Performance**: Should portfolio_core cache computed analytics or recalculate each time?

### Implementation Assumptions (Current):
- **Timezone**: All calculations use Europe/Berlin for bucket boundaries
- **Currency**: All stored values in EUR equivalents calculated at transaction time
- **Database Schema**: (user_id, symbol) as PRIMARY KEY for positions
- **Service Boundaries**: portfolio_core should not directly call external services (current)
- **FX Fallback**: Hardcoded 0.9 USD→EUR rate when real FX unavailable
- **Symbol Metadata**: Hardcoded defaults when market_data unavailable

### Phase 2 Architectural Decisions Needed:
1. **Analytics Data Source**: Real-time market data integration approach
2. **Benchmark Integration**: How S&P 500 and Gold data flows to analytics
3. **Snapshot Automation**: Daily maintenance scheduling (cron service ready)
4. **Service Authentication**: Shared secrets vs JWT for service-to-service calls
5. **Error Boundaries**: Graceful degradation when external data unavailable
6. **Database Migration**: Strategy for schema changes and data preservation

---

**Note**: This document serves as the single source of truth for project status. Update it as implementation progresses to keep the development context current for all team members and LLM assistants.