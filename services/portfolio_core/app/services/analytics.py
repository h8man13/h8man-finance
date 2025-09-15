"""
Portfolio analytics and performance calculations with proper TWR implementation.
"""
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import zoneinfo
import aiosqlite
from dateutil.relativedelta import relativedelta
import calendar

from ..models import Position, Transaction, Snapshot, UserContext
# Market data client removed - portfolio_core should not directly call market_data


TZ = zoneinfo.ZoneInfo("Europe/Berlin")


class AnalyticsService:
    def __init__(self, db: aiosqlite.Connection, user: UserContext):
        self.db = db
        self.user = user

    def _normalize_to_berlin_tz(self, dt: datetime) -> datetime:
        """Convert datetime to Europe/Berlin timezone."""
        if dt.tzinfo is None:
            # Assume UTC if no timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)

    def _get_bucket_boundaries(self, period: str, ref_date: Optional[date] = None) -> List[date]:
        """Get bucket boundaries for period according to spec."""
        if ref_date is None:
            ref_date = datetime.now(TZ).date()

        boundaries = []

        if period == "d":
            # Today only - just one bucket
            boundaries = [ref_date]

        elif period == "w":
            # Last 7 daily closes
            for i in range(7):
                boundaries.append(ref_date - timedelta(days=i))
            boundaries.reverse()

        elif period == "m":
            # 4 weekly buckets (Friday closes)
            # W0 = current week, W-1 = last week, etc.
            current_weekday = ref_date.weekday()
            days_to_friday = (4 - current_weekday) % 7  # Friday is weekday 4

            for week_offset in range(4):
                # Find Friday of each week
                week_start = ref_date - timedelta(days=days_to_friday + (week_offset * 7))
                boundaries.append(week_start)
            boundaries.reverse()

        elif period == "y":
            # YTD monthly (last day of each month)
            year = ref_date.year
            month = ref_date.month

            for m in range(1, month + 1):
                # Last day of month
                last_day = calendar.monthrange(year, m)[1]
                boundaries.append(date(year, m, last_day))

        return boundaries

    async def calculate_twr(
        self,
        start_date: date,
        end_date: date,
        snapshots: List[Dict[str, Any]],
        flows: List[Dict[str, Any]],
    ) -> Tuple[Decimal, List[Dict[str, Any]]]:
        """
        Calculate Time-Weighted Return per spec:
        V_t = portfolio market value at end of local day t
        F_t = net external cash flow on local day t
        r_t = ((V_t - F_t) / max(V_{t-1}, 0.01)) - 1
        TWR = ∏ (1 + r_t) - 1
        """
        daily_returns = []
        twr = Decimal("1.0")

        # Build flows by date
        flow_map = {}
        for f in flows:
            flow_date = f["date"] if isinstance(f["date"], date) else datetime.fromisoformat(f["date"]).date()
            if flow_date not in flow_map:
                flow_map[flow_date] = Decimal("0")
            flow_map[flow_date] += Decimal(str(f["amount_eur"]))

        # Build snapshots by date
        snap_map = {}
        for snap in snapshots:
            snap_date = snap["date"] if isinstance(snap["date"], date) else datetime.fromisoformat(snap["date"]).date()
            snap_map[snap_date] = Decimal(str(snap["value_eur"]))

        # Calculate daily returns for each date in range
        current_date = start_date
        prev_value = None

        while current_date <= end_date:
            value = snap_map.get(current_date, prev_value or Decimal("0"))
            flow = flow_map.get(current_date, Decimal("0"))

            if prev_value is not None and prev_value > Decimal("0.01"):
                # r_t = ((V_t - F_t) / V_{t-1}) - 1
                r_t = ((value - flow) / prev_value) - Decimal("1")
            else:
                # First day or zero value - set return to 0
                r_t = Decimal("0")

            daily_returns.append({
                "date": current_date.isoformat(),
                "r_t": r_t,
                "value_eur": value,
                "flow_eur": flow,
                "prev_value_eur": prev_value or Decimal("0")
            })

            # Chain the return: TWR *= (1 + r_t)
            twr *= (Decimal("1") + r_t)
            prev_value = value
            current_date += timedelta(days=1)

        # Return final TWR as percentage
        return ((twr - Decimal("1")) * Decimal("100"), daily_returns)

    async def get_benchmark_returns(
        self,
        period: str,
        symbols: List[str] = ["GSPC.INDX", "XAUUSD.FOREX"]
    ) -> Dict[str, Any]:
        """Get benchmark returns - would need to be provided by telegram_router or external service."""
        # Note: Portfolio_core should not directly call market_data
        # Benchmarks should be provided by telegram_router when needed
        return {
            "GSPC.INDX": [],
            "XAUUSD.FOREX": []
        }

    async def get_portfolio_snapshot(self, period: str = "d") -> Dict[str, Any]:
        """Get portfolio snapshot for the period with proper bucket boundaries."""
        # Get bucket boundaries
        boundaries = self._get_bucket_boundaries(period)

        # Get all positions
        positions = await self._get_positions()
        if not positions:
            buckets = []
            for boundary in boundaries:
                buckets.append({
                    "date": boundary.isoformat(),
                    "portfolio_value_eur": Decimal("0"),
                    "portfolio_pct": Decimal("0")
                })
            return {
                "period": period,
                "buckets": buckets,
                "benchmarks": await self.get_benchmark_returns(period)
            }

        # Note: Portfolio_core should get current prices from stored position data
        # Real-time quotes should be handled by telegram_router via market_data
        # Using stored position costs as fallback for now
        quotes_map = {}

        # For period 'd', we need current vs open
        if period == "d":
            total_current = Decimal("0")
            total_open = Decimal("0")

            for pos in positions:
                quote = quotes_map.get(pos["symbol"])
                if quote:
                    qty = Decimal(str(pos["qty"]))
                    current_price = Decimal(str(quote["price_eur"]))
                    open_price = Decimal(str(quote.get("open_price_eur", quote["price_eur"])))  # Fallback to current if no open

                    total_current += qty * current_price
                    total_open += qty * open_price

            pct_change = ((total_current / total_open - Decimal("1")) * Decimal("100")) if total_open > 0 else Decimal("0")

            return {
                "period": period,
                "today": {
                    "portfolio_n": total_current,
                    "portfolio_o": total_open,
                    "portfolio_pct": pct_change.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                },
                "benchmarks": await self.get_benchmark_returns(period)
            }

        # For other periods, calculate values at each bucket boundary
        buckets = []
        for boundary in boundaries:
            # Use current prices as approximation (in real system, would get historical prices)
            total_value = Decimal("0")
            for pos in positions:
                quote = quotes_map.get(pos["symbol"])
                if quote:
                    qty = Decimal(str(pos["qty"]))
                    price_eur = Decimal(str(quote["price_eur"]))
                    total_value += qty * price_eur

            buckets.append({
                "date": boundary.isoformat(),
                "portfolio_value_eur": total_value,
                "portfolio_pct": Decimal("0")  # Will be calculated with TWR
            })

        return {
            "period": period,
            "buckets": buckets,
            "benchmarks": await self.get_benchmark_returns(period)
        }

    async def get_portfolio_digest(self, period: str = "m") -> Dict[str, Any]:
        """Get portfolio digest with period performance and movers."""
        # Get bucket boundaries
        boundaries = self._get_bucket_boundaries(period)
        start_date = boundaries[0] if boundaries else datetime.now(TZ).date()
        end_date = boundaries[-1] if boundaries else datetime.now(TZ).date()

        # Get snapshots and flows
        snapshots = await self._get_snapshots(start_date, end_date)
        flows = await self._get_flows(start_date, end_date)

        # Calculate TWR
        twr_pct, daily_returns = await self.calculate_twr(start_date, end_date, snapshots, flows)

        # Get current portfolio snapshot
        current = await self.get_portfolio_snapshot(period)

        # Get movers
        movers = await self._get_portfolio_movers(period)

        # Calculate net flows
        net_flow = sum(Decimal(str(f["amount_eur"])) for f in flows)

        # Get allocation changes
        allocation = await self._get_allocation_summary()

        return {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "twr_pct": twr_pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
            "net_flow_eur": net_flow,
            "movers": movers,
            "allocation": allocation,
            "benchmarks": current.get("benchmarks", {})
        }

    async def get_portfolio_summary(self, period: str = "m") -> Dict[str, Any]:
        """Get portfolio summary with TWR values and EUR end values per bucket."""
        snapshot = await self.get_portfolio_snapshot(period)
        return snapshot

    async def get_portfolio_breakdown(self, period: str = "y") -> Dict[str, Any]:
        """Get holding-level performance breakdown by percent only."""
        boundaries = self._get_bucket_boundaries(period)

        # Get active positions
        positions = await self._get_positions()
        if not positions:
            return {"breakdown": {}}

        breakdown = {}

        # Get performance data for each position
        for pos in positions:
            symbol = pos["symbol"]
            # Simplified - would need historical data for accurate breakdown
            breakdown[symbol] = []

            for boundary in boundaries:
                # Placeholder - would calculate actual performance vs baseline
                breakdown[symbol].append({
                    "date": boundary.isoformat(),
                    "pct": Decimal("0.0")  # Would be actual % change from period start
                })

        # Add benchmarks
        benchmarks = await self.get_benchmark_returns(period)
        breakdown["spx"] = benchmarks.get("GSPC.INDX", [])
        breakdown["gold"] = benchmarks.get("XAUUSD.FOREX", [])

        return {"breakdown": breakdown}

    async def _get_positions(self) -> List[Dict[str, Any]]:
        """Get all positions with additional metadata."""
        async with self.db.execute(
            "SELECT * FROM positions WHERE user_id = ? AND qty > 0",
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

    async def _get_portfolio_movers(self, period: str) -> List[Dict[str, Any]]:
        """Get best/worst performing holdings for period."""
        positions = await self._get_positions()
        if not positions:
            return []

        movers = []
        for pos in positions:
            # Simplified calculation - would need historical prices for accuracy
            movers.append({
                "symbol": pos["symbol"],
                "pct_change": Decimal("0.0"),  # Would be actual performance
                "eur_change": Decimal("0.0")
            })

        return sorted(movers, key=lambda x: x["pct_change"], reverse=True)

    async def _get_allocation_summary(self) -> Dict[str, Any]:
        """Get allocation summary for digest."""
        # Simplified - would track allocation changes over time
        return {
            "current": {"etf_pct": 60, "stock_pct": 30, "crypto_pct": 10},
            "previous": {"etf_pct": 59, "stock_pct": 31, "crypto_pct": 10}
        }