"""Unit tests for Phase 274: Unified Canary Micro-Execution Rehearsal Runner & Risk Gates."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    CanaryCircuitBreakerRecoveryStateMachine,
)
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    CircuitBreakerState,
)
from autonomous_futures.feed.micro_execution_drill import (  # noqa: E402
    DEFAULT_MAKER_FEE_RATE,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_TAKER_FEE_RATE,
    STARTING_EQUITY_USDT,
    CanaryMicroExecutionDrillConfig,
    CanaryMicroExecutionDrillRunner,
    CircuitBreakerBlockError,
    JsonlOrderSink,
    LiquidityRole,
    MarginCapBreachError,
    MicroCanaryFill,
    MicroCanaryOrder,
    MicroCanaryPosition,
    MicroOrderRoutingSimulator,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    PositionSide,
    PositionStatus,
    PostOnlyViolationError,
    PreTradeRiskGateError,
    SinglePositionInvariantError,
    SqliteCanaryExecutionTelemetryStore,
    TimeInForce,
    verify_phase_274_hash_chain,
)
from scripts.run_phase_274_micro_execution_drill import (  # noqa: E402
    build_arg_parser,
    execute_phase_274_runner,
)
from scripts.run_phase_274_micro_execution_drill import (  # noqa: E402
    main as cli_main,
)


@pytest.fixture
def clean_sm() -> CanaryCircuitBreakerRecoveryStateMachine:
    """Provide a fresh recovery state machine."""
    return CanaryCircuitBreakerRecoveryStateMachine(recovery_hysteresis_ticks=5)


@pytest.fixture
def clean_sim(
    tmp_path: Path, clean_sm: CanaryCircuitBreakerRecoveryStateMachine
) -> tuple[MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink]:
    """Provide an isolated simulator with clean SQLite store and JSONL sink."""
    db_path = tmp_path / "test-telemetry.sqlite3"
    jsonl_path = tmp_path / "test-orders.jsonl"
    store = SqliteCanaryExecutionTelemetryStore(db_path)
    sink = JsonlOrderSink(jsonl_path)
    sim = MicroOrderRoutingSimulator(
        circuit_breaker=clean_sm,
        telemetry_store=store,
        jsonl_sink=sink,
        track_id="test_track",
        starting_equity=STARTING_EQUITY_USDT,
    )
    return sim, store, sink


class TestPhase274ModelsAndValidation:
    """Validate DomainModels, decimal coercion, and invariant enforcement."""

    def test_order_model_validates_and_coerces(self) -> None:
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
            created_at_utc="2026-09-18T14:00:00+00:00",
            updated_at_utc="2026-09-18T14:00:00+00:00",
        )
        assert order.price == Decimal("60000.00")
        assert order.quantity == Decimal("0.00008")
        assert order.notional_usdt == Decimal("4.80")
        assert order.status == OrderStatus.OPEN

    def test_fill_model_validates_and_coerces(self) -> None:
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
            fee_rate=Decimal("0.0002"),
            slippage_usdt=Decimal("0"),
            slippage_bps=Decimal("0"),
            realized_pnl_usdt=Decimal("0"),
            timestamp_utc="2026-09-18T14:00:00+00:00",
        )
        assert fill.liquidity_role == LiquidityRole.MAKER
        assert fill.fee_usdt == Decimal("0.00096")

    def test_position_model_validates_and_coerces(self) -> None:
        pos = MicroCanaryPosition(
            position_id="pos-001",
            track_id="track_1",
            candidate_id="cand-btcusdt-dcb-002",
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("0.00008"),
            entry_price=Decimal("60000.00"),
            current_price=Decimal("60500.00"),
            allocated_margin_usdt=Decimal("4.80"),
            opened_at_utc="2026-09-18T14:00:00+00:00",
        )
        assert pos.status == PositionStatus.OPEN
        assert pos.allocated_margin_usdt == Decimal("4.80")

    def test_portfolio_snapshot_model_validates(self) -> None:
        snap = PortfolioSnapshot(
            snapshot_id="snap-001",
            track_id="track_1",
            timestamp_utc="2026-09-18T14:00:00+00:00",
            starting_equity_usdt=Decimal("100.00"),
            cash_usdt=Decimal("95.20"),
            allocated_margin_usdt=Decimal("4.80"),
            unrealized_pnl_usdt=Decimal("0"),
            realized_pnl_usdt=Decimal("0"),
            total_equity_usdt=Decimal("100.00"),
            reserve_buffer_pct=Decimal("0.952"),
            margin_utilization_pct=Decimal("0.048"),
            drift_usdt=Decimal("0"),
            zero_drift=True,
        )
        assert snap.zero_drift is True
        assert snap.drift_usdt == Decimal("0")


class TestPhase274PreTradeRiskGates:
    """Validate pre-trade risk boundary enforcement and error classes."""

    def test_micro_order_size_ceiling_passes_under_limit(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # 60,000 * 0.00008 = 4.80 USDT <= 5.00 USDT
            order = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("59950.00"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )
            assert order.status == OrderStatus.OPEN
        finally:
            sink.close()
            store.close()

    def test_micro_order_size_ceiling_rejects_breach(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # 60,000 * 0.0001 = 6.00 USDT > 5.00 USDT
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.0001"),
                    price=Decimal("60000.00"),
                )
            assert "Micro-order size ceiling breached" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_single_position_invariant_rejects_concurrent_open(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Open first position
            sim.execute_taker_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.0019"),
                mark_price=Decimal("2500.00"),
            )
            assert "ETHUSDT" in sim.active_positions

            # Attempt to open second position on same symbol
            with pytest.raises(SinglePositionInvariantError) as exc_info:
                sim.place_order(
                    candidate_id="cand-ethusdt-dcb-003",
                    symbol="ETHUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.001"),
                    price=Decimal("2480.00"),
                )
            assert "Single-position invariant breached" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_per_asset_margin_ceiling_rejects_breach(
        self,
        tmp_path: Path,
        clean_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        store = SqliteCanaryExecutionTelemetryStore(tmp_path / "per_asset.sqlite3")
        sink = JsonlOrderSink(tmp_path / "per_asset.jsonl")
        sim = MicroOrderRoutingSimulator(
            circuit_breaker=clean_sm,
            telemetry_store=store,
            jsonl_sink=sink,
            starting_equity=Decimal("100.00"),
            # Relax micro notional to isolate per-asset ceiling
            max_micro_notional=Decimal("30.00"),
        )
        try:
            # Try order with 24.00 USDT margin > 20.00 USDT (20% ceiling)
            with pytest.raises(MarginCapBreachError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.0004"),
                    price=Decimal("60000.00"),
                )
            assert "Per-asset margin ceiling breached" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_aggregate_margin_ceiling_rejects_breach(
        self,
        tmp_path: Path,
        clean_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        store = SqliteCanaryExecutionTelemetryStore(tmp_path / "agg.sqlite3")
        sink = JsonlOrderSink(tmp_path / "agg.jsonl")
        sim = MicroOrderRoutingSimulator(
            circuit_breaker=clean_sm,
            telemetry_store=store,
            jsonl_sink=sink,
            starting_equity=Decimal("100.00"),
            max_micro_notional=Decimal("70.00"),
            max_per_asset_margin_pct=Decimal("0.70"),
        )
        try:
            # Try order with 66.00 USDT > 60.00 USDT (60% ceiling)
            with pytest.raises(MarginCapBreachError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.0011"),
                    price=Decimal("60000.00"),
                )
            assert "Aggregate margin ceiling breached" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_unencumbered_reserve_buffer_rejects_breach(
        self,
        tmp_path: Path,
        clean_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        store = SqliteCanaryExecutionTelemetryStore(tmp_path / "buf.sqlite3")
        sink = JsonlOrderSink(tmp_path / "buf.jsonl")
        sim = MicroOrderRoutingSimulator(
            circuit_breaker=clean_sm,
            telemetry_store=store,
            jsonl_sink=sink,
            starting_equity=Decimal("100.00"),
            max_micro_notional=Decimal("70.00"),
            max_per_asset_margin_pct=Decimal("0.70"),
            max_aggregate_margin_pct=Decimal("0.70"),
        )
        try:
            # 66.00 USDT leaves 34.00 USDT reserve < 40.00 USDT (40% buffer)
            with pytest.raises(MarginCapBreachError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.0011"),
                    price=Decimal("60000.00"),
                )
            assert "Unencumbered reserve buffer floor breached" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_post_only_spread_cross_rejected(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Mark: 60,000.00. BUY at 60,100.00 crosses spread -> would execute as taker
            with pytest.raises(PostOnlyViolationError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.00008"),
                    price=Decimal("60100.00"),
                    time_in_force=TimeInForce.POST_ONLY,
                    is_post_only=True,
                )
            assert "Post-only quote placement rejected: BUY limit price" in str(exc_info.value)

            # SELL at 59,900.00 <= 60,000.00 crosses spread
            with pytest.raises(PostOnlyViolationError) as exc_info2:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=Decimal("0.00008"),
                    price=Decimal("59900.00"),
                    time_in_force=TimeInForce.POST_ONLY,
                    is_post_only=True,
                )
            assert "Post-only quote placement rejected: SELL limit price" in str(exc_info2.value)
        finally:
            sink.close()
            store.close()


class TestPhase274OrderExecutionAndMatching:
    """Validate maker/taker fill matching, slippage, fees, and bracket OCO logic."""

    def test_maker_fill_matching_fees_and_slippage(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            order = sim.place_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.03"),
                price=Decimal("149.50"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )
            fill = sim.match_maker_fill(order.order_id)
            assert fill.liquidity_role == LiquidityRole.MAKER
            assert fill.fee_rate == DEFAULT_MAKER_FEE_RATE
            assert fill.fee_usdt == Decimal("149.50") * Decimal("0.03") * DEFAULT_MAKER_FEE_RATE
            assert fill.slippage_usdt == Decimal("0")
            assert fill.slippage_bps == Decimal("0")
            assert sim.active_positions["SOLUSDT"].status == PositionStatus.OPEN
        finally:
            sink.close()
            store.close()

    def test_taker_fill_execution_fees_and_slippage(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Mark: 2,500.00. BUY with 2.0 bps slippage -> fill at 2,500.50
            ord_item, fill = sim.execute_taker_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.0019"),
                mark_price=Decimal("2500.00"),
            )
            assert fill.liquidity_role == LiquidityRole.TAKER
            assert fill.fill_price == Decimal("2500.00") * (Decimal("1") + Decimal("0.0002"))
            assert fill.slippage_bps == DEFAULT_SLIPPAGE_BPS
            assert fill.fee_rate == DEFAULT_TAKER_FEE_RATE
        finally:
            sink.close()
            store.close()

    def test_bracket_orders_and_oco_cancellation(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # 1. Entry order
            entry_ord = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("59950.00"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )
            sim.match_maker_fill(entry_ord.order_id)
            assert "BTCUSDT" in sim.active_positions

            # 2. Attach bracket
            tp_ord, sl_ord = sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("59400.00"),
                take_profit_price=Decimal("60600.00"),
            )
            assert tp_ord.status == OrderStatus.OPEN
            assert sl_ord.status == OrderStatus.OPEN

            # 3. Match TP fill -> closes position and cancels SL order (OCO)
            sim.match_maker_fill(tp_ord.order_id, fill_price=Decimal("60600.00"))
            assert "BTCUSDT" not in sim.active_positions
            assert sim.orders[sl_ord.order_id].status == OrderStatus.CANCELLED
            assert "Bracket sibling cancelled" in (
                sim.orders[sl_ord.order_id].rejection_reason or ""
            )
        finally:
            sink.close()
            store.close()


class TestPhase274CircuitBreakerCoupling:
    """Validate circuit breaker state coupling with order routing and execution."""

    def test_tier_1_soft_freeze_cancels_quotes_and_blocks_placement(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Resting quote in book
            quote = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("59900.00"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )
            assert quote.status == OrderStatus.OPEN

            # Trip to Tier 1 Soft-Freeze
            tr = sim.circuit_breaker.process_tick(rtt_ms=450.0, drift_ms=10.0)
            assert tr is not None
            assert tr.new_state == CircuitBreakerState.TIER_1_SOFT_FREEZE
            sim.on_circuit_breaker_transition(tr)

            # Resting quote cancelled immediately
            assert sim.orders[quote.order_id].status == OrderStatus.CANCELLED

            # New orders blocked
            with pytest.raises(CircuitBreakerBlockError):
                sim.place_order(
                    candidate_id="cand-ethusdt-dcb-003",
                    symbol="ETHUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("0.0019"),
                    price=Decimal("2500.00"),
                )
        finally:
            sink.close()
            store.close()

    def test_auto_recovery_resumes_execution(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Trip to soft freeze
            tr_freeze = sim.circuit_breaker.process_tick(rtt_ms=450.0, drift_ms=10.0)
            assert tr_freeze is not None
            sim.on_circuit_breaker_transition(tr_freeze)

            # Ingest 5 healthy ticks
            rec_tr: Any = None
            for _ in range(5):
                rec = sim.circuit_breaker.process_tick(rtt_ms=25.0, drift_ms=5.0)
                if rec:
                    rec_tr = rec
            assert rec_tr is not None
            assert rec_tr.new_state == CircuitBreakerState.NORMAL
            sim.on_circuit_breaker_transition(rec_tr)
            assert sim.circuit_breaker.is_normal()

            # Placement resumes
            ord_item = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.00008"),
                price=Decimal("59950.00"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=True,
            )
            assert ord_item.status == OrderStatus.OPEN
        finally:
            sink.close()
            store.close()

    def test_tier_2_hard_abort_emergency_flattening_and_halt(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Open position
            sim.execute_taker_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.03"),
                mark_price=Decimal("150.00"),
            )
            assert "SOLUSDT" in sim.active_positions

            # Trigger Tier 2 Hard-Abort
            tr_abort = sim.circuit_breaker.process_tick(
                rtt_ms=50.0,
                drift_ms=4500.0,
                is_catastrophic=True,
            )
            assert tr_abort is not None
            assert tr_abort.new_state == CircuitBreakerState.TIER_2_HARD_ABORT
            sim.on_circuit_breaker_transition(tr_abort)

            # Position emergency flattened
            assert "SOLUSDT" not in sim.active_positions
            assert sim.liquidations_count == 1
            assert sim.circuit_breaker.is_hard_aborted()

            # Permanent halt
            with pytest.raises(CircuitBreakerBlockError):
                sim.execute_taker_order(
                    candidate_id="cand-solusdt-rgb-001",
                    symbol="SOLUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("0.03"),
                    mark_price=Decimal("150.00"),
                )
        finally:
            sink.close()
            store.close()


class TestPhase274AccountingDrift:
    """Validate zero-drift double-entry balance integrity and adverse drift injection."""

    def test_nominal_zero_drift_integrity(
        self, clean_sim: tuple[MicroOrderRoutingSimulator, Any, Any]
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Round-trip trade on ETHUSDT
            sim.execute_taker_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.0019"),
                mark_price=Decimal("2500.00"),
            )
            sim.execute_taker_order(
                candidate_id="cand-ethusdt-dcb-003",
                symbol="ETHUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.0019"),
                mark_price=Decimal("2505.00"),
            )
            drift = sim.current_drift
            assert drift < DOUBLE_ENTRY_MAX_DRIFT
        finally:
            sink.close()
            store.close()

    def test_synthetic_adverse_drift_injection_detected(
        self, tmp_path: Path, clean_sm: CanaryCircuitBreakerRecoveryStateMachine
    ) -> None:
        store = SqliteCanaryExecutionTelemetryStore(tmp_path / "drift.sqlite3")
        sink = JsonlOrderSink(tmp_path / "drift.jsonl")
        sim = MicroOrderRoutingSimulator(
            circuit_breaker=clean_sm,
            telemetry_store=store,
            jsonl_sink=sink,
            simulate_adverse_drift=True,  # Injects 0.05 USDT drift
        )
        try:
            drift = sim.current_drift
            assert drift >= Decimal("0.05")
            assert drift > DOUBLE_ENTRY_MAX_DRIFT
        finally:
            sink.close()
            store.close()


class TestPhase274DrillTracksAndRunner:
    """Validate individual tracks, full runner execution, and hash chain verification."""

    def test_track_1_execution(self, tmp_path: Path) -> None:
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=tmp_path / "track1_test",
            target_track="track_1",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert summary.tracks_executed == ["track_1"]
        assert summary.compliance["all_criteria_passed"] is True

    def test_track_2_execution(self, tmp_path: Path) -> None:
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=tmp_path / "track2_test",
            target_track="track_2",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert summary.tracks_executed == ["track_2"]
        assert summary.compliance["all_criteria_passed"] is True

    def test_track_3_execution(self, tmp_path: Path) -> None:
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=tmp_path / "track3_test",
            target_track="track_3",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert summary.tracks_executed == ["track_3"]
        assert summary.compliance["all_criteria_passed"] is True

    def test_track_4_execution(self, tmp_path: Path) -> None:
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=tmp_path / "track4_test",
            target_track="track_4",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert summary.tracks_executed == ["track_4"]
        assert summary.compliance["all_criteria_passed"] is True

    def test_full_drill_runner_and_hash_chain(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "phase274_full"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="all",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        (
            summary,
            db_path,
            jsonl_path,
            rep_path,
            exec_sum_path,
            paper_sum_path,
        ) = runner.execute_drill()

        assert summary.compliance["all_criteria_passed"] is True
        assert len(summary.tracks_executed) == 4
        assert db_path.is_file()
        assert jsonl_path.is_file()
        assert rep_path.is_file()
        assert exec_sum_path.is_file()
        assert paper_sum_path.is_file()

        # Verify cryptographic hash chain
        assert verify_phase_274_hash_chain(output_dir=out_dir) is True

    def test_hash_chain_fails_on_tampered_report(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "tamper_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="all",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        runner.execute_drill()

        # Tamper with canary-orders.jsonl
        jsonl = out_dir / "canary-orders.jsonl"
        with open(jsonl, "a", encoding="utf-8", newline="\n") as f:
            f.write('{"tampered": true}\n')

        # Hash chain verification must detect tamper and return False
        assert verify_phase_274_hash_chain(output_dir=out_dir) is False

    def test_cli_override_force_freeze(self, tmp_path: Path) -> None:
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=tmp_path / "freeze_override",
            force_freeze=True,
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert summary.tracks_executed == ["cli_override"]
        assert summary.circuit_breaker_stats["final_state"] == "TIER_1_SOFT_FREEZE"

    def test_cli_override_force_abort(self, tmp_path: Path) -> None:
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=tmp_path / "abort_override",
            force_abort=True,
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()
        assert summary.tracks_executed == ["cli_override"]
        assert summary.circuit_breaker_stats["final_state"] == "TIER_2_HARD_ABORT"


class TestPhase274Cli:
    """Validate CLI argument parser, summary formatting, and CLI main entrypoint."""

    def test_build_arg_parser_options(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--track", "1", "--json", "--verify-hash-chain"])
        assert args.track == "1"
        assert args.json is True
        assert args.verify_hash_chain is True

    def test_execute_phase_274_runner_cli(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "cli_run"
        rc = execute_phase_274_runner(
            output_dir=out_dir,
            track="1",
            verify_hash_chain=False,
            json_output=False,
        )
        assert rc == 0

    def test_cli_main(self, tmp_path: Path) -> None:
        out_dir = str(tmp_path / "cli_main_run")
        rc = cli_main(["--output-dir", out_dir, "--track", "1"])
        assert rc == 0


class TestPhase274ReviewFixesAndInvariants:
    """Validate reviewer bugfixes: telemetry counters, reconciliation, and bracket lifecycle."""

    def test_circuit_breaker_telemetry_counters_in_summary(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "cb_stats_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="all",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, _ = runner.execute_drill()

        cb_stats = summary.circuit_breaker_stats
        assert cb_stats["total_ticks_processed"] >= 7
        assert cb_stats["soft_freezes_triggered"] == 1
        assert cb_stats["hard_aborts_triggered"] == 1
        assert cb_stats["auto_recoveries"] == 1
        assert cb_stats["total_transitions"] == 3
        assert cb_stats["terminal_state"] == "NORMAL"

    def test_paper_summary_cash_and_pnl_consistency(self, tmp_path: Path) -> None:
        import json

        out_dir = tmp_path / "reconciliation_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="all",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, _, paper_sum_path = runner.execute_drill()

        with open(paper_sum_path, encoding="utf-8") as f:
            paper_data = json.load(f)

        starting_cap = Decimal(paper_data["starting_capital_usdt"])
        final_cash = Decimal(paper_data["final_cash_usdt"])
        realized_pnl = Decimal(paper_data["realized_pnl_usdt"])
        drift = abs(Decimal(paper_data["drift_usdt"]))

        # Strict mathematical reconciliation: Final Cash == Starting Capital + Realized PnL
        assert final_cash == starting_cap + realized_pnl
        assert drift < DOUBLE_ENTRY_MAX_DRIFT
        assert paper_data["zero_balance_drift"] is True
        assert Decimal(summary.portfolio_accounting["final_cash_usdt"]) == final_cash

    def test_post_only_flag_normalization(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        sim, store, sink = clean_sim
        try:
            # Place order with time_in_force=POST_ONLY and is_post_only=False
            order = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("59000.00"),
                quantity=Decimal("0.00008"),
                time_in_force=TimeInForce.POST_ONLY,
                is_post_only=False,
            )
            assert order.is_post_only is True

            # Verify persisted order record in SQLite
            stored = store.get_order(order.order_id)
            assert stored is not None
            assert stored.is_post_only is True
        finally:
            sink.close()
            store.close()

    def test_partial_fill_and_position_increase_lifecycle(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        sim, store, sink = clean_sim
        try:
            order = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("60000.00"),
                quantity=Decimal("0.00008"),
                time_in_force=TimeInForce.GTC,
            )
            # 1. Partial fill: 0.00004 of 0.00008
            fill1 = sim.match_maker_fill(
                order.order_id, fill_price=Decimal("60000.00"), fill_quantity=Decimal("0.00004")
            )
            assert fill1.fill_quantity == Decimal("0.00004")
            assert order.status == OrderStatus.PARTIALLY_FILLED
            assert order.quantity == Decimal("0.00004")  # Remaining unfilled quantity

            pos = sim.active_positions.get("BTCUSDT")
            assert pos is not None
            assert pos.status == PositionStatus.OPEN
            assert pos.quantity == Decimal("0.00004")

            # 2. Second partial fill to complete the remaining quantity
            fill2 = sim.match_maker_fill(
                order.order_id, fill_price=Decimal("60000.00"), fill_quantity=Decimal("0.00004")
            )
            assert fill2.fill_quantity == Decimal("0.00004")
            assert sim.orders[order.order_id].status == OrderStatus.FILLED
            assert pos.quantity == Decimal("0.00008")

            # 3. Double-entry drift must remain zero
            assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT
        finally:
            sink.close()
            store.close()

    def test_closing_position_cancels_attached_brackets(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        sim, store, sink = clean_sim
        try:
            parent_order = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("60000.00"),
                quantity=Decimal("0.00008"),
                time_in_force=TimeInForce.GTC,
            )
            sim.match_maker_fill(parent_order.order_id, fill_price=Decimal("60000.00"))

            # Attach TP and SL brackets
            tp_order, sl_order = sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("59000.00"),
                take_profit_price=Decimal("61000.00"),
            )
            assert tp_order.status == OrderStatus.OPEN
            assert sl_order.status == OrderStatus.OPEN

            # Close position via market taker order (unlinked exit)
            exit_order, exit_fill = sim.execute_taker_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00008"),
                mark_price=Decimal("60500.00"),
            )
            assert exit_fill.fill_quantity == Decimal("0.00008")
            assert sim.active_positions.get("BTCUSDT") is None
            assert len(sim.closed_positions) == 1
            assert sim.closed_positions[0].status == PositionStatus.CLOSED

            # Both attached brackets must be cancelled to prevent orphaned orders
            assert sim.orders[tp_order.order_id].status == OrderStatus.CANCELLED
            assert sim.orders[sl_order.order_id].status == OrderStatus.CANCELLED
            tp_stored = store.get_order(tp_order.order_id)
            sl_stored = store.get_order(sl_order.order_id)
            assert tp_stored is not None and tp_stored.status == OrderStatus.CANCELLED
            assert sl_stored is not None and sl_stored.status == OrderStatus.CANCELLED
        finally:
            sink.close()
            store.close()

    def test_risk_guardrails_global_extremums(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "extremum_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="all",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, _, _, _, exec_sum_path, _ = runner.execute_drill()

        import json

        with open(exec_sum_path, encoding="utf-8") as f:
            data = json.load(f)

        guardrails = data["risk_guardrails"]
        max_util = float(guardrails["max_observed_margin_utilization"].rstrip("%"))
        min_buf = float(guardrails["min_observed_reserve_buffer"].rstrip("%"))

        # Verify max_util matches peak across all tracks
        track_utils = [
            float(t["max_observed_margin_utilization"].rstrip("%"))
            for t in summary.tracks_summary.values()
        ]
        track_bufs = [
            float(t["min_observed_reserve_buffer"].rstrip("%"))
            for t in summary.tracks_summary.values()
        ]
        assert max_util == pytest.approx(max(track_utils), abs=0.01)
        assert min_buf == pytest.approx(min(track_bufs), abs=0.01)


class TestPhase274ReviewRound2Fixes:
    """Validate Review Round 2 bugfixes and robustness enhancements."""

    def test_track_4_rejected_orders_count_reconciliation(self, tmp_path: Path) -> None:
        """Verify Track 4 reports 6 rejected orders and matches SQLite exactly."""
        out_dir = tmp_path / "track4_rej_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="all",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, db_path, _, _, _, _ = runner.execute_drill()

        # Track 4 must report 6 rejected orders
        assert summary.tracks_summary["track_4"]["orders_rejected"] == 6

        # Overall summary must report 8 rejected orders
        assert summary.order_stats["total_orders_rejected"] == 8

        # Query SQLite to verify database row count matches
        store = SqliteCanaryExecutionTelemetryStore(db_path)
        try:
            cur = store._conn.execute("SELECT COUNT(*) FROM orders WHERE status = ?", ("REJECTED",))
            assert cur.fetchone()[0] == 8
        finally:
            store.close()

    def test_closing_order_quantity_exceeding_position_rejected(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify closing order quantity cannot exceed active position quantity."""
        sim, store, sink = clean_sim
        try:
            # Open position: BUY 0.00004 BTC (notional = ~2.40 USDT)
            order = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("59950.00"),
                quantity=Decimal("0.00004"),
                time_in_force=TimeInForce.GTC,
            )
            sim.match_maker_fill(order.order_id, fill_price=Decimal("59950.00"))
            assert "BTCUSDT" in sim.active_positions
            assert sim.active_positions["BTCUSDT"].quantity == Decimal("0.00004")

            # Closing SELL order: qty 0.00006 > 0.00004 (notional 3.60 USDT <= 5.00 USDT)
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    price=Decimal("60000.00"),
                    quantity=Decimal("0.00006"),
                    time_in_force=TimeInForce.GTC,
                )
            assert "exceeds active position quantity" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_non_positive_price_or_quantity_rejected(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify non-positive price or quantity is cleanly rejected with PreTradeRiskGateError."""
        sim, store, sink = clean_sim
        try:
            # Non-positive price
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    price=Decimal("0"),
                    quantity=Decimal("0.00008"),
                )
            assert "must be positive" in str(exc_info.value)

            # Negative quantity
            with pytest.raises(PreTradeRiskGateError) as exc_info2:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    price=Decimal("60000.00"),
                    quantity=Decimal("-0.00008"),
                )
            assert "must be positive" in str(exc_info2.value)

            # Taker with zero quantity
            with pytest.raises(PreTradeRiskGateError) as exc_info3:
                sim.execute_taker_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("0"),
                )
            assert "must be positive" in str(exc_info3.value)
        finally:
            sink.close()
            store.close()

    def test_unstaged_symbol_rejected_pre_trade(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify unstaged symbols outside Canary Staging Manifest are rejected fail-closed."""
        sim, store, sink = clean_sim
        try:
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-dogeusdt-001",
                    symbol="DOGEUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    price=Decimal("0.10"),
                    quantity=Decimal("10.0"),
                )
            assert "is not a permitted canary staged asset" in str(exc_info.value)
        finally:
            sink.close()
            store.close()

    def test_sqlite_store_get_fill_and_get_position_by_symbol(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify get_fill and get_position_by_symbol query methods in telemetry store."""
        sim, store, sink = clean_sim
        try:
            order = sim.place_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("149.50"),
                quantity=Decimal("0.03"),
                time_in_force=TimeInForce.GTC,
            )
            fill = sim.match_maker_fill(order.order_id, fill_price=Decimal("149.50"))

            # Query fill by ID
            fetched_fill = store.get_fill(fill.fill_id)
            assert fetched_fill is not None
            assert fetched_fill.fill_id == fill.fill_id
            assert fetched_fill.symbol == "SOLUSDT"
            assert fetched_fill.fill_price == Decimal("149.50")
            assert fetched_fill.liquidity_role == LiquidityRole.MAKER

            # Query position by symbol
            fetched_pos = store.get_position_by_symbol("SOLUSDT")
            assert fetched_pos is not None
            assert fetched_pos.symbol == "SOLUSDT"
            assert fetched_pos.status == PositionStatus.OPEN
            assert fetched_pos.entry_price == Decimal("149.50")
            assert fetched_pos.quantity == Decimal("0.03")

            # Non-existent queries return None
            assert store.get_fill("non-existent-fill") is None
            assert store.get_position_by_symbol("NONEXISTENT") is None
        finally:
            sink.close()
            store.close()

    def test_cli_override_force_recover_records_both_transitions(self, tmp_path: Path) -> None:
        """Verify force_recover records both intermediate freeze and recover in SQLite."""
        out_dir = tmp_path / "force_rec_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            force_recover=True,
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        summary, db_path, _, _, _, _ = runner.execute_drill()

        assert summary.tracks_executed == ["cli_override"]
        assert summary.circuit_breaker_stats["total_transitions"] == 2
        assert summary.circuit_breaker_stats["final_state"] == "NORMAL"

        store = SqliteCanaryExecutionTelemetryStore(db_path)
        try:
            rows = store._conn.execute(
                "SELECT previous_state, new_state FROM circuit_breaker_events ORDER BY id"
            ).fetchall()
            assert len(rows) == 2
            assert rows[0]["previous_state"] == "NORMAL"
            assert rows[0]["new_state"] == "TIER_1_SOFT_FREEZE"
            assert rows[1]["previous_state"] == "TIER_1_SOFT_FREEZE"
            assert rows[1]["new_state"] == "NORMAL"
        finally:
            store.close()

    def test_cli_verify_only_flag(self, tmp_path: Path) -> None:
        """Verify CLI --verify-only flag verifies existing artifacts without re-execution."""
        out_dir = tmp_path / "verify_only_dir"
        # First generate artifacts
        rc_gen = execute_phase_274_runner(
            output_dir=out_dir,
            track="all",
            verify_hash_chain=False,
        )
        assert rc_gen == 0

        # Run with verify_only=True
        rc_verify = execute_phase_274_runner(
            output_dir=out_dir,
            verify_only=True,
        )
        assert rc_verify == 0

        # Run via CLI main with --verify-only
        rc_main = cli_main(["--output-dir", str(out_dir), "--verify-only"])
        assert rc_main == 0


class TestPhase274ReviewRound3Fixes:
    """Validate Review Round 3 bugfixes, adversarial edge cases, and robustness enhancements."""

    def test_emergency_liquidation_creates_and_records_order(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify emergency liquidation creates and records an order in SQLite and JSONL."""
        sim, store, sink = clean_sim
        with store, sink:
            # 1. Open an active position
            order, fill = sim.execute_taker_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00008"),
                mark_price=Decimal("60000.00"),
            )
            assert "BTCUSDT" in sim.active_positions

            # 2. Trigger Tier 2 Hard-Abort
            tr_abort = sim.circuit_breaker.process_tick(
                rtt_ms=50.0,
                drift_ms=5000.0,
                is_catastrophic=True,
                anomaly_reason="Catastrophic clock drift",
            )
            assert tr_abort is not None
            sim.on_circuit_breaker_transition(tr_abort)

            # 3. Verify position was emergency liquidated
            assert "BTCUSDT" not in sim.active_positions
            assert sim.liquidations_count == 1
            assert len(sim.closed_positions) == 1

            # 4. Verify liquidation fill has a matching order in orders table
            liq_fill = sim.fills[-1]
            assert liq_fill.liquidity_role == LiquidityRole.TAKER
            liq_order = store.get_order(liq_fill.order_id)
            assert liq_order is not None
            assert liq_order.order_id == liq_fill.order_id
            assert liq_order.status == OrderStatus.FILLED
            assert liq_order.bracket_role == "LIQUIDATION"
            assert liq_order.side == OrderSide.SELL

            # 5. Relational join check: every fill has a matching order row
            cur = store._conn.execute(
                "SELECT f.fill_id, o.order_id FROM fills f JOIN orders o ON f.order_id = o.order_id"
            )
            joined = cur.fetchall()
            assert len(joined) == store.count_fills()

    def test_force_abort_with_attached_brackets_flattens_and_cancels(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify operator force_abort flattens position and cancels attached brackets."""
        sim, store, sink = clean_sim
        with store, sink:
            # 1. Open position and attach brackets
            entry_ord = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("59950.00"),
                quantity=Decimal("0.00008"),
            )
            sim.match_maker_fill(entry_ord.order_id)
            tp_ord, sl_ord = sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("59000.00"),
                take_profit_price=Decimal("61000.00"),
            )
            assert tp_ord.status == OrderStatus.OPEN
            assert sl_ord.status == OrderStatus.OPEN

            # 2. Operator force_abort
            tr_abort = sim.circuit_breaker.force_abort(
                operator_id="test-op", rationale="Emergency stop"
            )
            sim.on_circuit_breaker_transition(tr_abort)

            # 3. Position flattened to cash
            assert "BTCUSDT" not in sim.active_positions
            assert sim.liquidations_count == 1

            # 4. Attached brackets cancelled
            assert sim.orders[tp_ord.order_id].status == OrderStatus.CANCELLED
            assert sim.orders[sl_ord.order_id].status == OrderStatus.CANCELLED
            assert "Tier 2 Hard-Abort" in (sim.orders[tp_ord.order_id].rejection_reason or "")
            assert "Tier 2 Hard-Abort" in (sim.orders[sl_ord.order_id].rejection_reason or "")

            # 5. Exact zero balance drift maintained
            assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT

            # 6. Subsequent orders blocked fail-closed
            with pytest.raises(CircuitBreakerBlockError):
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    price=Decimal("59950.00"),
                    quantity=Decimal("0.00008"),
                )

    def test_bracket_order_rejected_without_open_position(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify placing closing bracket without open position is rejected fail-closed."""
        sim, store, sink = clean_sim
        with store, sink:
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.SELL,
                    order_type=OrderType.TAKE_PROFIT,
                    price=Decimal("61000.00"),
                    quantity=Decimal("0.00008"),
                    bracket_role="TAKE_PROFIT",
                )
            assert "without an active open position" in str(exc_info.value)

    def test_bracket_order_rejected_wrong_side(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify placing closing bracket on the same side as open position is rejected."""
        sim, store, sink = clean_sim
        with store, sink:
            entry = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("59950.00"),
                quantity=Decimal("0.00008"),
            )
            sim.match_maker_fill(entry.order_id)

            # Attempt to place BUY take-profit on a LONG position
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.TAKE_PROFIT,
                    price=Decimal("61000.00"),
                    quantity=Decimal("0.00008"),
                    bracket_role="TAKE_PROFIT",
                )
            assert "must be opposite to active position side" in str(exc_info.value)

    def test_bracket_order_inverted_prices_rejected(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify attach_bracket_orders rejects inverted take-profit and stop-loss prices."""
        sim, store, sink = clean_sim
        with store, sink:
            entry = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("60000.00"),
                quantity=Decimal("0.00008"),
            )
            sim.match_maker_fill(entry.order_id)

            # Inverted: TP <= entry
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.attach_bracket_orders(
                    symbol="BTCUSDT",
                    stop_price=Decimal("59000.00"),
                    take_profit_price=Decimal("59500.00"),
                )
            assert "must be greater than entry price" in str(exc_info.value)

            # Inverted: SL >= entry
            with pytest.raises(PreTradeRiskGateError) as exc_info2:
                sim.attach_bracket_orders(
                    symbol="BTCUSDT",
                    stop_price=Decimal("60500.00"),
                    take_profit_price=Decimal("61000.00"),
                )
            assert "must be less than entry price" in str(exc_info2.value)

    def test_duplicate_brackets_rejected(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify attaching duplicate active bracket orders is rejected."""
        sim, store, sink = clean_sim
        with store, sink:
            entry = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("60000.00"),
                quantity=Decimal("0.00008"),
            )
            sim.match_maker_fill(entry.order_id)

            # Attach first bracket set
            sim.attach_bracket_orders(
                symbol="BTCUSDT",
                stop_price=Decimal("59000.00"),
                take_profit_price=Decimal("61000.00"),
            )

            # Attempt to attach second bracket set
            with pytest.raises(Exception) as exc_info:
                sim.attach_bracket_orders(
                    symbol="BTCUSDT",
                    stop_price=Decimal("59200.00"),
                    take_profit_price=Decimal("60800.00"),
                )
            assert "Active bracket orders already attached" in str(exc_info.value)

    def test_negative_balance_and_insolvency_protection(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify orders are rejected when cash or equity drops to non-positive."""
        sim, store, sink = clean_sim
        with store, sink:
            # Artificially set cash to 0
            sim.cash = Decimal("0")
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                sim.place_order(
                    candidate_id="cand-btcusdt-dcb-002",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    price=Decimal("60000.00"),
                    quantity=Decimal("0.00008"),
                )
            assert "Portfolio insolvency / negative balance protection" in str(exc_info.value)

    def test_starting_equity_must_be_positive(
        self,
        tmp_path: Path,
        clean_sm: CanaryCircuitBreakerRecoveryStateMachine,
    ) -> None:
        """Verify simulator rejects non-positive starting equity during construction."""
        store = SqliteCanaryExecutionTelemetryStore(tmp_path / "zero_eq.sqlite3")
        sink = JsonlOrderSink(tmp_path / "zero_eq.jsonl")
        with store, sink:
            with pytest.raises(PreTradeRiskGateError) as exc_info:
                MicroOrderRoutingSimulator(
                    circuit_breaker=clean_sm,
                    telemetry_store=store,
                    jsonl_sink=sink,
                    starting_equity=Decimal("0"),
                )
            assert "Starting equity must be positive" in str(exc_info.value)

    def test_empty_database_handling(self, tmp_path: Path) -> None:
        """Verify count methods and require_records validation on empty database."""
        db_path = tmp_path / "empty_test.sqlite3"
        with SqliteCanaryExecutionTelemetryStore(db_path) as store:
            assert store.count_orders() == 0
            assert store.count_fills() == 0
            assert store.count_positions() == 0
            assert store.count_snapshots() == 0
            assert store.count_circuit_breaker_events() == 0
            assert store.get_snapshots() == []
            assert store.get_latest_snapshot() is None
            assert store.get_all_positions() == []
            assert store.get_open_positions() == []
            assert store.get_all_orders() == []
            assert store.get_all_fills() == []
            assert store.get_circuit_breaker_events() == []

            # By default (require_records=False), returns True
            ok_default, drift_default = store.verify_double_entry_integrity(require_records=False)
            assert ok_default is True
            assert drift_default == Decimal("0")

            # With require_records=True, returns False because no snapshots exist
            ok_req, _ = store.verify_double_entry_integrity(require_records=True)
            assert ok_req is False

    def test_sqlite_and_jsonl_context_managers_and_query_methods(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify context manager semantics and rich query methods on store and sink."""
        sim, store, sink = clean_sim
        with store as s, sink:
            order = sim.place_order(
                candidate_id="cand-solusdt-rgb-001",
                symbol="SOLUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("149.50"),
                quantity=Decimal("0.03"),
            )
            fill = sim.match_maker_fill(order.order_id, fill_price=Decimal("149.50"))

            # Query methods
            all_orders = s.get_all_orders()
            assert len(all_orders) == 1
            assert all_orders[0].order_id == order.order_id

            all_fills = s.get_all_fills()
            assert len(all_fills) == 1
            assert all_fills[0].fill_id == fill.fill_id

            open_pos = s.get_open_positions()
            assert len(open_pos) == 1
            assert open_pos[0].symbol == "SOLUSDT"

            all_pos = s.get_all_positions()
            assert len(all_pos) == 1

            snaps = s.get_snapshots()
            assert len(snaps) >= 1
            latest_snap = s.get_latest_snapshot()
            assert latest_snap is not None
            assert latest_snap.snapshot_id == snaps[-1].snapshot_id

        # After context exit, store is closed
        assert store._closed is True
        assert store.count_orders() == 0

    def test_arbitrary_decimal_fractions_zero_drift(
        self,
        clean_sim: tuple[
            MicroOrderRoutingSimulator, SqliteCanaryExecutionTelemetryStore, JsonlOrderSink
        ],
    ) -> None:
        """Verify multi-step partial fills with non-terminating fractions preserve zero drift."""
        sim, store, sink = clean_sim
        with store, sink:
            # Entry: 0.00009 BTC at 55432.123456 USDT (notional ~4.98889 USDT <= 5.00 USDT)
            entry = sim.place_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("55432.123456"),
                quantity=Decimal("0.00009"),
            )
            sim.match_maker_fill(entry.order_id)
            assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT

            # Step 1: Partial close of 1/3 (0.00003 BTC) at 56789.987654 USDT
            sim.execute_taker_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00003"),
                mark_price=Decimal("56789.987654"),
            )
            assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT

            # Step 2: Partial close of another 1/3 (0.00003 BTC) at 54321.111111 USDT
            sim.execute_taker_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00003"),
                mark_price=Decimal("54321.111111"),
            )
            assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT

            # Step 3: Final close of remaining 0.00003 BTC at 58000.555555 USDT
            sim.execute_taker_order(
                candidate_id="cand-btcusdt-dcb-002",
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.00003"),
                mark_price=Decimal("58000.555555"),
            )
            assert "BTCUSDT" not in sim.active_positions
            assert sim.current_drift < DOUBLE_ENTRY_MAX_DRIFT
            assert sim.allocated_margin == Decimal("0")

    def test_cli_help_and_invalid_arguments(self, tmp_path: Path) -> None:
        """Verify CLI --help, invalid track choices, and mutually exclusive arguments."""
        parser = build_arg_parser()

        # 1. --help raises SystemExit(0)
        with pytest.raises(SystemExit) as exc_help:
            parser.parse_args(["--help"])
        assert exc_help.value.code == 0

        # 2. Invalid track choice raises SystemExit(2)
        with pytest.raises(SystemExit) as exc_trk:
            parser.parse_args(["--track", "invalid_track_name"])
        assert exc_trk.value.code == 2

        # 3. Mutually exclusive flags raise SystemExit(2)
        with pytest.raises(SystemExit) as exc_mutex:
            parser.parse_args(["--force-freeze", "--force-abort"])
        assert exc_mutex.value.code == 2

        # 4. CLI with --simulate-adverse-drift returns exit code 1
        out_dir = tmp_path / "adverse_cli_test"
        rc_drift = execute_phase_274_runner(
            output_dir=out_dir,
            track="1",
            simulate_adverse_drift=True,
        )
        assert rc_drift == 1

    def test_jsonl_line_endings_pure_lf(self, tmp_path: Path) -> None:
        """Verify canary-orders.jsonl is written with pure LF (\\n) line endings.

        Must not contain CRLF (\\r\\n) line endings on any platform including Windows.
        """
        out_dir = tmp_path / "lf_test"
        cfg = CanaryMicroExecutionDrillConfig(
            output_dir=out_dir,
            target_track="track_1",
        )
        runner = CanaryMicroExecutionDrillRunner(cfg)
        runner.execute_drill()

        jsonl_path = out_dir / "canary-orders.jsonl"
        assert jsonl_path.is_file()
        content = jsonl_path.read_bytes()
        assert len(content) > 0
        assert b"\r\n" not in content, "canary-orders.jsonl must not contain CRLF line endings"
        assert b"\n" in content
