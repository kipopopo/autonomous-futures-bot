"""Regression checks for production truthfulness and micro-capital confinement."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from autonomous_futures.api.app import load_execution_status
from autonomous_futures.execution.account_evidence import atomic_json, observe_account, read_account
from autonomous_futures.execution.binance_gateway import BinanceAPIError, BinanceFuturesGateway
from autonomous_futures.execution.live_orders import LiveOrderBook
from autonomous_futures.execution.self_driving import (
    MicroCapitalConfig,
    Phase317SolvencyLedger,
    SelfDrivingTradingEngine,
)
from autonomous_futures.execution.writer_lease import ExecutionLease
from autonomous_futures.feed.kline_sequencer import MultiTimeframeCandleSequencer
from autonomous_futures.strategy.ict_mmxm import IctMmxmEngine


@pytest.fixture
def held_execution_lease(tmp_path):
    lease = ExecutionLease(tmp_path / "execution.lock")
    lease.acquire()
    yield lease
    lease.close()


def account_data() -> dict:
    timestamp = int(time.time() * 1000)
    return {
        "source": "binance_authenticated_rest",
        "timestamp_ms": timestamp,
        "testnet": True,
        "symbol_configuration": [{"symbol": "SOLUSDT", "leverage": "1"}],
        "daily_risk": {
            "verified": True,
            "equity_basis": "ACCOUNT",
            "testnet": True,
            "observed_ms": timestamp,
            "day": timestamp // 86400000,
            "captured_ms": timestamp // 86400000 * 86400000 + 1000,
            "day_start_equity": "100",
            "limit_pct": "5",
            "limit_usdt": "5",
            "loss_usdt": "0",
            "net_external_flows": "0",
            "remaining_usdt": "5",
            "breached": False,
        },
        "account": {
            "multiAssetsMargin": False,
            "totalWalletBalance": "100",
            "availableBalance": "100",
            "totalMarginBalance": "100",
            "totalInitialMargin": "0",
            "totalUnrealizedProfit": "0",
        },
        "positions": [],
        "open_orders": [],
        "daily_loss_usdt": "0",
        "reconciliation": {
            "verified": True,
            "starting_equity": "100",
            "net_realized_pnl": "0",
            "net_external_flows": "0",
            "wallet_drift": "0",
            "equity_drift": "0",
        },
        "daily_external_flows": [],
    }


@pytest.mark.parametrize("price", ["171", "185", "748.57"])
def test_sizing_never_steps_above_cap(tmp_path: Path, price: str) -> None:
    gateway = BinanceFuturesGateway(offline_mode=True)
    engine = SelfDrivingTradingEngine(gateway=gateway, storage_dir=tmp_path)
    try:
        _, qty, notional = engine._calculate_child_order_qty("SOLUSDT", Decimal(price))
        assert qty == 0
        assert notional == 0
    finally:
        engine.close()


def test_feasible_size_is_preserved(tmp_path: Path) -> None:
    engine = SelfDrivingTradingEngine(
        gateway=BinanceFuturesGateway(offline_mode=True), storage_dir=tmp_path
    )
    try:
        assert engine._calculate_child_order_qty("SOLUSDT", Decimal("100")) == (
            Decimal("100"),
            Decimal("0.05"),
            Decimal("5"),
        )
    finally:
        engine.close()


def test_decimal_ledger_reserves_and_releases_margin() -> None:
    ledger = Phase317SolvencyLedger(Decimal("100.00000000000000001"))
    ledger.record_fill("SOLUSDT", "BUY", Decimal("0.05"), Decimal("100"), Decimal("0.001"))
    assert ledger.allocated_margin == Decimal("5")
    assert ledger.cash == Decimal("94.99900000000000001")
    ledger.unrealized_pnl = Decimal("0.1")
    assert ledger.get_snapshot().zero_balance_drift
    ledger.record_fill(
        "SOLUSDT", "SELL", Decimal("0.05"), Decimal("102"), Decimal("0.00102"), Decimal("0.1")
    )
    ledger.unrealized_pnl = Decimal("0")
    assert ledger.allocated_margin == 0
    assert ledger.cash == Decimal("100.09798000000000001")
    assert ledger.get_snapshot().zero_balance_drift


def test_missing_account_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as error:
        load_execution_status(tmp_path)
    assert error.value.status_code == 503


def test_api_preserves_exchange_position_and_pending_order(tmp_path: Path) -> None:
    data = account_data()
    data["positions"] = [
        {
            "symbol": "SOLUSDT",
            "positionAmt": "0.04",
            "markPrice": "100",
            "entryPrice": "99",
            "unRealizedProfit": "0.04",
        }
    ]
    data["open_orders"] = [
        {
            "symbol": "SOLUSDT",
            "orderId": 1,
            "clientOrderId": "afbot-real",
            "origQty": "0.01",
            "price": "100",
            "executedQty": "0",
            "avgPrice": "0",
            "status": "NEW",
            "type": "LIMIT",
            "side": "BUY",
        }
    ]
    atomic_json(tmp_path / "exchange-account.json", data)
    response = load_execution_status(tmp_path)
    assert response.positions["SOLUSDT"].position_qty == 0.04
    assert response.aggregate_exposure_usdt == 4
    assert response.recent_orders[0].fill_price is None


@pytest.mark.parametrize("offset", [-30_001, 1000])
def test_stale_or_future_account_rejected(tmp_path: Path, offset: int) -> None:
    data = account_data()
    now = data["timestamp_ms"]
    data["timestamp_ms"] += offset
    path = tmp_path / "exchange-account.json"
    atomic_json(path, data)
    with pytest.raises(ValueError):
        read_account(path, now)


def test_unclosed_candle_never_enters_strategy_buffer() -> None:
    gateway = AsyncMock()
    gateway.get_klines.return_value = [
        [60_000, "100", "101", "99", "100", "1"],
        [120_000, "100", "101", "99", "100", "1"],
    ]
    sequencer = MultiTimeframeCandleSequencer(gateway=gateway, symbols=["SOLUSDT"])
    asyncio.run(sequencer.fetch_and_update_series("SOLUSDT", "1m", now_ts=150))
    assert [c.timestamp_ms for c in sequencer.get_candles("SOLUSDT", "1m")] == [60_000]


def test_ict_uses_canonical_ote() -> None:
    assert IctMmxmEngine().ote_lower == Decimal("0.62")


def test_algo_failure_never_disables_reduce_only() -> None:
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        code = -4120 if request.url.path == "/fapi/v1/order" else -2022
        return httpx.Response(400, json={"code": code, "msg": "rejected"})

    gateway = BinanceFuturesGateway(mock_transport=httpx.MockTransport(transport))
    with pytest.raises(BinanceAPIError):
        asyncio.run(
            gateway.create_order(
                symbol="SOLUSDT",
                side="SELL",
                order_type="STOP_MARKET",
                quantity=Decimal("0.01"),
                stop_price=Decimal("100"),
                reduce_only=True,
            )
        )
    assert len(requests) == 2
    assert all(r.url.params["reduceOnly"] == "true" for r in requests)


def test_live_submission_pending_is_durable_and_idempotent(
    tmp_path: Path, held_execution_lease
) -> None:
    data = account_data()
    atomic_json(tmp_path / "exchange-account.json", data)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        "SOLUSDT": {
            "step_size": Decimal("0.01"),
            "min_qty": Decimal("0.01"),
            "tick_size": Decimal("0.01"),
            "min_notional": Decimal("5"),
        }
    }
    gateway.create_order = AsyncMock(
        side_effect=lambda **request: {
            "orderId": 7,
            "status": "NEW",
            "executedQty": "0",
            "symbol": "SOLUSDT",
            "side": "BUY",
            "clientOrderId": request["client_order_id"],
            "origQty": "0.05",
            "price": "100",
            "reduceOnly": False,
        }
    )
    book = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)
    kwargs = dict(
        symbol="SOLUSDT",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("0.05"),
        signal_id="same-closed-bar",
        qualified=True,
        spectral_radius=Decimal("0.2"),
        event_timestamp_ms=int(time.time() * 1000),
        microstructure_beta_per_second=Decimal("7.5"),
        microstructure_calibration_sha256="a" * 64,
        microstructure_arrivals_sha256="b" * 64,
        microstructure_fit_timestamp_ms=int(time.time() * 1000),
        microstructure_generation=0,
        entry_guard=lambda _: None,
    )
    result = asyncio.run(book.submit(**kwargs))
    assert result["state"] == "NEW"
    restarted = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)
    assert asyncio.run(restarted.submit(**kwargs))["state"] == "NEW"
    assert gateway.create_order.await_count == 1


def test_uncertain_submission_is_not_retried(tmp_path: Path, held_execution_lease) -> None:
    atomic_json(tmp_path / "exchange-account.json", account_data())
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        "SOLUSDT": {
            "step_size": Decimal("0.01"),
            "min_qty": Decimal("0.01"),
            "tick_size": Decimal("0.01"),
            "min_notional": Decimal("5"),
        }
    }
    gateway.create_order = AsyncMock(side_effect=TimeoutError("lost acknowledgement"))
    book = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)
    kwargs = dict(
        symbol="SOLUSDT",
        side="BUY",
        price=Decimal("100"),
        quantity=Decimal("0.05"),
        signal_id="uncertain",
        qualified=True,
        spectral_radius=Decimal("0.2"),
        event_timestamp_ms=int(time.time() * 1000),
        microstructure_beta_per_second=Decimal("7.5"),
        microstructure_calibration_sha256="a" * 64,
        microstructure_arrivals_sha256="b" * 64,
        microstructure_fit_timestamp_ms=int(time.time() * 1000),
        microstructure_generation=0,
        entry_guard=lambda _: None,
    )
    with pytest.raises(TimeoutError):
        asyncio.run(book.submit(**kwargs))
    result = asyncio.run(
        LiveOrderBook(gateway, tmp_path, lease=held_execution_lease).submit(**kwargs)
    )
    assert result["state"] == "UNKNOWN"
    assert gateway.create_order.await_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_micro_order_notional_usdt", "5.01"),
        ("max_aggregate_exposure_usdt", "26"),
        ("min_cash_reserve_pct", "74.99"),
        ("intra_day_loss_ceiling_usdt", "3.01"),
    ],
)
def test_configuration_cannot_relax_limits(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        MicroCapitalConfig(**{field: Decimal(value)})


def test_live_engine_cannot_simulate_fills(tmp_path: Path) -> None:
    engine = SelfDrivingTradingEngine(
        gateway=BinanceFuturesGateway(offline_mode=False), storage_dir=tmp_path
    )
    try:
        with pytest.raises(RuntimeError, match="simulated fills disabled"):
            engine._execute_fill(None, Decimal("100"), 1)
        assert engine.ledger.cash == Decimal("100")
    finally:
        engine.close()


def test_exchange_ledger_deduplicates_income_and_detects_drift(tmp_path: Path) -> None:
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_account_balance = AsyncMock(return_value=account_data()["account"])
    gateway.get_symbol_configuration = AsyncMock(
        return_value=account_data()["symbol_configuration"]
    )
    gateway.get_position_risk = AsyncMock(return_value=[])
    gateway.get_open_orders = AsyncMock(return_value=[])
    gateway.get_open_algo_orders = AsyncMock(return_value=[])
    gateway.get_income_history = AsyncMock(return_value=[])
    path = tmp_path / "exchange-account.json"
    initial = asyncio.run(observe_account(gateway, path))
    assert initial["reconciliation"]["verified"] is True
    income = {
        "asset": "USDT",
        "incomeType": "COMMISSION",
        "tranId": 1,
        "income": "-0.001",
        "time": initial["timestamp_ms"] + 1,
    }
    gateway.get_income_history.return_value = [income, dict(income)]
    gateway.get_account_balance.return_value = {
        **account_data()["account"],
        "totalWalletBalance": "99.999",
        "totalMarginBalance": "99.999",
        "availableBalance": "99.999",
    }
    second = asyncio.run(observe_account(gateway, path))
    assert second["reconciliation"]["net_realized_pnl"] == "-0.001"
    assert second["daily_loss_usdt"] == "0.001"
    assert second["reconciliation"]["verified"] is True
    gateway.get_account_balance.return_value["totalWalletBalance"] = "99.998"
    third = asyncio.run(observe_account(gateway, path))
    assert third["reconciliation"]["verified"] is False
    gateway.get_income_history.return_value = [{**income, "income": "-0.002"}]
    with pytest.raises(ValueError, match="Persisted authenticated income amount changed"):
        asyncio.run(observe_account(gateway, path))


def test_exchange_ledger_reconciles_transfer_as_basis_not_trading_pnl(tmp_path: Path) -> None:
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_account_balance = AsyncMock(return_value=account_data()["account"])
    gateway.get_symbol_configuration = AsyncMock(
        return_value=account_data()["symbol_configuration"]
    )
    gateway.get_position_risk = AsyncMock(return_value=[])
    gateway.get_open_orders = AsyncMock(return_value=[])
    gateway.get_open_algo_orders = AsyncMock(return_value=[])
    gateway.get_income_history = AsyncMock(return_value=[])
    path = tmp_path / "exchange-account.json"
    initial = asyncio.run(observe_account(gateway, path))
    transfer = {
        "asset": "USDT",
        "incomeType": "TRANSFER",
        "tranId": 9,
        "income": "10",
        "time": initial["timestamp_ms"] + 1,
    }
    gateway.get_income_history.return_value = [transfer]
    gateway.get_account_balance.return_value = {
        **account_data()["account"],
        "totalWalletBalance": "110",
        "totalMarginBalance": "110",
        "availableBalance": "110",
    }

    result = asyncio.run(observe_account(gateway, path))

    assert result["reconciliation"]["verified"] is True
    assert result["reconciliation"]["net_realized_pnl"] == "0"
    assert result["reconciliation"]["net_external_flows"] == "10"
    assert result["reconciliation"]["wallet_drift"] == "0"
    assert result["daily_external_flows"][0]["income"] == "10"


def test_account_observation_adjusts_daily_loss_for_post_baseline_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import autonomous_futures.execution.account_evidence as account_evidence
    from autonomous_futures.execution.daily_risk import DailyRiskTracker

    day_start = int(datetime(2026, 10, 13, tzinfo=UTC).timestamp() * 1000)
    current_ms = [day_start + 1_000]

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(current_ms[0] / 1000, tz=tz or UTC)

    monkeypatch.setattr(account_evidence, "datetime", FrozenDatetime)
    monkeypatch.setattr(account_evidence.time, "time", lambda: current_ms[0] / 1000)

    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_account_balance = AsyncMock(return_value=account_data()["account"])
    gateway.get_symbol_configuration = AsyncMock(
        return_value=account_data()["symbol_configuration"]
    )
    gateway.get_position_risk = AsyncMock(return_value=[])
    gateway.get_open_orders = AsyncMock(return_value=[])
    gateway.get_open_algo_orders = AsyncMock(return_value=[])
    gateway.get_income_history = AsyncMock(return_value=[])
    tracker = DailyRiskTracker(tmp_path / "day-risk.json", equity_basis="ACCOUNT")
    path = tmp_path / "exchange-account.json"

    initial = asyncio.run(observe_account(gateway, path, risk_tracker=tracker))
    assert initial["daily_risk"]["day_start_equity"] == "100"

    transfer_time = day_start + 5_000
    gateway.get_income_history.return_value = [
        {
            "asset": "USDT",
            "incomeType": "TRANSFER",
            "tranId": 10,
            "income": "10",
            "time": transfer_time,
        }
    ]
    gateway.get_account_balance.return_value = {
        **account_data()["account"],
        "totalWalletBalance": "110",
        "totalUnrealizedProfit": "-4",
        "totalMarginBalance": "106",
        "availableBalance": "106",
    }
    gateway.get_position_risk.return_value = [
        {
            "symbol": "SOLUSDT",
            "positionAmt": "1",
            "entryPrice": "99",
            "markPrice": "95",
            "unRealizedProfit": "-4",
        }
    ]
    current_ms[0] = day_start + 10_000

    result = asyncio.run(observe_account(gateway, path, risk_tracker=tracker))

    assert result["reconciliation"]["verified"] is True
    assert result["reconciliation"]["net_external_flows"] == "10"
    assert result["daily_risk"]["net_external_flows"] == "10"
    assert result["daily_risk"]["loss_usdt"] == "4"
    assert result["daily_risk"]["remaining_usdt"] == "1"
    assert result["daily_loss_usdt"] == "4"


def test_daily_loss_telemetry_uses_verified_day_start_equity_for_carried_positions(
    tmp_path: Path,
) -> None:
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_account_balance = AsyncMock(return_value=account_data()["account"])
    gateway.get_symbol_configuration = AsyncMock(
        return_value=account_data()["symbol_configuration"]
    )
    gateway.get_position_risk = AsyncMock(return_value=[])
    gateway.get_open_orders = AsyncMock(return_value=[])
    gateway.get_open_algo_orders = AsyncMock(return_value=[])
    gateway.get_income_history = AsyncMock(return_value=[])
    path = tmp_path / "exchange-account.json"
    asyncio.run(observe_account(gateway, path))

    gateway.get_account_balance.return_value = {
        **account_data()["account"],
        "totalMarginBalance": "94",
        "totalUnrealizedProfit": "-6",
    }
    gateway.get_position_risk.return_value = [
        {
            "symbol": "SOLUSDT",
            "positionAmt": "0.06",
            "entryPrice": "200",
            "markPrice": "100",
            "unRealizedProfit": "-6",
        }
    ]

    class DayStartRisk:
        def observe(self, snapshot: dict, now_ms: int) -> dict:
            return {
                "verified": True,
                "loss_usdt": "0",
                "remaining_usdt": "5",
                "breached": False,
            }

    result = asyncio.run(observe_account(gateway, path, risk_tracker=DayStartRisk()))
    assert result["reconciliation"]["verified"] is True
    assert result["daily_risk"]["verified"] is True
    assert result["daily_loss_usdt"] == "0"


def test_ledger_baseline_rejects_flat_account_with_pending_conditional_order(tmp_path):
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.get_account_balance = AsyncMock(return_value=account_data()["account"])
    gateway.get_symbol_configuration = AsyncMock(return_value=[])
    gateway.get_position_risk = AsyncMock(return_value=[])
    gateway.get_open_orders = AsyncMock(return_value=[])
    gateway.get_open_algo_orders = AsyncMock(
        return_value=[{"symbol": "SOLUSDT", "clientAlgoId": "foreign-fixture"}]
    )
    gateway.get_income_history = AsyncMock(return_value=[])
    path = tmp_path / "exchange-account.json"
    with pytest.raises(ValueError, match="flat account with no pending"):
        asyncio.run(observe_account(gateway, path))
    assert not path.exists()
    assert not path.with_name("exchange-ledger.json").exists()


def test_repaired_candles_block_entry() -> None:
    gateway = AsyncMock()
    gateway.get_klines.return_value = [
        [60_000, "100", "101", "99", "100", "1"],
        [180_000, "100", "101", "99", "100", "1"],
    ]
    sequencer = MultiTimeframeCandleSequencer(
        gateway=gateway, symbols=["SOLUSDT"], timeframes=["1m"]
    )
    asyncio.run(sequencer.fetch_and_update_series("SOLUSDT", "1m", now_ts=240))
    assert sequencer.is_trade_ready("SOLUSDT", now_ts=240) is False
