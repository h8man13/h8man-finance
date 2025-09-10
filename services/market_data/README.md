# Market Data Service

FastAPI service providing quotes, benchmarks, and symbol metadata for internal consumers. Conforms to JSON envelope `{ ok, data, ts }` and error envelope `{ ok: false, error, ts }`.

## Endpoints
- `GET /quote?symbols=AMZN,SXR8.XETRA` → batch quotes
- `GET /benchmarks?period=d|w|m|y&symbols=spx,gold` → benchmark series normalization
- `GET /meta?symbol=AMZN.US` → symbol meta/classification

## Quote shape
- Returns `data.quotes` with: `symbol`, `market`, `currency`, `price`, `price_eur`, `open`, `open_eur`, `ts`
- EUR conversion is applied with fx service for USD markets; non-USD passthrough

## Run
- Local: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (adjust if entry differs)
- Docker: `docker build -t market_data . && docker run -p 8000:8000 market_data`
- Compose: `docker compose up market_data`

## Notes
- No human formatting; router transforms JSON to MarkdownV2 for Telegram.
- See `app/api.py` for envelope helpers and normalization rules.
