from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from pydantic import ValidationError

from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.research.trade_simulation import (
    TradeSimulationConfig,
    simulate_cached_signals,
)

START = datetime(2026, 8, 7, 12, tzinfo=UTC)


def _signal_frame(
    signals: tuple[int, ...],
    *,
    opens: tuple[str, ...] | None = None,
    closes: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    default_prices = tuple(str(100 + index) for index in range(len(signals)))
    open_values = opens or default_prices
    close_values = closes or open_values
    return pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(len(signals))],
            "open": [Decimal(value) for value in open_values],
            "high": [Decimal(value) + Decimal("1") for value in open_values],
            "low": [Decimal(value) - Decimal("1") for value in open_values],
            "close": [Decimal(value) for value in close_values],
            "signal": signals,
        }
    )


def _config(*, slippage: str = "0", fee: str = "0.0004") -> TradeSimulationConfig:
    return TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("1"),
        taker_fee_rate=Decimal(fee),
        slippage_rate=Decimal(slippage),
    )


def _risk_frame(
    signals: tuple[int, ...],
    *,
    highs: tuple[str, ...],
    lows: tuple[str, ...],
    closes: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    close_values = closes or ("100",) * len(signals)
    return pd.DataFrame(
        {
            "timestamp": [START + timedelta(minutes=5 * index) for index in range(len(signals))],
            "open": [Decimal("100")] * len(signals),
            "high": [Decimal(value) for value in highs],
            "low": [Decimal(value) for value in lows],
            "close": [Decimal(value) for value in close_values],
            "signal": signals,
        }
    )


def _risk_config() -> TradeSimulationConfig:
    return TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("1"),
        taker_fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        atr_lookback=3,
        stop_atr_multiplier=Decimal("1"),
        take_profit_atr_multiplier=Decimal("1"),
    )


def _trailing_config() -> TradeSimulationConfig:
    return TradeSimulationConfig(
        starting_equity=Decimal("100"),
        position_fraction=Decimal("1"),
        taker_fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
        atr_lookback=3,
        trailing_atr_multiplier=Decimal("1"),
    )


@pytest.mark.parametrize("signal", [1, -1])
def test_constant_price_round_trip_charges_both_fees_and_forces_final_close(signal: int) -> None:
    frame = _signal_frame((0, signal, 0, 0), opens=("100",) * 4, closes=("100",) * 4)

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_config())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == ("LONG" if signal == 1 else "SHORT")
    assert trade.exit_reason == "forced_end_of_window"
    assert trade.entry_fee == Decimal("0.0400")
    assert trade.exit_fee == Decimal("0.0400")
    assert trade.fees == Decimal("0.0800")
    assert trade.net_pnl == Decimal("-0.0800")
    assert result.total_fees == Decimal("0.0800")
    assert result.total_slippage_cost == Decimal("0")
    assert result.final_equity == Decimal("99.9200")
    assert result.equity_curve[-1].equity == result.final_equity


def test_opposite_signal_closes_at_current_open_without_same_candle_reverse() -> None:
    frame = _signal_frame(
        (0, 1, 0, -1, 0),
        opens=("100", "100", "105", "110", "100"),
        closes=("100", "100", "105", "110", "100"),
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_config(fee="0"))

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.side == "LONG"
    assert trade.exit_reason == "signal_exit"
    assert trade.exit_price == Decimal("110")
    assert result.final_equity == Decimal("110")


def test_slippage_is_direction_aware_and_recorded_separately_from_fees() -> None:
    frame = _signal_frame(
        (0, 1, 0),
        opens=("100", "100", "100"),
        closes=("100", "100", "110"),
    )

    result = simulate_cached_signals(
        frame,
        symbol="BTCUSDT",
        config=_config(slippage="0.01", fee="0"),
    )

    trade = result.trades[0]
    assert trade.entry_price == Decimal("101.00")
    assert trade.exit_price == Decimal("108.90")
    assert trade.gross_pnl == Decimal("7.90")
    assert trade.net_pnl == Decimal("7.90")
    assert trade.slippage_cost == Decimal("2.10")
    assert result.total_fees == Decimal("0")
    assert result.total_slippage_cost == Decimal("2.10")
    assert result.final_equity == Decimal("107.90")


def test_simulation_does_not_mutate_signal_frame_and_is_deterministic() -> None:
    frame = _signal_frame((0, 1, 0, 0), opens=("100",) * 4, closes=("100",) * 4)
    before = frame.copy(deep=True)

    first = simulate_cached_signals(frame, symbol="BTCUSDT", config=_config())
    second = simulate_cached_signals(frame, symbol="BTCUSDT", config=_config())

    assert first == second
    pd.testing.assert_frame_equal(frame, before)


