"""Empirical mathematical stress testing & adversarial edge case suite.

Phase 263 Challenger 1: Mathematical Stress Testing & Edge Cases
Evaluates `src/autonomous_futures/analytics/metrics.py` and `attribution.py`
against severe boundary conditions, extreme numerical values, and edge cases:
1. Zero trades (empty sequences)
2. 1-trade sequences (single win, single loss, single breakeven)
3. 100% win rate (zero losses, infinite profit factor, zero downside Sortino)
4. 100% loss rate (zero wins, profit factor 0.0, max drawdown equals sum of losses)
5. Flat returns (standard deviation = 0, Sharpe division by zero handling)
6. Extreme values (large numbers 10^9, microscopic numbers 10^-8, numerical precision)
7. Unrecovered and multi-stage drawdown scenarios
8. Asset attribution edge cases (missing symbols, negative PnL ranking, zero notional)
9. Dataclass schema serialization consistency under extreme numbers
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from autonomous_futures.analytics.attribution import (
    DEFAULT_PORTFOLIO_SYMBOLS,
    calculate_asset_attribution,
    calculate_performance_ranking,
)
from autonomous_futures.analytics.metrics import (
    calculate_drawdown_metrics,
    calculate_execution_slippage_stats,
    calculate_holding_duration_stats,
    calculate_performance_metrics,
)
from autonomous_futures.analytics.models import TradeRecord


def _create_trade(
    sequence: int,
    trade_id: str,
    symbol: str = "BTCUSDT",
    side: str = "LONG",
    quantity: str = "0.01",
    entry_price: str = "50000.00",
    exit_price: str = "51000.00",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
    entry_fee: str = "0.02",
    exit_fee: str = "0.02",
    slippage_cost: str = "0.01",
    net_pnl: str = "10.00",
    gross_pnl: str = "10.04",
    exit_reason: str = "normal_close",
) -> TradeRecord:
    t0 = opened_at or datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
    t1 = closed_at or (t0 + timedelta(minutes=5))
    ent_f = Decimal(entry_fee)
    ext_f = Decimal(exit_fee)
    dur = max(0.0, (t1 - t0).total_seconds())
    return TradeRecord(
        close_sequence=sequence,
        trade_id=trade_id,
        candidate_id="cand-stress-01",
        candidate_artifact_hash="f" * 64,
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        entry_price=Decimal(entry_price),
        exit_price=Decimal(exit_price),
        opened_at=t0,
        closed_at=t1,
        holding_duration_seconds=dur,
        entry_fee=ent_f,
        exit_fee=ext_f,
        total_fees=ent_f + ext_f,
        slippage_cost=Decimal(slippage_cost),
        gross_pnl=Decimal(gross_pnl),
        net_pnl=Decimal(net_pnl),
        exit_reason=exit_reason,
    )


# ===========================================================================
# 1. Zero Trades (Empty Sequences)
# ===========================================================================


class TestZeroTradesAdversarial:
    """Stress test empty sequences across all analytics functions."""

    def test_empty_metrics_exact_invariants(self) -> None:
        """Verify complete zeroed/neutral baseline for empty sequence."""
        m = calculate_performance_metrics([])
        assert m.total_trades == 0
        assert m.winning_trades == 0
        assert m.losing_trades == 0
        assert m.breakeven_trades == 0
        assert m.win_rate_pct == 0.0
        assert m.gross_profit == Decimal("0.00")
        assert m.gross_loss == Decimal("0.00")
        assert m.net_pnl == Decimal("0.00")
        assert m.profit_factor is None
        assert m.sharpe_ratio_trade is None
        assert m.sharpe_ratio_annualized is None
        assert m.sortino_ratio is None
        assert m.max_drawdown_amount == Decimal("0.00")
        assert m.max_drawdown_pct == 0.0
        assert m.max_drawdown_peak_time is None
        assert m.max_drawdown_trough_time is None
        assert m.max_drawdown_duration_seconds is None
        assert m.recovery_duration_seconds is None
        assert m.is_drawdown_recovered is True
        assert m.calmar_ratio is None
        assert m.recovery_factor is None
        assert m.average_win is None
        assert m.average_loss is None
        assert m.payoff_ratio is None
        assert m.expectancy == Decimal("0.00")
        assert m.expectancy_ratio is None
        assert m.total_fees_paid == Decimal("0.00")
        assert m.fee_drag_ratio is None
        assert m.holding_duration_mean_seconds is None
        assert m.holding_duration_median_seconds is None
        assert m.holding_duration_min_seconds is None
        assert m.holding_duration_max_seconds is None
        assert m.total_slippage_cost == Decimal("0.00")
        assert m.average_slippage_bps is None
        assert m.max_slippage_bps is None

        # Verify JSON serialization
        d = m.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
        assert d["trade_count"] == 0
        assert d["net_realized_pnl_usdt"] == 0.0
        assert d["profit_factor"] is None
        assert d["sharpe_ratio_trade"] is None

    def test_empty_drawdown_metrics(self) -> None:
        """Verify drawdown pure function with empty input."""
        res = calculate_drawdown_metrics([])
        assert res == (Decimal("0.00"), 0.0, None, None, None, None, True)

    def test_empty_duration_and_slippage(self) -> None:
        """Verify duration and slippage helpers return neutral zeros."""
        dur = calculate_holding_duration_stats([])
        assert dur.avg == 0.0
        assert dur.median == 0.0
        assert dur.min == 0.0
        assert dur.max == 0.0

        slip = calculate_execution_slippage_stats([])
        assert slip.total_slippage_cost_usdt == 0.0
        assert slip.average_slippage_bps == 0.0
        assert slip.max_slippage_bps == 0.0

    def test_empty_attribution_all_symbols_intact(self) -> None:
        """Verify all default portfolio symbols exist in empty attribution."""
        attr = calculate_asset_attribution([])
        assert set(attr.keys()) == set(DEFAULT_PORTFOLIO_SYMBOLS)
        for sym, a in attr.items():
            assert a.symbol == sym
            assert a.trade_count == 0
            assert a.win_rate_pct == 0.0
            assert a.net_realized_pnl_usdt == Decimal("0.00")
            assert a.profit_factor is None
            assert a.max_drawdown_pct == 0.0

        ranking = calculate_performance_ranking(attr)
        assert len(ranking) == 4


# ===========================================================================
# 2. Single Trade Boundary Testing (N = 1)
# ===========================================================================


class TestSingleTradeBoundary:
    """Stress test single trade cases where N < 2 disables sample variance."""

    def test_single_winning_trade(self) -> None:
        """Single win: profit factor None (infinite), Sharpe/Sortino None (N<2)."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            entry_price="50000",
            exit_price="51000",
            quantity="0.01",
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=15),
            net_pnl="10.00",
            entry_fee="0.10",
            exit_fee="0.10",
            slippage_cost="0.05",
        )
        m = calculate_performance_metrics([trade], starting_capital=Decimal("100.00"))

        assert m.total_trades == 1
        assert m.winning_trades == 1
        assert m.losing_trades == 0
        assert m.breakeven_trades == 0
        assert m.win_rate_pct == 100.0
        assert m.gross_profit == Decimal("10.00")
        assert m.gross_loss == Decimal("0.00")
        assert m.net_pnl == Decimal("10.00")
        assert m.profit_factor is None  # Infinite
        assert m.average_win == Decimal("10.00")
        assert m.average_loss is None
        assert m.payoff_ratio is None
        assert m.expectancy == Decimal("10.00")
        assert m.expectancy_ratio is None

        # N < 2 guarantees sample stdev cannot be computed
        assert m.sharpe_ratio_trade is None
        assert m.sharpe_ratio_annualized is None
        assert m.sortino_ratio is None

        # Zero drawdown for monotonic increase
        assert m.max_drawdown_amount == Decimal("0.00")
        assert m.max_drawdown_pct == 0.0
        assert m.is_drawdown_recovered is True
        assert m.calmar_ratio is None
        assert m.recovery_factor is None

        # Durations
        assert m.holding_duration_mean_seconds == 900.0
        assert m.holding_duration_median_seconds == 900.0
        assert m.holding_duration_min_seconds == 900.0
        assert m.holding_duration_max_seconds == 900.0

    def test_single_losing_trade(self) -> None:
        """Single loss: profit factor 0.0, payoff 0.0, drawdown equals loss."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            entry_price="50000",
            exit_price="48500",
            quantity="0.01",
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=20),
            net_pnl="-15.00",
        )
        m = calculate_performance_metrics([trade], starting_capital=Decimal("100.00"))

        assert m.total_trades == 1
        assert m.winning_trades == 0
        assert m.losing_trades == 1
        assert m.win_rate_pct == 0.0
        assert m.gross_profit == Decimal("0.00")
        assert m.gross_loss == Decimal("15.00")
        assert m.net_pnl == Decimal("-15.00")
        assert m.profit_factor == 0.0
        assert m.average_win is None
        assert m.average_loss == Decimal("15.00")
        assert m.payoff_ratio == 0.0
        assert m.expectancy == Decimal("-15.00")
        assert m.expectancy_ratio == -1.0

        # Sharpe & Sortino undefined for N < 2
        assert m.sharpe_ratio_trade is None
        assert m.sortino_ratio is None

        # Drawdown is exactly the loss
        assert m.max_drawdown_amount == Decimal("15.00")
        assert m.max_drawdown_pct == 15.0
        assert m.max_drawdown_peak_time == t0
        assert m.max_drawdown_trough_time == t0 + timedelta(minutes=20)
        assert m.max_drawdown_duration_seconds == 1200.0
        assert m.recovery_duration_seconds is None
        assert m.is_drawdown_recovered is False
        assert m.recovery_factor == -1.0  # -15 / 15

    def test_single_breakeven_trade(self) -> None:
        """Single breakeven (net_pnl == 0.00)."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            net_pnl="0.00",
            gross_pnl="0.04",
            entry_fee="0.02",
            exit_fee="0.02",
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=5),
        )
        m = calculate_performance_metrics([trade], starting_capital=Decimal("100.00"))

        assert m.total_trades == 1
        assert m.winning_trades == 0
        assert m.losing_trades == 0
        assert m.breakeven_trades == 1
        assert m.win_rate_pct == 0.0
        assert m.gross_profit == Decimal("0.00")
        assert m.gross_loss == Decimal("0.00")
        assert m.net_pnl == Decimal("0.00")
        assert m.profit_factor is None
        assert m.average_win is None
        assert m.average_loss is None
        assert m.expectancy == Decimal("0.00")
        assert m.max_drawdown_amount == Decimal("0.00")
        assert m.max_drawdown_pct == 0.0
        assert m.is_drawdown_recovered is True


