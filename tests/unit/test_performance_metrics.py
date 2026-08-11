from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.research.performance_metrics import (
    TradePerformanceMetrics,
    calculate_performance_metrics,
)
from autonomous_futures.research.trade_simulation import (
    EquityPoint,
    SimulatedTrade,
    TradeSimulationConfig,
    TradeSimulationResult,
    simulate_cached_signals,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _trade(index: int, net_pnl: str) -> SimulatedTrade:
    timestamp = START + timedelta(minutes=5 * index)
    pnl = Decimal(net_pnl)
    return SimulatedTrade(
        trade_id=f"btc-{index:06d}",
        symbol="BTCUSDT",
        side="LONG",
        entry_timestamp=timestamp,
        exit_timestamp=timestamp + timedelta(minutes=5),
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + pnl,
        entry_notional=Decimal("100"),
        exit_notional=Decimal("100") + pnl,
        entry_fee=Decimal("0"),
        exit_fee=Decimal("0"),
        fees=Decimal("0"),
        slippage_cost=Decimal("0"),
        gross_pnl=pnl,
        net_pnl=pnl,
        exit_reason="signal_exit",
    )


def _result(
    *, pnl_values: tuple[str, ...], equity_values: tuple[str, ...]
) -> TradeSimulationResult:
    trades = tuple(_trade(index, pnl) for index, pnl in enumerate(pnl_values))
    equity_curve = tuple(
        EquityPoint(
            timestamp=START + timedelta(minutes=5 * index),
            equity=Decimal(value),
        )
        for index, value in enumerate(equity_values)
    )
    return TradeSimulationResult(
        symbol="BTCUSDT",
        starting_equity=Decimal("100"),
        final_equity=equity_curve[-1].equity,
        total_fees=Decimal("0"),
        total_slippage_cost=Decimal("0"),
        trades=trades,
        equity_curve=equity_curve,
    )


def test_metrics_use_net_ledger_and_equity_curve_for_drawdown_and_return() -> None:
    result = _result(pnl_values=("10", "-4", "0"), equity_values=("100", "110", "106", "106"))

    metrics = calculate_performance_metrics(result)

    assert metrics.symbol == "BTCUSDT"
    assert metrics.trade_count == 3
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.breakeven_trades == 1
    assert metrics.win_rate == Decimal("1") / Decimal("3")
    assert metrics.gross_profit == Decimal("10")
    assert metrics.gross_loss == Decimal("4")
    assert metrics.net_pnl == Decimal("6")
    assert metrics.average_trade_pnl == Decimal("2")
    assert metrics.return_pct == Decimal("6")
    assert metrics.profit_factor == Decimal("2.5")
    assert metrics.max_drawdown == Decimal("4")
    assert metrics.max_drawdown_pct == (Decimal("4") / Decimal("110")) * Decimal("100")
    assert metrics.peak_equity == Decimal("110")
    assert metrics.final_equity == Decimal("106")


def test_no_trades_has_zero_rate_metrics_and_undefined_profit_factor() -> None:
    result = _result(pnl_values=(), equity_values=("100", "100"))

    metrics = calculate_performance_metrics(result)

    assert metrics.trade_count == 0
    assert metrics.winning_trades == 0
    assert metrics.losing_trades == 0
    assert metrics.breakeven_trades == 0
    assert metrics.win_rate == Decimal("0")
    assert metrics.average_trade_pnl == Decimal("0")
    assert metrics.net_pnl == Decimal("0")
    assert metrics.return_pct == Decimal("0")
    assert metrics.profit_factor is None
    assert metrics.max_drawdown == Decimal("0")
    assert metrics.max_drawdown_pct == Decimal("0")


def test_profit_factor_is_undefined_when_there_are_no_losses() -> None:
    result = _result(pnl_values=("5",), equity_values=("100", "105"))

    metrics = calculate_performance_metrics(result)

    assert metrics.gross_profit == Decimal("5")
    assert metrics.gross_loss == Decimal("0")
    assert metrics.profit_factor is None


def test_metrics_are_deterministic_and_cached_only() -> None:
    result = _result(pnl_values=("2", "-1"), equity_values=("100", "102", "101"))

    first = calculate_performance_metrics(result)
    second = calculate_performance_metrics(result)

    assert first == second
    assert first.data_source == "cached_only"
    assert first.exchange_access is False


def test_metrics_reconcile_repeated_realistic_decimal_trades() -> None:
    count = 400
    signals = tuple(0 if index == 0 else 1 if index % 2 else -1 for index in range(count))
    prices = tuple(Decimal(str(100 + index / 10)) for index in range(count))
    frame = pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(count)],
            "open": prices,
            "high": tuple(price + Decimal("1") for price in prices),
            "low": tuple(price - Decimal("1") for price in prices),
            "close": prices,
            "signal": signals,
        }
    )
    result = simulate_cached_signals(
        frame,
        symbol="BTCUSDT",
        config=TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1"),
            taker_fee_rate=Decimal("0.0004"),
            slippage_rate=Decimal("0.0002"),
        ),
    )

    metrics = calculate_performance_metrics(result)

    with localcontext() as context:
        context.prec = 80
        assert metrics.net_pnl == metrics.gross_profit - metrics.gross_loss


def test_metrics_canonicalize_mixed_sign_decimal_sums() -> None:
    values = (
        "0.1234567890123456789012345678",
        "-0.9876543210987654321098765432",
        "0.2222222222222222222222222222",
        "-0.1111111111111111111111111111",
        "0.3333333333333333333333333333",
    )
    signed_sum = sum((Decimal(value) for value in values), Decimal("0"))
    result = _result(pnl_values=values, equity_values=("100", str(Decimal("100") + signed_sum)))

    metrics = calculate_performance_metrics(result)

    assert metrics.net_pnl == metrics.gross_profit - metrics.gross_loss


def test_metric_contract_rejects_inconsistent_trade_buckets() -> None:
    with pytest.raises(ValidationError):
        TradePerformanceMetrics(
            symbol="BTCUSDT",
            starting_equity=Decimal("100"),
            final_equity=Decimal("100"),
            trade_count=1,
            winning_trades=1,
            losing_trades=1,
            breakeven_trades=0,
            win_rate=Decimal("1"),
            gross_profit=Decimal("1"),
            gross_loss=Decimal("0"),
            net_pnl=Decimal("1"),
            average_trade_pnl=Decimal("1"),
            return_pct=Decimal("1"),
            profit_factor=None,
            max_drawdown=Decimal("0"),
            max_drawdown_pct=Decimal("0"),
            peak_equity=Decimal("100"),
        )
