"""Unit tests for Phase 275: Unified End-to-End Canary Rehearsal & Promotion Certification."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.canary_rehearsal import (  # noqa: E402
    DEFAULT_MAKER_FEE_RATE,
    STARTING_EQUITY_USDT,
    CanaryHeartbeatDaemon,
    CanaryHeartbeatDaemonConfig,
    CanaryMicroExecutionRunner,
    CanaryRehearsalConfig,
    CanaryRehearsalDaemon,
    CanaryRehearsalRunner,
    CircuitBreakerBlockError,
    JsonlCanaryOrderSink,
    LiquidityRole,
    MarginCapBreachError,
    MarketDepthTick,
    MicroCanaryFill,
    MicroCanaryOrder,
    MicroCanaryPosition,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    PositionSide,
    PositionStatus,
    PostOnlyViolationError,
    PreTradeRiskGateError,
    PromotionReadinessAssessment,
    SinglePositionInvariantError,
    SqliteCanaryRehearsalTelemetryStore,
    TimeInForce,
    verify_phase_275_hash_chain,
)
from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    CanaryCircuitBreakerRecoveryStateMachine,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    CircuitBreakerState,
)
from scripts.run_phase_275_canary_rehearsal import (  # noqa: E402
    build_arg_parser,
    execute_phase_275_runner,
    format_summary_table,
)
from scripts.run_phase_275_canary_rehearsal import (  # noqa: E402
    main as cli_main,
)


@pytest.fixture
def fresh_sm() -> CanaryCircuitBreakerRecoveryStateMachine:
    """Provide a fresh circuit breaker recovery state machine with K=5 hysteresis."""
    return CanaryCircuitBreakerRecoveryStateMachine(recovery_hysteresis_ticks=5)


@pytest.fixture
def fresh_runner_env(
    tmp_path: Path, fresh_sm: CanaryCircuitBreakerRecoveryStateMachine
) -> tuple[
    CanaryMicroExecutionRunner,
    SqliteCanaryRehearsalTelemetryStore,
    JsonlCanaryOrderSink,
]:
    """Provide an isolated runner environment with temporary SQLite store and JSONL sink."""
    db_path = tmp_path / "test-canary-rehearsal.sqlite3"
    jsonl_path = tmp_path / "test-canary-orders.jsonl"
    store = SqliteCanaryRehearsalTelemetryStore(db_path)
    sink = JsonlCanaryOrderSink(jsonl_path)
    runner = CanaryMicroExecutionRunner(
        circuit_breaker=fresh_sm,
        telemetry_store=store,
        jsonl_sink=sink,
        track_id="unit_test_track",
        starting_equity=STARTING_EQUITY_USDT,
    )
    return runner, store, sink


# =====================================================================
# 1. Models and Validation Tests
# =====================================================================


class TestPhase275ModelsAndValidation:
    """Validate DomainModels, decimal coercion, and invariant enforcement."""

    def test_order_model_coercion_and_properties(self) -> None:
        order = MicroCanaryOrder(
            order_id="ord-001",
            client_order_id="coid-001",
            track_id="track_1",
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.POST_ONLY,
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),
            notional_usdt=Decimal("4.80"),
            status=OrderStatus.OPEN,
            is_post_only=True,
            created_at_utc="2026-09-18T12:00:00Z",
            updated_at_utc="2026-09-18T12:00:00Z",
        )
        assert order.order_id == "ord-001"
        assert order.price == Decimal("60000.00")
        assert order.is_post_only is True
        assert order.side == OrderSide.BUY

    def test_fill_model_coercion_and_properties(self) -> None:
        fill = MicroCanaryFill(
            fill_id="fill-001",
            order_id="ord-001",
            client_order_id="coid-001",
            track_id="track_1",
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            liquidity_role=LiquidityRole.MAKER,
            fill_price=Decimal("60000.00"),
            fill_quantity=Decimal("0.00008"),
            notional_usdt=Decimal("4.80"),
            fee_usdt=Decimal("0.00096"),
            fee_rate=DEFAULT_MAKER_FEE_RATE,
            slippage_usdt=Decimal("0.00"),
            slippage_bps=Decimal("0.0"),
            realized_pnl_usdt=Decimal("0.00"),
            timestamp_utc="2026-09-18T12:00:01Z",
        )
        assert fill.liquidity_role == LiquidityRole.MAKER
        assert fill.fee_rate == Decimal("0.0002")
        assert fill.slippage_bps == Decimal("0.0")

    def test_position_model_coercion_and_brackets(self) -> None:
        pos = MicroCanaryPosition(
            position_id="pos-001",
            track_id="track_1",
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.0019"),
            entry_price=Decimal("2500.00"),
            current_price=Decimal("2525.00"),
            allocated_margin_usdt=Decimal("4.75"),
            unrealized_pnl_usdt=Decimal("0.0475"),
            status=PositionStatus.OPEN,
            opened_at_utc="2026-09-18T12:00:00Z",
            stop_loss_order_id="sl-001",
            take_profit_order_id="tp-001",
        )
        assert pos.symbol == "ETHUSDT"
        assert pos.unrealized_pnl_usdt == Decimal("0.0475")
        assert pos.stop_loss_order_id == "sl-001"

    def test_market_depth_tick_model(self) -> None:
        tick = MarketDepthTick(
            mark_id="mark-001",
            timestamp_utc="2026-09-18T12:00:00Z",
            track_id="track_1",
            symbol="SOLUSDT",
            bid_price=Decimal("149.95"),
            bid_quantity=Decimal("10.5"),
            ask_price=Decimal("150.05"),
            ask_quantity=Decimal("8.2"),
            mark_price=Decimal("150.00"),
            latency_ms=12.4,
        )
        assert tick.mark_price == Decimal("150.00")
        assert tick.symbol == "SOLUSDT"
        assert tick.latency_ms == 12.4

    def test_portfolio_snapshot_model(self) -> None:
        snap = PortfolioSnapshot(
            snapshot_id="snap-001",
            track_id="track_1",
            timestamp_utc="2026-09-18T12:00:00Z",
            starting_equity_usdt=Decimal("100.00"),
            cash_usdt=Decimal("95.20"),
            allocated_margin_usdt=Decimal("4.80"),
            unrealized_pnl_usdt=Decimal("0.00"),
            realized_pnl_usdt=Decimal("-0.00096"),
            total_equity_usdt=Decimal("99.99904"),
            reserve_buffer_pct=Decimal("0.952"),
            margin_utilization_pct=Decimal("0.048"),
            drift_usdt=Decimal("0"),
            zero_drift=True,
        )
        assert snap.zero_drift is True
        assert snap.starting_equity_usdt == Decimal("100.00")

    def test_promotion_assessment_model(self) -> None:
        assessment = PromotionReadinessAssessment(
            promotion_state="CERTIFIED_FOR_PRODUCTION_CANARY",
            promotion_authorized=True,
            decision_rationale="All 4 Phase 275 tracks certified with zero drift.",
            evaluated_at_utc="2026-09-18T12:00:00Z",
            all_criteria_passed=True,
            checks={"zero_balance_drift": True, "read_only_safety_compliant": True},
        )
        assert assessment.promotion_authorized is True
        assert assessment.checks["zero_balance_drift"] is True


# =====================================================================
# 2. Persistence Store & JSONL Sink Tests
# =====================================================================


class TestPhase275PersistenceAndStore:
    """Verify SQLite telemetry store schema, batch insertions, queries, and lock safety."""

    def test_store_initialization_and_pragmas(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test-init.sqlite3"
        store = SqliteCanaryRehearsalTelemetryStore(db_path)
        try:
            assert store.verify_unlocked()
            assert store.count_orders() == 0
            assert store.count_fills() == 0
            assert store.count_positions() == 0
            assert store.count_execution_marks() == 0
        finally:
            store.close()

    def test_record_and_query_order_and_fill(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test-query.sqlite3"
        store = SqliteCanaryRehearsalTelemetryStore(db_path)
        try:
            order = MicroCanaryOrder(
                order_id="ord-101",
                client_order_id="coid-101",
                track_id="track_1",
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.GTC,
                price=Decimal("60000.00"),
                quantity=Decimal("0.00008"),
                notional_usdt=Decimal("4.80"),
                status=OrderStatus.OPEN,
                created_at_utc="2026-09-18T12:00:00Z",
                updated_at_utc="2026-09-18T12:00:00Z",
            )
            store.record_order(order)
            assert store.count_orders() == 1

            retrieved = store.get_order("ord-101")
            assert retrieved is not None
            assert retrieved.order_id == "ord-101"
            assert retrieved.notional_usdt == Decimal("4.80")

            fill = MicroCanaryFill(
                fill_id="fill-101",
                order_id="ord-101",
                client_order_id="coid-101",
                track_id="track_1",
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                liquidity_role=LiquidityRole.MAKER,
                fill_price=Decimal("60000.00"),
                fill_quantity=Decimal("0.00008"),
                notional_usdt=Decimal("4.80"),
                fee_usdt=Decimal("0.00096"),
                fee_rate=Decimal("0.0002"),
                slippage_usdt=Decimal("0"),
                slippage_bps=Decimal("0"),
                realized_pnl_usdt=Decimal("0"),
                timestamp_utc="2026-09-18T12:00:01Z",
            )
            store.record_fill(fill)
            assert store.count_fills() == 1
        finally:
            store.close()

    def test_record_execution_marks_batch(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test-marks.sqlite3"
        store = SqliteCanaryRehearsalTelemetryStore(db_path)
        try:
            marks = [
                MarketDepthTick(
                    mark_id=f"mark-{i}",
                    timestamp_utc="2026-09-18T12:00:00Z",
                    track_id="track_1",
                    symbol="BTCUSDT",
                    bid_price=Decimal("59990.00"),
                    bid_quantity=Decimal("1.5"),
                    ask_price=Decimal("60010.00"),
                    ask_quantity=Decimal("2.0"),
                    mark_price=Decimal("60000.00"),
                    latency_ms=10.0 + i,
                )
                for i in range(5)
            ]
            store.record_execution_marks_batch(marks)
            assert store.count_execution_marks() == 5
        finally:
            store.close()

    def test_jsonl_sink_appends_and_flushes(self, tmp_path: Path) -> None:
        jsonl_path = tmp_path / "test.jsonl"
        with JsonlCanaryOrderSink(jsonl_path) as sink:
            sink.write_record("TEST_EVENT", {"symbol": "BTCUSDT", "value": 123})
            sink.flush()
        assert jsonl_path.is_file()
        content = jsonl_path.read_text(encoding="utf-8")
        assert "TEST_EVENT" in content
        assert "BTCUSDT" in content


# =====================================================================
# 3. Pre-Trade Risk Gates & Guardrails Tests
# =====================================================================


class TestPhase275PreTradeRiskGates:
    """Verify micro size limits, margin ceilings, reserve buffer, and invariants."""

    def test_reject_non_staged_asset(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        with pytest.raises(PreTradeRiskGateError, match="not a permitted canary staged asset"):
            sim.place_order(
                candidate_id="cand-dogeusdt-001",
                symbol="DOGEUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("100"),
                price=Decimal("0.10"),
            )

    def test_reject_order_exceeding_micro_ceiling(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        # 0.00009 * 60000.00 = 5.40 USDT > 5.00 USDT ceiling
        with pytest.raises(PreTradeRiskGateError, match="Micro-order size ceiling breached"):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00009"),
                price=Decimal("60000.00"),
            )

    def test_reject_single_position_invariant_violation(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        # 1. Open active position on BTCUSDT
        sim.execute_taker_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        assert "BTCUSDT" in sim.active_positions

        # 2. Attempt second order to add to position
        with pytest.raises(
            SinglePositionInvariantError, match="Single-position invariant breached"
        ):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00005"),
                price=Decimal("60000.00"),
            )

    def test_reject_per_asset_margin_cap(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.max_per_asset_margin_pct = Decimal("0.03")  # 3.00 USDT cap
        with pytest.raises(MarginCapBreachError, match="Per-asset margin ceiling breached"):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),  # 4.80 USDT > 3.00 USDT
                price=Decimal("60000.00"),
            )

    def test_reject_aggregate_margin_cap(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.max_aggregate_margin_pct = Decimal("0.04")  # 4.00 USDT aggregate cap
        with pytest.raises(MarginCapBreachError, match="Aggregate margin ceiling breached"):
            sim.place_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0019"),  # 4.75 USDT > 4.00 USDT
                price=Decimal("2500.00"),
            )

    def test_reject_reserve_buffer_breach(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.min_reserve_buffer_pct = Decimal("0.99")  # Requires >= 99.00 USDT cash
        with pytest.raises(MarginCapBreachError, match="Unencumbered cash reserve buffer breached"):
            sim.place_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.03"),  # 4.50 USDT breaches 99% reserve floor
                price=Decimal("150.00"),
            )

    def test_reject_post_only_spread_crossing(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.reference_bids["BTCUSDT"] = Decimal("59990.00")
        sim.reference_asks["BTCUSDT"] = Decimal("60010.00")

        # BUY post-only quote at 60015.00 >= ask (60010.00)
        with pytest.raises(PostOnlyViolationError, match="Post-only BUY order price"):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60015.00"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )

        # SELL post-only quote at 59980.00 <= bid (59990.00)
        with pytest.raises(PostOnlyViolationError, match="Post-only SELL order price"):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("59980.00"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )


# =====================================================================
# 4. Order Lifecycle, Brackets & Dynamic Mark Revaluation Tests
# =====================================================================


class TestPhase275OrderLifecycleAndDynamicMarkRevaluation:
    """Verify maker/taker matching, OCO cancellation, and real-time mark updates."""

    def test_maker_fill_and_bracket_oco_lifecycle(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env

        # 1. Place resting quote
        order = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("59990.00"),
            time_in_force=TimeInForce.POST_ONLY,
            is_post_only=True,
        )
        assert order.status == OrderStatus.OPEN

        # 2. Match maker fill -> position opened
        fill = sim.match_maker_fill(order.order_id, fill_price=Decimal("59990.00"))
        assert fill.liquidity_role == LiquidityRole.MAKER
        assert "BTCUSDT" in sim.active_positions
        pos = sim.active_positions["BTCUSDT"]
        assert pos.entry_price == Decimal("59990.00")

        # 3. Attach bracket orders
        tp_ord, sl_ord = sim.attach_bracket_orders(
            symbol="BTCUSDT",
            stop_price=Decimal("59390.00"),
            take_profit_price=Decimal("60590.00"),
        )
        assert tp_ord.status == OrderStatus.OPEN
        assert sl_ord.status == OrderStatus.OPEN

        # 4. Ingress mark price tick triggers Take-Profit
        tick = MarketDepthTick(
            mark_id="m-tp-trigger",
            timestamp_utc="2026-09-18T12:01:00Z",
            track_id="unit_test",
            symbol="BTCUSDT",
            bid_price=Decimal("60590.00"),
            bid_quantity=Decimal("1.0"),
            ask_price=Decimal("60610.00"),
            ask_quantity=Decimal("1.0"),
            mark_price=Decimal("60600.00"),
            latency_ms=15.0,
        )
        sim.on_market_tick(tick)

        # 5. Position closed, SL cancelled via OCO
        assert "BTCUSDT" not in sim.active_positions
        assert sim.orders[tp_ord.order_id].status == OrderStatus.FILLED
        assert sim.orders[sl_ord.order_id].status == OrderStatus.CANCELLED
        assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_dynamic_mark_revaluation_updates_unrealized_pnl(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env

        # Open Long ETHUSDT @ 2500.00
        sim.execute_taker_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            mark_price=Decimal("2500.00"),
        )
        pos = sim.active_positions["ETHUSDT"]

        # Ingress tick @ 2550.00
        tick = MarketDepthTick(
            mark_id="m-reval-1",
            timestamp_utc="2026-09-18T12:01:00Z",
            track_id="unit_test",
            symbol="ETHUSDT",
            bid_price=Decimal("2549.00"),
            bid_quantity=Decimal("5.0"),
            ask_price=Decimal("2551.00"),
            ask_quantity=Decimal("5.0"),
            mark_price=Decimal("2550.00"),
            latency_ms=18.0,
        )
        sim.on_market_tick(tick)

        assert pos.current_price == Decimal("2550.00")
        # Expected unrealized = (2550 - entry_price) * 0.0019
        expected_unrealized = (Decimal("2550.00") - pos.entry_price) * pos.quantity
        assert pos.unrealized_pnl_usdt == expected_unrealized
        assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 5. Circuit Breaker Coupling & Auto-Recovery Tests
# =====================================================================


class TestPhase275CircuitBreakerCoupling:
    """Verify soft-freeze quote cancellation, hard-abort liquidation, and K=5 recovery."""

    def test_soft_freeze_cancels_resting_quotes_and_blocks_entry(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env

        # Place quote
        quote = sim.place_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.03"),
            price=Decimal("149.00"),
            time_in_force=TimeInForce.POST_ONLY,
            is_post_only=True,
        )
        assert quote.status == OrderStatus.OPEN

        # Latency spike triggers soft freeze
        tr = sim.circuit_breaker.process_tick(rtt_ms=450.0, drift_ms=10.0)
        assert tr is not None
        assert tr.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
        sim.on_circuit_breaker_transition(tr)

        # Verify quote cancelled
        assert sim.orders[quote.order_id].status == OrderStatus.CANCELLED

        # Verify placement blocked
        with pytest.raises(CircuitBreakerBlockError):
            sim.place_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.03"),
                price=Decimal("149.00"),
            )

    def test_hard_abort_emergency_flattens_positions(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env

        # Establish open position
        sim.execute_taker_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            mark_price=Decimal("2500.00"),
        )
        assert "ETHUSDT" in sim.active_positions

        # Catastrophic anomaly triggers Hard-Abort
        tr = sim.circuit_breaker.process_tick(
            rtt_ms=50.0, drift_ms=4500.0, is_catastrophic=True, anomaly_reason="Catastrophic drift"
        )
        assert tr is not None
        assert tr.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
        sim.on_circuit_breaker_transition(tr)

        # Verify position flattened to cash
        assert "ETHUSDT" not in sim.active_positions
        assert sim.liquidations_count == 1
        assert len(sim.closed_positions) == 1
        assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_k5_hysteresis_auto_recovery(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env

        # Trigger soft freeze
        tr_freeze = sim.circuit_breaker.process_tick(rtt_ms=450.0, drift_ms=10.0)
        assert tr_freeze is not None
        sim.on_circuit_breaker_transition(tr_freeze)

        # Feed 4 healthy ticks -> remains in soft-freeze
        for _ in range(4):
            t = sim.circuit_breaker.process_tick(rtt_ms=25.0, drift_ms=5.0)
            assert t is None
            assert sim.circuit_breaker.is_soft_frozen()

        # 5th healthy tick triggers auto-recovery
        t_rec = sim.circuit_breaker.process_tick(rtt_ms=25.0, drift_ms=5.0)
        assert t_rec is not None
        assert t_rec.new_state == CircuitBreakerState.NORMAL
        sim.on_circuit_breaker_transition(t_rec)
        assert sim.circuit_breaker.current_state == CircuitBreakerState.NORMAL


# =====================================================================
# 6. Integrated Rehearsal Runner & Hash Chain Tests
# =====================================================================


class TestPhase275IntegratedRunnerAndHashChain:
    """Verify execution of all rehearsal tracks, reporting, and Merkle DAG verification."""

    def test_execute_all_tracks_and_verify_hash_chain(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="all")
        runner = CanaryRehearsalRunner(cfg)
        report = runner.execute_all_tracks()

        assert report.promotion_assessment.promotion_authorized is True
        assert report.promotion_assessment.promotion_state == "CERTIFIED_FOR_PRODUCTION_CANARY"
        assert len(report.tracks) == 4

        # Verify cryptographic Merkle DAG hash chain
        assert verify_phase_275_hash_chain(output_dir=tmp_path) is True

    def test_hash_chain_detects_corrupted_report(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="all")
        runner = CanaryRehearsalRunner(cfg)
        runner.execute_all_tracks()

        rep_path = tmp_path / "canary-live-readiness-report.json"
        data = json.loads(rep_path.read_text(encoding="utf-8"))
        data["staged_manifest_hash"] = "tampered_hash_value"
        rep_path.write_text(json.dumps(data), encoding="utf-8")

        # Hash chain verification must fail
        assert verify_phase_275_hash_chain(output_dir=tmp_path) is False

    def test_adverse_drift_blocks_promotion(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(
            output_dir=tmp_path,
            track="1",
            simulate_adverse_drift=True,
        )
        runner = CanaryRehearsalRunner(cfg)
        report = runner.execute_all_tracks()

        assert report.promotion_assessment.promotion_authorized is False
        assert report.promotion_assessment.promotion_state == "BLOCKED"
        assert report.compliance["zero_balance_drift"] is False


# =====================================================================
# 7. CLI Script Execution Tests
# =====================================================================


class TestPhase275CliExecution:
    """Verify CLI argument parsing, runner invocation, and formatted tables."""

    def test_build_arg_parser_defaults(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        assert args.track == "all"
        assert args.rehearsal_seconds == 30.0
        assert args.max_ticks == 50
        assert args.recovery_hysteresis_ticks == 5
        assert args.offline_replay is False

    def test_cli_runner_execute_single_track(self, tmp_path: Path) -> None:
        exit_code = execute_phase_275_runner(
            output_dir=tmp_path,
            track="1",
        )
        assert exit_code == 0
        assert (tmp_path / "canary-live-readiness-report.json").is_file()

    def test_cli_runner_verify_only_mode(self, tmp_path: Path) -> None:
        execute_phase_275_runner(output_dir=tmp_path, track="all")
        verify_exit = execute_phase_275_runner(output_dir=tmp_path, verify_only=True)
        assert verify_exit == 0

    def test_format_summary_table_renders(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="1")
        runner = CanaryRehearsalRunner(cfg)
        report = runner.execute_all_tracks()
        rendered = format_summary_table(report)
        assert "PHASE 275: CANARY REHEARSAL" in rendered
        assert "CERTIFIED_FOR_PRODUCTION_CANARY" in rendered

    def test_cli_main_invocation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        test_args = [
            "run_phase_275_canary_rehearsal.py",
            "--output-dir",
            str(tmp_path),
            "--track",
            "1",
        ]
        monkeypatch.setattr(sys, "argv", test_args)
        assert cli_main() == 0

    def test_cli_json_output_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = execute_phase_275_runner(
            output_dir=tmp_path,
            track="1",
            json_output=True,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["phase"] == "phase_275"
        assert data["promotion_assessment"]["promotion_authorized"] is True

    def test_cli_override_track(self, tmp_path: Path) -> None:
        exit_code = execute_phase_275_runner(
            output_dir=tmp_path,
            track="cli_override",
            force_freeze=True,
        )
        assert exit_code == 0


# =====================================================================
# 8. Edge Cases, Daemon & Fail-Closed Invariants
# =====================================================================


class TestPhase275EdgeCasesAndInvariants:
    """Validate boundary conditions, parameter errors, and daemon lifecycle."""

    def test_cancel_order_edge_cases(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        with pytest.raises(Exception, match="Order not found"):
            sim.cancel_order("non-existent-order-id")

        order = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("59900.00"),
            time_in_force=TimeInForce.POST_ONLY,
            is_post_only=True,
        )
        cancelled = sim.cancel_order(order.order_id)
        assert cancelled.status == OrderStatus.CANCELLED

        # Cancelling again returns the same cancelled order without error
        second_cxl = sim.cancel_order(order.order_id)
        assert second_cxl.status == OrderStatus.CANCELLED

    def test_bracket_price_boundary_validations(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        # Open LONG
        sim.execute_taker_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )

        # Long Take Profit <= entry_price must fail
        with pytest.raises(PreTradeRiskGateError, match="Long take-profit price"):
            sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("59000.00"),
                take_profit_price=Decimal("59999.00"),
            )

        # Long Stop Loss >= entry_price must fail
        with pytest.raises(PreTradeRiskGateError, match="Long stop-loss price"):
            sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("60100.00"),
                take_profit_price=Decimal("61000.00"),
            )

    def test_bracket_attachment_without_active_position_raises(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        with pytest.raises(Exception, match="No active open position"):
            sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("59000.00"),
                take_profit_price=Decimal("61000.00"),
            )

    def test_invalid_order_parameters_raise(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        with pytest.raises(
            PreTradeRiskGateError, match="price .* and quantity .* must be positive"
        ):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0"),
                price=Decimal("60000.00"),
            )

        with pytest.raises(PreTradeRiskGateError, match="candidate_id must be non-empty"):
            sim.place_order(
                candidate_id="",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("60000.00"),
            )

    def test_daemon_lifecycle_and_run(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="1")
        daemon = CanaryRehearsalDaemon(cfg)
        report = daemon.run()
        assert report.promotion_assessment.promotion_authorized is True
        assert (tmp_path / "canary-live-readiness-report.json").is_file()

    def test_hash_chain_detects_missing_file(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="1")
        runner = CanaryRehearsalRunner(cfg)
        runner.execute_all_tracks()

        # Delete paper summary
        (tmp_path / "paper-summary.json").unlink()
        assert verify_phase_275_hash_chain(output_dir=tmp_path) is False

    def test_store_double_entry_integrity_empty_requires_records(self, tmp_path: Path) -> None:
        store = SqliteCanaryRehearsalTelemetryStore(tmp_path / "empty.sqlite3")
        try:
            ok, drift = store.verify_double_entry_integrity(require_records=True)
            assert ok is False
            ok_empty, _ = store.verify_double_entry_integrity(require_records=False)
            assert ok_empty is True
        finally:
            store.close()

    def test_take_profit_attachment_allowed_when_profit_exceeds_entry_ceiling(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.execute_taker_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        tp_ord, sl_ord = sim.attach_bracket_orders(
            symbol="BTCUSDT",
            stop_price=Decimal("59000.00"),
            take_profit_price=Decimal("65000.00"),
        )
        assert tp_ord.status == OrderStatus.OPEN
        assert tp_ord.notional_usdt == Decimal("5.20")
        assert sl_ord.status == OrderStatus.OPEN

    def test_closing_order_allowed_when_cash_depleted(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.execute_taker_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00008"),
            mark_price=Decimal("60000.00"),
        )
        sim.cash = Decimal("0.0")

        with pytest.raises(
            PreTradeRiskGateError, match="Portfolio insolvency / negative balance protection"
        ):
            sim.place_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.0019"),
                price=Decimal("2500.00"),
            )

        close_order = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
        )
        assert close_order.status == OrderStatus.OPEN
        sim.match_maker_fill(close_order.order_id)
        assert "BTCUSDT" not in sim.active_positions
        assert sim.cash > Decimal("0.0")

    def test_reject_concurrent_resting_opening_orders_for_same_symbol(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        quote1 = sim.place_order(
            candidate_id="cand-solusdt-rgb-001",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.03"),
            price=Decimal("148.00"),
            time_in_force=TimeInForce.POST_ONLY,
            is_post_only=True,
        )
        assert quote1.status == OrderStatus.OPEN

        with pytest.raises(
            SinglePositionInvariantError, match="active resting entry order already open"
        ):
            sim.place_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.03"),
                price=Decimal("148.50"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )

    def test_reject_fill_quantity_exceeding_position_quantity(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        sim.execute_taker_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            mark_price=Decimal("2500.00"),
        )
        close_ord = sim.place_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0019"),
            price=Decimal("2550.00"),
        )
        # 1. Fill quantity exceeding order quantity rejected
        with pytest.raises(DomainViolation, match="exceeds remaining order quantity"):
            sim.match_maker_fill(close_ord.order_id, fill_quantity=Decimal("0.0050"))

        # 2. Simulate position partially reduced, so order quantity > position quantity
        sim.active_positions["ETHUSDT"].quantity = Decimal("0.0010")
        with pytest.raises(DomainViolation, match="exceeds active position quantity"):
            sim.match_maker_fill(close_ord.order_id, fill_quantity=Decimal("0.0015"))

    def test_circuit_breaker_hard_abort_records_liquidated_snapshot(
        self,
        fresh_runner_env: tuple[
            CanaryMicroExecutionRunner, SqliteCanaryRehearsalTelemetryStore, Any
        ],
    ) -> None:
        sim, store, _ = fresh_runner_env
        sim.execute_taker_order(
            candidate_id="cand-ethusdt-dcb-003",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.0019"),
            mark_price=Decimal("2500.00"),
        )
        tr = sim.circuit_breaker.process_tick(
            rtt_ms=50.0,
            drift_ms=4500.0,
            is_catastrophic=True,
            anomaly_reason="Catastrophic drift",
        )
        assert tr is not None
        sim.on_circuit_breaker_transition(tr)

        snapshots = store.get_snapshots("unit_test_track")
        assert len(snapshots) >= 2
        final_snap = snapshots[-1]
        assert final_snap.allocated_margin_usdt == Decimal("0")
        assert final_snap.zero_drift is True
        assert len(sim.active_positions) == 0

    def test_daemon_offline_replay_ingress_stream(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(
            output_dir=tmp_path,
            offline_replay=True,
            max_ticks=10,
            rehearsal_seconds=3.0,
        )
        daemon = CanaryRehearsalDaemon(cfg)
        ticks = asyncio.run(daemon.run_live_ingress_stream(duration_seconds=3.0, max_ticks=10))
        assert ticks == 10

    def test_cli_override_flags_force_abort_and_recover(self, tmp_path: Path) -> None:
        exit_code_abort = execute_phase_275_runner(
            output_dir=tmp_path / "abort",
            track="all",
            force_abort=True,
        )
        assert exit_code_abort == 0
        rep_abort = json.loads(
            (tmp_path / "abort" / "canary-live-readiness-report.json").read_text(encoding="utf-8")
        )
        assert rep_abort["tracks"][0]["status"] == "SUCCESS_CLI_OVERRIDE_ABORT"

        exit_code_rec = execute_phase_275_runner(
            output_dir=tmp_path / "recover",
            track="all",
            force_recover=True,
        )
        assert exit_code_rec == 0
        rep_rec = json.loads(
            (tmp_path / "recover" / "canary-live-readiness-report.json").read_text(encoding="utf-8")
        )
        assert rep_rec["tracks"][0]["status"] == "SUCCESS_CLI_OVERRIDE_RECOVER"

    def test_hash_chain_detects_tampered_paper_summary_safety_invariants(
        self, tmp_path: Path
    ) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="1")
        runner = CanaryRehearsalRunner(cfg)
        runner.execute_all_tracks()

        paper_path = tmp_path / "paper-summary.json"
        data = json.loads(paper_path.read_text(encoding="utf-8"))
        data["safety_invariants"]["execution_authority"] = True
        paper_path.write_text(json.dumps(data), encoding="utf-8")

        assert verify_phase_275_hash_chain(output_dir=tmp_path) is False

    def test_high_frequency_cancellation_and_checkpoint_concurrency(
        self,
        fresh_runner_env: tuple[
            CanaryMicroExecutionRunner, SqliteCanaryRehearsalTelemetryStore, Any
        ],
    ) -> None:
        sim, store, _ = fresh_runner_env
        errors: list[Exception] = []
        candidates = [
            ("BTCUSDT", "cand-btcusdt-dcb-002", Decimal("59000.00"), Decimal("0.00008")),
            ("ETHUSDT", "cand-ethusdt-dcb-003", Decimal("2400.00"), Decimal("0.0019")),
            ("SOLUSDT", "cand-solusdt-rgb-001", Decimal("140.00"), Decimal("0.03")),
        ]

        def worker(worker_id: int) -> None:
            sym, cand, base_px, qty = candidates[worker_id]
            try:
                for i in range(15):
                    order = sim.place_order(
                        candidate_id=cand,
                        symbol=sym,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=qty,
                        price=base_px + Decimal(str(i)) * Decimal("0.1"),
                        time_in_force=TimeInForce.POST_ONLY,
                        is_post_only=True,
                    )
                    sim.cancel_order(order.order_id)
            except Exception as e:
                errors.append(e)

        def checkpoint_worker() -> None:
            try:
                for _ in range(5):
                    store.checkpoint()
                    import time

                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        threads.append(threading.Thread(target=checkpoint_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent workers encountered errors: {errors}"
        assert store.count_orders() >= 45

    def test_canary_heartbeat_daemon_aliasing_and_config(self) -> None:
        cfg = CanaryHeartbeatDaemonConfig(daemon_seconds=5.0)
        daemon = CanaryHeartbeatDaemon(cfg)
        assert daemon.config.daemon_seconds == 5.0

    def test_reject_concurrent_excess_closing_orders_for_same_symbol(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        # Open LONG position: 0.00008 BTC
        order = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            time_in_force=TimeInForce.GTC,
        )
        sim.match_maker_fill(order.order_id)
        assert sim.active_positions["BTCUSDT"].quantity == Decimal("0.00008")

        # First resting closing order: 0.00005 BTC (allowed, 0.00005 <= 0.00008)
        close_1 = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60500.00"),
            time_in_force=TimeInForce.GTC,
        )
        assert close_1.status == OrderStatus.OPEN

        # Second resting closing order: 0.00005 BTC
        # (0.00005 + 0.00005 = 0.00010 > 0.00008) -> Must Reject!
        with pytest.raises(PreTradeRiskGateError, match="exceeds active position quantity"):
            sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00005"),
                price=Decimal("60600.00"),
                time_in_force=TimeInForce.GTC,
            )

    def test_partial_fill_synchronizes_bracket_order_quantities(
        self, fresh_runner_env: tuple[CanaryMicroExecutionRunner, Any, Any]
    ) -> None:
        sim, _, _ = fresh_runner_env
        # Open LONG position: 0.00008 BTC
        order = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            time_in_force=TimeInForce.GTC,
        )
        sim.match_maker_fill(order.order_id)
        tp_ord, sl_ord = sim.attach_bracket_orders(
            symbol="BTCUSDT",
            stop_price=Decimal("59000.00"),
            take_profit_price=Decimal("61000.00"),
        )
        assert tp_ord.quantity == Decimal("0.00008")
        assert sl_ord.quantity == Decimal("0.00008")

        # Partial manual closing fill of 0.00004
        partial_close_ord = sim.place_order(
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00004"),
            price=Decimal("60200.00"),
            time_in_force=TimeInForce.GTC,
        )
        sim.match_maker_fill(partial_close_ord.order_id)
        assert sim.active_positions["BTCUSDT"].quantity == Decimal("0.00004")

        # Verify attached brackets were synchronized to remaining 0.00004
        assert sim.orders[tp_ord.order_id].quantity == Decimal("0.00004")
        assert sim.orders[sl_ord.order_id].quantity == Decimal("0.00004")

        # Now simulate TP fill on remaining quantity -> must succeed cleanly without DomainViolation
        fill = sim.match_maker_fill(tp_ord.order_id)
        assert fill.fill_quantity == Decimal("0.00004")
        assert "BTCUSDT" not in sim.active_positions
        assert sim.orders[sl_ord.order_id].status == OrderStatus.CANCELLED

    def test_paper_summary_double_entry_balance_equation_and_drift(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="all")
        runner = CanaryRehearsalRunner(cfg)
        runner.execute_all_tracks()

        paper_path = tmp_path / "paper-summary.json"
        data = json.loads(paper_path.read_text(encoding="utf-8"))

        starting = Decimal(str(data["starting_capital_usdt"]))
        final_cash = Decimal(str(data["final_cash_usdt"]))
        realized_pnl = Decimal(str(data["realized_pnl_usdt"]))
        drift = Decimal(str(data["drift_usdt"]))

        # Exact mathematical balance reconciliation
        balance_discrepancy = abs(final_cash - (starting + realized_pnl))
        assert balance_discrepancy < DOUBLE_ENTRY_MAX_DRIFT
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        assert data["zero_balance_drift"] is True
        assert verify_phase_275_hash_chain(output_dir=tmp_path) is True

    def test_hash_chain_detects_paper_summary_balance_discrepancy(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path, track="all")
        runner = CanaryRehearsalRunner(cfg)
        runner.execute_all_tracks()

        paper_path = tmp_path / "paper-summary.json"
        data = json.loads(paper_path.read_text(encoding="utf-8"))
        # Inject subtle 0.01 USDT discrepancy
        data["final_cash_usdt"] = str(Decimal(str(data["final_cash_usdt"])) + Decimal("0.01"))
        paper_path.write_text(json.dumps(data), encoding="utf-8")

        # Hash chain verification must detect and reject discrepancy
        assert verify_phase_275_hash_chain(output_dir=tmp_path) is False

    def test_market_depth_tick_rejects_inverted_spread_or_negative_latency(
        self,
    ) -> None:
        # Inverted spread: ask < bid
        with pytest.raises((ValidationError, DomainViolation), match="Inverted order book spread"):
            MarketDepthTick(
                mark_id="mark-inv",
                timestamp_utc="2026-09-18T12:00:00Z",
                track_id="t1",
                symbol="BTCUSDT",
                bid_price=Decimal("60100.00"),
                bid_quantity=Decimal("1.0"),
                ask_price=Decimal("60000.00"),  # ask < bid!
                ask_quantity=Decimal("1.0"),
                mark_price=Decimal("60050.00"),
                latency_ms=10.0,
            )

        # Negative latency
        with pytest.raises(
            (ValidationError, DomainViolation), match="Invalid market depth latency"
        ):
            MarketDepthTick(
                mark_id="mark-neg-lat",
                timestamp_utc="2026-09-18T12:00:00Z",
                track_id="t1",
                symbol="BTCUSDT",
                bid_price=Decimal("60000.00"),
                bid_quantity=Decimal("1.0"),
                ask_price=Decimal("60100.00"),
                ask_quantity=Decimal("1.0"),
                mark_price=Decimal("60050.00"),
                latency_ms=-5.0,
            )

    def test_cli_override_precedence_over_explicit_track(self, tmp_path: Path) -> None:
        # Pass --track 1 along with --force-abort; override must take precedence!
        exit_code = execute_phase_275_runner(
            output_dir=tmp_path,
            track="1",
            force_abort=True,
        )
        assert exit_code == 0
        rep_path = tmp_path / "canary-live-readiness-report.json"
        rep_data = json.loads(rep_path.read_text(encoding="utf-8"))
        assert "cli_override" in rep_data["tracks_executed"]

    def test_cli_stream_ingress_mode_offline(self, tmp_path: Path) -> None:
        # Execute stream ingress mode via CLI runner
        exit_code = execute_phase_275_runner(
            output_dir=tmp_path,
            stream_ingress=True,
            offline_replay=True,
            max_ticks=6,
            rehearsal_seconds=5.0,
        )
        assert exit_code == 0
        db_path = tmp_path / "canary-rehearsal-telemetry.sqlite3"
        store = SqliteCanaryRehearsalTelemetryStore(db_path)
        try:
            assert store.count_execution_marks() >= 6
        finally:
            store.close()

    def test_daemon_create_heartbeat_daemon_coupling(self, tmp_path: Path) -> None:
        cfg = CanaryRehearsalConfig(output_dir=tmp_path)
        daemon = CanaryRehearsalDaemon(cfg)
        hb = daemon.create_heartbeat_daemon()
        assert hb is not None
        assert hb.config.output_dir == tmp_path
