"""
API routes for portfolio operations.
"""
from typing import Optional, List
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, Query

from .db import open_db, upsert_user
from .models import (
    OkEnvelope,
    ErrEnvelope,
    ErrorBody,
    UserContext,
    Position,
    Transaction
)
from .services.portfolio import PortfolioService
from .services.analytics import AnalyticsService
# Market data client removed - portfolio_core should not directly call market_data


router = APIRouter()


def ok(data: dict, partial: Optional[bool] = None, error: Optional[ErrorBody] = None) -> OkEnvelope:
    """Create success response envelope."""
    return OkEnvelope(ok=True, data=data, ts=datetime.now(timezone.utc), partial=partial, error=error)


def err(code: str, message: str, source: str, retriable: bool = False, details=None) -> ErrEnvelope:
    """Create error response envelope."""
    return ErrEnvelope(
        ok=False,
        error=ErrorBody(code=code, message=message, source=source, retriable=retriable, details=details),
        ts=datetime.now(timezone.utc),
    )


async def db_dep():
    """Database dependency."""
    conn = await open_db()
    try:
        yield conn
    finally:
        await conn.close()


async def user_dep(
    user_id: Optional[int] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    language_code: Optional[str] = None,
) -> UserContext:
    """Extract user context from request."""
    return UserContext(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name or "",
        username=username,
        language_code=language_code,
    )


