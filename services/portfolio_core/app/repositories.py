"""Database repository helpers."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

import aiosqlite


class PortfolioRepository:
    """High level data access helpers around the SQLite schema."""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    # ------------------------------------------------------------------ positions

    async def list_positions(self, user_id: int) -> List[Dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM positions WHERE user_id = ? ORDER BY symbol",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_position(self, user_id: int, symbol: str) -> Optional[Dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM positions WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def upsert_position(
        self,
        *,
        user_id: int,
        symbol: str,
        asset_class: str,
        market: str,
        qty: Decimal,
        avg_cost_eur: Decimal,
        avg_cost_ccy: Decimal,
        ccy: str,
        display_name: Optional[str] = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO positions (
                user_id, symbol, asset_class, market, qty, avg_cost_eur, avg_cost_ccy, ccy, display_name,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, symbol) DO UPDATE SET
                qty = excluded.qty,
                avg_cost_eur = excluded.avg_cost_eur,
                avg_cost_ccy = excluded.avg_cost_ccy,
                asset_class = excluded.asset_class,
                market = excluded.market,
                ccy = excluded.ccy,
                display_name = COALESCE(excluded.display_name, positions.display_name),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                symbol,
                asset_class,
                market,
                qty,
                avg_cost_eur,
                avg_cost_ccy,
                ccy,
                display_name,
            ),
        )
        await self.conn.commit()

    async def delete_position(self, user_id: int, symbol: str) -> None:
        await self.conn.execute(
            "DELETE FROM positions WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        )
        await self.conn.commit()

    # --------------------------------------------------------------------- cash

    async def get_cash(self, user_id: int) -> Decimal:
        async with self.conn.execute(
            "SELECT amount_eur FROM cash_balances WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return Decimal("0")
        value = row["amount_eur"]
        return Decimal(value) if not isinstance(value, Decimal) else value

    async def set_cash(self, user_id: int, amount: Decimal) -> None:
        await self.conn.execute(
            """
            INSERT INTO cash_balances (user_id, amount_eur, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET amount_eur = excluded.amount_eur, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, amount),
        )
        await self.conn.commit()

    # --------------------------------------------------------------- transactions

    async def add_transaction(
        self,
        *,
        user_id: int,
        op_id: Optional[str],
        tx_type: str,
        symbol: Optional[str],
        asset_class: Optional[str],
        qty: Optional[Decimal],
        price_eur: Optional[Decimal],
        amount_eur: Optional[Decimal],
        cash_delta_eur: Optional[Decimal],
        fees_eur: Optional[Decimal] = None,
        note: Optional[str] = None,
    ) -> int:
        async with self.conn.execute(
            """
            INSERT INTO transactions (
                user_id, op_id, type, symbol, asset_class, qty,
                price_eur, amount_eur, cash_delta_eur, fees_eur, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING tx_id
            """,
            (
                user_id,
                op_id,
                tx_type,
                symbol,
                asset_class,
                qty,
                price_eur,
                amount_eur,
                cash_delta_eur,
                fees_eur,
                note,
            ),
        ) as cursor:
            row = await cursor.fetchone()
        await self.conn.commit()
        return int(row[0])

    async def list_transactions(self, user_id: int, limit: int) -> List[Dict[str, Any]]:
        async with self.conn.execute(
            """
            SELECT *
            FROM transactions
            WHERE user_id = ?
            ORDER BY datetime(ts) DESC, tx_id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def flows_on_date(self, user_id: int, date_str: str) -> Decimal:
        async with self.conn.execute(
            """
            SELECT COALESCE(SUM(cash_delta_eur), 0) AS total
            FROM transactions
            WHERE user_id = ? AND DATE(ts) = DATE(?)
                AND type IN ('cash_add', 'cash_remove')
            """,
            (user_id, date_str),
        ) as cursor:
            row = await cursor.fetchone()
        total = row["total"] if row else 0
        return Decimal(str(total))

    # --------------------------------------------------------------- allocations

    async def get_allocation(self, user_id: int) -> Dict[str, int]:
        async with self.conn.execute(
            "SELECT stock_pct, etf_pct, crypto_pct FROM allocations WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return {"stock_pct": 0, "etf_pct": 0, "crypto_pct": 0}
        return {k: int(row[k]) for k in ("stock_pct", "etf_pct", "crypto_pct")}

    async def set_allocation(self, user_id: int, *, stock_pct: int, etf_pct: int, crypto_pct: int) -> None:
        await self.conn.execute(
            """
            INSERT INTO allocations (user_id, stock_pct, etf_pct, crypto_pct, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                stock_pct = excluded.stock_pct,
                etf_pct = excluded.etf_pct,
                crypto_pct = excluded.crypto_pct,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, stock_pct, etf_pct, crypto_pct),
        )
        await self.conn.commit()

    # ------------------------------------------------------------------ snapshots

    async def upsert_snapshot(
        self,
        *,
        user_id: int,
        date: str,
        value_eur: Decimal,
        net_external_flows_eur: Decimal,
        daily_r_t: Optional[Decimal],
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO snapshots (user_id, date, value_eur, net_external_flows_eur, daily_r_t)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                value_eur = excluded.value_eur,
                net_external_flows_eur = excluded.net_external_flows_eur,
                daily_r_t = excluded.daily_r_t
            """,
            (user_id, date, value_eur, net_external_flows_eur, daily_r_t),
        )
        await self.conn.commit()

    async def list_snapshots(self, user_id: int, start_date: str | None = None, end_date: str | None = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM snapshots WHERE user_id = ?"
        params: List[Any] = [user_id]
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date ASC"
        async with self.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------- alerts

    async def list_alerts(self, user_id: int) -> List[Dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM alerts WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ----------------------------------------------------------------- utilities

    async def execute(self, query: str, params: Sequence[Any]) -> None:
        await self.conn.execute(query, params)
        await self.conn.commit()