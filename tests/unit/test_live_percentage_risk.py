import asyncio
from decimal import Decimal as D
from unittest.mock import AsyncMock

import pytest
from test_production_remediation import account_data

from autonomous_futures.execution.account_evidence import atomic_json
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway
from autonomous_futures.execution.entry_risk import remaining_daily_budget
from autonomous_futures.execution.live_orders import LiveOrderBook
from autonomous_futures.execution.writer_lease import ExecutionLease
from autonomous_futures.feed.exchange_clock import ExchangeClock


@pytest.fixture(name="held_execution_lease")
def execution_lease_fixture(tmp_path):
    lease = ExecutionLease(tmp_path / "execution.lock")
    lease.acquire()
    yield lease
    lease.close()


def exchange_ack(**request):
    return {
        "symbol": request["symbol"],
        "side": request["side"],
        "clientOrderId": request["client_order_id"],
        "origQty": str(request["quantity"]),
        "price": str(request["price"]),
        "reduceOnly": request["reduce_only"],
        "status": "NEW",
        "executedQty": "0",
        "orderId": 1,
    }


def test_daily_limit_is_recomputed_and_missing_or_latched_evidence_rejects():
    data = account_data()
    assert remaining_daily_budget(data) == D("5")
    data["daily_risk"]["limit_usdt"] = "3"
    with pytest.raises(ValueError, match="disagrees"):
        remaining_daily_budget(data)
    data["daily_risk"]["limit_usdt"] = "5"
    data["daily_risk"]["breached"] = True
    with pytest.raises(ValueError, match="budget exhausted"):
        remaining_daily_budget(data)
    data.pop("daily_risk")
    with pytest.raises(ValueError, match="missing"):
        remaining_daily_budget(data)


@pytest.mark.parametrize("guard_rejects", [False, True])
def test_live_journal_accepts_fifty_dollar_entry_under_new_percentage_policy(
    tmp_path,
    held_execution_lease,
    guard_rejects,  # noqa: F811
):
    data = account_data()
    atomic_json(tmp_path / "exchange-account.json", data)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        "SOLUSDT": {
            "step_size": D(".01"),
            "min_qty": D(".01"),
            "tick_size": D(".01"),
            "min_notional": D("5"),
        }
    }
    gateway.create_order = AsyncMock(side_effect=exchange_ack)
    book = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)

    def guard(now):
        if guard_rejects:
            raise ValueError("Feed changed while waiting for writer lock")
        return {
            "spectral_radius": D(".25"),
            "event_timestamp_ms": data["timestamp_ms"],
            "beta_per_second": D("7.5"),
            "calibration_sha256": "c" * 64,
            "arrivals_sha256": "d" * 64,
            "fit_timestamp_ms": data["timestamp_ms"],
            "generation": 1,
        }

    call = book.submit(
        symbol="SOLUSDT",
        side="BUY",
        price=D("100"),
        quantity=D(".5"),
        signal_id="new-policy-unit-fixture",
        qualified=True,
        spectral_radius=D(".2"),
        event_timestamp_ms=data["timestamp_ms"],
        microstructure_beta_per_second=D("7.5"),
        microstructure_calibration_sha256="a" * 64,
        microstructure_arrivals_sha256="b" * 64,
        microstructure_fit_timestamp_ms=data["timestamp_ms"],
        microstructure_generation=0,
        entry_guard=guard,
    )
    if guard_rejects:
        with pytest.raises(ValueError, match="writer lock"):
            asyncio.run(call)
        assert not book.orders
        gateway.create_order.assert_not_awaited()
        return
    result = asyncio.run(call)
    assert result["state"] == "NEW"
    assert result["quantity"] == "0.5" or D(result["quantity"]) == D(".5")
    assert result["microstructure"] == {
        "spectral_radius": "0.25",
        "event_timestamp_ms": data["timestamp_ms"],
        "beta_per_second": "7.5",
        "calibration_sha256": "c" * 64,
        "arrivals_sha256": "d" * 64,
        "fit_timestamp_ms": data["timestamp_ms"],
        "generation": 1,
    }
    assert gateway.create_order.await_count == 1


