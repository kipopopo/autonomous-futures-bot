"""Autonomous Futures Bot - Phase 310 Unit Tests: Closed-Loop Autopsy Feedback.

Verifies:
- StrategyAutopsyEngine decomposition (timing error, adverse selection, realized edge)
- Dynamic candidate health tier classification (ELITE, HEALTHY, DEGRADED)
- Fail-closed daily drawdown pause on breaching the 3.00 USDT ceiling
- Persistence of autopsy records and candidate health in SQLite telemetry DB
- Event logging into canary-production-events.jsonl
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from autonomous_futures.execution.self_driving import (
    OrderSide,
    OrderStatus,
    SelfDrivingOrder,
    SelfDrivingState,
    build_default_self_driving_engine,
)
from autonomous_futures.feed.auto_evolution import (
    AutopsyAttributionCause,
    CandidateHealthTier,
    ContinuousSelfLearningDaemon,
    StrategyAutopsyEngine,
    TradeAutopsyRecord,
)


class TestStrategyAutopsyDecomposition:
    """Verifies quantitative decomposition of trade outcomes into alpha and friction."""

    def test_profitable_trade_autopsy_decomposition(self) -> None:
        engine = StrategyAutopsyEngine()
        autopsy = engine.deconstruct_trade(
            trade_id="trd-sol-001",
            candidate_id="cand-sol-scalper",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=170.0,
            exit_price=175.0,
            fill_qty=0.02,
            optimal_price=170.0,
            hawkes_intensity=0.15,
            adverse_delta_pct=0.0002,
            timestamp_ms=1700000000000,
        )

        assert isinstance(autopsy, TradeAutopsyRecord)
        assert autopsy.trade_id == "trd-sol-001"
        assert autopsy.symbol == "SOLUSDT"
        assert autopsy.gross_pnl_usdt > 0.0
        assert autopsy.net_pnl_usdt > 0.0
        assert autopsy.cause == AutopsyAttributionCause.ORGANIC_ALPHA

    def test_losing_trade_autopsy_decomposition(self) -> None:
        engine = StrategyAutopsyEngine()
        autopsy = engine.deconstruct_trade(
            trade_id="trd-sol-002",
            candidate_id="cand-sol-scalper",
            symbol="SOLUSDT",
            side="BUY",
            entry_price=175.0,
            exit_price=168.0,
            fill_qty=0.02,
            optimal_price=175.0,
            hawkes_intensity=0.85,
            adverse_delta_pct=0.025,
            timestamp_ms=1700000000000,
        )

        assert isinstance(autopsy, TradeAutopsyRecord)
        assert autopsy.net_pnl_usdt < 0.0
        assert autopsy.adverse_selection_bps > 0.0


class TestCandidateHealthEvaluation:
    """Verifies continuous self-learning daemon health classification."""

    def test_health_tier_elite_on_high_performance(self) -> None:
        daemon = ContinuousSelfLearningDaemon(min_sample_size=3)
        autopsies: list[TradeAutopsyRecord] = []
        for i in range(5):
            autopsies.append(
                TradeAutopsyRecord(
                    trade_id=f"trd-win-{i}",
                    candidate_id="cand-sol",
                    symbol="SOLUSDT",
                    side="BUY",
                    entry_price=170.0,
                    exit_price=175.0,
                    fill_qty=0.02,
                    entry_timing_error_bps=1.0,
                    hawkes_slip_drag_bps=0.5,
                    adverse_selection_bps=0.2,
                    realized_edge_bps=280.0,
                    gross_pnl_usdt=0.10,
                    fee_cost_usdt=0.001,
                    net_pnl_usdt=0.099,
                    cause=AutopsyAttributionCause.ORGANIC_ALPHA,
                    timestamp_ms=1700000000000 + i * 1000,
                )
            )

        eval_res = daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies)
        assert eval_res.tier in (CandidateHealthTier.ELITE, CandidateHealthTier.HEALTHY)
        assert eval_res.win_rate_pct >= 80.0

    def test_health_tier_degraded_on_persistent_drawdown(self) -> None:
        daemon = ContinuousSelfLearningDaemon(min_sample_size=3)
        autopsies: list[TradeAutopsyRecord] = []
        for i in range(5):
            autopsies.append(
                TradeAutopsyRecord(
                    trade_id=f"trd-loss-{i}",
                    candidate_id="cand-sol",
                    symbol="SOLUSDT",
                    side="BUY",
                    entry_price=175.0,
                    exit_price=165.0,
                    fill_qty=0.02,
                    entry_timing_error_bps=20.0,
                    hawkes_slip_drag_bps=15.0,
                    adverse_selection_bps=45.0,
                    realized_edge_bps=-500.0,
                    gross_pnl_usdt=-0.20,
                    fee_cost_usdt=0.001,
                    net_pnl_usdt=-0.201,
                    cause=AutopsyAttributionCause.SPREAD_CROSS,
                    timestamp_ms=1700000000000 + i * 1000,
                )
            )

        eval_res = daemon.evaluate_candidate("cand-sol", "SOLUSDT", autopsies)
        assert eval_res.tier == CandidateHealthTier.DEGRADED
        assert eval_res.win_rate_pct == 0.0


class TestDailyDrawdownCircuitBreaker:
    """Verifies the 3.00 USDT daily drawdown circuit breaker fail-closed shutdown."""

    def test_daily_drawdown_ceiling_breach_halts_trading(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

        # Activate engine
        engine.state = SelfDrivingState.MICRO_CAPITAL_ACTIVE

        # Simulate losing trades accumulating to 3.05 USDT loss
        engine.intra_day_loss_usdt = Decimal("3.05")

        # Attempt to process a tick with buy signal
        order = engine.process_microstructure_tick(
            symbol="SOLUSDT",
            price=Decimal("180.00"),
            hawkes_spectral_radius=0.15,
            heartbeat_age_ms=50.0,
            ensemble_signal="LONG",
            ts_ms=1700000000000,
        )

        # Order must be blocked fail-closed and engine transitioned to CIRCUIT_FLATTENED
        assert order is None
        assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
        assert engine.interlock_blocks_count >= 1

    def test_autopsy_and_health_db_persistence(self, tmp_path: Path) -> None:
        engine = build_default_self_driving_engine(
            starting_capital_usdt=Decimal("100.00"),
            storage_dir=tmp_path,
        )
        now_ms = 1700000000000

        # Simulate position open and close to trigger autopsy
        order_open = SelfDrivingOrder(
            order_id="ord-open-01",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type="LIMIT",
            price=Decimal("170.00"),
            quantity=Decimal("0.02"),
            notional_usdt=Decimal("3.40"),
            status=OrderStatus.PENDING,
            timestamp_ms=now_ms,
            client_order_id="canary-p310-sol-1700000000000-000001",
            is_maker=True,
        )
        engine._execute_fill(order_open, Decimal("170.00"), now_ms)

        order_close = SelfDrivingOrder(
            order_id="ord-close-01",
            symbol="SOLUSDT",
            side=OrderSide.SELL,
            order_type="LIMIT",
            price=Decimal("174.00"),
            quantity=Decimal("0.02"),
            notional_usdt=Decimal("3.48"),
            status=OrderStatus.PENDING,
            timestamp_ms=now_ms + 900000,
            client_order_id="canary-p310-sol-1700000900000-000002",
            is_maker=True,
        )
        engine._execute_fill(order_close, Decimal("174.00"), now_ms + 900000)

        # Verify DB records
        db_path = tmp_path / "canary-production-telemetry.sqlite3"
        assert db_path.is_file()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM trade_autopsies")
        count = cur.fetchone()[0]
        assert count >= 1

        cur.execute("SELECT symbol, net_pnl_usdt FROM trade_autopsies WHERE symbol='SOLUSDT'")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "SOLUSDT"
        assert row[1] > 0.0
        conn.close()

        # Verify events jsonl
        events_path = tmp_path / "canary-production-events.jsonl"
        assert events_path.is_file()
        content = events_path.read_text(encoding="utf-8")
        assert "TRADE_AUTOPSY" in content
