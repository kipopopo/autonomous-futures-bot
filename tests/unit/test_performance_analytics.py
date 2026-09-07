"""Unit test suite for autonomous_futures.analytics.

Verifies:
1. Exact mathematical formulation of 10 quantitative risk & performance metrics.
2. Boundary conditions and edge cases (100% wins, 100% losses, mixed, zero trades, zero variance).
3. Read-only SQLite ledger reader with self-join query and Decimal precision.
4. Per-asset attribution and performance ranking across BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT.
5. Daily performance report generation, JSON schema validation, and persistence.
6. Telegram MarkdownV2 character escaping and plain-text representation.
7. Standalone CLI runner scripts/generate_performance_report.py execution.
8. Interactive Telegram command integration (/analytics, enhanced /pnl, /help, daily report worker).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.analytics import (  # noqa: E402
    DEFAULT_PORTFOLIO_SYMBOLS,
    AssetAttribution,
    CapitalState,
    DailyPerformanceReport,
    PerformanceMetrics,
    ReadOnlyLedgerReader,
    TradeRecord,
    calculate_asset_attribution,
    calculate_drawdown_metrics,
    calculate_execution_slippage_stats,
    calculate_holding_duration_stats,
    calculate_performance_metrics,
    calculate_performance_ranking,
    format_analytics_command_reply,
    format_daily_performance_report,
    format_duration,
    generate_and_persist_daily_report,
    generate_daily_performance_report,
)
from autonomous_futures.notify.telegram import TelegramConfig  # noqa: E402
from scripts.run_telegram_notifier import TelegramNotifierDaemon  # noqa: E402


def _make_trade(
    sequence: int,
    trade_id: str,
    symbol: str,
    side: str,
    quantity: str,
    entry_price: str,
    exit_price: str,
    opened_at: datetime,
    closed_at: datetime,
    entry_fee: str = "0.02",
    exit_fee: str = "0.02",
    slippage_cost: str = "0.01",
    net_pnl: str = "1.00",
    gross_pnl: str = "1.04",
    exit_reason: str = "normal_close",
) -> TradeRecord:
    """Helper to construct strongly typed TradeRecord for testing."""
    ent_f = Decimal(entry_fee)
    ext_f = Decimal(exit_fee)
    dur = max(0.0, (closed_at - opened_at).total_seconds())
    return TradeRecord(
        close_sequence=sequence,
        trade_id=trade_id,
        candidate_id="cand-test-01",
        candidate_artifact_hash="a" * 64,
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        entry_price=Decimal(entry_price),
        exit_price=Decimal(exit_price),
        opened_at=opened_at,
        closed_at=closed_at,
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
# 1. Mathematical Metrics & Edge Cases Tests
# ===========================================================================


class TestMetricsEdgeCases:
    """Test mathematical formulations and edge cases in metrics.py."""

    def test_zero_trades_returns_clean_baseline(self) -> None:
        """When 0 trades exist, all metrics return zeroed/None baseline without exception."""
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
        assert m.calmar_ratio is None
        assert m.recovery_factor is None
        assert m.average_win is None
        assert m.average_loss is None
        assert m.payoff_ratio is None
        assert m.expectancy == Decimal("0.00")
        assert m.fee_drag_ratio is None

        d = m.to_dict()
        assert d["trade_count"] == 0
        assert d["profit_factor"] is None
        assert d["sharpe_ratio_annualized"] is None

    def test_perfect_win_sequence_100_pct(self) -> None:
        """100% win sequence has infinite profit factor (None) and zero drawdown."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50500",
                t0,
                t0 + timedelta(minutes=10),
                net_pnl="5.00",
            ),
            _make_trade(
                2,
                "t2",
                "ETHUSDT",
                "LONG",
                "0.1",
                "3000",
                "3050",
                t0 + timedelta(minutes=15),
                t0 + timedelta(minutes=25),
                net_pnl="5.00",
            ),
            _make_trade(
                3,
                "t3",
                "SOLUSDT",
                "LONG",
                "1.0",
                "150",
                "155",
                t0 + timedelta(minutes=30),
                t0 + timedelta(minutes=40),
                net_pnl="5.00",
            ),
        ]

        m = calculate_performance_metrics(trades)
        assert m.total_trades == 3
        assert m.winning_trades == 3
        assert m.losing_trades == 0
        assert m.breakeven_trades == 0
        assert m.win_rate_pct == 100.0
        assert m.gross_profit == Decimal("15.00")
        assert m.gross_loss == Decimal("0.00")
        assert m.net_pnl == Decimal("15.00")
        assert m.profit_factor is None
        assert m.average_loss is None
        assert m.payoff_ratio is None
        assert m.sortino_ratio is None
        assert m.max_drawdown_amount == Decimal("0.00")
        assert m.max_drawdown_pct == 0.0

    def test_all_loss_sequence_0_pct(self) -> None:
        """0% win sequence has 0.0 profit factor and max drawdown equal to loss sum."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "49500",
                t0,
                t0 + timedelta(minutes=10),
                net_pnl="-5.00",
            ),
            _make_trade(
                2,
                "t2",
                "ETHUSDT",
                "LONG",
                "0.1",
                "3000",
                "2950",
                t0 + timedelta(minutes=15),
                t0 + timedelta(minutes=25),
                net_pnl="-3.00",
            ),
        ]

        m = calculate_performance_metrics(trades, starting_capital=Decimal("100.00"))
        assert m.total_trades == 2
        assert m.winning_trades == 0
        assert m.losing_trades == 2
        assert m.win_rate_pct == 0.0
        assert m.gross_profit == Decimal("0.00")
        assert m.gross_loss == Decimal("8.00")
        assert m.net_pnl == Decimal("-8.00")
        assert m.profit_factor == 0.0
        assert m.average_win is None
        assert m.average_loss == Decimal("4.00")
        assert m.payoff_ratio == 0.0
        assert m.max_drawdown_amount == Decimal("8.00")
        assert m.max_drawdown_pct == 8.0

    def test_zero_variance_sharpe_handling(self) -> None:
        """When all returns are identical, variance is zero and Sharpe returns None."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0,
                t0 + timedelta(minutes=5),
                net_pnl="1.00",
            ),
            _make_trade(
                2,
                "t2",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0 + timedelta(minutes=6),
                t0 + timedelta(minutes=11),
                net_pnl="1.00",
            ),
            _make_trade(
                3,
                "t3",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0 + timedelta(minutes=12),
                t0 + timedelta(minutes=17),
                net_pnl="1.00",
            ),
        ]

        m = calculate_performance_metrics(trades)
        assert m.total_trades == 3
        assert m.sharpe_ratio_trade is None
        assert m.sharpe_ratio_annualized is None

    def test_mixed_sequence_exact_calculation(self) -> None:
        """Verify exact values for a mixed sequence with 2 wins and 1 loss."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50600",
                t0,
                t0 + timedelta(minutes=10),
                net_pnl="6.00",
                entry_fee="0.50",
                exit_fee="0.50",
            ),
            _make_trade(
                2,
                "t2",
                "ETHUSDT",
                "SHORT",
                "0.1",
                "3000",
                "3020",
                t0 + timedelta(minutes=15),
                t0 + timedelta(minutes=25),
                net_pnl="-2.00",
                entry_fee="0.25",
                exit_fee="0.25",
            ),
            _make_trade(
                3,
                "t3",
                "SOLUSDT",
                "LONG",
                "1.0",
                "150",
                "154",
                t0 + timedelta(minutes=30),
                t0 + timedelta(minutes=40),
                net_pnl="4.00",
                entry_fee="0.25",
                exit_fee="0.25",
            ),
        ]

        m = calculate_performance_metrics(trades, starting_capital=Decimal("100.00"))
        assert m.total_trades == 3
        assert m.winning_trades == 2
        assert m.losing_trades == 1
        assert m.breakeven_trades == 0
        assert round(m.win_rate_pct, 2) == 66.67
        assert m.gross_profit == Decimal("10.00")
        assert m.gross_loss == Decimal("2.00")
        assert m.net_pnl == Decimal("8.00")
        assert m.profit_factor == 5.0
        assert m.average_win == Decimal("5.00")
        assert m.average_loss == Decimal("2.00")
        assert m.payoff_ratio == 2.5
        assert m.expectancy == Decimal("8.00") / Decimal(3)
        assert m.total_fees_paid == Decimal("2.00")
        assert m.fee_drag_ratio == 0.20
        assert m.sharpe_ratio_annualized is not None
        assert m.sortino_ratio is not None

    def test_duration_and_slippage_stats(self) -> None:
        """Test auxiliary duration and slippage calculation helpers."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0,
                t0 + timedelta(seconds=300),
                slippage_cost="0.20",
            ),
            _make_trade(
                2,
                "t2",
                "ETHUSDT",
                "SHORT",
                "0.1",
                "3000",
                "2950",
                t0,
                t0 + timedelta(seconds=900),
                slippage_cost="0.10",
            ),
        ]
        dur = calculate_holding_duration_stats(trades)
        assert dur.min == 300.0
        assert dur.max == 900.0
        assert dur.avg == 600.0
        assert dur.median == 600.0

        slip = calculate_execution_slippage_stats(trades)
        assert slip.total_slippage_cost_usdt == 0.30
        assert slip.max_slippage_bps > 0.0

    def test_drawdown_recovery_flow(self) -> None:
        """Verify drawdown tracking when equity recovers back to peak."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0,
                t0 + timedelta(minutes=10),
                net_pnl="-10.00",
            ),
            _make_trade(
                2,
                "t2",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0 + timedelta(minutes=15),
                t0 + timedelta(minutes=25),
                net_pnl="15.00",
            ),
        ]
        mdd_amt, mdd_pct, peak_t, trough_t, dd_dur, rec_dur, is_rec = calculate_drawdown_metrics(
            trades, starting_capital=Decimal("100.00")
        )
        assert mdd_amt == Decimal("10.00")
        assert mdd_pct == 10.0
        assert is_rec is True
        assert rec_dur is not None and rec_dur > 0.0


# ===========================================================================
# 2. ReadOnlyLedgerReader Tests
# ===========================================================================


class TestReadOnlyLedgerReader:
    """Test non-blocking SQLite reading and self-join correlation."""

    @pytest.fixture
    def test_ledger_dir(self, tmp_path: Path) -> Path:
        """Create a populated paper trading directory with SQLite databases."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
            """
        )

        t0 = "2026-09-07T01:00:00+00:00"
        t1 = "2026-09-07T01:15:00+00:00"
        t2 = "2026-09-07T02:00:00+00:00"
        t3 = "2026-09-07T02:30:00+00:00"
        t4 = "2026-09-07T03:00:00+00:00"

        # Trade 1: closed (BTCUSDT)
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 'open', 'trade-btc-01', 'c1', 'hash1', 'BTCUSDT', 'LONG',
             '0.001', '60000.00', ?, 'app-1', '0.024', NULL, '0.012', NULL, NULL)
            """,
            (t0,),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (2, 'close', 'trade-btc-01', 'c1', 'hash1', 'BTCUSDT', 'LONG',
             '0.001', '60500.00', ?, 'app-2', '0.024', '0.0242', '0.024', '0.50', '0.4518')
            """,
            (t1,),
        )

        # Trade 2: closed (ETHUSDT)
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (3, 'open', 'trade-eth-02', 'c2', 'hash2', 'ETHUSDT', 'SHORT',
             '0.05', '3000.00', ?, 'app-3', '0.06', NULL, '0.03', NULL, NULL)
            """,
            (t2,),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (4, 'close', 'trade-eth-02', 'c2', 'hash2', 'ETHUSDT', 'SHORT',
             '0.05', '2950.00', ?, 'app-4', '0.06', '0.059', '0.06', '2.50', '2.3810')
            """,
            (t3,),
        )

        # Trade 3: open (SOLUSDT - no close yet)
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (5, 'open', 'trade-sol-03', 'c3', 'hash3', 'SOLUSDT', 'LONG',
             '1.0', '150.00', ?, 'app-5', '0.06', NULL, '0.03', NULL, NULL)
            """,
            (t4,),
        )

        conn.commit()
        conn.close()

        # Create paper-lifecycle.sqlite3 with exit reason
        lc_path = tmp_path / "paper-lifecycle.sqlite3"
        conn_lc = sqlite3.connect(lc_path)
        conn_lc.execute(
            """
            CREATE TABLE paper_lifecycle_marks (
                sequence INTEGER PRIMARY KEY,
                candidate_id TEXT,
                candidate_artifact_hash TEXT,
                trade_id TEXT,
                marked_at TEXT,
                payload TEXT
            );
            """
        )
        lc_payload = json.dumps(
            {
                "lifecycle_status": "closed",
                "reason_codes": ["lifecycle_open", "take_profit_hit"],
            }
        )
        conn_lc.execute(
            "INSERT INTO paper_lifecycle_marks VALUES (1, 'c1', 'hash1', 'trade-btc-01', ?, ?)",
            (t1, lc_payload),
        )
        conn_lc.commit()
        conn_lc.close()

        return tmp_path

    def test_read_closed_trades_self_join(self, test_ledger_dir: Path) -> None:
        """ReadOnlyLedgerReader correctly pairs open and close events."""
        reader = ReadOnlyLedgerReader(test_ledger_dir)
        trades = reader.read_closed_trades()

        assert len(trades) == 2
        t1 = trades[0]
        assert t1.trade_id == "trade-btc-01"
        assert t1.symbol == "BTCUSDT"
        assert t1.entry_price == Decimal("60000.00")
        assert t1.exit_price == Decimal("60500.00")
        assert t1.net_pnl == Decimal("0.4518")
        assert t1.holding_duration_seconds == 900.0
        assert t1.exit_reason == "take_profit_hit"

        t2 = trades[1]
        assert t2.trade_id == "trade-eth-02"
        assert t2.symbol == "ETHUSDT"
        assert t2.entry_price == Decimal("3000.00")
        assert t2.exit_price == Decimal("2950.00")
        assert t2.net_pnl == Decimal("2.3810")
        assert t2.holding_duration_seconds == 1800.0
        assert t2.exit_reason == "normal_close"

    def test_date_and_symbol_filtering(self, test_ledger_dir: Path) -> None:
        """Test temporal and symbol filtering."""
        reader = ReadOnlyLedgerReader(test_ledger_dir)

        btc_trades = reader.read_closed_trades(symbols=["BTCUSDT"])
        assert len(btc_trades) == 1
        assert btc_trades[0].symbol == "BTCUSDT"

        start = datetime(2026, 9, 7, 2, 0, 0, tzinfo=UTC)
        end = datetime(2026, 9, 7, 3, 0, 0, tzinfo=UTC)
        eth_trades = reader.read_closed_trades(start_time=start, end_time=end)
        assert len(eth_trades) == 1
        assert eth_trades[0].trade_id == "trade-eth-02"

    def test_open_trades_and_cash_reconciliation(self, test_ledger_dir: Path) -> None:
        """Test counting open trades and exact cash balance reconciliation."""
        reader = ReadOnlyLedgerReader(test_ledger_dir)
        open_count = reader.read_open_trades_count()
        assert open_count == 1

        cash = reader.calculate_reconciled_cash(starting_capital=Decimal("100.00"))
        expected_cash = Decimal("100.00") + Decimal("0.4518") + Decimal("2.3810") - Decimal("0.06")
        assert cash == expected_cash


