# FX Service

A FastAPI service exposing cached USD/EUR FX rates (and generic `BASE_QUOTE` pairs). Used by other services for EUR conversions and by the Telegram router for `/fx`.

## Endpoints
- `GET /fx?pair=USD_EUR` → `{ ok, data: { base, quote, rate }, ts }`
- `GET /fx/usd-eur` → shorthand for USD/EUR
- `GET /fx/cache/{key}` → inspect cache entry

## Run
- Local: `uvicorn main:app --host 0.0.0.0 --port 8000`
- Docker: `docker build -t fx . && docker run -p 8020:8000 fx`
- Compose: `docker compose up fx`

## Notes
- Returns JSON envelopes only; no human formatting.
- Pair format is `BASE_QUOTE` (uppercase). Example: `USD_EUR`.
