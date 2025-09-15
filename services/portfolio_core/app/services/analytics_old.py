"""
Portfolio analytics and performance calculations.
"""
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import zoneinfo
import aiosqlite
from dateutil.relativedelta import relativedelta
import calendar

from ..models import Position, Transaction, Snapshot, UserContext
from ..clients.market_data import market_data


TZ = zoneinfo.ZoneInfo("Europe/Berlin")


class AnalyticsService:
    def __init__(self, db: aiosqlite.Connection, user: UserContext):
        self.db = db
        self.user = user

    async def calculate_twr(
        self,
        start_date: date,
        end_date: date,
        snapshots: List[Dict[str, Any]],
        flows: List[Dict[str, Any]],
    ) -> Tuple[Decimal, List[Dict[str, Any]]]:
        """
        Calculate Time-Weighted Return between dates.
        Returns (twr_pct, daily_returns)
        """
        daily_returns = []
        twr = Decimal("1.0")

        # Build flows by date
        flow_map = {}
        for f in flows:
            d = f["date"]
            if d not in flow_map:
                flow_map[d] = Decimal("0")
            flow_map[d] += Decimal(str(f["amount_eur"]))

        # Process each day
        prev_value = None
        for snap in snapshots:
            d = snap["date"]
            value = Decimal(str(snap["value_eur"]))
            flow = flow_map.get(d, Decimal("0"))
            
            if prev_value is not None and prev_value > 0:
                r = ((value - flow) / prev_value) - 1
            else:
                r = Decimal("0")

            daily_returns.append({
                "date": d,
                "r": r,
                "value": value,
                "flow": flow
            })
            
            twr *= (1 + r)
            prev_value = value

        return (twr - 1, daily_returns)

    async def get_benchmark_returns(
        self,
        period: str,
        symbols: List[str] = ["GSPC.INDX", "XAUUSD.FOREX"]
    ) -> Dict[str, Any]:
        """Get benchmark returns aligned to our period buckets."""
        bench_data = await market_data.get_benchmarks(period, symbols)
        return bench_data.get("benchmarks", {})

    async def get_portfolio_snapshot(self, period: str = "d") -> Dict[str, Any]:
        """Get portfolio snapshot for the period."""
        # Get all positions
        positions = await self._get_positions()
        if not positions:
            return {"value_eur": 0, "pct_change": 0}

        # Get quotes for all positions
        symbols = [p["symbol"] for p in positions]
        quotes = await market_data.get_quote(symbols)

        # Calculate current values
        total_value = Decimal("0")
        for pos in positions:
            quote = next((q for q in quotes.get("quotes", []) if q["symbol"] == pos["symbol"]), None)
            if quote:
                price_eur = Decimal(str(quote["price_eur"]))
                pos["value_eur"] = price_eur * Decimal(str(pos["qty"]))
                total_value += pos["value_eur"]

        # Get benchmarks
        benchmarks = await self.get_benchmark_returns(period)

        return {
            "value_eur": total_value,
            "positions": positions,
            "benchmarks": benchmarks
        }

    async def get_portfolio_digest(self, period: str = "m") -> Dict[str, Any]:
        """Get portfolio digest with period performance."""
        # Get period boundaries
        end_date = datetime.now(TZ).date()
        if period == "d":
            start_date = end_date
        elif period == "w":
            start_date = end_date - timedelta(days=7)
        elif period == "m":
            start_date = end_date - relativedelta(months=1)
        else:  # y
            start_date = date(end_date.year, 1, 1)

        # Get snapshots and flows
        snapshots = await self._get_snapshots(start_date, end_date)
        flows = await self._get_flows(start_date, end_date)
        
        # Calculate TWR
        twr_pct, daily_returns = await self.calculate_twr(start_date, end_date, snapshots, flows)

        # Get current snapshot
        current = await self.get_portfolio_snapshot(period)
        
        # Calculate period flow total
        net_flow = sum(f["amount_eur"] for f in flows)

        return {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "value_eur": current["value_eur"],
            "twr_pct": twr_pct,
            "net_flow_eur": net_flow,
            "positions": current["positions"],
            "benchmarks": current["benchmarks"],
            "daily_returns": daily_returns
        }

    async def _get_positions(self) -> List[Dict[str, Any]]:
        """Get all positions with additional metadata."""
        async with self.db.execute(
            "SELECT * FROM positions WHERE user_id = ?",
            (self.user.user_id,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def _get_snapshots(
        self,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """Get snapshots for date range."""
        async with self.db.execute(
            """
            SELECT * FROM snapshots 
            WHERE user_id = ? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (self.user.user_id, start_date, end_date),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def _get_flows(
        self,
        start_date: date,
        end_date: date
    ) -> List[Dict[str, Any]]:
        """Get cash flows for date range."""
        async with self.db.execute(
            """
            SELECT date(ts) as date, SUM(amount_eur) as amount_eur
            FROM transactions 
            WHERE user_id = ? 
              AND date(ts) BETWEEN ? AND ?
              AND type IN ('deposit', 'withdraw')
            GROUP BY date(ts)
            ORDER BY date(ts)
            """,
            (self.user.user_id, start_date, end_date),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]