# ===========================================================================
# 3. Multi-Asset Attribution & Ranking Tests
# ===========================================================================


class TestAttributionAndRanking:
    """Test portfolio multi-asset attribution and ranking."""

    def test_asset_attribution_all_symbols_present(self) -> None:
        """Verify that all default symbols are present in attribution even with 0 trades."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50500",
                t0,
                t0 + timedelta(minutes=5),
                net_pnl="2.50",
            ),
            _make_trade(
                2,
                "t2",
                "ETHUSDT",
                "LONG",
                "0.1",
                "3000",
                "2950",
                t0,
                t0 + timedelta(minutes=5),
                net_pnl="-1.20",
            ),
        ]

        attrs = calculate_asset_attribution(trades, symbols=DEFAULT_PORTFOLIO_SYMBOLS)
        assert set(attrs.keys()) == set(DEFAULT_PORTFOLIO_SYMBOLS)

        btc = attrs["BTCUSDT"]
        assert btc.trade_count == 1
        assert btc.winning_trades == 1
        assert btc.net_realized_pnl_usdt == Decimal("2.50")

        doge = attrs["DOGEUSDT"]
        assert doge.trade_count == 0
        assert doge.winning_trades == 0
        assert doge.net_realized_pnl_usdt == Decimal("0.00")
        assert doge.profit_factor is None

    def test_ranking_sorted_descending(self) -> None:
        """Verify performance ranking sorts symbols descending by net realized PnL."""
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        trades = [
            _make_trade(
                1,
                "t1",
                "SOLUSDT",
                "LONG",
                "1.0",
                "150",
                "160",
                t0,
                t0 + timedelta(minutes=5),
                net_pnl="10.00",
            ),
            _make_trade(
                2,
                "t2",
                "BTCUSDT",
                "LONG",
                "0.01",
                "50000",
                "50100",
                t0,
                t0 + timedelta(minutes=5),
                net_pnl="1.00",
            ),
            _make_trade(
                3,
                "t3",
                "DOGEUSDT",
                "SHORT",
                "100",
                "0.15",
                "0.16",
                t0,
                t0 + timedelta(minutes=5),
                net_pnl="-1.00",
            ),
        ]

        attrs = calculate_asset_attribution(trades)
        ranking = calculate_performance_ranking(attrs)

        assert ranking == ["SOLUSDT", "BTCUSDT", "ETHUSDT", "DOGEUSDT"]


# ===========================================================================
# 4. Report Generation & Schema Persistence Tests
# ===========================================================================


class TestReportGenerationAndPersistence:
    """Test daily report generation, schema compliance, and atomic persistence."""

    def test_daily_report_generation_and_schema(self, tmp_path: Path) -> None:
        """Verify report generation produces valid Draft-07 compliant schema."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                candidate_artifact_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
            """
        )
        t_open = "2026-09-07T05:00:00+00:00"
        t_close = "2026-09-07T05:30:00+00:00"
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 'open', 'tr-1', 'c1', 'hash1', 'BTCUSDT', 'LONG',
             '0.01', '50000', ?, 'a1', '0.02', NULL, '0.01', NULL, NULL)
            """,
            (t_open,),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (2, 'close', 'tr-1', 'c1', 'hash1', 'BTCUSDT', 'LONG',
             '0.01', '50500', ?, 'a2', '0.02', '0.02', '0.02', '5.00', '4.96')
            """,
            (t_close,),
        )
        conn.commit()
        conn.close()

        report = generate_daily_performance_report(
            storage_dir=tmp_path,
            report_date="2026-09-07",
        )
        data = report.to_dict()

        assert "report_metadata" in data
        assert "daemon_health" in data
        assert "safety_invariants" in data
        assert "capital_summary" in data
        assert "portfolio_performance" in data
        assert "asset_breakdown" in data
        assert "asset_ranking" in data

        si = data["safety_invariants"]
        assert si["orders_submitted"] == 0
        assert si["execution_authority"] is False
        assert si["live_trading_activation"] is False
        assert si["paper_activation"] is True
        assert si["zero_private_credentials"] is True
        assert si["all_invariants_pass"] is True

        perf = data["portfolio_performance"]
        assert perf["trade_count"] == 1
        assert perf["winning_trades"] == 1
        assert perf["net_realized_pnl_usdt"] == 4.96

        cap = data["capital_summary"]
        assert cap["starting_cash_usdt"] == 100.00
        assert cap["ending_cash_usdt"] == 104.96

    def test_persist_report_to_disk(self, tmp_path: Path) -> None:
        """Verify atomic JSON file persistence."""
        out_file = tmp_path / "custom_reports" / "report.json"
        res = generate_and_persist_daily_report(
            storage_dir=tmp_path,
            report_date="2026-09-07",
            output_path=out_file,
        )
        assert out_file.is_file()
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        assert loaded["report_metadata"]["report_date"] == "2026-09-07"
        assert res == loaded

    def test_domain_model_dataclass_methods(self) -> None:
        """Test CapitalState, AssetAttribution, DailyPerformanceReport methods directly."""
        cap = CapitalState()
        d_cap = cap.to_dict()
        assert d_cap["starting_cash_usdt"] == 100.00

        attr = AssetAttribution(symbol="BTCUSDT")
        d_attr = attr.to_dict()
        assert d_attr["symbol"] == "BTCUSDT"

        m = PerformanceMetrics()
        rep = DailyPerformanceReport(
            report_metadata={"report_date": "2026-09-07"},
            daemon_health={},
            safety_invariants={},
            capital_summary=d_cap,
            portfolio_performance=m.to_dict(),
            asset_breakdown={"BTCUSDT": d_attr},
            asset_ranking=["BTCUSDT"],
        )
        assert "2026-09-07" in rep.to_json()

    def test_domain_models_from_dict_and_from_json_roundtrip(self) -> None:
        """Verify from_dict and from_json roundtrip deserialization for all domain models."""
        from autonomous_futures.analytics.models import (
            ExecutionSlippageStats,
            HoldingDurationStats,
        )

        # 1. HoldingDurationStats
        h_orig = HoldingDurationStats(avg=120.5, median=110.0, min=45.0, max=360.0)
        h_dict = h_orig.to_dict()
        h_deser = HoldingDurationStats.from_dict(h_dict)
        assert h_deser == h_orig

        # 2. ExecutionSlippageStats
        s_orig = ExecutionSlippageStats(
            total_slippage_cost_usdt=12.5, average_slippage_bps=2.1, max_slippage_bps=5.0
        )
        s_dict = s_orig.to_dict()
        s_deser = ExecutionSlippageStats.from_dict(s_dict)
        assert s_deser == s_orig

        # 3. CapitalState
        c_orig = CapitalState(
            starting_cash_usdt=Decimal("100.00"),
            ending_cash_usdt=Decimal("108.45"),
            current_equity_usdt=Decimal("110.20"),
            peak_equity_usdt=Decimal("112.00"),
            net_realized_pnl_usdt=Decimal("8.45"),
            realized_pnl_pct=8.45,
            unrealized_pnl_usdt=Decimal("1.75"),
            margin_allocated_usdt=Decimal("20.00"),
            margin_utilization_pct=18.15,
            reserve_buffer_pct=81.85,
        )
        c_dict = c_orig.to_dict()
        c_deser = CapitalState.from_dict(c_dict)
        assert c_deser.starting_cash_usdt == Decimal("100.00")
        assert c_deser.ending_cash_usdt == Decimal("108.45")
        assert c_deser.current_equity_usdt == Decimal("110.20")
        assert c_deser.realized_pnl_pct == 8.45

        # 4. AssetAttribution
        a_orig = AssetAttribution(
            symbol="ETHUSDT",
            trade_count=15,
            winning_trades=10,
            losing_trades=5,
            breakeven_trades=0,
            win_rate_pct=66.67,
            gross_profit_usdt=Decimal("15.50"),
            gross_loss_usdt=Decimal("6.00"),
            net_realized_pnl_usdt=Decimal("9.50"),
            total_fees_usdt=Decimal("1.20"),
            profit_factor=2.58,
            max_drawdown_pct=2.15,
            holding_duration_avg_seconds=1800.0,
        )
        a_dict = a_orig.to_dict()
        a_deser = AssetAttribution.from_dict(a_dict)
        assert a_deser.symbol == "ETHUSDT"
        assert a_deser.trade_count == 15
        assert a_deser.net_realized_pnl_usdt == Decimal("9.50")
        assert a_deser.profit_factor == 2.58

        # 5. PerformanceMetrics
        m_orig = PerformanceMetrics(
            total_trades=20,
            winning_trades=12,
            losing_trades=8,
            breakeven_trades=0,
            win_rate_pct=60.0,
            gross_profit=Decimal("25.00"),
            gross_loss=Decimal("10.00"),
            net_pnl=Decimal("15.00"),
            profit_factor=2.5,
            sharpe_ratio_trade=1.8,
            sharpe_ratio_annualized=2.4,
            sortino_ratio=3.1,
            max_drawdown_amount=Decimal("3.50"),
            max_drawdown_pct=3.5,
            total_fees_paid=Decimal("2.10"),
            holding_duration_mean_seconds=1200.0,
            holding_duration_median_seconds=1100.0,
            holding_duration_min_seconds=300.0,
            holding_duration_max_seconds=2500.0,
            total_slippage_cost=Decimal("0.50"),
            average_slippage_bps=1.8,
            max_slippage_bps=3.2,
        )
        m_dict = m_orig.to_dict()
        m_deser = PerformanceMetrics.from_dict(m_dict)
        assert m_deser.total_trades == 20
        assert m_deser.gross_profit == Decimal("25.00")
        assert m_deser.profit_factor == 2.5
        assert m_deser.holding_duration_mean_seconds == 1200.0
        assert m_deser.total_slippage_cost == Decimal("0.50")

        # 6. DailyPerformanceReport
        rep = DailyPerformanceReport(
            report_metadata={"report_date": "2026-09-07", "schema_version": "1.0.0"},
            daemon_health={"daemon_status": "RUNNING", "pid": 1234},
            safety_invariants={"orders_submitted": 0, "execution_authority": False},
            capital_summary=c_dict,
            portfolio_performance=m_dict,
            asset_breakdown={"ETHUSDT": a_dict},
            asset_ranking=["ETHUSDT"],
        )
        json_payload = rep.to_json()
        rep_from_json = DailyPerformanceReport.from_json(json_payload)
        assert rep_from_json.report_metadata["report_date"] == "2026-09-07"
        assert rep_from_json.asset_ranking == ["ETHUSDT"]

        # Typed accessors
        typed_cap = rep_from_json.get_capital_state()
        assert typed_cap.ending_cash_usdt == Decimal("108.45")
        typed_perf = rep_from_json.get_performance_metrics()
        assert typed_perf.total_trades == 20
        assert typed_perf.net_pnl == Decimal("15.00")
        typed_attrs = rep_from_json.get_asset_attributions()
        assert "ETHUSDT" in typed_attrs
        assert typed_attrs["ETHUSDT"].symbol == "ETHUSDT"

        # 7. TradeRecord
        t0 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC)
        tr = TradeRecord(
            close_sequence=1,
            trade_id="tr-test-1",
            candidate_id="cand-1",
            candidate_artifact_hash="hash-1",
            symbol="BTCUSDT",
            side="LONG",
            quantity=Decimal("0.05"),
            entry_price=Decimal("60000.00"),
            exit_price=Decimal("61000.00"),
            opened_at=t0,
            closed_at=t0 + timedelta(minutes=15),
            holding_duration_seconds=900.0,
            entry_fee=Decimal("1.20"),
            exit_fee=Decimal("1.22"),
            total_fees=Decimal("2.42"),
            slippage_cost=Decimal("0.30"),
            gross_pnl=Decimal("50.00"),
            net_pnl=Decimal("47.58"),
        )
        tr_dict = tr.to_dict()
        tr_deser = TradeRecord.from_dict(tr_dict)
        assert tr_deser.trade_id == "tr-test-1"
        assert tr_deser.quantity == Decimal("0.05")
        assert tr_deser.net_pnl == Decimal("47.58")


# ===========================================================================
# 5. Telegram MarkdownV2 Formatter Tests
# ===========================================================================


class TestTelegramFormatters:
    """Test character escaping and layout formatting for Telegram."""

    def test_format_duration(self) -> None:
        """Test duration formatting."""
        assert format_duration(0.0) == "0s"
        assert format_duration(45.0) == "45s"
        assert format_duration(1470.0) == "24m 30s"
        assert format_duration(7320.0) == "2h 2m"

    def test_format_daily_performance_report_escaping(self) -> None:
        """Verify that format_daily_performance_report escapes dots, dashes, etc."""
        report_data = {
            "report_metadata": {
                "report_date": "2026-09-07",
                "generated_at_utc": "2026-09-07T00:00:00+00:00",
            },
            "capital_summary": {
                "starting_cash_usdt": 100.0,
                "ending_cash_usdt": 105.42,
                "current_equity_usdt": 105.42,
                "net_realized_pnl_usdt": 5.42,
                "realized_pnl_pct": 5.42,
                "margin_utilization_pct": 0.0,
                "reserve_buffer_pct": 100.0,
            },
            "portfolio_performance": {
                "trade_count": 12,
                "winning_trades": 8,
                "losing_trades": 3,
                "breakeven_trades": 1,
                "win_rate_pct": 66.7,
                "win_loss_payoff_ratio": 1.85,
                "profit_factor": 3.71,
                "sharpe_ratio_annualized": 2.14,
                "sortino_ratio": 3.42,
                "max_drawdown_usdt": 1.20,
                "max_drawdown_pct": 1.14,
                "expectancy_usdt": 0.45,
                "total_taker_fees_usdt": 0.48,
                "fee_drag_ratio": 0.081,
                "holding_duration_seconds": {"avg": 1470.0},
            },
            "asset_breakdown": {
                "ETHUSDT": {
                    "net_realized_pnl_usdt": 3.20,
                    "trade_count": 5,
                    "win_rate_pct": 80.0,
                },
                "BTCUSDT": {
                    "net_realized_pnl_usdt": 1.80,
                    "trade_count": 4,
                    "win_rate_pct": 75.0,
                },
            },
            "asset_ranking": ["ETHUSDT", "BTCUSDT"],
            "daemon_health": {"daemon_status": "RUNNING", "pid": 677393},
        }

        text = format_daily_performance_report(report_data)
        assert "DAILY PERFORMANCE REPORT" in text
        assert "ETHUSDT" in text
        assert "BTCUSDT" in text
        assert "2026\\-09\\-07" in text
        assert "100\\.00" in text

    def test_format_analytics_command_reply(self) -> None:
        """Test formatting of /analytics interactive response."""
        report_data = {
            "capital_summary": {
                "ending_cash_usdt": 104.50,
                "current_equity_usdt": 104.50,
                "margin_utilization_pct": 12.5,
                "reserve_buffer_pct": 87.5,
            },
            "portfolio_performance": {
                "trade_count": 5,
                "winning_trades": 3,
                "losing_trades": 2,
                "win_rate_pct": 60.0,
                "profit_factor": 2.50,
                "win_loss_payoff_ratio": 1.67,
                "sharpe_ratio_annualized": 1.85,
                "sortino_ratio": 2.90,
                "max_drawdown_usdt": 1.10,
                "max_drawdown_pct": 1.05,
                "net_realized_pnl_usdt": 4.50,
                "total_taker_fees_usdt": 0.35,
                "fee_drag_ratio": 0.07,
                "expectancy_usdt": 0.90,
            },
            "asset_breakdown": {
                "BTCUSDT": {
                    "net_realized_pnl_usdt": 3.00,
                    "trade_count": 3,
                    "win_rate_pct": 66.7,
                },
                "ETHUSDT": {
                    "net_realized_pnl_usdt": 1.50,
                    "trade_count": 2,
                    "win_rate_pct": 50.0,
                },
            },
            "asset_ranking": ["BTCUSDT", "ETHUSDT"],
        }

        reply = format_analytics_command_reply(report_data)
        assert "QUANTITATIVE ANALYTICS" in reply
        assert "Closed Trades" in reply
        assert "BTCUSDT" in reply
        assert "ETHUSDT" in reply


# ===========================================================================
# 6. CLI Runner Execution Tests
# ===========================================================================


class TestCLIExecution:
    """Test scripts/generate_performance_report.py execution."""

    def test_cli_dry_run_json(self, tmp_path: Path) -> None:
        """Test running CLI with --json and --dry-run flags."""
        script_path = _REPO_ROOT / "scripts" / "generate_performance_report.py"
        cmd = [
            sys.executable,
            str(script_path),
            "--storage-dir",
            str(tmp_path),
            "--date",
            "2026-09-07",
            "--json",
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["report_metadata"]["report_date"] == "2026-09-07"
        assert data["safety_invariants"]["orders_submitted"] == 0

    def test_cli_invalid_date(self, tmp_path: Path) -> None:
        """CLI returns exit code 1 on invalid date format."""
        script_path = _REPO_ROOT / "scripts" / "generate_performance_report.py"
        cmd = [
            sys.executable,
            str(script_path),
            "--storage-dir",
            str(tmp_path),
            "--date",
            "invalid-date",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 1

    def test_cli_invalid_storage_dir(self, tmp_path: Path) -> None:
        """CLI returns exit code 2 on non-existent storage directory."""
        script_path = _REPO_ROOT / "scripts" / "generate_performance_report.py"
        non_existent = tmp_path / "does_not_exist"
        cmd = [
            sys.executable,
            str(script_path),
            "--storage-dir",
            str(non_existent),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 2


# ===========================================================================
# 7. Telegram Sidecar Commands & Worker Tests
# ===========================================================================


class TestTelegramNotifierIntegration:
    """Test /analytics, enhanced /pnl, and daily report worker in sidecar."""

    @pytest.fixture
    def populated_sidecar_dir(self, tmp_path: Path) -> Path:
        """Create sidecar storage dir with ledger and health snapshot."""
        db_path = tmp_path / "paper-ledger.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE paper_ledger_events (
                sequence INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                candidate_id TEXT,
                candidate_artifact_hash TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                approval_id TEXT,
                entry_fee TEXT,
                exit_fee TEXT,
                slippage_cost TEXT,
                gross_pnl TEXT,
                net_pnl TEXT
            );
            """
        )
        t_open = "2026-09-06T12:00:00+00:00"
        t_close = "2026-09-06T12:15:00+00:00"
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (1, 'open', 'tr-1', 'c1', 'h1', 'BTCUSDT', 'LONG',
             '0.01', '50000', ?, 'a1', '0.02', NULL, '0.01', NULL, NULL)
            """,
            (t_open,),
        )
        conn.execute(
            """
            INSERT INTO paper_ledger_events VALUES
            (2, 'close', 'tr-1', 'c1', 'h1', 'BTCUSDT', 'LONG',
             '0.01', '50200', ?, 'a2', '0.02', '0.02', '0.02', '2.00', '1.96')
            """,
            (t_close,),
        )
        conn.commit()
        conn.close()

        health_file = tmp_path / "paper-daemon-health.json"
        health_data = {
            "daemon_status": "RUNNING",
            "pid": 12345,
            "uptime_seconds": 3600.0,
            "starting_capital_usdt": "100.00",
            "current_cash_usdt": "101.96",
            "current_equity_usdt": "101.96",
            "margin_utilization_pct": 0.0,
            "reserve_buffer_pct": 100.0,
            "active_positions": {},
            "circuit_breaker_status": "NORMAL",
            "feed_messages_received": 1000,
            "feed_throughput_per_sec": 12.5,
            "feed_reconnects_count": 0,
            "zero_order_safety_invariants": {
                "orders_submitted": 0,
                "execution_authority": False,
                "live_trading_activation": False,
                "paper_activation": True,
                "zero_private_credentials": True,
            },
        }
        health_file.write_text(json.dumps(health_data), encoding="utf-8")
        return tmp_path

    def test_analytics_command(self, populated_sidecar_dir: Path) -> None:
        """Verify /analytics command returns formatted metrics."""
        cfg = TelegramConfig(dry_run=True, chat_id="123456")
        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=populated_sidecar_dir,
        )
        reply = daemon._execute_command("/analytics")
        assert "QUANTITATIVE ANALYTICS" in reply
        assert "BTCUSDT" in reply
        assert "1\\.9600" in reply

    def test_enhanced_pnl_command(self, populated_sidecar_dir: Path) -> None:
        """Verify /pnl command displays per-asset breakdown."""
        cfg = TelegramConfig(dry_run=True, chat_id="123456")
        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=populated_sidecar_dir,
        )
        reply = daemon._execute_command("/pnl")
        assert "PNL & PERFORMANCE SUMMARY" in reply
        assert "Per\\-Asset Realized PnL" in reply
        assert "BTCUSDT" in reply

    def test_help_command_contains_analytics(self, populated_sidecar_dir: Path) -> None:
        """Verify /help includes /analytics."""
        cfg = TelegramConfig(dry_run=True, chat_id="123456")
        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=populated_sidecar_dir,
        )
        reply = daemon._execute_command("/help")
        assert "/analytics" in reply
        assert "/pnl" in reply
        assert "/status" in reply

    def test_daily_report_worker_schedule_and_deduplication(
        self, populated_sidecar_dir: Path
    ) -> None:
        """Verify daily report fires once per calendar day and doesn't re-fire."""
        cfg = TelegramConfig(dry_run=True, chat_id="123456")
        now_hour = datetime.now(UTC).hour
        daemon = TelegramNotifierDaemon(
            config=cfg,
            storage_dir=populated_sidecar_dir,
            daily_report_utc_hour=now_hour,
        )

        triggered = daemon.poll_daily_performance_report()
        assert triggered is True
        assert daemon.checkpoint.last_daily_report_date != ""

        triggered_again = daemon.poll_daily_performance_report()
        assert triggered_again is False