def test_repeated_trades_keep_final_equity_exactly_reconciled() -> None:
    count = 400
    signals = tuple(0 if index == 0 else 1 if index % 2 else -1 for index in range(count))
    prices = tuple(str(100 + index / 10) for index in range(count))
    frame = _signal_frame(signals, opens=prices, closes=prices)

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_config())

    assert result.final_equity == result.equity_curve[-1].equity


def test_invalid_signal_or_missing_signal_is_rejected() -> None:
    invalid = _signal_frame((0, 2, 0))
    with pytest.raises(DataQualityError, match="signal"):
        simulate_cached_signals(invalid, symbol="BTCUSDT", config=_config())

    missing = _signal_frame((0, 1, 0)).drop(columns=["signal"])
    with pytest.raises(DataQualityError, match="signal"):
        simulate_cached_signals(missing, symbol="BTCUSDT", config=_config())


def test_simulation_config_rejects_unsafe_costs_and_bad_symbol() -> None:
    with pytest.raises(ValidationError):
        TradeSimulationConfig(
            starting_equity=Decimal("100"),
            position_fraction=Decimal("1.1"),
            taker_fee_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        )

    with pytest.raises(DataQualityError, match="symbol"):
        simulate_cached_signals(_signal_frame((0, 1, 0)), symbol="btc", config=_config())


def test_take_profit_uses_prior_atr_not_current_candle_range() -> None:
    frame = _risk_frame(
        (0, 0, 0, 0, 1, 0),
        highs=("101", "101", "101", "101", "101", "110"),
        lows=("99", "99", "99", "99", "99", "99"),
        closes=("100", "100", "100", "100", "100", "105"),
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_risk_config())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "take_profit"
    assert result.trades[0].exit_price == Decimal("102")
    assert result.trades[0].net_pnl == Decimal("2")
    assert result.final_equity == Decimal("102")


def test_protective_stop_wins_when_stop_and_target_cross_same_candle() -> None:
    frame = _risk_frame(
        (0, 0, 0, 0, 1, -1),
        highs=("101", "101", "101", "101", "101", "110"),
        lows=("99", "99", "99", "99", "99", "95"),
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_risk_config())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].exit_price == Decimal("98")
    assert result.final_equity == Decimal("98")


def test_short_take_profit_uses_inverse_atr_geometry() -> None:
    frame = _risk_frame(
        (0, 0, 0, 0, -1, 0),
        highs=("101", "101", "101", "101", "101", "101"),
        lows=("99", "99", "99", "99", "99", "90"),
        closes=("100", "100", "100", "100", "100", "95"),
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_risk_config())

    assert len(result.trades) == 1
    assert result.trades[0].side == "SHORT"
    assert result.trades[0].exit_reason == "take_profit"
    assert result.trades[0].exit_price == Decimal("98")
    assert result.final_equity == Decimal("102")


def test_protected_signal_before_atr_warmup_does_not_open_unprotected_position() -> None:
    frame = _risk_frame(
        (0, 1, 0, 0, 0),
        highs=("101",) * 5,
        lows=("99",) * 5,
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_risk_config())

    assert result.trades == ()
    assert result.final_equity == Decimal("100")


@pytest.mark.parametrize(
    ("signal", "highs", "lows", "close", "expected_equity"),
    [
        (
            1,
            ("101", "101", "101", "101", "110"),
            ("99", "99", "99", "99", "99"),
            "105",
            "105",
        ),
        (
            -1,
            ("101", "101", "101", "101", "101"),
            ("99", "99", "99", "99", "90"),
            "95",
            "105",
        ),
    ],
)
def test_trailing_stop_does_not_use_current_extreme_before_survival_check(
    signal: int,
    highs: tuple[str, ...],
    lows: tuple[str, ...],
    close: str,
    expected_equity: str,
) -> None:
    frame = _risk_frame(
        (0, 0, 0, 0, signal),
        highs=highs,
        lows=lows,
        closes=("100", "100", "100", "100", close),
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_trailing_config())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "forced_end_of_window"
    assert result.trades[0].exit_price == Decimal(close)
    assert result.final_equity == Decimal(expected_equity)


def test_long_trailing_stop_uses_watermark_from_completed_prior_candle() -> None:
    frame = _risk_frame(
        (0, 0, 0, 0, 1, 0),
        highs=("101", "101", "101", "101", "101", "105"),
        lows=("99", "99", "99", "99", "99", "98"),
        closes=("100", "100", "100", "100", "100", "99"),
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_trailing_config())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "trailing_stop"
    assert result.trades[0].exit_price == Decimal("99")
    assert result.final_equity == Decimal("99")


def test_trailing_only_signal_before_atr_warmup_does_not_open_position() -> None:
    frame = _risk_frame(
        (0, 1, 0, 0, 0),
        highs=("101",) * 5,
        lows=("99",) * 5,
    )

    result = simulate_cached_signals(frame, symbol="BTCUSDT", config=_trailing_config())

    assert result.trades == ()
    assert result.final_equity == Decimal("100")