# ===========================================================================
# 3. 100% Win Rate Sequences
# ===========================================================================


class TestHundredPercentWins:
    """Stress test 100% win sequences with N >= 2."""

    def test_consecutive_wins_sortino_zero_downside(self) -> None:
        """Zero downside returns -> downside deviation = 0 -> Sortino is None (no crash)."""
        t0 = datetime(2026, 9, 7, 8, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                i,
                f"t{i}",
                net_pnl=str(pnl),
                opened_at=t0 + timedelta(hours=i),
                closed_at=t0 + timedelta(hours=i, minutes=30),
            )
            for i, pnl in enumerate([5.0, 10.0, 8.0, 12.0, 15.0], start=1)
        ]
        m = calculate_performance_metrics(trades, starting_capital=Decimal("100.00"))

        assert m.total_trades == 5
        assert m.winning_trades == 5
        assert m.losing_trades == 0
        assert m.win_rate_pct == 100.0
        assert m.gross_profit == Decimal("50.00")
        assert m.gross_loss == Decimal("0.00")
        assert m.profit_factor is None  # Infinite

        # Downside deviation is exactly 0.0 -> Sortino is None
        assert m.sortino_ratio is None

        # Sharpe ratio is computable because returns vary
        assert m.sharpe_ratio_trade is not None
        assert m.sharpe_ratio_trade > 0.0
        assert m.sharpe_ratio_annualized is not None
        assert m.sharpe_ratio_annualized > m.sharpe_ratio_trade

        # Drawdown is strictly zero
        assert m.max_drawdown_amount == Decimal("0.00")
        assert m.max_drawdown_pct == 0.0
        assert m.is_drawdown_recovered is True


