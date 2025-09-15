"""
Core portfolio service operations.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, date
from decimal import Decimal
from operator import itemgetter
import aiosqlite

from ..models import (
    Position,
    Transaction,
    CashBalance,
    UserContext,
    Snapshot,
    PositionPerformance,
    TargetAllocation
)
# Market data client removed - portfolio_core should not directly call market_data


class PortfolioService:
    def __init__(self, db: aiosqlite.Connection, user: UserContext):
        self.db = db
        self.user = user
        
    async def get_portfolio_snapshot(self) -> Dict[str, Any]:
        """Get current portfolio snapshot with total value, cash, and positions."""
        # 1. Get active positions - will return positions with Decimal values
        positions = await self._get_active_positions()
        
        # Note: Portfolio_core should use stored position data, not real-time quotes
        # Real-time quotes should be handled by telegram_router via market_data
        # Using stored average costs as current values for portfolio calculations
        quotes_map = {}
        for p in positions:
            quotes_map[p["symbol"]] = {
                "symbol": p["symbol"],
                "price_ccy": p["avg_cost_ccy"],
                "price_eur": p["avg_cost_eur"],
                "currency": p["ccy"],
                "fx_rate": Decimal("1.0")  # Assume EUR equivalent already calculated
            }
        
        # 3. Get cash balance - already returns Decimal
        cash = await self.get_cash_balance()
        
        # 4. Calculate totals
        total_value = Decimal("0")
        positions_with_value = []
        
        for p in positions:
            quote = quotes_map.get(p["symbol"])
            if not quote:
                continue
                
            value_eur = p["qty"] * quote["price_eur"]
            total_value += value_eur
            
            positions_with_value.append({
                "symbol": p["symbol"],
                "nickname": p["nickname"],
                "qty": p["qty"],  # Already Decimal from _get_active_positions
                "value_eur": value_eur,
                "price_ccy": quote["price_ccy"],
                "fx_rate": quote["fx_rate"],
                "ccy": p["ccy"],
                "weight_pct": Decimal("0"),  # Will be calculated after total
                "asset_class": p["asset_class"]
            })
            
        # Add cash to total
        total_value += cash
        
        # Calculate weights
        if total_value > 0:
            for p in positions_with_value:
                p["weight_pct"] = (p["value_eur"] / total_value * 100).quantize(Decimal("0.1"))
                
        return {
            "total_eur": total_value,
            "cash_eur": cash,
            "positions": sorted(positions_with_value, key=itemgetter("value_eur"), reverse=True)
        }
    
    async def _get_active_positions(self) -> List[Dict[str, Any]]:
        """Get all active positions (qty > 0)."""
        async with self.db.execute(
            """
            SELECT p.*, p.qty as qty, p.avg_cost_ccy as avg_cost_ccy, p.avg_cost_eur as avg_cost_eur
            FROM positions p
            WHERE p.user_id = ? AND CAST(p.qty AS NUMERIC) > 0 
            ORDER BY p.symbol
            """,
            (self.user.user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            # Convert numeric fields to Decimal
            positions = []
            for row in rows:
                p = dict(row)
                p["qty"] = Decimal(str(p["qty"]))
                p["avg_cost_ccy"] = Decimal(str(p["avg_cost_ccy"]))
                p["avg_cost_eur"] = Decimal(str(p["avg_cost_eur"]))
                positions.append(p)
            return positions
            
    async def get_cash_balance(self) -> Decimal:
        """Get current cash balance in EUR."""
        async with self.db.execute(
            "SELECT amount_eur FROM cash_balances WHERE user_id = ?",
            (self.user.user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return Decimal(str(row["amount_eur"])) if row else Decimal("0")
            
    async def record_transaction(
        self,
        type: str,
        symbol: Optional[str] = None,
        qty: Optional[Decimal] = None,
        price_ccy: Optional[Decimal] = None,
        amount_eur: Optional[Decimal] = None,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record a transaction and update position/cash as needed."""
        # Note: Portfolio_core should not fetch quotes directly
        # Amount EUR should be provided by caller (telegram_router with real-time data)
        fx_rate = Decimal("1.0")  # Default rate
        if symbol and qty and price_ccy and not amount_eur:
            # Fallback: assume USD to EUR conversion rate of 0.9 for demo
            # In production, telegram_router should provide amount_eur
            fx_rate = Decimal("0.9")
            amount_eur = qty * price_ccy * fx_rate
        elif not amount_eur:
            amount_eur = Decimal("0")
            
        # Start transaction
        async with self.db.execute("BEGIN TRANSACTION"):
            try:
                # Record transaction (amount is always positive for buy, negative for sell)
                tx_amount = -abs(amount_eur) if type == "sell" else abs(amount_eur)
                async with self.db.execute(
                    """
                    INSERT INTO transactions (
                        user_id, type, symbol, qty, price_ccy,
                        ccy, amount_eur, fx_rate_used, note, ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    RETURNING *
                    """,
                    (
                        self.user.user_id,
                        type,
                        symbol,
                        str(qty) if qty is not None else None,
                        str(price_ccy) if price_ccy is not None else None,
                        "USD" if symbol else None,
                        str(tx_amount),
                        str(fx_rate) if symbol else None,
                        note,
                    ),
                ) as cursor:
                    tx = dict(await cursor.fetchone())
                    
                # Update position for buy/sell
                if symbol and qty:
                    # Note: Symbol metadata should be provided by caller (telegram_router)
                    # Using sensible defaults for now
                    meta = {
                        "market": "US",
                        "asset_class": "stock",
                        "currency": "USD"
                    }

                    async with self.db.execute(
                        """
                        INSERT INTO positions (
                            user_id, symbol, market, asset_class, qty,
                            avg_cost_ccy, avg_cost_eur, ccy, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id, symbol) DO UPDATE SET
                            qty = CAST(qty AS NUMERIC) + CAST(excluded.qty AS NUMERIC),
                            avg_cost_ccy = CASE 
                                WHEN CAST(qty AS NUMERIC) + CAST(excluded.qty AS NUMERIC) > 0 THEN
                                    (CAST(qty AS NUMERIC) * CAST(avg_cost_ccy AS NUMERIC) + 
                                    CAST(excluded.qty AS NUMERIC) * CAST(excluded.avg_cost_ccy AS NUMERIC)) / 
                                    (CAST(qty AS NUMERIC) + CAST(excluded.qty AS NUMERIC))
                                ELSE CAST(excluded.avg_cost_ccy AS NUMERIC)
                            END,
                            avg_cost_eur = CASE
                                WHEN CAST(qty AS NUMERIC) + CAST(excluded.qty AS NUMERIC) > 0 THEN
                                    (CAST(qty AS NUMERIC) * CAST(avg_cost_eur AS NUMERIC) + 
                                    CAST(excluded.qty AS NUMERIC) * CAST(excluded.avg_cost_eur AS NUMERIC)) / 
                                    (CAST(qty AS NUMERIC) + CAST(excluded.qty AS NUMERIC))
                                ELSE CAST(excluded.avg_cost_eur AS NUMERIC)
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE CAST(qty AS NUMERIC) + CAST(excluded.qty AS NUMERIC) >= 0
                        RETURNING *
                        """,
                        (
                            self.user.user_id,
                            symbol,
                            meta["market"],
                            meta["asset_class"].lower(),
                            str(qty),
                            str(price_ccy),
                            str(abs(amount_eur / qty)) if qty != 0 else "0",  # Cost is always positive
                            meta["currency"],
                        ),
                    ) as cursor:
                        position = await cursor.fetchone()
                        if not position:
                            raise ValueError("Position update failed or would result in negative quantity")
                        
                # Update cash balance
                if amount_eur:
                    # For deposit/withdraw, use amount_eur as is
                    # For buy/sell, multiply by -1 for buy (money out), keep as is for sell (money in)
                    if type in ("buy", "sell"):
                        cash_delta = -abs(amount_eur) if type == "buy" else abs(amount_eur)
                    else:
                        cash_delta = amount_eur
                        
                    cash_delta_str = str(cash_delta)
                    async with self.db.execute(
                        """
                        INSERT INTO cash_balances (user_id, amount_eur, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id) DO UPDATE SET
                            amount_eur = CAST(
                                COALESCE(amount_eur, '0') AS NUMERIC
                            ) + CAST(? AS NUMERIC),
                            updated_at = CURRENT_TIMESTAMP
                        RETURNING *
                        """,
                        (self.user.user_id, cash_delta_str, cash_delta_str),
                    ) as cursor:
                        balance = await cursor.fetchone()
                        if not balance:
                            raise ValueError("Cash balance update failed")
                        
                await self.db.commit()
                return tx
                
            except Exception as e:
                await self.db.rollback()
                raise e
            
    async def update_cash(self, amount_eur: Decimal, note: Optional[str] = None) -> Dict[str, Any]:
        """Record a cash deposit/withdrawal."""
        amount_str = str(amount_eur)
        async with self.db.execute(
            """
            INSERT INTO cash_balances (user_id, amount_eur, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                amount_eur = CAST(amount_eur AS NUMERIC) + CAST(? AS NUMERIC),
                updated_at = CURRENT_TIMESTAMP
            RETURNING *
            """,
            (self.user.user_id, amount_str, amount_str),
        ) as cursor:
            balance = dict(await cursor.fetchone())
            await self.db.commit()

        # Log transaction
        return await self.record_transaction(
            type="deposit" if amount_eur > 0 else "withdraw",
            amount_eur=amount_eur,
            note=note
        )
        
    async def get_recent_transactions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent transactions, sorted by timestamp descending."""
        limit = min(max(1, limit), 50)  # Limit between 1 and 50
        
        async with self.db.execute(
            """
            SELECT * FROM transactions 
            WHERE user_id = ? 
            ORDER BY ts DESC 
            LIMIT ?
            """,
            (self.user.user_id, limit),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
            
    async def take_snapshot(self) -> Dict[str, Any]:
        """Take a portfolio snapshot and calculate time-weighted return."""
        # Get current portfolio state
        portfolio = await self.get_portfolio_snapshot()
        total_value = portfolio["total_eur"]
        
        # Calculate net external flows since last snapshot
        today = date.today()
        async with self.db.execute(
            """
            SELECT COALESCE(SUM(amount_eur), 0) as flow
            FROM transactions 
            WHERE user_id = ? 
              AND type IN ('deposit', 'withdraw')
              AND DATE(ts) = ?
            """,
            (self.user.user_id, today),
        ) as cursor:
            row = await cursor.fetchone()
            flows = Decimal(str(row["flow"]))
            
        # Calculate daily return if we have yesterday's snapshot
        daily_r = None
        async with self.db.execute(
            """
            SELECT value_eur, net_external_flows_eur
            FROM snapshots
            WHERE user_id = ? AND date = DATE('now', '-1 day')
            """,
            (self.user.user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                prev_value = Decimal(str(row["value_eur"]))
                if prev_value > 0:
                    daily_r = ((total_value - flows) / prev_value - 1) * 100
                    
        # Record snapshot
        async with self.db.execute(
            """
            INSERT INTO snapshots (
                user_id, date, value_eur, net_external_flows_eur, daily_r_t
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                value_eur = excluded.value_eur,
                net_external_flows_eur = excluded.net_external_flows_eur,
                daily_r_t = excluded.daily_r_t
            RETURNING *
            """,
            (self.user.user_id, today, total_value, flows, daily_r),
        ) as cursor:
            return dict(await cursor.fetchone())
            
    async def get_performance(self, period: str = "d") -> Dict[str, Any]:
        """Get performance data for the specified period."""
        bucket_sql = {
            "d": "AND date = CURRENT_DATE",  # Today's hourly
            "w": "AND date >= DATE('now', '-7 days')",  # Last 7 daily closes
            "m": "AND date >= DATE('now', '-1 month')",  # Last 4 weekly closes
            "y": "AND date >= DATE('now', 'start of year')",  # YTD monthly closes
        }.get(period, "AND date = CURRENT_DATE")
        
        # Get snapshots for period
        async with self.db.execute(
            f"""
            SELECT date, value_eur, net_external_flows_eur, daily_r_t
            FROM snapshots
            WHERE user_id = ? {bucket_sql}
            ORDER BY date DESC
            """,
            (self.user.user_id,),
        ) as cursor:
            snapshots = [dict(row) for row in await cursor.fetchall()]
            
        # Get benchmark data from market_data
        spx = await market_data.get_benchmark("SPY", period)
        gold = await market_data.get_benchmark("GLD", period)
        
        # Calculate holding-level performance
        positions = await self._get_active_positions()
        if positions:
            symbols = [p["symbol"] for p in positions]
            perf = await market_data.get_performance(symbols, period)
        else:
            perf = {"performance": []}
            
        return {
            "snapshots": snapshots,
            "spx": spx,
            "gold": gold,
            "holdings": perf["performance"]
        }
        
    async def get_movers(self, period: str = "d") -> List[Dict[str, Any]]:
        """Get best/worst performing holdings for period."""
        positions = await self._get_active_positions()
        if not positions:
            return []
            
        symbols = [p["symbol"] for p in positions]
        perf = await market_data.get_performance(symbols, period)
        
        movers = []
        for p in positions:
            symbol_perf = next((sp for sp in perf["performance"] if sp["symbol"] == p["symbol"]), None)
            if not symbol_perf:
                continue
                
            movers.append({
                "symbol": p["symbol"],
                "nickname": p["nickname"],
                "return_pct": symbol_perf["return_pct"],
                "value_change_eur": symbol_perf["value_change_eur"]
            })
            
        return sorted(movers, key=itemgetter("return_pct"), reverse=True)
        
    async def get_allocation(self) -> Dict[str, Any]:
        """Get current allocation breakdown with target comparison."""
        # Get current portfolio state
        portfolio = await self.get_portfolio_snapshot()
        total_value = portfolio["total_eur"]
        
        # Calculate current allocation
        class_totals = {"etf": 0, "stock": 0, "crypto": 0}
        
        for pos in portfolio["positions"]:
            asset_class = pos["asset_class"].lower()
            if asset_class not in class_totals:
                continue
            class_totals[asset_class] += pos["value_eur"]
            
        current = {
            "etf_pct": int((class_totals["etf"] / total_value * 100) if total_value > 0 else 0),
            "stock_pct": int((class_totals["stock"] / total_value * 100) if total_value > 0 else 0),
            "crypto_pct": int((class_totals["crypto"] / total_value * 100) if total_value > 0 else 0),
        }
        
        # Get target allocation
        async with self.db.execute(
            """
            SELECT * FROM targets
            WHERE user_id = ?
            """,
            (self.user.user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            target = dict(row) if row else {
                "etf_target_pct": 60,
                "stock_target_pct": 30,
                "crypto_target_pct": 10
            }
            
        return {
            "current": current,
            "target": {
                "etf_pct": target["etf_target_pct"],
                "stock_pct": target["stock_target_pct"],
                "crypto_pct": target["crypto_target_pct"]
            }
        }
        
    async def set_allocation_targets(self, etf_pct: int, stock_pct: int, crypto_pct: int) -> Dict[str, Any]:
        """Set target allocation percentages."""
        if etf_pct + stock_pct + crypto_pct != 100:
            raise ValueError("Target percentages must sum to 100")
            
        async with self.db.execute(
            """
            INSERT INTO targets (
                user_id, etf_target_pct, stock_target_pct, crypto_target_pct, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                etf_target_pct = excluded.etf_target_pct,
                stock_target_pct = excluded.stock_target_pct,
                crypto_target_pct = excluded.crypto_target_pct,
                updated_at = CURRENT_TIMESTAMP
            RETURNING *
            """,
            (self.user.user_id, etf_pct, stock_pct, crypto_pct),
        ) as cursor:
            target = dict(await cursor.fetchone())
            
        # Return both old and new allocation
        current = await self.get_allocation()
        return {
            "current": current["current"],
            "target": {
                "etf_pct": target["etf_target_pct"],
                "stock_pct": target["stock_target_pct"],
                "crypto_pct": target["crypto_target_pct"]
            }
        }



    async def get_positions(self) -> List[Position]:
        """Get all positions for the user."""
        async with self.db.execute(
            """
            SELECT * FROM positions 
            WHERE user_id = ? 
            ORDER BY asset_class, symbol
            """,
            (self.user.user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [Position(**dict(row)) for row in rows]

    async def get_cash_balance(self) -> Decimal:
        """Get current cash balance."""
        async with self.db.execute(
            "SELECT amount_eur FROM cash_balances WHERE user_id = ?",
            (self.user.user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return Decimal(row["amount_eur"]) if row else Decimal("0")

    async def add_position(self, symbol: str, qty: Decimal, type_hint: Optional[str] = None) -> Position:
        """Add a new position or update existing."""
        # 1. Get symbol metadata from market_data
        meta = await market_data.get_meta(symbol)
        if not meta:
            raise ValueError(f"Symbol {symbol} not found")

        # 2. Validate type if provided
        asset_class = meta.get("asset_class", "").lower()
        if type_hint and type_hint.lower() != asset_class:
            raise ValueError(f"Type mismatch: provided {type_hint}, but {symbol} is {asset_class}")

        # 3. Get current quote
        quote = await market_data.get_quote([symbol])
        quotes = quote.get("quotes", [])
        if not quotes:
            raise ValueError(f"No quote available for {symbol}")
        
        q = quotes[0]
        price_ccy = Decimal(str(q["price_ccy"]))
        price_eur = Decimal(str(q["price_eur"]))
        
        # 4. Update or insert position
        async with self.db.execute(
            """
            INSERT INTO positions (
                user_id, symbol, market, asset_class, qty,
                avg_cost_ccy, avg_cost_eur, ccy, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, symbol) DO UPDATE SET
                qty = qty + excluded.qty,
                avg_cost_ccy = (
                    (qty * avg_cost_ccy + excluded.qty * excluded.avg_cost_ccy) / 
                    (qty + excluded.qty)
                ),
                avg_cost_eur = (
                    (qty * avg_cost_eur + excluded.qty * excluded.avg_cost_eur) / 
                    (qty + excluded.qty)
                ),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                self.user.user_id,
                meta["symbol"],
                meta["market"],
                asset_class,
                qty,
                price_ccy,
                price_eur,
                meta["currency"],
            ),
        ):
            await self.db.commit()

        # 5. Log transaction
        await self._log_transaction(
            type="add",
            symbol=symbol,
            qty=qty,
            price_ccy=price_ccy,
            ccy=meta["currency"],
            amount_eur=price_eur * qty,
            fx_rate_used=q.get("fx_rate"),
        )

        # 6. Return updated position
        async with self.db.execute(
            "SELECT * FROM positions WHERE user_id = ? AND symbol = ?",
            (self.user.user_id, symbol),
        ) as cursor:
            row = await cursor.fetchone()
            return Position(**dict(row))

    async def remove_position(self, symbol: str) -> None:
        """Remove a position completely."""
        # 1. Get current position
        async with self.db.execute(
            "SELECT * FROM positions WHERE user_id = ? AND symbol = ?",
            (self.user.user_id, symbol),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Position {symbol} not found")
            
            position = Position(**dict(row))

        # 2. Get current quote for P/L calculation
        quote = await market_data.get_quote([symbol])
        quotes = quote.get("quotes", [])
        if not quotes:
            raise ValueError(f"No quote available for {symbol}")
        
        q = quotes[0]
        price_ccy = Decimal(str(q["price_ccy"]))
        price_eur = Decimal(str(q["price_eur"]))

        # 3. Delete position
        async with self.db.execute(
            "DELETE FROM positions WHERE user_id = ? AND symbol = ?",
            (self.user.user_id, symbol),
        ):
            await self.db.commit()

        # 4. Log transaction
        await self._log_transaction(
            type="remove",
            symbol=symbol,
            qty=position.qty,
            price_ccy=price_ccy,
            ccy=position.ccy,
            amount_eur=price_eur * position.qty,
            fx_rate_used=q.get("fx_rate"),
        )

    async def update_cash(self, amount_eur: Decimal) -> CashBalance:
        """Update cash balance (positive for deposit, negative for withdrawal)."""
        async with self.db.execute(
            """
            INSERT INTO cash_balances (user_id, amount_eur, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                amount_eur = amount_eur + excluded.amount_eur,
                updated_at = CURRENT_TIMESTAMP
            """,
            (self.user.user_id, amount_eur),
        ):
            await self.db.commit()

        # Log transaction
        await self._log_transaction(
            type="deposit" if amount_eur > 0 else "withdraw",
            amount_eur=amount_eur,
        )

        # Return updated balance
        async with self.db.execute(
            "SELECT * FROM cash_balances WHERE user_id = ?",
            (self.user.user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return CashBalance(**dict(row))

    async def _log_transaction(
        self,
        type: str,
        amount_eur: Decimal,
        symbol: Optional[str] = None,
        qty: Optional[Decimal] = None,
        price_ccy: Optional[Decimal] = None,
        ccy: Optional[str] = None,
        fx_rate_used: Optional[Decimal] = None,
        note: Optional[str] = None,
    ) -> Transaction:
        """Log a transaction."""
        async with self.db.execute(
            """
            INSERT INTO transactions (
                user_id, ts, type, symbol, qty, price_ccy,
                ccy, amount_eur, fx_rate_used, note
            ) VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING tx_id
            """,
            (
                self.user.user_id,
                type,
                symbol,
                qty,
                price_ccy,
                ccy,
                amount_eur,
                fx_rate_used,
                note,
            ),
        ) as cursor:
            row = await cursor.fetchone()
            tx_id = row[0]  # Get tx_id from RETURNING clause
            await self.db.commit()

        async with self.db.execute(
            "SELECT * FROM transactions WHERE tx_id = ?",
            (tx_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return Transaction(**dict(row))
            
    async def simulate_price_change(
        self,
        symbol: Optional[str] = None,
        asset_class: Optional[str] = None,
        pct_change: Decimal = Decimal("0")
    ) -> Dict[str, Any]:
        """Simulate impact of price change on portfolio."""
        # Get current portfolio state
        current = await self.get_portfolio_snapshot()
        
        # Deep copy the snapshot for simulation
        simulated = {
            "total_eur": current["total_eur"],
            "cash_eur": current["cash_eur"],
            "positions": [dict(p) for p in current["positions"]]
        }
        
        # Apply changes to matching positions
        for pos in simulated["positions"]:
            matches = False
            if symbol and pos["symbol"] == symbol:
                matches = True
            elif asset_class and pos["asset_class"].lower() == asset_class.lower():
                matches = True
                
            if matches:
                old_value = pos["value_eur"]
                new_value = old_value * (1 + pct_change / 100)
                simulated["total_eur"] = simulated["total_eur"] - old_value + new_value
                
                pos["value_eur"] = new_value
                if simulated["total_eur"] > 0:
                    pos["weight_pct"] = (new_value / simulated["total_eur"] * 100).quantize(Decimal("0.1"))
                    
        return {
            "current": {
                "total_eur": current["total_eur"],
                "positions": [{
                    "symbol": p["symbol"],
                    "value_eur": p["value_eur"],
                    "weight_pct": p["weight_pct"]
                } for p in current["positions"] if p["symbol"] == symbol]
            },
            "simulated": {
                "total_eur": simulated["total_eur"],
                "positions": [{
                    "symbol": p["symbol"],
                    "value_eur": p["value_eur"],
                    "weight_pct": p["weight_pct"]
                } for p in simulated["positions"] if p["symbol"] == symbol]
            },
            "delta_eur": simulated["total_eur"] - current["total_eur"],
            "delta_pct": ((simulated["total_eur"] / current["total_eur"]) - 1) * 100 if current["total_eur"] > 0 else 0
        }
        
    async def set_symbol_nickname(self, symbol: str, nickname: Optional[str] = None) -> Dict[str, Any]:
        """Set or clear a nickname for a symbol."""
        # 1. Check if position exists
        async with self.db.execute(
            "SELECT * FROM positions WHERE user_id = ? AND symbol = ?",
            (self.user.user_id, symbol),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Position {symbol} not found")
                
        # 2. Update nickname
        async with self.db.execute(
            """
            UPDATE positions
            SET nickname = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND symbol = ?
            RETURNING *
            """,
            (nickname, self.user.user_id, symbol),
        ) as cursor:
            updated = dict(await cursor.fetchone())
            await self.db.commit()
            return updated
            
    async def get_symbol_nickname(self, symbol: str) -> Optional[str]:
        """Get nickname for a symbol if set."""
        async with self.db.execute(
            "SELECT nickname FROM positions WHERE user_id = ? AND symbol = ?",
            (self.user.user_id, symbol),
        ) as cursor:
            row = await cursor.fetchone()
            return row["nickname"] if row else None