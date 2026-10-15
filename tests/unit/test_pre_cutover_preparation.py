from __future__ import annotations

import asyncio
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
import pytest

from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.pre_cutover_preparation import (
    prepare_portfolio_cutover,
    reconstruct_utc_day_start_baseline,
    set_symbol_leverage,
)
from scripts.preflight_qualified_runtime import REPO, evaluate_preflight


def _build_mock_gateway(
    *,
    initial_leverage: int = 20,
    dual_side: bool = False,
    open_position_amt: str = "0",
    income_rows: list[dict[str, Any]] | None = None,
) -> tuple[BinanceFuturesGateway, dict[str, int]]:
    leverages = {
        "AVAXUSDT": initial_leverage,
        "ETHUSDT": initial_leverage,
        "SOLUSDT": initial_leverage,
        "BTCUSDT": 1,
    }
    income_data = [] if income_rows is None else list(income_rows)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(urllib.parse.parse_qsl(request.url.query.decode("utf-8")))
        now_ms = int(time.time() * 1000)

        if path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": now_ms})
        if path == "/fapi/v1/positionSide/dual":
            return httpx.Response(200, json={"dualSidePosition": dual_side})
        if path == "/fapi/v2/account":
            return httpx.Response(
                200,
                json={
                    "multiAssetsMargin": False,
                    "totalWalletBalance": "4224.09882354",
                    "availableBalance": "4224.09882354",
                    "totalMarginBalance": "4224.09882354",
                    "totalInitialMargin": "0.00000000",
                    "totalUnrealizedProfit": "0.00000000",
                },
            )
        if path == "/fapi/v2/positionRisk":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "ETHUSDT",
                        "positionAmt": open_position_amt,
                        "entryPrice": "0.00",
                        "markPrice": "2500.00",
                        "unRealizedProfit": "0.00000000",
                    },
                    {
                        "symbol": "SOLUSDT",
                        "positionAmt": "0",
                        "entryPrice": "0.00",
                        "markPrice": "150.00",
                        "unRealizedProfit": "0.00000000",
                    },
                    {
                        "symbol": "AVAXUSDT",
                        "positionAmt": "0",
                        "entryPrice": "0.00",
                        "markPrice": "25.00",
                        "unRealizedProfit": "0.00000000",
                    },
                ],
            )
        if path == "/fapi/v1/openOrders":
            return httpx.Response(200, json=[])
        if path == "/fapi/v1/openAlgoOrders":
            return httpx.Response(200, json=[])
        if path == "/fapi/v1/symbolConfig":
            return httpx.Response(
                200,
                json=[{"symbol": sym, "leverage": lev} for sym, lev in sorted(leverages.items())],
            )
        if path == "/fapi/v1/leverage" and request.method == "POST":
            sym = str(params["symbol"])
            lev = int(params["leverage"])
            leverages[sym] = lev
            return httpx.Response(
                200,
                json={"symbol": sym, "leverage": lev, "maxNotionalValue": "1000000"},
            )
        if path == "/fapi/v1/income":
            return httpx.Response(200, json=income_data)
        return httpx.Response(404, json={"code": -1000, "msg": f"Unhandled {path}"})

    transport = httpx.MockTransport(handler)
    gateway = BinanceFuturesGateway(
        api_key="test-key",
        api_secret="test-secret",
        testnet=True,
        mock_transport=transport,
        offline_mode=False,
    )
    return gateway, leverages


def test_set_symbol_leverage_updates_exchange_config() -> None:
    gateway, leverages = _build_mock_gateway(initial_leverage=20)
    ack = asyncio.run(set_symbol_leverage(gateway, "ETHUSDT", 1))
    assert ack["symbol"] == "ETHUSDT"
    assert ack["leverage"] == 1
    assert leverages["ETHUSDT"] == 1


def test_reconstruct_utc_day_start_baseline_rejects_intraday_trading_income() -> None:
    now_ms = int(time.time() * 1000)
    gateway, _ = _build_mock_gateway(
        income_rows=[
            {
                "incomeType": "REALIZED_PNL",
                "asset": "USDT",
                "time": now_ms - 1000,
                "tranId": "9001",
                "income": "-1.25",
            }
        ]
    )
    with pytest.raises(ValueError, match="trading income exists"):
        asyncio.run(reconstruct_utc_day_start_baseline(gateway, now_ms=now_ms))


def test_reconstruct_utc_day_start_baseline_rejects_non_flat_account() -> None:
    gateway, _ = _build_mock_gateway(open_position_amt="0.5")
    with pytest.raises(ValueError, match="flat account"):
        asyncio.run(reconstruct_utc_day_start_baseline(gateway))


def test_prepare_portfolio_cutover_normalizes_leverage_and_passes_preflight(
    tmp_path: Path,
) -> None:
    gateway, leverages = _build_mock_gateway(initial_leverage=20)

    # 1. Read-only inspection first
    dry_report = asyncio.run(
        prepare_portfolio_cutover(
            repo=REPO,
            storage_dir=tmp_path,
            gateway=gateway,
            apply_leverage=False,
            bootstrap_daily_risk=False,
        )
    )
    assert dry_report["execution_authority"] is False
    assert dry_report["leverage"]["matches_domain"] is False
    assert dry_report["leverage"]["observed_after"] == {
        "AVAXUSDT": 20,
        "ETHUSDT": 20,
        "SOLUSDT": 20,
    }
    assert dry_report["daily_risk"]["verified"] is False
    assert dry_report["execution_domain_verified"] is False

    # 2. Apply 1x leverage normalization and bootstrap daily-risk.json + exchange-account.json
    applied_report = asyncio.run(
        prepare_portfolio_cutover(
            repo=REPO,
            storage_dir=tmp_path,
            gateway=gateway,
            apply_leverage=True,
            bootstrap_daily_risk=True,
        )
    )
    assert applied_report["execution_authority"] is False
    assert applied_report["leverage"]["matches_domain"] is True
    assert applied_report["leverage"]["observed_after"] == {
        "AVAXUSDT": 1,
        "ETHUSDT": 1,
        "SOLUSDT": 1,
    }
    assert leverages["AVAXUSDT"] == 1
    assert leverages["ETHUSDT"] == 1
    assert leverages["SOLUSDT"] == 1
    assert applied_report["daily_risk"]["verified"] is True
    assert applied_report["daily_risk"]["bootstrapped"] is True
    assert applied_report["daily_risk"]["day_start_equity_usdt"] == "4224.09882354"
    assert applied_report["execution_domain_verified"] is True

    # 3. Verify preflight_qualified_runtime.py passes account_and_portfolio_domain check
    preflight = evaluate_preflight(
        repo=REPO,
        storage_dir=tmp_path,
        account_path=tmp_path / "exchange-account.json",
    )
    assert "account_daily_risk_unverified" not in preflight["blocking_reasons"]
    assert "portfolio_symbol_leverage_mismatch" not in preflight["blocking_reasons"]
    assert preflight["checks"]["account_and_portfolio_domain"]["passed"] is True
    assert (
        preflight["checks"]["account_and_portfolio_domain"]["portfolio_audits"][0]["passed"] is True
    )
