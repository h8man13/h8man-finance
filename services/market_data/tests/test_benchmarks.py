from decimal import Decimal
from datetime import datetime, timedelta, timezone


def _gen_daily(n=10, start_date=None, base=100.0, step=1.0):
    # Produce n days of ascending closes as strings like EODHD returns
    if start_date is None:
        start_date = datetime.now(timezone.utc).date() - timedelta(days=n)
    out = []
    for i in range(n):
        d = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        out.append({"date": d, "close": base + step * i})
    return out


def test_benchmarks_day_and_week(client, monkeypatch):
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    async def _hist(self, sym, period):
        return _gen_daily(7)

    async def _fx(self):
        return Decimal("1.0")

    monkeypatch.setattr(eod_mod.EodhdClient, "historical", _hist)
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", _fx)

    # Day
    r = client.get("/benchmarks", params={"period": "d", "symbols": "AAPL"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    bn = js["data"]["benchmarks"]["AAPL.US"]
    assert set(bn.keys()) == {"n_pct", "o_pct"}

    # Week: should return Mon..Sun (7 entries) filling missing with 0.0
    r = client.get("/benchmarks", params={"period": "w", "symbols": "AAPL"})
    assert r.status_code == 200
    js = r.json()
    arr = js["data"]["benchmarks"]["AAPL.US"]
    assert isinstance(arr, list) and len(arr) == 7
    labels = [x["label"] for x in arr]
    assert labels == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def test_benchmarks_month_and_year(client, monkeypatch):
    from app.clients import eodhd as eod_mod  # type: ignore
    from app.clients import fx as fx_mod  # type: ignore

    # Craft daily data across weeks and months
    today = datetime.now(timezone.utc).date()
    # For 'm', generate last 28 days increasing close
    hist_m = []
    for i in range(28):
        d = (today - timedelta(days=27 - i)).strftime("%Y-%m-%d")
        hist_m.append({"date": d, "close": 100 + i})

    # For 'y', pick end-of-month-like days for Jan, Feb, Mar
    year = today.year
    hist_y = [
        {"date": f"{year}-01-31", "close": 100},
        {"date": f"{year}-02-29" if year % 4 == 0 else f"{year}-02-28", "close": 110},
        {"date": f"{year}-03-31", "close": 120},
    ]

    async def hist(self, sym, period):
        return hist_m if period == "daily" else hist_m

    async def fx(self):
        return Decimal("1.0")

    monkeypatch.setattr(eod_mod.EodhdClient, "historical", hist)
    monkeypatch.setattr(fx_mod.FxClient, "usd_to_eur", fx)

    # Month
    r = client.get("/benchmarks", params={"period": "m", "symbols": "AAPL"})
    assert r.status_code == 200
    js = r.json()
    arr = js["data"]["benchmarks"]["AAPL.US"]
    # Ensure labels subset/order W0..W-3
    labels = [x["label"] for x in arr]
    assert labels == [lbl for lbl in ["W0", "W-1", "W-2", "W-3"] if lbl in labels]

    # Year
    # Swap historical to our monthly dataset
    async def hist_yield(self, sym, period):
        return hist_y

    monkeypatch.setattr(eod_mod.EodhdClient, "historical", hist_yield)
    r = client.get("/benchmarks", params={"period": "y", "symbols": "AAPL"})
    assert r.status_code == 200
    js = r.json()
    arr = js["data"]["benchmarks"]["AAPL.US"]
    labels = [x["label"] for x in arr]
    # Expect Jan..Mar present in order
    assert labels[:3] == ["Jan", "Feb", "Mar"]


def test_benchmarks_invalid_period_validation(client):
    r = client.get("/benchmarks", params={"period": "z", "symbols": "AAPL"})
    assert r.status_code == 400
    js = r.json()
    assert js["ok"] is False and js["error"]["code"] == "BAD_INPUT"


def test_benchmarks_missing_period_guard(client):
    # Middleware should transform missing/blank period to BAD_INPUT 400
    r = client.get("/benchmarks", params={"symbols": "AAPL"})
    assert r.status_code == 400
    js = r.json()
    assert js["ok"] is False
    assert js["error"]["code"] == "BAD_INPUT"
