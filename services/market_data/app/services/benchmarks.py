import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

from ..clients.eodhd import EodhdClient
from ..clients.fx import FxClient
from ..db import cache_get, cache_set
from ..settings import settings
from ..utils.symbols import normalize_symbol, infer_market_currency

TZ = ZoneInfo(settings.TZ)

def qd(x: Decimal, q: str = "0.1%") -> str:
    # For percents we will pass a decimal fraction and format later upstream. Here we keep numeric string with 1 dp
    if q.endswith("%"):
        # convert percent step to fraction step
        step = q.replace("%","")
        quant = Decimal(step) / Decimal(100)
        return str(x.quantize(quant, rounding=ROUND_HALF_UP))
    return str(x.quantize(Decimal(q), rounding=ROUND_HALF_UP))

def end_of_day_berlin(d: datetime) -> datetime:
    dt = d.astimezone(TZ)
    end = dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return end

def friday_of_iso_week(dt: datetime) -> datetime:
    # Return Friday 23:59:59 of the ISO week of dt
    dtb = dt.astimezone(TZ)
    # Monday=1..Sunday=7; want Friday=5
    delta = 5 - dtb.isoweekday()
    target = dtb + timedelta(days=delta)
    return target.replace(hour=23, minute=59, second=59, microsecond=0, tzinfo=TZ)

async def get_benchmarks(conn, period: str, symbols: List[str]) -> Dict:
    syms = [normalize_symbol(s) for s in symbols]
    key = f"bench:{period}:{','.join(syms)}"
    now_iso = datetime.now(timezone.utc).isoformat()

    cached = await cache_get(conn, "benchmarks_cache", key, now_iso)
    if cached:
        return json.loads(cached)

    eod = EodhdClient()
    fx = FxClient()
    usd_eur = await fx.usd_to_eur()

    series: Dict[str, List[Dict]] = {}

    for s in syms:
        # Load full daily history, then downsample per spec buckets and convert to EUR if needed
        hist = await eod.historical(s, period="daily")
        market, ccy = infer_market_currency(s)

        # Convert to timezone aware and to EUR values
        daily: List[Tuple[datetime, Decimal]] = []
        for bar in hist:
            # EODHD 'date' is YYYY-MM-DD
            dt = datetime.fromisoformat(bar["date"]).replace(tzinfo=TZ)
            close = Decimal(str(bar["close"]))
            close_eur = close * usd_eur if ccy == "USD" else close
            daily.append((end_of_day_berlin(dt), close_eur))

        daily.sort(key=lambda x: x[0])

        points: List[Dict] = []

        if period == "d":
            # Today only: N vs O, but benchmarks return percent series aligned to bucket rules.
            # For d we return a single node labeled 'today' with pct since open.
            today = datetime.now(TZ).date()
            today_bars = [p for p in daily if p[0].date() == today]
            if today_bars:
                # Use last available close as "now" proxy for benchmark, and the first price of day as open
                first = today_bars[0][1]
                last = today_bars[-1][1]
                pct = (last / first) - Decimal("1") if first > 0 else Decimal("0")
                points.append({"label": "today", "pct": qd(pct, "0.1%")})
            else:
                points.append({"label": "today", "pct": "0.0"})
        elif period == "w":
            # Last 7 daily closes, labels by weekday
            last7 = []
            seen = set()
            # iterate from most recent backwards and collect unique local calendar days with a close
            for dt, val in reversed(daily):
                keyd = dt.date()
                if keyd in seen:
                    continue
                seen.add(keyd)
                last7.append((dt, val))
                if len(last7) == 7:
                    break
            last7 = list(reversed(last7))
            if last7:
                base = last7[0][1]
                for dt, val in last7:
                    pct = (val / base) - Decimal("1") if base > 0 else Decimal("0")
                    points.append({"label": dt.strftime("%a"), "pct": qd(pct, "0.1%")})
        elif period == "m":
            # 4 weekly buckets W0..W-3 keyed to Friday close
            # Build map week -> close at or before Friday
            buckets: List[Tuple[str, Decimal]] = []
            # We scan recent days and pick the last available close up to each Friday of current and prior weeks
            today = datetime.now(TZ)
            fridays = []
            base_friday = friday_of_iso_week(today)
            for k in range(4):
                fridays.append(base_friday - timedelta(weeks=k))
            fridays = list(reversed(fridays))  # oldest to newest

            # For each target Friday, pick the last close at or before that Friday
            for fri in fridays:
                chosen = None
                for dt, val in reversed(daily):
                    if dt <= fri:
                        chosen = (fri, val)
                        break
                if chosen:
                    buckets.append((f"W-{len(fridays)-1 - fridays.index(fri)}" if fri != fridays[-1] else "W0", chosen[1]))

            if buckets:
                base = buckets[0][1]
                for label, val in buckets:
                    pct = (val / base) - Decimal("1") if base > 0 else Decimal("0")
                    points.append({"label": label, "pct": qd(pct, "0.1%")})
        elif period == "y":
            # YTD monthly buckets end-of-month close
            by_month: Dict[str, Decimal] = {}
            for dt, val in daily:
                if dt.year != datetime.now(TZ).year:
                    continue
                keym = dt.strftime("%Y-%m")
                by_month[keym] = val  # last write wins ensures last close in month
            labels = sorted(by_month.keys())
            if labels:
                base = by_month[labels[0]]
                for m in labels:
                    pct = (by_month[m] / base) - Decimal("1") if base > 0 else Decimal("0")
                    # Label with month short name
                    pretty = datetime.strptime(m, "%Y-%m").strftime("%b")
                    points.append({"label": pretty, "pct": qd(pct, "0.1%")})
        else:
            raise ValueError("invalid period")

        series[s] = points

    payload = {"series": series}
    await cache_set(conn, "benchmarks_cache", key, json.dumps(payload), settings.BENCH_TTL_SEC, now_iso)
    return payload