@router.get("/portfolios/", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolios(
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get all portfolios."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        portfolios = await portfolio_service.get_portfolios()
        return ok({"portfolios": portfolios})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/portfolios/", response_model=OkEnvelope | ErrEnvelope)
async def create_portfolio(
    name: str,
    description: str,
    base_currency: str,
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Create a new portfolio."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        portfolio = await portfolio_service.create_portfolio(name, description, base_currency)
        return ok(portfolio)
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/portfolios/{portfolio_id}/positions/", response_model=OkEnvelope | ErrEnvelope)
async def add_position(
    portfolio_id: int,
    symbol: str,
    quantity: Decimal,
    avg_price: Decimal,
    currency: str,
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Add a new position to a portfolio."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        position = await portfolio_service.add_portfolio_position(
            portfolio_id, symbol, quantity, avg_price, currency
        )
        return ok(position)
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/portfolios/{portfolio_id}/positions/{position_id}/transactions/", response_model=OkEnvelope | ErrEnvelope)
async def add_transaction(
    portfolio_id: int,
    position_id: int,
    quantity: Decimal,
    price: Decimal,
    date: datetime,
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Add a transaction to a portfolio position."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        transaction = await portfolio_service.add_portfolio_transaction(
            portfolio_id, position_id, quantity, price, date
        )
        return ok(transaction)
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolios/{portfolio_id}/performance/", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_performance(
    portfolio_id: int,
    start_date: datetime,
    end_date: datetime,
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio performance."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics_service = AnalyticsService(conn, uc)
        performance = await analytics_service.calculate_portfolio_performance(
            portfolio_id, start_date, end_date
        )
        return ok(performance)
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_snapshot", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_snapshot(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio snapshot for period (Telegram /portfolio_snapshot command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        snapshot = await analytics.get_portfolio_snapshot(period)
        return ok({"snapshot": snapshot})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_summary", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_summary(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio summary for period (Telegram /portfolio_summary command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        summary = await analytics.get_portfolio_summary(period)
        return ok({"summary": summary})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_breakdown", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_breakdown(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio breakdown for period (Telegram /portfolio_breakdown command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        breakdown = await analytics.get_portfolio_breakdown(period)
        return ok({"breakdown": breakdown})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_digest", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_digest(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio digest for period (Telegram /portfolio_digest command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        digest = await analytics.get_portfolio_digest(period)
        return ok({"digest": digest})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


# ========== TELEGRAM COMMAND ENDPOINTS ==========

# REMOVED: /price endpoint - this functionality should be handled by telegram_router
# which calls market_data service directly. Portfolio_core should not duplicate this.


@router.get("/portfolio", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio(
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio snapshot (Telegram /portfolio command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        snapshot = await portfolio_service.get_portfolio_snapshot()
        return ok({"portfolio": snapshot})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/add", response_model=OkEnvelope | ErrEnvelope)
async def add_position(
    qty: Decimal = Query(...),
    symbol: str = Query(...),
    type: Optional[str] = Query(None, alias="type"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Add position (Telegram /add command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        position = await portfolio_service.add_position(symbol, qty, type)
        return ok({"position": position.model_dump()})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/remove", response_model=OkEnvelope | ErrEnvelope)
async def remove_position(
    symbol: str = Query(...),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Remove position (Telegram /remove command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        await portfolio_service.remove_position(symbol)
        return ok({"removed": symbol})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/cash", response_model=OkEnvelope | ErrEnvelope)
async def get_cash(
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get cash balance (Telegram /cash command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        balance = await portfolio_service.get_cash_balance()
        return ok({"cash_balance": balance})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/cash_add", response_model=OkEnvelope | ErrEnvelope)
async def add_cash(
    amount: Decimal = Query(...),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Add/withdraw cash (Telegram /cash_add command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        result = await portfolio_service.update_cash(amount)
        return ok({"cash_balance": result})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/buy", response_model=OkEnvelope | ErrEnvelope)
async def buy_position(
    qty: Decimal = Query(...),
    symbol: str = Query(...),
    price_ccy: Decimal = Query(...),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Buy position (Telegram /buy command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        tx = await portfolio_service.record_transaction(
            type="buy",
            symbol=symbol,
            qty=qty,
            price_ccy=price_ccy
        )
        return ok({"tx": tx})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/sell", response_model=OkEnvelope | ErrEnvelope)
async def sell_position(
    qty: Decimal = Query(...),
    symbol: str = Query(...),
    price_ccy: Optional[Decimal] = Query(None),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Sell position (Telegram /sell command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)

        # Get current price if not provided
        if not price_ccy:
            quote_response = await market_data.get_quote([symbol])
            if not quote_response.get("quotes"):
                return err("BAD_INPUT", f"No quote available for {symbol}", "portfolio_core")
            price_ccy = Decimal(str(quote_response["quotes"][0]["price_ccy"]))

        tx = await portfolio_service.record_transaction(
            type="sell",
            symbol=symbol,
            qty=-qty,  # Negative for sell
            price_ccy=price_ccy
        )
        return ok({"tx": tx})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/tx", response_model=OkEnvelope | ErrEnvelope)
async def get_transactions(
    limit: int = Query(10, ge=1, le=50),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get recent transactions (Telegram /tx command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        txs = await portfolio_service.get_recent_transactions(limit)
        return ok({"transactions": txs})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_snapshot", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_snapshot(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio snapshot for period (Telegram /portfolio_snapshot command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        snapshot = await analytics.get_portfolio_snapshot(period)
        return ok({"snapshot": snapshot})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_summary", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_summary(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio summary for period (Telegram /portfolio_summary command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        summary = await analytics.get_portfolio_summary(period)
        return ok({"summary": summary})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_breakdown", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_breakdown(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio breakdown for period (Telegram /portfolio_breakdown command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        breakdown = await analytics.get_portfolio_breakdown(period)
        return ok({"breakdown": breakdown})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_digest", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_digest(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio digest for period (Telegram /portfolio_digest command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        analytics = AnalyticsService(conn, uc)
        digest = await analytics.get_portfolio_digest(period)
        return ok({"digest": digest})
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "portfolio_core")
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/allocation", response_model=OkEnvelope | ErrEnvelope)
async def get_allocation(
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get allocation vs targets (Telegram /allocation command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        allocation = await portfolio_service.get_allocation()
        return ok({"allocation": allocation})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/allocation_edit", response_model=OkEnvelope | ErrEnvelope)
async def edit_allocation(
    etf_pct: int = Query(...),
    stock_pct: int = Query(...),
    crypto_pct: int = Query(...),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Edit allocation targets (Telegram /allocation_edit command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        result = await portfolio_service.set_allocation_targets(etf_pct, stock_pct, crypto_pct)
        return ok({"targets": result})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/portfolio_movers", response_model=OkEnvelope | ErrEnvelope)
async def get_portfolio_movers(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get portfolio movers for period (Telegram /portfolio_movers command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        movers = await portfolio_service.get_movers(period)
        return ok({"movers": movers})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/po_if", response_model=OkEnvelope | ErrEnvelope)
async def portfolio_what_if(
    symbol: Optional[str] = Query(None),
    pick: Optional[str] = Query(None, pattern="^(stocks|etf|crypto)$"),
    pct_change: Decimal = Query(...),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Portfolio what-if simulation (Telegram /po_if command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)

        if symbol:
            result = await portfolio_service.simulate_price_change(symbol=symbol, pct_change=pct_change)
        elif pick:
            result = await portfolio_service.simulate_price_change(asset_class=pick, pct_change=pct_change)
        else:
            return err("BAD_INPUT", "Must provide either symbol or pick parameter", "portfolio_core")

        return ok({"whatif": result})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/rename", response_model=OkEnvelope | ErrEnvelope)
async def rename_symbol(
    symbol: str = Query(...),
    nickname: str = Query(...),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Rename symbol (Telegram /rename command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        result = await portfolio_service.set_symbol_nickname(symbol, nickname)
        return ok({"rename": {"symbol": symbol, "nickname": nickname}})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.post("/snapshots/run", response_model=OkEnvelope | ErrEnvelope)
async def run_snapshots(
    date: Optional[str] = Query(None, description="YYYY-MM-DD format, defaults to today"),
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Run snapshot maintenance (maintenance endpoint)."""
    try:
        await upsert_user(conn, uc.model_dump())
        portfolio_service = PortfolioService(conn, uc)
        snapshot = await portfolio_service.take_snapshot()
        return ok({
            "date": snapshot["date"],
            "users_processed": 1,
            "snapshots_written": 1
        })
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


@router.get("/help", response_model=OkEnvelope | ErrEnvelope)
async def get_help(
    uc: UserContext = Depends(user_dep),
    conn = Depends(db_dep),
):
    """Get help commands (Telegram /help command)."""
    try:
        await upsert_user(conn, uc.model_dump())
        commands = [
            {"command": "/po", "description": "portfolio snapshot"},
            {"command": "/cash", "description": "cash report"},
            {"command": "/buy", "description": "record buy"},
            {"command": "/sell", "description": "record sell"},
            {"command": "/tx", "description": "transactions"},
            {"command": "/allocation", "description": "weights"},
            {"command": "/add", "description": "add position"},
            {"command": "/remove", "description": "remove position"},
        ]
        return ok({"help": commands})
    except Exception as e:
        return err("INTERNAL", str(e), "portfolio_core")


# Aliases for command endpoints
router.add_api_route("/po", get_portfolio, methods=["GET"])
# /p alias removed - price quotes handled by telegram_router
router.add_api_route("/po_snapshot", get_portfolio_snapshot, methods=["GET"])
router.add_api_route("/po_summary", get_portfolio_summary, methods=["GET"])
router.add_api_route("/po_breakdown", get_portfolio_breakdown, methods=["GET"])
router.add_api_route("/po_digest", get_portfolio_digest, methods=["GET"])
router.add_api_route("/po_movers", get_portfolio_movers, methods=["GET"])


# Admin endpoints for snapshot management
@router.post("/admin/snapshots/run", response_model=OkEnvelope | ErrEnvelope)
async def run_snapshots(
    user_id: Optional[int] = Query(None, description="Run for specific user, or all users if None"),
    conn = Depends(db_dep),
):
    """Run daily portfolio snapshots (admin endpoint for cron job)."""
    try:
        from .services.analytics import AnalyticsService
        from .models import UserContext

        if user_id:
            # Run for specific user
            uc = UserContext(user_id=user_id, first_name="Admin", last_name="Run")
            analytics = AnalyticsService(conn, uc)
            snapshot = await analytics.run_daily_snapshot()
            return ok({"snapshot": snapshot, "user_id": user_id})
        else:
            # Run for all users with positions
            cursor = await conn.execute("""
                SELECT DISTINCT user_id
                FROM positions
                WHERE qty > 0
            """)
            user_ids = [row[0] for row in await cursor.fetchall()]

            results = []
            for uid in user_ids:
                try:
                    uc = UserContext(user_id=uid, first_name="Admin", last_name="Run")
                    analytics = AnalyticsService(conn, uc)
                    snapshot = await analytics.run_daily_snapshot()
                    results.append({"user_id": uid, "snapshot": snapshot, "success": True})
                except Exception as e:
                    results.append({"user_id": uid, "error": str(e), "success": False})

            return ok({"results": results, "processed_users": len(user_ids)})

    except Exception as e:
        return err("INTERNAL", f"Snapshot run failed: {str(e)}", "portfolio_core")


@router.get("/admin/snapshots/status", response_model=OkEnvelope | ErrEnvelope)
async def get_snapshots_status(
    user_id: Optional[int] = Query(None, description="Get status for specific user, or all users if None"),
    conn = Depends(db_dep),
):
    """Get snapshot status and statistics (admin endpoint)."""
    try:
        if user_id:
            # Get status for specific user
            cursor = await conn.execute("""
                SELECT
                    date(snapshot_date) as date,
                    value_eur,
                    created_at
                FROM portfolio_snapshots
                WHERE user_id = ?
                ORDER BY snapshot_date DESC
                LIMIT 10
            """, (user_id,))
            snapshots = []
            for row in await cursor.fetchall():
                snapshots.append({
                    "date": row[0],
                    "value_eur": float(row[1]),
                    "created_at": row[2]
                })

            return ok({"user_id": user_id, "recent_snapshots": snapshots})
        else:
            # Get overview for all users
            cursor = await conn.execute("""
                SELECT
                    user_id,
                    COUNT(*) as snapshot_count,
                    MAX(date(snapshot_date)) as latest_date,
                    MIN(date(snapshot_date)) as earliest_date,
                    SUM(value_eur) as total_value
                FROM portfolio_snapshots
                GROUP BY user_id
                ORDER BY latest_date DESC
            """)
            users = []
            for row in await cursor.fetchall():
                users.append({
                    "user_id": row[0],
                    "snapshot_count": row[1],
                    "latest_date": row[2],
                    "earliest_date": row[3],
                    "total_value": float(row[4]) if row[4] else 0
                })

            return ok({"users": users, "total_users": len(users)})

    except Exception as e:
        return err("INTERNAL", f"Status check failed: {str(e)}", "portfolio_core")


@router.delete("/admin/snapshots/cleanup", response_model=OkEnvelope | ErrEnvelope)
async def cleanup_snapshots(
    days_to_keep: int = Query(90, description="Number of days to keep (default 90)"),
    user_id: Optional[int] = Query(None, description="Clean for specific user, or all users if None"),
    conn = Depends(db_dep),
):
    """Clean up old snapshots (admin endpoint)."""
    try:
        from datetime import datetime, timedelta

        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        if user_id:
            # Clean for specific user
            cursor = await conn.execute("""
                DELETE FROM portfolio_snapshots
                WHERE user_id = ? AND snapshot_date < ?
            """, (user_id, cutoff_date))
            deleted_count = cursor.rowcount
            return ok({"user_id": user_id, "deleted_snapshots": deleted_count, "cutoff_date": cutoff_date.isoformat()})
        else:
            # Clean for all users
            cursor = await conn.execute("""
                DELETE FROM portfolio_snapshots
                WHERE snapshot_date < ?
            """, (cutoff_date,))
            deleted_count = cursor.rowcount
            return ok({"deleted_snapshots": deleted_count, "cutoff_date": cutoff_date.isoformat()})

    except Exception as e:
        return err("INTERNAL", f"Cleanup failed: {str(e)}", "portfolio_core")


@router.get("/admin/health", response_model=OkEnvelope | ErrEnvelope)
async def admin_health_check(conn = Depends(db_dep)):
    """Admin health check with service dependencies."""
    try:
        from .adapters import fx_client, market_data_client

        # Check database
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        user_count = (await cursor.fetchone())[0]

        # Check external services
        fx_healthy = await fx_client.health_check()
        market_data_healthy = await market_data_client.health_check()

        # Get cache stats
        fx_cache_stats = getattr(fx_client, 'cache', {})
        market_cache_stats = market_data_client.get_cache_stats()

        return ok({
            "database": {"healthy": True, "user_count": user_count},
            "fx_service": {"healthy": fx_healthy},
            "market_data_service": {"healthy": market_data_healthy},
            "cache_stats": {
                "fx_cache_entries": len(fx_cache_stats),
                "market_data_cache": market_cache_stats
            }
        })

    except Exception as e:
        return err("INTERNAL", f"Health check failed: {str(e)}", "portfolio_core")