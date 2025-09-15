"""Test core buy/sell transaction flow."""
import pytest
from decimal import Decimal
from app.models import UserContext
from app.services.portfolio import PortfolioService


@pytest.mark.asyncio
async def test_buy_sell_flow(db, test_user, market_data_mock):
    """Test complete buy/sell flow with position updates."""
    service = PortfolioService(db, test_user)
    
    print("\n--- Test start ---")
    
    # 1. Initial cash deposit
    print("\nStep 1: Initial deposit")
    deposit_tx = await service.record_transaction(
        type="deposit",
        amount_eur=Decimal("1000.00"),
        note="Initial deposit"
    )
    print("Deposit transaction:", dict(deposit_tx))
    
    # Verify cash balance
    cash = await service.get_cash_balance()
    print("Cash balance after deposit:", cash)
    assert cash == Decimal("1000.00"), "Initial cash balance incorrect"
    
    # 2. Buy some BTC
    print("\nStep 2: First BTC buy")
    buy1_tx = await service.record_transaction(
        type="buy",
        symbol="BTC",
        qty=Decimal("0.01"),  # Small test amount
        price_ccy=Decimal("30000.00")  # Price is from mock data
    )
    print("Buy transaction 1:", dict(buy1_tx))
    
    # Verify transaction record
    assert buy1_tx is not None, "Transaction should be recorded"
    assert buy1_tx["tx_id"] is not None, "Transaction should have an ID"
    assert buy1_tx["type"] == "buy", "Transaction type should be buy"
    assert buy1_tx["symbol"] == "BTC", "Transaction symbol should be BTC"
    assert Decimal(str(buy1_tx["qty"])) == Decimal("0.01"), "Transaction qty incorrect"
    assert Decimal(str(buy1_tx["price_ccy"])) == Decimal("30000.00"), "Transaction price incorrect"
    assert Decimal(str(buy1_tx["amount_eur"])) == Decimal("273.00"), "Transaction EUR amount incorrect"
    
    # Verify cash was deducted
    cash = await service.get_cash_balance()
    print("Cash balance after first buy:", cash)
    assert cash == Decimal("727.00"), "Cash balance after buy incorrect"
    
    # 3. Buy more BTC
    print("\nStep 3: Second BTC buy")
    buy2_tx = await service.record_transaction(
        type="buy",
        symbol="BTC",
        qty=Decimal("0.01"),
        price_ccy=Decimal("30000.00")
    )
    print("Buy transaction 2:", dict(buy2_tx))
    
    # Get portfolio snapshot
    snapshot = await service.get_portfolio_snapshot()
    print("\nSnapshot after second buy:")
    print(f"Total: {snapshot['total_eur']}")
    print(f"Cash: {snapshot['cash_eur']}")
    for pos in snapshot["positions"]:
        print(f"Position {pos['symbol']}: qty={pos['qty']} value={pos['value_eur']}")
    
    # Verify position
    btc = next((p for p in snapshot["positions"] if p["symbol"] == "BTC"), None)
    assert btc is not None, "BTC position should exist"
    assert btc["qty"] == Decimal("0.02"), "Total position qty incorrect"
    assert btc["value_eur"] == Decimal("546.00"), "Position value incorrect"
    
    # 4. Sell half position
    print("\nStep 4: Sell half BTC")
    sell_tx = await service.record_transaction(
        type="sell",
        symbol="BTC",
        qty=Decimal("-0.01"),  # Negative for sell
        price_ccy=Decimal("30000.00")
    )
    print("Sell transaction:", dict(sell_tx))
    
    # Get all transactions
    async with db.execute(
        """
        SELECT tx_id, type, symbol, qty, price_ccy, amount_eur, fx_rate_used 
        FROM transactions ORDER BY tx_id
        """
    ) as cursor:
        txs = await cursor.fetchall()
        print("\nAll transactions:")
        for tx in txs:
            print(dict(tx))
            
    # Get all cash balances
    async with db.execute(
        "SELECT * FROM cash_balances"
    ) as cursor:
        balances = await cursor.fetchall()
        print("\nAll cash balances:")
        for b in balances:
            print(dict(b))
    
    # Get final snapshot
    snapshot = await service.get_portfolio_snapshot()
    print("\nFinal snapshot:")
    print(f"Total: {snapshot['total_eur']}")
    print(f"Cash: {snapshot['cash_eur']}")
    for pos in snapshot["positions"]:
        print(f"Position {pos['symbol']}: qty={pos['qty']} value={pos['value_eur']}")
    
    # Verify final position
    btc = next((p for p in snapshot["positions"] if p["symbol"] == "BTC"), None)
    assert btc is not None, "BTC position should still exist"
    assert btc["qty"] == Decimal("0.01"), "Final position qty incorrect"
    assert btc["value_eur"] == Decimal("273.00"), "Final position value incorrect"
    
    # Verify final cash
    cash = await service.get_cash_balance()
    print("\nFinal cash balance:", cash)
    
    assert cash == Decimal("727.00"), "Final cash balance incorrect"