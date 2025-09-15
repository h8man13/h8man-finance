"""
Portfolio domain models and business rules.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, date
from decimal import Decimal
from dataclasses import dataclass


@dataclass
class PortfolioPosition:
    """Portfolio position domain model."""
    user_id: int
    symbol: str
    market: str
    asset_class: str
    qty: Decimal
    avg_cost_ccy: Decimal
    avg_cost_eur: Decimal
    ccy: str
    nickname: Optional[str] = None
    updated_at: Optional[datetime] = None

    def current_value_eur(self, current_price_eur: Decimal) -> Decimal:
        """Calculate current value in EUR."""
        return self.qty * current_price_eur

    def unrealized_pnl_eur(self, current_price_eur: Decimal) -> Decimal:
        """Calculate unrealized P&L in EUR."""
        return self.current_value_eur(current_price_eur) - (self.qty * self.avg_cost_eur)


@dataclass
class PortfolioSnapshot:
    """Portfolio snapshot for analytics."""
    user_id: int
    date: date
    total_value_eur: Decimal
    cash_eur: Decimal
    positions: List[PortfolioPosition]
    net_flows_eur: Decimal = Decimal("0")
    daily_return_pct: Optional[Decimal] = None

    def calculate_allocation(self) -> Dict[str, Decimal]:
        """Calculate asset class allocation percentages."""
        if self.total_value_eur <= 0:
            return {"etf": Decimal("0"), "stock": Decimal("0"), "crypto": Decimal("0")}

        allocation = {"etf": Decimal("0"), "stock": Decimal("0"), "crypto": Decimal("0")}

        for pos in self.positions:
            value_eur = pos.qty * pos.avg_cost_eur  # Using stored cost for now
            asset_class = pos.asset_class.lower()
            if asset_class in allocation:
                allocation[asset_class] += value_eur

        # Convert to percentages
        for asset_class in allocation:
            allocation[asset_class] = (allocation[asset_class] / self.total_value_eur * 100).quantize(Decimal("0.1"))

        return allocation


class PortfolioCalculator:
    """Portfolio calculation business logic."""

    @staticmethod
    def calculate_time_weighted_return(
        snapshots: List[PortfolioSnapshot]
    ) -> Decimal:
        """Calculate Time-Weighted Return for a series of snapshots."""
        if len(snapshots) < 2:
            return Decimal("0")

        twr = Decimal("1.0")

        for i in range(1, len(snapshots)):
            prev_snapshot = snapshots[i - 1]
            curr_snapshot = snapshots[i]

            if prev_snapshot.total_value_eur > Decimal("0.01"):
                # r_t = ((V_t - F_t) / V_{t-1}) - 1
                daily_return = (
                    (curr_snapshot.total_value_eur - curr_snapshot.net_flows_eur) /
                    prev_snapshot.total_value_eur
                ) - Decimal("1")

                twr *= (Decimal("1") + daily_return)

        return (twr - Decimal("1")) * Decimal("100")  # Convert to percentage

    @staticmethod
    def validate_allocation_targets(etf_pct: int, stock_pct: int, crypto_pct: int) -> bool:
        """Validate that allocation targets sum to 100%."""
        return etf_pct + stock_pct + crypto_pct == 100

    @staticmethod
    def calculate_rebalancing_trades(
        current_allocation: Dict[str, Decimal],
        target_allocation: Dict[str, int],
        total_value_eur: Decimal
    ) -> Dict[str, Decimal]:
        """Calculate trades needed to rebalance to target allocation."""
        trades = {}

        for asset_class, target_pct in target_allocation.items():
            current_pct = current_allocation.get(asset_class, Decimal("0"))
            diff_pct = Decimal(str(target_pct)) - current_pct

            # Calculate EUR amount to trade
            trades[asset_class] = (diff_pct / 100) * total_value_eur

        return trades