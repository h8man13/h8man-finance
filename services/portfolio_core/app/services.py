"""Domain services implementing portfolio business logic."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from . import db
from .clients import MarketDataClient, market_data_client
from .models import (
    AddPositionRequest,
    AllocationDiff,
    AllocationEditRequest,
    AllocationSnapshot,
    CashBalance,
    CashMutationRequest,
    ErrorCode,
    HoldingSnapshot,
    PortfolioSnapshot,
    RemovePositionRequest,
    RenameRequest,
    TradeRequest,
    TransactionRecord,
    TxQuery,
    UserContext,
)
from .repositories import PortfolioRepository
from .settings import settings


ASSET_CLASS_NORMALISATION = {
    "stock": "stock",
    "stocks": "stock",
    "equity": "stock",
    "equities": "stock",
    "share": "stock",
    "shares": "stock",
    "etf": "etf",
    "etfs": "etf",
    "fund": "etf",
    "funds": "etf",
    "crypto": "crypto",
    "crypt": "crypto",
    "cryptocurrency": "crypto",
    "coin": "crypto",
    "coins": "crypto",
    "btc": "crypto",
}


@dataclass(slots=True)
class BusinessError(Exception):
    code: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        payload = {"code": self.code.value, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class PortfolioService:
    """Core entrypoint for portfolio operations."""

    def __init__(self, conn: aiosqlite.Connection, market_client: MarketDataClient | None = None) -> None:
        self.conn = conn
        self.repo = PortfolioRepository(conn)
        self.market = market_client or market_data_client

    # ------------------------------------------------------------------ utilities

    async def _ensure_user(self, user: UserContext) -> None:
        await db.upsert_user(self.conn, user.model_dump())
        await db.ensure_user_state(
            self.conn,
            user.user_id,
            defaults={
                "stock_pct": settings.DEFAULT_STOCK_TARGET_PCT,
                "etf_pct": settings.DEFAULT_ETF_TARGET_PCT,
                "crypto_pct": settings.DEFAULT_CRYPTO_TARGET_PCT,
            },
        )

    def _normalise_symbol(self, symbol: str) -> str:
        symbol = symbol.strip().upper()
        if "." not in symbol:
            symbol = f"{symbol}.US"
        return symbol

    def _normalise_asset_class(self, provided: Optional[str], meta: Optional[str]) -> str:
        if provided:
            key = provided.strip().lower()
            if key in ASSET_CLASS_NORMALISATION:
                return ASSET_CLASS_NORMALISATION[key]
        if meta:
            key = meta.strip().lower()
            if key in ASSET_CLASS_NORMALISATION:
                return ASSET_CLASS_NORMALISATION[key]
        return "stock"

    async def _with_idempotency(
        self,
        *,
        user_id: int,
        op_id: str,
        command: str,
        producer,
    ) -> Dict[str, Any]:
        cached = await db.get_operation(self.conn, user_id=user_id, op_id=op_id)
        if cached is not None:
            return cached
        result = await producer()
        await db.record_operation(
            self.conn,
            user_id=user_id,
            op_id=op_id,
            command=command,
            result=result,
        )
        return result

    async def _build_snapshot(self, user_id: int) -> PortfolioSnapshot:
        positions = await self.repo.list_positions(user_id)
        cash = await self.repo.get_cash(user_id)
        symbols = [row["symbol"].upper() for row in positions]
        quotes = await self.market.get_quotes(symbols, force_refresh=True)
        meta = await self.market.get_meta(symbols)

        holdings: List[HoldingSnapshot] = []
        total_value = Decimal("0")
        for row in positions:
            symbol = row["symbol"].upper()
            qty = Decimal(str(row["qty"]))
            avg_cost = Decimal(str(row["avg_cost_eur"]))
            quote = quotes.get(symbol)
            price = Decimal(str(quote.price_eur)) if quote else avg_cost
            value = (price * qty).quantize(Decimal("0.01"))
            total_value += value
            holdings.append(
                HoldingSnapshot(
                    symbol=symbol,
                    display_name=row.get("display_name"),
                    asset_class=row.get("asset_class"),
                    market=row.get("market"),
                    qty_total=qty,
                    price_eur=price.quantize(Decimal("0.01")),
                    value_eur=value,
                    currency=row.get("ccy"),
                    freshness=quote.freshness if quote else None,
                )
            )

        total_value += cash
        return PortfolioSnapshot(
            total_value_eur=total_value.quantize(Decimal("0.01")),
            cash_eur=cash.quantize(Decimal("0.01")),
            holdings=holdings,
        )

    async def _record_snapshot(self, user_id: int, *, flows_eur: Decimal) -> PortfolioSnapshot:
        snapshot = await self._build_snapshot(user_id)
        today = datetime.now(timezone.utc).date().isoformat()
        prev_rows = await self.repo.list_snapshots(user_id)
        prev_value = None
        if prev_rows:
            for row in reversed(prev_rows):
                if row["date"] < today:
                    prev_value = Decimal(str(row["value_eur"]))
                    break
        value_now = snapshot.total_value_eur
        daily_return: Optional[Decimal] = None
        if prev_value is not None and prev_value > 0:
            daily_return = ((value_now - flows_eur) / prev_value) - Decimal("1")
        elif prev_value is not None:
            daily_return = Decimal("0")
        await self.repo.upsert_snapshot(
            user_id=user_id,
            date=today,
            value_eur=value_now,
            net_external_flows_eur=flows_eur,
            daily_r_t=daily_return,
        )
        return snapshot

    # -------------------------------------------------------------- query methods

    async def portfolio(self, user: UserContext) -> PortfolioSnapshot:
        await self._ensure_user(user)
        return await self._build_snapshot(user.user_id)

    async def cash_balance(self, user: UserContext) -> CashBalance:
        await self._ensure_user(user)
        cash = await self.repo.get_cash(user.user_id)
        return CashBalance(cash_eur=cash.quantize(Decimal("0.01")))

    async def transactions(self, user: UserContext, query: TxQuery) -> List[TransactionRecord]:
        await self._ensure_user(user)
        rows = await self.repo.list_transactions(user.user_id, query.limit)
        records: List[TransactionRecord] = []
        for row in rows:
            ts = datetime.fromisoformat(row["ts"]) if row.get("ts") else datetime.now(timezone.utc)
            records.append(
                TransactionRecord(
                    tx_id=row["tx_id"],
                    ts=ts,
                    type=row.get("type"),
                    symbol=row.get("symbol"),
                    asset_class=row.get("asset_class"),
                    qty=Decimal(str(row["qty"])) if row.get("qty") is not None else None,
                    price_eur=Decimal(str(row["price_eur"])) if row.get("price_eur") is not None else None,
                    amount_eur=Decimal(str(row["amount_eur"])) if row.get("amount_eur") is not None else None,
                    cash_delta_eur=Decimal(str(row["cash_delta_eur"])) if row.get("cash_delta_eur") is not None else None,
                    fees_eur=Decimal(str(row["fees_eur"])) if row.get("fees_eur") is not None else None,
                )
            )
        return records

    async def allocation(self, user: UserContext) -> Dict[str, AllocationSnapshot]:
        await self._ensure_user(user)
        snapshot = await self._build_snapshot(user.user_id)
        totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for holding in snapshot.holdings:
            totals[holding.asset_class] += holding.value_eur
        total_value = snapshot.total_value_eur - snapshot.cash_eur
        if total_value <= 0:
            current = AllocationSnapshot(stock_pct=0, etf_pct=0, crypto_pct=0)
        else:
            current = AllocationSnapshot(
                stock_pct=int((totals.get("stock", Decimal("0")) / total_value * 100).quantize(Decimal("1"))),
                etf_pct=int((totals.get("etf", Decimal("0")) / total_value * 100).quantize(Decimal("1"))),
                crypto_pct=int((totals.get("crypto", Decimal("0")) / total_value * 100).quantize(Decimal("1"))),
            )
        target = AllocationSnapshot(**await self.repo.get_allocation(user.user_id))
        return {"current": current, "target": target}

    # -------------------------------------------------------------- mutation flow

    async def add(self, user: UserContext, request: AddPositionRequest) -> Dict[str, Any]:
        await self._ensure_user(user)
        symbol = self._normalise_symbol(request.symbol)
        meta = (await self.market.get_meta([symbol])).get(symbol)
        asset_class = self._normalise_asset_class(request.asset_class, meta.asset_class if meta else None)
        market = meta.market.upper() if meta and meta.market else (symbol.split(".")[-1])
        ccy = meta.currency.upper() if meta and meta.currency else "EUR"
        quotes = await self.market.get_quotes([symbol], force_refresh=True)
        price = Decimal(str(quotes.get(symbol).price_eur)) if symbol in quotes else Decimal("0")

        async def _run() -> Dict[str, Any]:
            existing = await self.repo.get_position(user.user_id, symbol)
            qty = Decimal(str(request.qty))
            if existing:
                new_qty = Decimal(str(existing["qty"])) + qty
                avg_cost_eur = Decimal(str(existing["avg_cost_eur"]))
                avg_cost_ccy = Decimal(str(existing["avg_cost_ccy"]))
                display_name = existing.get("display_name")
            else:
                new_qty = qty
                avg_cost_eur = price if price > 0 else Decimal("0")
                avg_cost_ccy = avg_cost_eur
                display_name = None
            await self.repo.upsert_position(
                user_id=user.user_id,
                symbol=symbol,
                asset_class=asset_class,
                market=market,
                qty=new_qty,
                avg_cost_eur=avg_cost_eur,
                avg_cost_ccy=avg_cost_ccy,
                ccy=ccy,
                display_name=display_name,
            )
            await self.repo.add_transaction(
                user_id=user.user_id,
                op_id=request.op_id,
                tx_type="add",
                symbol=symbol,
                asset_class=asset_class,
                qty=qty,
                price_eur=None,
                amount_eur=None,
                cash_delta_eur=Decimal("0"),
            )
            snapshot = await self._record_snapshot(user.user_id, flows_eur=Decimal("0"))
            return snapshot.model_dump()

        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="add",
            producer=_run,
        )

    async def remove(self, user: UserContext, request: RemovePositionRequest) -> Dict[str, Any]:
        await self._ensure_user(user)
        symbol = self._normalise_symbol(request.symbol)

        async def _run() -> Dict[str, Any]:
            existing = await self.repo.get_position(user.user_id, symbol)
            if not existing:
                raise BusinessError(ErrorCode.NOT_FOUND, f"{symbol} not held")
            await self.repo.delete_position(user.user_id, symbol)
            await self.repo.add_transaction(
                user_id=user.user_id,
                op_id=request.op_id,
                tx_type="remove",
                symbol=symbol,
                asset_class=existing.get("asset_class"),
                qty=Decimal(str(existing["qty"])),
                price_eur=None,
                amount_eur=None,
                cash_delta_eur=Decimal("0"),
            )
            snapshot = await self._record_snapshot(user.user_id, flows_eur=Decimal("0"))
            return snapshot.model_dump()

        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="remove",
            producer=_run,
        )

    async def cash_add(self, user: UserContext, request: CashMutationRequest) -> Dict[str, Any]:
        await self._ensure_user(user)

        async def _run() -> Dict[str, Any]:
            amount = Decimal(str(request.amount_eur))
            current = await self.repo.get_cash(user.user_id)
            await self.repo.set_cash(user.user_id, current + amount)
            await self.repo.add_transaction(
                user_id=user.user_id,
                op_id=request.op_id,
                tx_type="cash_add",
                symbol=None,
                asset_class=None,
                qty=None,
                price_eur=None,
                amount_eur=amount,
                cash_delta_eur=amount,
            )
            snapshot = await self._record_snapshot(user.user_id, flows_eur=amount)
            return snapshot.model_dump()

        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="cash_add",
            producer=_run,
        )

    async def cash_remove(self, user: UserContext, request: CashMutationRequest) -> Dict[str, Any]:
        await self._ensure_user(user)

        async def _run() -> Dict[str, Any]:
            amount = Decimal(str(request.amount_eur))
            current = await self.repo.get_cash(user.user_id)
            if current < amount:
                raise BusinessError(ErrorCode.INSUFFICIENT, "Insufficient cash balance", details={"current_balance": str(current)})
            await self.repo.set_cash(user.user_id, current - amount)
            await self.repo.add_transaction(
                user_id=user.user_id,
                op_id=request.op_id,
                tx_type="cash_remove",
                symbol=None,
                asset_class=None,
                qty=None,
                price_eur=None,
                amount_eur=amount,
                cash_delta_eur=-amount,
            )
            snapshot = await self._record_snapshot(user.user_id, flows_eur=-amount)
            return snapshot.model_dump()

        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="cash_remove",
            producer=_run,
        )

    async def buy(self, user: UserContext, request: TradeRequest) -> Dict[str, Any]:
        await self._ensure_user(user)
        symbol = self._normalise_symbol(request.symbol)
        meta = (await self.market.get_meta([symbol])).get(symbol)
        asset_class = self._normalise_asset_class(None, meta.asset_class if meta else None)
        market = meta.market.upper() if meta and meta.market else (symbol.split(".")[-1])
        ccy = meta.currency.upper() if meta and meta.currency else "EUR"

        async def _run() -> Dict[str, Any]:
            qty = Decimal(str(request.qty))
            existing = await self.repo.get_position(user.user_id, symbol)
            if existing:
                old_qty = Decimal(str(existing["qty"]))
                old_avg = Decimal(str(existing["avg_cost_eur"]))
            else:
                old_qty = Decimal("0")
                old_avg = Decimal("0")
            fee_raw = Decimal(str(request.fees_eur)) if request.fees_eur is not None else Decimal("0")
            fees = fee_raw.quantize(Decimal("0.01")) if fee_raw != 0 else Decimal("0")
            price = Decimal(str(request.price_eur)) if request.price_eur is not None else None
            if price is None:
                quotes = await self.market.get_quotes([symbol], force_refresh=True)
                quote = quotes.get(symbol)
                if not quote:
                    raise BusinessError(ErrorCode.BAD_INPUT, f"Price missing for {symbol}")
                price = Decimal(str(quote.price_eur))
            current_cash = await self.repo.get_cash(user.user_id)
            amount = (price * qty).quantize(Decimal("0.01"))
            total_cost = (amount + fees).quantize(Decimal("0.01"))
            if current_cash < total_cost:
                raise BusinessError(
                    ErrorCode.INSUFFICIENT,
                    "Not enough cash to buy",
                    details={"current_balance": str(current_cash)}
                )
            new_qty = old_qty + qty
            new_avg = ((old_qty * old_avg) + amount) / new_qty if new_qty > 0 else price
            await self.repo.upsert_position(
                user_id=user.user_id,
                symbol=symbol,
                asset_class=asset_class,
                market=market,
                qty=new_qty,
                avg_cost_eur=new_avg,
                avg_cost_ccy=new_avg,
                ccy=ccy,
                display_name=existing.get("display_name") if existing else None,
            )
            await self.repo.set_cash(user.user_id, current_cash - total_cost)
            await self.repo.add_transaction(
                user_id=user.user_id,
                op_id=request.op_id,
                tx_type="buy",
                symbol=symbol,
                asset_class=asset_class,
                qty=qty,
                price_eur=price,
                amount_eur=amount,
                cash_delta_eur=-total_cost,
                fees_eur=fees if fees != 0 else None,
            )
            snapshot = await self._record_snapshot(user.user_id, flows_eur=Decimal("0"))
            return snapshot.model_dump()
        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="buy",
            producer=_run,
        )

    async def sell(self, user: UserContext, request: TradeRequest) -> Dict[str, Any]:
        await self._ensure_user(user)
        symbol = self._normalise_symbol(request.symbol)

        async def _run() -> Dict[str, Any]:
            qty = Decimal(str(request.qty))
            existing = await self.repo.get_position(user.user_id, symbol)
            if not existing:
                raise BusinessError(ErrorCode.NOT_FOUND, f"{symbol} not held")
            old_qty = Decimal(str(existing["qty"]))
            if qty > old_qty:
                raise BusinessError(ErrorCode.INSUFFICIENT, "Sell amount exceeds holdings", details={"available_qty": str(old_qty)})
            fee_raw = Decimal(str(request.fees_eur)) if request.fees_eur is not None else Decimal("0")
            fees = fee_raw.quantize(Decimal("0.01")) if fee_raw != 0 else Decimal("0")
            price = Decimal(str(request.price_eur)) if request.price_eur is not None else None
            if price is None:
                quotes = await self.market.get_quotes([symbol], force_refresh=True)
                quote = quotes.get(symbol)
                if not quote:
                    raise BusinessError(ErrorCode.BAD_INPUT, f"Price missing for {symbol}")
                price = Decimal(str(quote.price_eur))
            amount = (price * qty).quantize(Decimal("0.01"))
            net_proceeds = (amount - fees).quantize(Decimal("0.01"))
            if net_proceeds < Decimal("0"):
                raise BusinessError(ErrorCode.BAD_INPUT, "Fees exceed sale proceeds", details={"amount": str(amount), "fees": str(fees)})
            remaining_qty = old_qty - qty
            if remaining_qty == 0:
                await self.repo.delete_position(user.user_id, symbol)
            else:
                await self.repo.upsert_position(
                    user_id=user.user_id,
                    symbol=symbol,
                    asset_class=existing.get("asset_class") or "stock",
                    market=existing.get("market") or (symbol.split(".")[-1]),
                    qty=remaining_qty,
                    avg_cost_eur=Decimal(str(existing["avg_cost_eur"]))
                    if existing.get("avg_cost_eur") is not None
                    else Decimal("0"),
                    avg_cost_ccy=Decimal(str(existing["avg_cost_ccy"]))
                    if existing.get("avg_cost_ccy") is not None
                    else Decimal("0"),
                    ccy=existing.get("ccy") or "EUR",
                    display_name=existing.get("display_name"),
                )
            current_cash = await self.repo.get_cash(user.user_id)
            await self.repo.set_cash(user.user_id, current_cash + net_proceeds)
            await self.repo.add_transaction(
                user_id=user.user_id,
                op_id=request.op_id,
                tx_type="sell",
                symbol=symbol,
                asset_class=existing.get("asset_class"),
                qty=qty,
                price_eur=price,
                amount_eur=amount,
                cash_delta_eur=net_proceeds,
                fees_eur=fees if fees != 0 else None,
            )
            snapshot = await self._record_snapshot(user.user_id, flows_eur=Decimal("0"))
            return snapshot.model_dump()
        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="sell",
            producer=_run,
        )

    async def allocation_edit(self, user: UserContext, request: AllocationEditRequest) -> Dict[str, Any]:
        await self._ensure_user(user)
        total = request.stock_pct + request.etf_pct + request.crypto_pct
        if total != 100:
            raise BusinessError(ErrorCode.BAD_INPUT, "Allocation values must sum to 100", details={"total": total})

        async def _run() -> Dict[str, Any]:
            before = AllocationSnapshot(**await self.repo.get_allocation(user.user_id))
            await self.repo.set_allocation(
                user.user_id,
                stock_pct=request.stock_pct,
                etf_pct=request.etf_pct,
                crypto_pct=request.crypto_pct,
            )
            state = await self.allocation(user)
            return {
                "previous": before.model_dump(),
                "current": state["current"].model_dump(),
                "target": state["target"].model_dump(),
            }

        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="allocation_edit",
            producer=_run,
        )

    async def rename(self, user: UserContext, request: RenameRequest) -> Dict[str, Any]:
        await self._ensure_user(user)
        symbol = self._normalise_symbol(request.symbol)

        async def _run() -> Dict[str, Any]:
            existing = await self.repo.get_position(user.user_id, symbol)
            if not existing:
                raise BusinessError(ErrorCode.NOT_FOUND, f"{symbol} not held")
            await self.repo.upsert_position(
                user_id=user.user_id,
                symbol=symbol,
                asset_class=existing.get("asset_class") or "stock",
                market=existing.get("market") or (symbol.split(".")[-1]),
                qty=Decimal(str(existing["qty"])),
                avg_cost_eur=Decimal(str(existing["avg_cost_eur"])),
                avg_cost_ccy=Decimal(str(existing["avg_cost_ccy"])),
                ccy=existing.get("ccy") or "EUR",
                display_name=request.display_name.strip(),
            )
            return {"rename": {"symbol": symbol, "display_name": request.display_name.strip()}}

        return await self._with_idempotency(
            user_id=user.user_id,
            op_id=request.op_id,
            command="rename",
            producer=_run,
        )

    # ------------------------------------------------------------ analytics stubs

    async def portfolio_snapshot(self, user: UserContext, period: str) -> Dict[str, Any]:
        await self._ensure_user(user)
        snapshot = await self._build_snapshot(user.user_id)
        benchmarks = await self.market.get_benchmarks(["GSPC.INDX", "XAUUSD.FOREX"], period)
        return {
            "partial": True,
            "portfolio": snapshot.total_value_eur,
            "cash": snapshot.cash_eur,
            "benchmarks": benchmarks,
        }

    async def portfolio_summary(self, user: UserContext, period: str) -> Dict[str, Any]:
        await self._ensure_user(user)
        benchmarks = await self.market.get_benchmarks(["GSPC.INDX", "XAUUSD.FOREX"], period)
        return {"partial": True, "benchmarks": benchmarks}

    async def portfolio_breakdown(self, user: UserContext, period: str) -> Dict[str, Any]:
        await self._ensure_user(user)
        return {"partial": True}

    async def portfolio_digest(self, user: UserContext, period: str) -> Dict[str, Any]:
        await self._ensure_user(user)
        return {"partial": True}

    async def portfolio_movers(self, user: UserContext, period: str) -> Dict[str, Any]:
        await self._ensure_user(user)
        return {"partial": True}

    async def what_if(self, user: UserContext, symbol: str, delta_pct: Decimal) -> Dict[str, Any]:
        await self._ensure_user(user)
        snapshot = await self._build_snapshot(user.user_id)
        impact = snapshot.total_value_eur * (delta_pct / Decimal("100"))
        return {
            "partial": True,
            "portfolio": snapshot.total_value_eur,
            "delta_pct": float(delta_pct),
            "delta_eur": impact.quantize(Decimal("0.01")),
        }