# ===========================================================================
# 4. 100% Loss Rate Sequences
# ===========================================================================


class TestHundredPercentLosses:
    """Stress test 100% loss sequences with N >= 2."""

    def test_consecutive_losses_drawdown_equals_sum(self) -> None:
        """Every trade is a loss: MDD equals exact sum of net losses, profit factor = 0.0."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        losses = ["5.00", "12.50", "8.25", "4.25", "10.00"]
        total_loss_sum = Decimal("40.00")

        trades = [
            _create_trade(
                i,
                f"t{i}",
                net_pnl=f"-{loss}",
                opened_at=t0 + timedelta(hours=i),
                closed_at=t0 + timedelta(hours=i, minutes=45),
            )
            for i, loss in enumerate(losses, start=1)
        ]
        m = calculate_performance_metrics(trades, starting_capital=Decimal("100.00"))

        assert m.total_trades == 5
        assert m.winning_trades == 0
        assert m.losing_trades == 5
        assert m.win_rate_pct == 0.0
        assert m.gross_profit == Decimal("0.00")
        assert m.gross_loss == total_loss_sum
        assert m.net_pnl == -total_loss_sum
        assert m.profit_factor == 0.0
        assert m.payoff_ratio == 0.0

        # Max drawdown must strictly equal the cumulative sum of losses
        assert m.max_drawdown_amount == total_loss_sum
        assert m.max_drawdown_pct == 40.0  # 40 / 100 * 100
        assert m.max_drawdown_peak_time == trades[0].opened_at
        assert m.max_drawdown_trough_time == trades[-1].closed_at
        assert m.is_drawdown_recovered is False
        assert m.recovery_duration_seconds is None

        # Sortino and Sharpe should be negative finite numbers
        assert m.sharpe_ratio_trade is not None
        assert m.sharpe_ratio_trade < 0.0
        assert m.sortino_ratio is not None
        assert m.sortino_ratio < 0.0


# ===========================================================================
# 5. Flat Returns (Zero Variance / Stdev = 0)
# ===========================================================================


class TestFlatReturnsZeroVariance:
    """Stress test zero return variance where sample standard deviation = 0."""

    def test_flat_positive_returns_sharpe_none(self) -> None:
        """Multiple trades with identical returns: stdev = 0 -> Sharpe is None."""
        t0 = datetime(2026, 9, 7, 1, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                i,
                f"t{i}",
                quantity="0.01",
                entry_price="50000.00",  # notional = 500
                net_pnl="10.00",  # ret = 10 / 500 = 0.02
                opened_at=t0 + timedelta(hours=i),
                closed_at=t0 + timedelta(hours=i, minutes=10),
            )
            for i in range(1, 6)
        ]
        m = calculate_performance_metrics(trades)

        assert m.total_trades == 5
        # Stdev is 0.0 -> Sharpe must be None
        assert m.sharpe_ratio_trade is None
        assert m.sharpe_ratio_annualized is None
        # All positive returns -> downside dev = 0.0 -> Sortino is None
        assert m.sortino_ratio is None

    def test_flat_negative_returns_sharpe_none(self) -> None:
        """Multiple trades with identical negative returns: stdev = 0 -> Sharpe is None."""
        t0 = datetime(2026, 9, 7, 1, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                i,
                f"t{i}",
                quantity="0.01",
                entry_price="50000.00",
                net_pnl="-10.00",  # ret = -0.02
                opened_at=t0 + timedelta(hours=i),
                closed_at=t0 + timedelta(hours=i, minutes=10),
            )
            for i in range(1, 6)
        ]
        m = calculate_performance_metrics(trades)

        assert m.total_trades == 5
        assert m.sharpe_ratio_trade is None
        assert m.sharpe_ratio_annualized is None
        # In this case, downside squared is positive and identical ((-0.02)^2),
        # so downside_dev = 0.02 > 1e-12. Sortino is computable.
        assert m.sortino_ratio is not None
        assert m.sortino_ratio < 0.0


# ===========================================================================
# 6. Extreme Values (Large 10^9 & Microscopic 10^-8 Numbers)
# ===========================================================================


class TestExtremeNumericalValues:
    """Stress test numerical stability and precision under extreme orders of magnitude."""

    def test_large_numbers_billion_scale(self) -> None:
        """Trades with 10^9 scale values do not overflow or lose Decimal precision."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        large_trades = [
            _create_trade(
                1,
                "t_large_1",
                quantity="1000000000.00",  # 10^9
                entry_price="1000.00",
                exit_price="1100.00",
                net_pnl="100000000000.00",  # 10^11
                slippage_cost="10000000.00",  # 10^7
                entry_fee="5000000.00",
                exit_fee="5000000.00",
                opened_at=t0,
                closed_at=t0 + timedelta(hours=1),
            ),
            _create_trade(
                2,
                "t_large_2",
                quantity="1000000000.00",
                entry_price="1100.00",
                exit_price="1050.00",
                net_pnl="-50000000000.00",  # -5 * 10^10
                slippage_cost="5000000.00",
                entry_fee="2500000.00",
                exit_fee="2500000.00",
                opened_at=t0 + timedelta(hours=2),
                closed_at=t0 + timedelta(hours=3),
            ),
        ]
        m = calculate_performance_metrics(
            large_trades, starting_capital=Decimal("1000000000000.00")
        )

        assert m.total_trades == 2
        assert m.gross_profit == Decimal("100000000000.00")
        assert m.gross_loss == Decimal("50000000000.00")
        assert m.net_pnl == Decimal("50000000000.00")
        assert m.profit_factor == 2.0  # 100B / 50B
        assert m.total_fees_paid == Decimal("15000000.00")

        # Verify slippage stats under 10^9 scale
        slip = calculate_execution_slippage_stats(large_trades)
        assert slip.total_slippage_cost_usdt == 15000000.0
        assert math.isfinite(slip.average_slippage_bps)

        # Verify JSON serialization does not fail on large numbers
        d = m.to_dict()
        assert d["net_realized_pnl_usdt"] == 50000000000.0
        assert d["profit_factor"] == 2.0

    def test_microscopic_numbers_satoshi_scale(self) -> None:
        """Trades with 10^-8 scale (Satoshi-level) maintain Decimal integrity."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        micro_trades = [
            _create_trade(
                1,
                "t_micro_1",
                quantity="0.00000001",  # 10^-8
                entry_price="10000.00",  # notional = 0.0001
                exit_price="10100.00",
                net_pnl="0.00000100",  # 10^-6
                slippage_cost="0.00000001",
                entry_fee="0.00000001",
                exit_fee="0.00000001",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=5),
            ),
            _create_trade(
                2,
                "t_micro_2",
                quantity="0.00000001",
                entry_price="10100.00",
                exit_price="10050.00",
                net_pnl="-0.00000050",
                slippage_cost="0.00000001",
                entry_fee="0.00000001",
                exit_fee="0.00000001",
                opened_at=t0 + timedelta(minutes=10),
                closed_at=t0 + timedelta(minutes=15),
            ),
        ]
        m = calculate_performance_metrics(micro_trades, starting_capital=Decimal("1.00"))

        assert m.total_trades == 2
        assert m.gross_profit == Decimal("0.00000100")
        assert m.gross_loss == Decimal("0.00000050")
        assert m.net_pnl == Decimal("0.00000050")
        assert pytest.approx(m.profit_factor, rel=1e-6) == 2.0
        assert m.total_fees_paid == Decimal("0.00000004")

        # Check precision behavior on rounded slippage cost
        # total slippage is 2e-8. float rounding to 4 decimal places yields 0.0
        assert m.total_slippage_cost == Decimal("0")

    def test_mixed_orders_of_magnitude(self) -> None:
        """Combine 10^6 trade with 10^-6 trade in same sequence."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                1,
                "t1",
                quantity="100.00",
                entry_price="10000.00",
                net_pnl="100000.00",
                opened_at=t0,
                closed_at=t0 + timedelta(hours=1),
            ),
            _create_trade(
                2,
                "t2",
                quantity="0.00001",
                entry_price="100.00",
                net_pnl="0.00001",
                opened_at=t0 + timedelta(hours=2),
                closed_at=t0 + timedelta(hours=3),
            ),
        ]
        m = calculate_performance_metrics(trades)
        assert m.total_trades == 2
        assert m.gross_profit == Decimal("100000.00001")


