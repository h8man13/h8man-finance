from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from app.clients import market_data_client, Meta, Quote


@pytest.mark.asyncio
async def test_phase1_command_flow(async_client):
    meta = Meta(symbol="AMZN.US", asset_class="stock", market="US", currency="USD")
    quote = Quote(symbol="AMZN.US", price_eur=Decimal("100"), currency="USD", market="US", freshness="eod")

    orig_get_meta = market_data_client.get_meta
    orig_get_quotes = market_data_client.get_quotes
    market_data_client.get_meta = AsyncMock(return_value={"AMZN.US": meta})
    market_data_client.get_quotes = AsyncMock(return_value={"AMZN.US": quote})

    try:
        user_params = {"user_id": 1}

        resp = await async_client.post(
            "/cash_add",
            params=user_params,
            json={"op_id": "cash-add", "amount_eur": "5000"},
        )
        assert resp.status_code == 200
        cash_snapshot = resp.json()["data"]
        assert cash_snapshot["cash_eur"] == "5000.00"

        resp = await async_client.post(
            "/add",
            params=user_params,
            json={"op_id": "add-amzn", "symbol": "AMZN", "qty": "3", "asset_class": "stock"},
        )
        assert resp.status_code == 200
        holdings = resp.json()["data"]["holdings"]
        assert len(holdings) == 1
        assert holdings[0]["symbol"] == "AMZN.US"

        resp = await async_client.post(
            "/rename",
            params=user_params,
            json={"op_id": "rename-amzn", "symbol": "AMZN", "display_name": "Amazon Inc"},
        )
        assert resp.status_code == 200
        rename_data = resp.json()["data"]["rename"]
        assert rename_data == {"symbol": "AMZN.US", "display_name": "Amazon Inc"}

        resp = await async_client.post(
            "/buy",
            params=user_params,
            json={"op_id": "buy-amzn", "symbol": "AMZN", "qty": "2", "price_eur": "110", "fees_eur": "5"},
        )
        assert resp.status_code == 200
        portfolio = resp.json()["data"]
        expected_cash_after_buy = Decimal("5000") - (Decimal("110") * 2) - Decimal("5")
        assert Decimal(portfolio["cash_eur"]) == expected_cash_after_buy

        resp = await async_client.post(
            "/sell",
            params=user_params,
            json={"op_id": "sell-amzn", "symbol": "AMZN", "qty": "1", "price_eur": "115", "fees_eur": "1.5"},
        )
        assert resp.status_code == 200
        portfolio = resp.json()["data"]
        expected_cash_after_sell = expected_cash_after_buy + Decimal("115") - Decimal("1.5")
        assert Decimal(portfolio["cash_eur"]) == expected_cash_after_sell

        resp = await async_client.post(
            "/allocation_edit",
            params=user_params,
            json={"op_id": "alloc-update", "stock_pct": 40, "etf_pct": 40, "crypto_pct": 20},
        )
        assert resp.status_code == 200
        allocation = resp.json()["data"]
        assert allocation["target"] == {"stock_pct": 40, "etf_pct": 40, "crypto_pct": 20}

        resp = await async_client.post(
            "/remove",
            params=user_params,
            json={"op_id": "remove-amzn", "symbol": "AMZN"},
        )
        assert resp.status_code == 200
        portfolio = resp.json()["data"]
        assert portfolio["holdings"] == []

        resp = await async_client.post(
            "/cash_remove",
            params=user_params,
            json={"op_id": "cash-rem", "amount_eur": "1000"},
        )
        assert resp.status_code == 200
        portfolio = resp.json()["data"]
        assert Decimal(portfolio["cash_eur"]) > 0

        resp = await async_client.get("/cash", params=user_params)
        assert resp.status_code == 200
        assert Decimal(resp.json()["data"]["cash_eur"]) >= 0

        resp = await async_client.get("/portfolio", params=user_params)
        body = resp.json()
        assert body["ok"]
        assert body["data"]["holdings"] == []

        resp = await async_client.get("/tx", params={"user_id": 1, "limit": 10})
        tx_body = resp.json()
        assert tx_body["ok"]
        assert len(tx_body["data"]["transactions"]) >= 4
        assert tx_body["data"].get("count") == len(tx_body["data"]["transactions"])
        fees_logged = [
            Decimal(str(tx["fees_eur"]))
            for tx in tx_body["data"]["transactions"]
            if tx.get("fees_eur") not in (None, "None")
        ]
        assert Decimal("5") in fees_logged
        assert Decimal("1.5") in fees_logged
    finally:
        market_data_client.get_meta = orig_get_meta
        market_data_client.get_quotes = orig_get_quotes


@pytest.mark.asyncio
async def test_remove_not_owned(async_client):
    resp = await async_client.post(
        "/remove",
        params={"user_id": 999},
        json={"op_id": "remove-missing", "symbol": "XYZ"},
    )
    assert resp.status_code == 404
    payload = resp.json()
    assert not payload["ok"]
    assert payload["error"]["code"] == "NOT_FOUND"