def test_opening_order_without_final_admission_guard_fails_closed(tmp_path, held_execution_lease):
    data = account_data()
    atomic_json(tmp_path / "exchange-account.json", data)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        "SOLUSDT": {
            "step_size": D(".01"),
            "min_qty": D(".01"),
            "tick_size": D(".01"),
            "min_notional": D("5"),
        }
    }
    gateway.create_order = AsyncMock(side_effect=exchange_ack)
    book = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)
    with pytest.raises(ValueError, match="final genuine admission guard"):
        asyncio.run(
            book.submit(
                symbol="SOLUSDT",
                side="BUY",
                price=D("100"),
                quantity=D(".5"),
                signal_id="missing-entry-guard",
                qualified=True,
                spectral_radius=D(".2"),
                event_timestamp_ms=data["timestamp_ms"],
            )
        )
    assert not book.orders
    gateway.create_order.assert_not_awaited()


def test_opening_order_without_calibration_provenance_fails_closed(tmp_path, held_execution_lease):
    data = account_data()
    atomic_json(tmp_path / "exchange-account.json", data)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        "SOLUSDT": {
            "step_size": D(".01"),
            "min_qty": D(".01"),
            "tick_size": D(".01"),
            "min_notional": D("5"),
        }
    }
    gateway.create_order = AsyncMock(side_effect=exchange_ack)
    book = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)
    with pytest.raises(ValueError, match="Hawkes fit provenance"):
        asyncio.run(
            book.submit(
                symbol="SOLUSDT",
                side="BUY",
                price=D("100"),
                quantity=D(".5"),
                signal_id="missing-calibration-provenance",
                qualified=True,
                spectral_radius=D(".2"),
                event_timestamp_ms=data["timestamp_ms"],
                entry_guard=lambda _: None,
            )
        )
    assert not book.orders
    gateway.create_order.assert_not_awaited()


@pytest.mark.parametrize("age,accepted", [(200, True), (450, False)])
def test_submission_uses_exchange_offset_and_uncertainty(
    tmp_path,
    held_execution_lease,
    monkeypatch,
    age,
    accepted,  # noqa: F811
):
    data = account_data()
    now = data["timestamp_ms"]
    monkeypatch.setattr("autonomous_futures.execution.live_orders.time.time", lambda: now / 1000)
    atomic_json(tmp_path / "exchange-account.json", data)
    gateway = BinanceFuturesGateway(offline_mode=False)
    gateway.symbol_specs = {
        "SOLUSDT": {
            "step_size": D(".01"),
            "min_qty": D(".01"),
            "tick_size": D(".01"),
            "min_notional": D("5"),
        }
    }
    gateway.create_order = AsyncMock(side_effect=exchange_ack)
    book = LiveOrderBook(gateway, tmp_path, lease=held_execution_lease)
    # Observed exchange clock leads local time by 600ms with 100ms uncertainty.
    clock = ExchangeClock(now - 200, now, now + 500)
    call = book.submit(
        symbol="SOLUSDT",
        side="BUY",
        price=D("100"),
        quantity=D(".5"),
        signal_id="clock-unit-fixture",
        qualified=True,
        spectral_radius=D(".2"),
        event_timestamp_ms=now + 600 - age,
        microstructure_beta_per_second=D("7.5"),
        microstructure_calibration_sha256="a" * 64,
        microstructure_arrivals_sha256="b" * 64,
        microstructure_fit_timestamp_ms=now + 600,
        microstructure_generation=0,
        exchange_clock=clock,
        entry_guard=lambda _: None,
    )
    if accepted:
        assert asyncio.run(call)["state"] == "NEW"
    else:
        with pytest.raises(ValueError, match="stale"):
            asyncio.run(call)
        assert not book.orders
    assert gateway.create_order.await_count == int(accepted)