# ===========================================================================
# 7. Drawdown Edge Cases (Unrecovered, Multi-Stage, Negative Equity)
# ===========================================================================


class TestDrawdownEdgeCases:
    """Stress test high-water mark, unrecovered drawdowns, and duration tracking."""

    def test_unrecovered_drawdown_flag_and_durations(self) -> None:
        """Equity drops from peak and never recovers -> is_drawdown_recovered = False."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        # Starting capital: 100
        # Trade 1: +20 -> Equity = 120 (Peak) at 10:10
        # Trade 2: -40 -> Equity = 80 (Trough) at 10:30
        # Trade 3: +10 -> Equity = 90 (Partial recovery, < 120) at 10:50
        trades = [
            _create_trade(
                1,
                "t1",
                net_pnl="20.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=10),
            ),
            _create_trade(
                2,
                "t2",
                net_pnl="-40.00",
                opened_at=t0 + timedelta(minutes=15),
                closed_at=t0 + timedelta(minutes=30),
            ),
            _create_trade(
                3,
                "t3",
                net_pnl="10.00",
                opened_at=t0 + timedelta(minutes=35),
                closed_at=t0 + timedelta(minutes=50),
            ),
        ]
        (
            max_dd_amount,
            max_dd_pct,
            peak_time,
            trough_time,
            dd_duration,
            recovery_dur,
            is_recovered,
        ) = calculate_drawdown_metrics(trades, starting_capital=Decimal("100.00"))

        assert max_dd_amount == Decimal("40.00")
        assert pytest.approx(max_dd_pct, rel=1e-5) == (40.0 / 120.0) * 100.0
        assert peak_time == t0 + timedelta(minutes=10)
        assert trough_time == t0 + timedelta(minutes=30)
        assert dd_duration == 1200.0  # 20 minutes = 1200s
        assert recovery_dur is None
        assert is_recovered is False

    def test_fully_recovered_drawdown_flow(self) -> None:
        """Equity drops from peak and later exceeds peak -> is_drawdown_recovered = True."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        # Starting capital: 100
        # Trade 1: +20 -> 120 (Peak) at 10:10
        # Trade 2: -30 -> 90 (Trough) at 10:25
        # Trade 3: +35 -> 125 (Recovered!) at 10:40
        trades = [
            _create_trade(
                1,
                "t1",
                net_pnl="20.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=10),
            ),
            _create_trade(
                2,
                "t2",
                net_pnl="-30.00",
                opened_at=t0 + timedelta(minutes=15),
                closed_at=t0 + timedelta(minutes=25),
            ),
            _create_trade(
                3,
                "t3",
                net_pnl="35.00",
                opened_at=t0 + timedelta(minutes=30),
                closed_at=t0 + timedelta(minutes=40),
            ),
        ]
        (
            max_dd_amount,
            max_dd_pct,
            peak_time,
            trough_time,
            dd_dur,
            recovery_dur,
            is_recovered,
        ) = calculate_drawdown_metrics(trades, starting_capital=Decimal("100.00"))

        assert max_dd_amount == Decimal("30.00")
        assert pytest.approx(max_dd_pct, rel=1e-5) == (30.0 / 120.0) * 100.0
        assert peak_time == t0 + timedelta(minutes=10)
        assert trough_time == t0 + timedelta(minutes=25)
        assert dd_dur == 900.0  # 15 min = 900s
        assert recovery_dur == 900.0  # 10:40 - 10:25 = 15 min = 900s
        assert is_recovered is True

    def test_immediate_first_trade_drawdown(self) -> None:
        """First trade is a loss: peak is starting_capital at first trade opened_at."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            net_pnl="-25.00",
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=10),
        )
        (
            max_dd_amount,
            max_dd_pct,
            peak_time,
            trough_time,
            dd_dur,
            recovery_dur,
            is_recovered,
        ) = calculate_drawdown_metrics([trade], starting_capital=Decimal("100.00"))

        assert max_dd_amount == Decimal("25.00")
        assert max_dd_pct == 25.0
        assert peak_time == t0  # Trade opened_at
        assert trough_time == t0 + timedelta(minutes=10)
        assert dd_dur == 600.0
        assert recovery_dur is None
        assert is_recovered is False

    def test_multiple_drawdowns_tracks_global_maximum(self) -> None:
        """First drawdown 10 USDT, second drawdown 25 USDT -> MDD selects second."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        # 100 -> 90 (dd 10) -> 110 (peak) -> 85 (dd 25) -> 120 (recovered)
        trades = [
            _create_trade(
                1,
                "t1",
                net_pnl="-10.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=10),
            ),
            _create_trade(
                2,
                "t2",
                net_pnl="20.00",
                opened_at=t0 + timedelta(minutes=15),
                closed_at=t0 + timedelta(minutes=25),
            ),
            _create_trade(
                3,
                "t3",
                net_pnl="-25.00",
                opened_at=t0 + timedelta(minutes=30),
                closed_at=t0 + timedelta(minutes=45),
            ),
            _create_trade(
                4,
                "t4",
                net_pnl="35.00",
                opened_at=t0 + timedelta(minutes=50),
                closed_at=t0 + timedelta(minutes=65),
            ),
        ]
        (
            max_dd_amount,
            max_dd_pct,
            peak_time,
            trough_time,
            dd_dur,
            recovery_dur,
            is_recovered,
        ) = calculate_drawdown_metrics(trades, starting_capital=Decimal("100.00"))

        assert max_dd_amount == Decimal("25.00")
        assert peak_time == t0 + timedelta(minutes=25)  # Peak at 110
        assert trough_time == t0 + timedelta(minutes=45)  # Trough at 85
        assert dd_dur == 1200.0  # 20 min
        assert recovery_dur == 1200.0  # 10:65 - 10:45 = 20 min
        assert is_recovered is True

    def test_negative_equity_catastrophic_drawdown(self) -> None:
        """Loss exceeds starting capital resulting in negative equity."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            net_pnl="-150.00",
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=10),
        )
        (
            max_dd_amount,
            max_dd_pct,
            peak_time,
            trough_time,
            _,
            _,
            is_recovered,
        ) = calculate_drawdown_metrics([trade], starting_capital=Decimal("100.00"))

        assert max_dd_amount == Decimal("150.00")
        assert max_dd_pct == 150.0  # 150 / 100 * 100
        assert is_recovered is False


# ===========================================================================
# 8. Asset Attribution & Portfolio Ranking
# ===========================================================================


class TestAttributionEdgeCases:
    """Stress test asset attribution under single-asset and negative PnL conditions."""

    def test_single_active_asset_others_zero(self) -> None:
        """Only BTC traded: BTC has populated stats, ETH/SOL/DOGE remain exact zeros."""
        t0 = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                1,
                "t1",
                symbol="BTCUSDT",
                net_pnl="25.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=10),
            )
        ]
        attr = calculate_asset_attribution(trades)

        assert attr["BTCUSDT"].trade_count == 1
        assert attr["BTCUSDT"].net_realized_pnl_usdt == Decimal("25.00")
        assert attr["BTCUSDT"].win_rate_pct == 100.0

        for sym in ("ETHUSDT", "SOLUSDT", "DOGEUSDT"):
            assert attr[sym].trade_count == 0
            assert attr[sym].win_rate_pct == 0.0
            assert attr[sym].net_realized_pnl_usdt == Decimal("0.00")

        ranking = calculate_performance_ranking(attr)
        assert ranking[0] == "BTCUSDT"

    def test_all_negative_pnl_ranking_order(self) -> None:
        """All assets lose money: ranking must sort from least negative to most negative."""
        t0 = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                1,
                "t1",
                symbol="BTCUSDT",
                net_pnl="-5.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=5),
            ),
            _create_trade(
                2,
                "t2",
                symbol="ETHUSDT",
                net_pnl="-20.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=5),
            ),
            _create_trade(
                3,
                "t3",
                symbol="SOLUSDT",
                net_pnl="-2.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=5),
            ),
            _create_trade(
                4,
                "t4",
                symbol="DOGEUSDT",
                net_pnl="-50.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=5),
            ),
        ]
        attr = calculate_asset_attribution(trades)
        ranking = calculate_performance_ranking(attr)

        # Best to worst: -2.00 (SOL) > -5.00 (BTC) > -20.00 (ETH) > -50.00 (DOGE)
        assert ranking == ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT"]


# ===========================================================================
# 9. Holding Duration and Slippage Extreme Boundaries
# ===========================================================================


class TestDurationAndSlippageBoundaries:
    """Stress test 0-second duration and 0-notional slippage handling."""

    def test_zero_second_holding_duration(self) -> None:
        """Holding duration = 0.0s (instant fill and exit)."""
        t0 = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            opened_at=t0,
            closed_at=t0,  # identical timestamps
        )
        assert trade.holding_duration_seconds == 0.0
        dur = calculate_holding_duration_stats([trade])
        assert dur.avg == 0.0
        assert dur.median == 0.0
        assert dur.min == 0.0
        assert dur.max == 0.0

    def test_zero_notional_slippage_no_division_error(self) -> None:
        """Trade with quantity = 0.0 or price = 0.0 avoids division by zero."""
        t0 = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            quantity="0.00",
            entry_price="0.00",
            exit_price="0.00",
            slippage_cost="0.00",
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=1),
        )
        slip = calculate_execution_slippage_stats([trade])
        assert slip.total_slippage_cost_usdt == 0.0
        assert slip.average_slippage_bps == 0.0
        assert slip.max_slippage_bps == 0.0

    def test_negative_slippage_cost_price_improvement(self) -> None:
        """Negative slippage (favorable fill better than mark price)."""
        t0 = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
        trade = _create_trade(
            1,
            "t1",
            quantity="1.00",
            entry_price="100.00",
            exit_price="100.00",
            slippage_cost="-0.02",  # favorable fill
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=1),
        )
        slip = calculate_execution_slippage_stats([trade])
        assert slip.total_slippage_cost_usdt == -0.02
        assert slip.average_slippage_bps < 0.0


# ===========================================================================
# 10. Deep Stress Testing & Empirical Boundary Discoveries
# ===========================================================================


class TestDeepStressAndInvariants:
    """Stress test throughput, mathematical invariants, and boundary conditions."""

    def test_high_throughput_10k_trades(self) -> None:
        """Verify O(N) performance on 10,000 trade sequence."""
        import time

        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                i,
                f"t{i}",
                net_pnl="1.00" if i % 2 == 0 else "-0.50",
                opened_at=t0 + timedelta(seconds=i * 60),
                closed_at=t0 + timedelta(seconds=i * 60 + 30),
            )
            for i in range(1, 10001)
        ]

        t_start = time.perf_counter()
        m = calculate_performance_metrics(trades)
        t_elapsed = time.perf_counter() - t_start

        assert m.total_trades == 10000
        assert m.winning_trades == 5000
        assert m.losing_trades == 5000
        assert m.win_rate_pct == 50.0
        # Processing 10,000 trades must take under 1.0 second
        assert t_elapsed < 1.0

    def test_exact_decimal_conservation_law(self) -> None:
        """Conservation: net_pnl must strictly equal gross_profit - gross_loss."""
        import random

        random.seed(42)
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                i,
                f"t{i}",
                net_pnl=f"{random.uniform(-100, 100):.4f}",
                opened_at=t0 + timedelta(seconds=i * 60),
                closed_at=t0 + timedelta(seconds=i * 60 + 30),
            )
            for i in range(1, 501)
        ]
        m = calculate_performance_metrics(trades)
        assert m.net_pnl == m.gross_profit - m.gross_loss

    def test_starting_capital_zero_division_boundary(self) -> None:
        """starting_capital = Decimal('0.00') raises DivisionByZero if max_dd_pct > 0."""
        from decimal import DivisionByZero

        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        t1 = _create_trade(
            1, "t1", net_pnl="10.00", opened_at=t0, closed_at=t0 + timedelta(minutes=5)
        )
        t2 = _create_trade(
            2,
            "t2",
            net_pnl="-5.00",
            opened_at=t0 + timedelta(minutes=6),
            closed_at=t0 + timedelta(minutes=10),
        )

        with pytest.raises(DivisionByZero):
            calculate_performance_metrics([t1, t2], starting_capital=Decimal("0.00"))

    def test_dollar_vs_percentage_drawdown_coupling(self) -> None:
        """max_dd_pct reflects the percentage at the peak of the max dollar drawdown."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        # Sequence:
        # 1. Drops from 100 to 50: Dollar DD = $50, Pct DD = 50%
        # 2. Rises to 1000 (+950)
        # 3. Drops from 1000 to 900 (-100): Dollar DD = $100, Pct DD = 10%
        trades = [
            _create_trade(
                1, "t1", net_pnl="-50.00", opened_at=t0, closed_at=t0 + timedelta(minutes=10)
            ),
            _create_trade(
                2,
                "t2",
                net_pnl="950.00",
                opened_at=t0 + timedelta(minutes=15),
                closed_at=t0 + timedelta(minutes=25),
            ),
            _create_trade(
                3,
                "t3",
                net_pnl="-100.00",
                opened_at=t0 + timedelta(minutes=30),
                closed_at=t0 + timedelta(minutes=45),
            ),
        ]
        mdd_amt, mdd_pct, peak, trough, _, _, _ = calculate_drawdown_metrics(
            trades, starting_capital=Decimal("100.00")
        )

        assert mdd_amt == Decimal("100.00")
        assert mdd_pct == 10.0  # reflects the 100/1000 drop, not the earlier 50% drop

    def test_attribution_extraneous_symbol_omitted(self) -> None:
        """Symbols in trades not included in symbols filter are excluded from attribution."""
        t0 = datetime(2026, 9, 7, 0, 0, 0, tzinfo=UTC)
        trades = [
            _create_trade(
                1,
                "t1",
                symbol="XRPUSDT",
                net_pnl="50.00",
                opened_at=t0,
                closed_at=t0 + timedelta(minutes=5),
            )
        ]
        attr = calculate_asset_attribution(trades)  # uses DEFAULT_PORTFOLIO_SYMBOLS
        assert "XRPUSDT" not in attr
        assert set(attr.keys()) == set(DEFAULT_PORTFOLIO_SYMBOLS)
