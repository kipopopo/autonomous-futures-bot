"""Unit tests for Phase 282: Production Canary Continuous Multi-Candidate Autonomous Daemon Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress
  (Phase 281, 280, 279, 278, 277, 276).
- Dual-confirmation client order tag format (c=canary-p282-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms) and backward NTP clock drift (> 250 ms
  triggers HEARTBEAT_FREEZE with 50 ms recovery hysteresis).
- Stepped concurrent exposure scaling across stages:
  - Stage 1 seed probe cap (<= 5.00 USDT)
  - Stage 2 expanded concurrent cap (<= 10.00 USDT)
  - Stage 3 continuous expansion cap (<= 15.00 USDT across all symbols)
  - Micro order cap <= 5.00 USDT with ROUND_DOWN precision.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
- Active committed working margin reservation on unfilled/working orders.
- Intra-phase cumulative loss budget ceiling <= 2.50 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Continuous session longevity supervision, WebSocket stream flap, epoched reconnect,
  trade deduplication, and out-of-order sequencing.
- Continuous autonomous daemon lifecycle (INITIALIZING -> RUNNING -> DRAINING -> STOPPED)
  and graceful shutdown signal handling / hanging working order cancellation.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT) across snapshots.
- Strict containment invariants (execution_authority: False, orders: 0, api_keys_loaded: 0).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    STARTING_EQUITY_USDT,
    OrderSide,
    OrderType,
)
from autonomous_futures.feed.canary_probe import (  # noqa: E402
    SafetyInvariantViolation,
)
from autonomous_futures.feed.continuous_daemon import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_PHASE282_OUTPUT_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    INTRA_PHASE_LOSS_CEILING_USDT,
    MAX_CLOCK_SKEW_TOLERANCE_MS,
    AggregateExposureCapExceededError,
    BalanceSnapshot,
    CanaryContinuousDaemonConfig,
    CanaryContinuousDaemonRunner,
    CapitalExpansionStage,
    CircuitBreakerActiveError,
    CircuitBreakerState,
    ClockSkewExceededError,
    ContinuousAutonomousDaemon,
    ContinuousDaemonTrackResult,
    ContinuousMicroOrderDispatcher,
    ContinuousOrderDispatchInterlock,
    ContinuousOrderRecord,
    ContinuousStreamSequencer,
    ContinuousUserDataStreamReconciler,
    DaemonState,
    DynamicMarginAllocationCeilingError,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatFreezeActiveError,
    HeartbeatStatus,
    IntraPhaseLossCeilingExceededError,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    MicroNotionalCapExceededError,
    MockBinanceContinuousGateway,
    OrderLifecycleState,
    SqliteCanaryContinuousDaemonTelemetryStore,
    TimeInForce,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_282_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_282_continuous_daemon import (  # noqa: E402
    execute_phase_282_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-telemetry.sqlite3"
    store = SqliteCanaryContinuousDaemonTelemetryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path):
    jsonl_path = tmp_path / "test-orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_path)


# =====================================================================
# 1. Dual-Confirmation Client Order ID Tagging Tests
# =====================================================================


def test_generate_and_validate_canary_client_order_id():
    cid = generate_canary_client_order_id(
        "BTCUSDT", timestamp_ms=1700000000000, uuid_str="abc12345"
    )
    assert cid == "c=canary-p282-BTCUSDT-1700000000000-abc12345"

    ok, err = validate_canary_client_order_id(cid, expected_symbol="BTCUSDT")
    assert ok is True
    assert err is None
    assert_valid_canary_client_order_id(cid, expected_symbol="BTCUSDT")

    # Mismatched symbol
    ok, err = validate_canary_client_order_id(cid, expected_symbol="ETHUSDT")
    assert ok is False
    assert "does not match expected symbol" in (err or "")

    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id(cid, expected_symbol="ETHUSDT")

    # Invalid prefix format (e.g. from phase 281)
    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id("c=canary-p281-BTCUSDT-1700000000000-abc12345")

    # Unauthorized symbol
    with pytest.raises(SafetyInvariantViolation):
        generate_canary_client_order_id("DOGEUSDT")


# =====================================================================
# 2. Gateway Heartbeat Freshness & Recovery Hysteresis Tests
# =====================================================================


def test_gateway_heartbeat_freshness_and_hysteresis():
    mon = GatewayHeartbeatMonitor()

    # Initially empty monitor -> age very high -> not fresh
    assert mon.is_fresh() is False
    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_fresh()

    # Record fresh heartbeat
    now_ms = int(time.time() * 1000)
    rec = mon.record_heartbeat(server_time_ms=now_ms - 40, latency_ms=40.0, track_id="test")
    assert rec.status == HeartbeatStatus.HEALTHY
    assert mon.is_fresh() is True

    # Simulate latency spike > 500 ms
    mon.set_simulated_stale_age(550.0)
    assert mon.is_fresh() is False
    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_fresh()

    # Recovery hysteresis: 480 ms is <= 500 ms but > 450 ms recovery ceiling
    mon.set_simulated_stale_age(480.0)
    assert mon.is_fresh() is False

    # Recover when age <= 450 ms
    mon.set_simulated_stale_age(440.0)
    assert mon.is_fresh() is True


def test_gateway_heartbeat_clock_skew_and_freeze():
    mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)

    # Initial healthy heartbeat
    mon.record_heartbeat(
        server_time_ms=now_ms,
        latency_ms=10.0,
        track_id="skew_init",
    )

    # Server time behind local time by > 250 ms -> backward clock skew
    rec = mon.record_heartbeat(
        server_time_ms=now_ms - int(MAX_CLOCK_SKEW_TOLERANCE_MS + 50),
        latency_ms=10.0,
        track_id="skew_test",
    )
    assert rec.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_clock_skew_frozen is True

    # Interlock should raise ClockSkewExceededError (subclass of HeartbeatFreezeActiveError)
    assert issubclass(ClockSkewExceededError, HeartbeatFreezeActiveError)
    with pytest.raises(ClockSkewExceededError):
        mon.assert_fresh()
    with pytest.raises(HeartbeatFreezeActiveError):
        mon.assert_fresh()

    # Recovery hysteresis: 220 ms drift is <= 250 ms tolerance, but > 200 ms recovery ceiling
    rec_hys = mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 220,
        latency_ms=10.0,
        track_id="skew_hysteresis",
    )
    assert rec_hys.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_clock_skew_frozen is True

    # Recovery occurs when drift <= 200 ms (tolerance - 50 ms)
    rec_recov = mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 190,
        latency_ms=10.0,
        track_id="skew_recovered",
    )
    assert rec_recov.status == HeartbeatStatus.HEALTHY
    assert mon.is_clock_skew_frozen is False


# =====================================================================
# 3. Stepped Concurrent Exposure Scaling Tests
# =====================================================================


def test_stepped_concurrent_exposure_limits(temp_telemetry_store):
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000),
        latency_ms=20.0,
        track_id="test",
    )
    rec = ContinuousUserDataStreamReconciler(track_id="test")
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=rec,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_1_SEED_PROBE,
    )

    # Hard micro cap: 5.01 USDT exceeds 5.00 USDT
    cid_err = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MicroNotionalCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.0000835"),
            client_order_id=cid_err,
        )

    # Stage 1: aggregate cap is 5.00 USDT. Micro order of 4.80 USDT succeeds.
    cid1 = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.00008"),
        client_order_id=cid1,
    )

    # Simulate position fill of 4.80 USDT
    rec.positions["BTCUSDT"] = Decimal("0.00008")
    rec.position_entry_prices["BTCUSDT"] = Decimal("60000.00")
    rec.allocated_margin = Decimal("4.80")
    rec.per_asset_margin["BTCUSDT"] = Decimal("4.80")

    # In Stage 1, another 4.80 USDT order exceeds 5.00 USDT aggregate cap
    cid2 = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.0016"),
            client_order_id=cid2,
        )

    # Transition to Stage 2: aggregate cap is 10.00 USDT -> 4.80 USDT order now succeeds!
    interlock.expansion_stage = CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT
    interlock.validate_dispatch(
        symbol="ETHUSDT",
        price=Decimal("3000.00"),
        quantity=Decimal("0.0016"),
        client_order_id=cid2,
    )

    # Simulate second fill
    rec.positions["ETHUSDT"] = Decimal("0.0016")
    rec.position_entry_prices["ETHUSDT"] = Decimal("3000.00")
    rec.allocated_margin = Decimal("9.60")
    rec.per_asset_margin["ETHUSDT"] = Decimal("4.80")

    # In Stage 2, a 3rd order of 4.50 USDT (total 14.10 USDT) exceeds 10.00 USDT cap
    cid3 = generate_canary_client_order_id("SOLUSDT")
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.validate_dispatch(
            symbol="SOLUSDT",
            price=Decimal("150.00"),
            quantity=Decimal("0.03"),
            client_order_id=cid3,
        )

    # Transition to Stage 3: aggregate cap is 15.00 USDT -> 4.50 USDT order now succeeds!
    interlock.expansion_stage = CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION
    interlock.validate_dispatch(
        symbol="SOLUSDT",
        price=Decimal("150.00"),
        quantity=Decimal("0.03"),
        client_order_id=cid3,
    )


# =====================================================================
# 4. Margin Headroom & Working Margin Reservation Tests
# =====================================================================


def test_active_working_committed_margin_and_reserve(temp_telemetry_store):
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000),
        latency_ms=20.0,
        track_id="test",
    )
    rec = ContinuousUserDataStreamReconciler(track_id="test", starting_equity=Decimal("20.00"))
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=rec,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
    )

    # Mock working order provider
    working_orders: dict[str, ContinuousOrderRecord] = {}
    interlock.set_orders_provider(lambda: working_orders)

    # With equity 20.00 USDT, 20% per-asset cap is 4.00 USDT
    cid_asset_exceeded = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(DynamicMarginAllocationCeilingError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),
            client_order_id=cid_asset_exceeded,
        )

    # Increase equity to 100 USDT (20% is 20 USDT)
    rec.starting_equity = Decimal("100.00")
    rec.cash = Decimal("100.00")

    # Add working open order of 4.80 USDT
    cid_work = generate_canary_client_order_id("BTCUSDT")
    now_utc = datetime.now(UTC).isoformat()
    working_orders[cid_work] = ContinuousOrderRecord(
        order_id="101",
        client_order_id=cid_work,
        track_id="test",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY.value,
        order_type=OrderType.LIMIT.value,
        time_in_force=TimeInForce.GTC.value,
        price="60000.00",
        quantity="0.00008",
        notional_usdt="4.80",
        status=OrderLifecycleState.NEW,
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )

    # Interlock accounts for active working committed margin (4.80 USDT)
    assert interlock.get_working_committed_margin() == Decimal("4.80")
    assert interlock.get_aggregate_active_exposure() == Decimal("4.80")


# =====================================================================
# 5. Intra-Phase Loss Ceiling & Emergency Flattening Tests
# =====================================================================


def test_intra_phase_loss_ceiling_and_flattening(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    sequencer = ContinuousStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000),
        latency_ms=25.0,
        track_id="test",
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
        intra_phase_loss_ceiling_usdt=INTRA_PHASE_LOSS_CEILING_USDT,
    )
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )

    # Buy BTC
    cid_buy = generate_canary_client_order_id("BTCUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        client_order_id=cid_buy,
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

    # Adverse price drop causes realized loss of 2.70 USDT (> 2.50 USDT ceiling)
    cid_sell = generate_canary_client_order_id("BTCUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("26250.00"),
        client_order_id=cid_sell,
        is_closing=True,
    )

    assert reconciler.cumulative_realized_loss >= INTRA_PHASE_LOSS_CEILING_USDT

    # Circuit breaker lockout must activate fail-closed on next order dispatch
    cid_blocked = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises((CircuitBreakerActiveError, IntraPhaseLossCeilingExceededError)):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.001"),
            price=Decimal("3000.00"),
            client_order_id=cid_blocked,
        )

    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

    # Emergency flattening flattens positions and cancels open orders
    flattening_orders = dispatcher.execute_emergency_flattening()
    assert isinstance(flattening_orders, list)
    assert reconciler.allocated_margin == Decimal("0")


# =====================================================================
# 6. Stream Flap, Epoched Reconnect & Trade Deduplication Tests
# =====================================================================


def test_websocket_flap_and_rest_reconciliation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    sequencer = ContinuousStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000),
        latency_ms=25.0,
        track_id="test",
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
    )
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )

    # 1. Disconnect WebSocket stream
    gateway.disconnect_stream()
    cid = generate_canary_client_order_id("BTCUSDT")
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        client_order_id=cid,
    )
    assert ord_rec.status == OrderLifecycleState.NEW

    # 2. Reconnect stream and reconcile via REST
    gateway.reconnect_stream()
    sequencer.notify_reconnect(new_epoch=1)
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED

    # 3. Inject duplicate and out-of-order execution packets
    gateway.inject_out_of_order_events = True
    gateway.inject_duplicate_events = True

    eth_cid = generate_canary_client_order_id("ETHUSDT")
    eth_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=eth_cid,
    )
    assert eth_rec.status == OrderLifecycleState.FILLED
    assert sequencer.deduplicated_count >= 1
    assert sequencer.out_of_order_count >= 1


# =====================================================================
# 7. Exact Double-Entry Balance Accounting & Zero Drift Tests
# =====================================================================


def test_exact_double_entry_balance_reconciliation():
    rec = ContinuousUserDataStreamReconciler(track_id="test", starting_equity=Decimal("100.00"))
    assert rec.verify_zero_balance_drift() is True

    # Fill Buy BTC: 0.00008 @ 60,000 USDT (notional 4.80 USDT, comm 0.00192 USDT)
    rec.process_fill(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.00008"),
        commission=Decimal("0.00192"),
    )
    assert rec.cash == Decimal("95.19808")
    assert rec.allocated_margin == Decimal("4.80")
    assert rec.realized_pnl == Decimal("-0.00192")
    assert rec.verify_zero_balance_drift() is True
    assert rec.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Price moves: mark price drops to 55,000 USDT -> unrealized PnL = -0.40 USDT
    rec.mark_prices["BTCUSDT"] = Decimal("55000.00")
    assert rec.unrealized_pnl == Decimal("-0.40000000")
    assert rec.verify_zero_balance_drift() is True
    assert rec.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Close BTC: sell at 55,000 USDT
    rec.process_fill(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("55000.00"),
        quantity=Decimal("0.00008"),
        commission=Decimal("0.00176"),
        is_closing=True,
    )
    assert rec.positions["BTCUSDT"] == Decimal("0")
    assert rec.allocated_margin == Decimal("0")
    assert rec.verify_zero_balance_drift() is True
    assert rec.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 8. Continuous Autonomous Daemon Lifecycle & Shutdown Tests
# =====================================================================


def test_daemon_lifecycle_and_graceful_shutdown(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    sequencer = ContinuousStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000),
        latency_ms=25.0,
        track_id="test",
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
    )
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )
    daemon = ContinuousAutonomousDaemon(
        dispatcher=dispatcher,
        reconciler=reconciler,
        interlock=interlock,
        heartbeat_monitor=heartbeat_mon,
        telemetry_store=temp_telemetry_store,
        track_id="test",
    )

    assert daemon.state == DaemonState.INITIALIZING
    daemon.start()
    assert daemon.state == DaemonState.RUNNING

    # Health check
    health = daemon.check_health()
    assert health["state"] == DaemonState.RUNNING.value
    assert health["heartbeat_fresh"] is True
    assert health["zero_drift"] is True

    # Shutdown
    daemon.shutdown(graceful=True)
    assert daemon.state == DaemonState.STOPPED


# =====================================================================
# 9. Full Phase 282 Runner & Merkle DAG Hash Chain Tests
# =====================================================================


def test_full_phase_282_runner_and_hash_chain(tmp_path: Path):
    config = CanaryContinuousDaemonConfig(
        output_dir=tmp_path / "artifacts" / "phase282",
    )
    runner = CanaryContinuousDaemonRunner(config=config)
    report = runner.execute_all_tracks()

    assert report.phase == "phase_282"
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True
    assert len(report.tracks) == 4

    # Verify SHA-256 Merkle DAG hash chain
    chain_ok = verify_phase_282_hash_chain(output_dir=tmp_path / "artifacts" / "phase282")
    assert chain_ok is True


def test_adverse_drift_detection_fail_closed(tmp_path: Path):
    config = CanaryContinuousDaemonConfig(
        output_dir=tmp_path / "adverse_drift",
        simulate_adverse_drift=True,
    )
    runner = CanaryContinuousDaemonRunner(config=config)
    report = runner.execute_all_tracks()
    assert report.compliance["zero_balance_drift"] is False
    assert report.compliance["all_criteria_passed"] is False


def test_cli_execute_phase_282_runner_verify_only():
    exit_code = execute_phase_282_runner(
        output_dir=DEFAULT_PHASE282_OUTPUT_DIR,
        verify_only=True,
    )
    assert exit_code == 0


def test_strict_containment_invariants():
    report_file = DEFAULT_PHASE282_OUTPUT_DIR / "canary-continuous-daemon-report.json"
    summary_file = DEFAULT_PHASE282_OUTPUT_DIR / "continuous-daemon-summary.json"
    paper_file = DEFAULT_PHASE282_OUTPUT_DIR / "paper-summary.json"

    assert report_file.exists()
    assert summary_file.exists()
    assert paper_file.exists()

    with open(summary_file, encoding="utf-8") as f:
        summary_data = json.load(f)
    with open(paper_file, encoding="utf-8") as f:
        paper_data = json.load(f)

    # Invariants in paper-summary
    assert paper_data["safety_invariants"]["execution_authority"] is False
    assert paper_data["safety_invariants"]["orders"] == 0
    assert paper_data["safety_invariants"]["api_keys_loaded"] == 0
    assert paper_data["safety_invariants"]["zero_secret_leakage"] is True

    # Invariants in continuous-daemon-summary
    assert summary_data["compliance"]["read_only_safety_compliant"] is True
    assert summary_data["compliance"]["zero_secret_leakage"] is True


def test_all_database_balance_snapshots_zero_drift():
    db_file = DEFAULT_PHASE282_OUTPUT_DIR / "canary-continuous-daemon-telemetry.sqlite3"
    assert db_file.exists()
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT drift_usdt FROM balance_snapshots").fetchall()
        assert len(rows) > 0
        for (d_str,) in rows:
            assert Decimal(d_str) < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 10. Robustness & Adversarial Edge Case Tests
# =====================================================================


def test_identical_timestamp_monotonic_event_sorting_and_transition_guard(
    temp_telemetry_store, temp_jsonl_sink
):
    """Test that events sharing identical timestamps sort NEW before FILLED, and terminal
    states reject retrograde status updates.
    """
    seq = ContinuousStreamSequencer()
    cid = generate_canary_client_order_id("BTCUSDT")

    # Identical millisecond for NEW and FILLED
    now_ms = 1700000000000
    pkt_new = {
        "e": "ORDER_TRADE_UPDATE",
        "E": now_ms,
        "T": now_ms,
        "s_seq": 1,
        "o": {"c": cid, "s": "BTCUSDT", "X": "NEW", "x": "NEW", "t": 0},
    }
    pkt_fill = {
        "e": "ORDER_TRADE_UPDATE",
        "E": now_ms,
        "T": now_ms,
        "s_seq": 2,
        "o": {
            "c": cid,
            "s": "BTCUSDT",
            "X": "FILLED",
            "x": "TRADE",
            "t": 1001,
            "L": "60000.00",
            "l": "0.00008",
            "z": "0.00008",
            "n": "0.00192",
            "S": "BUY",
        },
    }

    # Pass in scrambled order [pkt_fill, pkt_new]
    sorted_pkts = seq.sort_and_deduplicate_batch([pkt_fill, pkt_new], track_id="test")
    assert sorted_pkts[0]["o"]["X"] == "NEW"
    assert sorted_pkts[1]["o"]["X"] == "FILLED"

    # Verify dispatcher processes them without reverting to NEW
    gateway = MockBinanceContinuousGateway()
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000), latency_ms=10.0, track_id="test"
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
    )
    dispatcher_seq = ContinuousStreamSequencer()
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=dispatcher_seq,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )

    now_utc = datetime.now(UTC).isoformat()
    ord_rec = ContinuousOrderRecord(
        order_id="1001",
        client_order_id=cid,
        track_id="test",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        price="60000.00",
        quantity="0.00008",
        notional_usdt="4.80",
        status=OrderLifecycleState.PENDING_NEW,
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )
    dispatcher.orders[cid] = ord_rec
    gateway.ws_outbound_queue.extend([pkt_new, pkt_fill])
    dispatcher.drain_and_reconcile_stream()

    assert ord_rec.status == OrderLifecycleState.FILLED

    # Inject late out-of-order NEW event -> must NOT revert FILLED state
    late_new = {
        "e": "ORDER_TRADE_UPDATE",
        "E": now_ms + 10,
        "T": now_ms + 10,
        "s_seq": 3,
        "o": {"c": cid, "s": "BTCUSDT", "X": "NEW", "x": "NEW", "t": 0},
    }
    gateway.ws_outbound_queue.append(late_new)
    dispatcher.drain_and_reconcile_stream()
    assert ord_rec.status == OrderLifecycleState.FILLED


def test_emergency_flattening_with_disconnected_stream(temp_telemetry_store, temp_jsonl_sink):
    """Test that emergency flattening cleanly flattens positions even when the WebSocket stream
    is completely disconnected by leveraging REST synchronization.
    """
    gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    sequencer = ContinuousStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000), latency_ms=10.0, track_id="test"
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
    )
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )

    # Open position while stream is active
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
    assert reconciler.allocated_margin > Decimal("0")

    # Socket drops right before emergency liquidation
    gateway.disconnect_stream()

    # Emergency flattening executes with disconnected stream
    flatten_orders = dispatcher.execute_emergency_flattening()
    assert len(flatten_orders) >= 1
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.verify_zero_balance_drift() is True


def test_daemon_shutdown_hanging_orders_cleanup(temp_telemetry_store, temp_jsonl_sink):
    """Test that daemon graceful shutdown cancels any unexecuted working orders."""
    gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    sequencer = ContinuousStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000), latency_ms=10.0, track_id="test"
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
    )
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )
    daemon = ContinuousAutonomousDaemon(
        dispatcher=dispatcher,
        reconciler=reconciler,
        interlock=interlock,
        heartbeat_monitor=heartbeat_mon,
        telemetry_store=temp_telemetry_store,
        track_id="test",
    )
    daemon.start()

    # Inject an open working order (NEW)
    cid = generate_canary_client_order_id("BTCUSDT")
    now_utc = datetime.now(UTC).isoformat()
    ord_rec = ContinuousOrderRecord(
        order_id="2001",
        client_order_id=cid,
        track_id="test",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        price="60000.00",
        quantity="0.00008",
        notional_usdt="4.80",
        status=OrderLifecycleState.NEW,
        expansion_stage=CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION,
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )
    dispatcher.orders[cid] = ord_rec
    gateway.orders[cid] = {"orderId": "2001", "status": "NEW", "symbol": "BTCUSDT"}

    # Execute shutdown
    daemon.shutdown(graceful=True)
    assert daemon.state == DaemonState.STOPPED
    assert ord_rec.status == OrderLifecycleState.CANCELLED
    assert dispatcher.orders_cancelled_count >= 1


def test_concurrent_order_dispatch_thread_safety(temp_telemetry_store, temp_jsonl_sink):
    """Test that concurrent order dispatch across threads strictly enforces aggregate caps
    without TOCTOU over-allocation.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = ContinuousUserDataStreamReconciler(track_id="test")
    sequencer = ContinuousStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000), latency_ms=10.0, track_id="test"
    )
    interlock = ContinuousOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # Cap: 5.00 USDT
    )
    dispatcher = ContinuousMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test",
    )

    # Two orders each 4.80 USDT: only 1 can succeed under 5.00 USDT cap
    orders_to_dispatch = [
        ("cand-btc", "BTCUSDT", Decimal("0.00008"), Decimal("60000.00")),
        ("cand-eth", "ETHUSDT", Decimal("0.0016"), Decimal("3000.00")),
    ]

    successes = []
    failures = []

    def dispatch_worker(cand, sym, qty, px):
        return dispatcher.dispatch_micro_order(
            candidate_id=cand,
            symbol=sym,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=qty,
            price=px,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(dispatch_worker, cand, sym, qty, px): sym
            for cand, sym, qty, px in orders_to_dispatch
        }
        for fut in as_completed(futures):
            try:
                res = fut.result()
                successes.append(res)
            except AggregateExposureCapExceededError as exc:
                failures.append(exc)

    assert len(successes) == 1
    assert len(failures) == 1
    assert interlock.get_aggregate_active_exposure() <= Decimal("5.00")


class TestPhase282AdversarialHardening:
    """Adversarial stress-testing of Phase 282 continuous daemon components."""

    def test_vwap_multi_fill_zero_drift(self):
        """Verify that multi-fill executions across varying price levels compute exact VWAP
        and maintain zero balance drift (|drift| < 1e-15 USDT) on partial and complete liquidation.
        """
        reconciler = ContinuousUserDataStreamReconciler(
            track_id="test_vwap", starting_equity=Decimal("1000.00")
        )

        # Fill 1: Buy 0.0001 BTC @ 60,000 USDT
        # Notional: 6.00 USDT, margin: 6.00 USDT, fee: 0.003 USDT
        reconciler.process_fill(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("60000.00"),
            quantity=Decimal("0.0001"),
            commission=Decimal("0.003"),
            is_closing=False,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.0001")
        assert reconciler.position_entry_prices["BTCUSDT"] == Decimal("60000.00")
        assert reconciler.verify_zero_balance_drift()

        # Fill 2: Buy 0.0001 BTC @ 70,000 USDT
        # Notional: 7.00 USDT, margin: 7.00 USDT, fee: 0.0035 USDT
        reconciler.process_fill(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("70000.00"),
            quantity=Decimal("0.0001"),
            commission=Decimal("0.0035"),
            is_closing=False,
        )
        assert reconciler.positions["BTCUSDT"] == Decimal("0.0002")
        # VWAP = (60000 * 0.0001 + 70000 * 0.0001) / 0.0002 = 65000.00
        assert reconciler.position_entry_prices["BTCUSDT"] == Decimal("65000.00000000")
        assert reconciler.verify_zero_balance_drift()

        # Partial Close: Sell 0.0001 BTC @ 80,000 USDT (fee: 0.004 USDT)
        # Realized PnL = 0.0001 * (80000 - 65000) = 1.50 USDT
        pnl_1 = reconciler.process_fill(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            price=Decimal("80000.00"),
            quantity=Decimal("0.0001"),
            commission=Decimal("0.004"),
            is_closing=True,
        )
        assert pnl_1 == Decimal("1.50000000")
        assert reconciler.positions["BTCUSDT"] == Decimal("0.0001")
        assert reconciler.verify_zero_balance_drift()
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

        # Final Close: Sell 0.0001 BTC @ 85,000 USDT (fee: 0.00425 USDT)
        # Realized PnL = 0.0001 * (85000 - 65000) = 2.00 USDT
        pnl_2 = reconciler.process_fill(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            price=Decimal("85000.00"),
            quantity=Decimal("0.0001"),
            commission=Decimal("0.00425"),
            is_closing=True,
        )
        assert pnl_2 == Decimal("2.00000000")
        assert reconciler.positions["BTCUSDT"] == Decimal("0")
        assert reconciler.allocated_margin == Decimal("0")
        assert reconciler.verify_zero_balance_drift()
        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    def test_single_l_canceled_bidirectional_tolerance(self, temp_telemetry_store, temp_jsonl_sink):
        """Verify that single-'L' Binance status 'CANCELED' parses without error in enum,
        user data stream drain, and REST reconciliation.
        """
        assert OrderLifecycleState("CANCELED") == OrderLifecycleState.CANCELLED
        assert OrderLifecycleState("CANCELLED") == OrderLifecycleState.CANCELLED
        assert OrderLifecycleState("canceled") == OrderLifecycleState.CANCELLED

        gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
        reconciler = ContinuousUserDataStreamReconciler(track_id="test_cancel")
        sequencer = ContinuousStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(
            server_time_ms=int(time.time() * 1000), latency_ms=5.0, track_id="test_cancel"
        )
        interlock = ContinuousOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
        )
        dispatcher = ContinuousMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=temp_telemetry_store,
            jsonl_sink=temp_jsonl_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="test_cancel",
        )

        cid = generate_canary_client_order_id("BTCUSDT", timestamp_ms=int(time.time() * 1000))
        rec = ContinuousOrderRecord(
            order_id="ord-cancel-1",
            client_order_id=cid,
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force=TimeInForce.GTC.value,
            price="60000.00",
            quantity="0.00008",
            notional_usdt="4.80000000",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
            track_id="test_cancel",
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid] = rec
        gateway.orders[cid] = {"orderId": "3001", "status": "NEW", "symbol": "BTCUSDT"}

        # Simulate Binance WebSocket ORDER_TRADE_UPDATE with single-L "CANCELED"
        ws_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": int(time.time() * 1000),
            "T": int(time.time() * 1000),
            "s_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "X": "CANCELED",
                "i": 3001,
                "l": "0",
                "z": "0",
                "L": "0",
                "n": "0",
                "T": int(time.time() * 1000),
                "t": 0,
            },
        }
        gateway.push_user_data_event(ws_event)
        dispatcher.drain_and_reconcile_stream()

        assert rec.status == OrderLifecycleState.CANCELLED
        assert dispatcher.orders_cancelled_count == 1

        # Test REST poll with single-L "CANCELED"
        cid2 = generate_canary_client_order_id("ETHUSDT", timestamp_ms=int(time.time() * 1000))
        rec2 = ContinuousOrderRecord(
            order_id="ord-cancel-2",
            client_order_id=cid2,
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force=TimeInForce.GTC.value,
            price="3000.00",
            quantity="0.001",
            notional_usdt="3.00000000",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
            track_id="test_cancel",
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid2] = rec2
        gateway.orders[cid2] = {
            "orderId": "3002",
            "status": "CANCELED",  # single-L
            "symbol": "ETHUSDT",
            "executedQty": "0",
            "avgPrice": "0",
        }
        dispatcher.reconcile_via_rest()
        assert rec2.status == OrderLifecycleState.CANCELLED
        assert dispatcher.orders_cancelled_count == 2

    def test_fail_closed_shutdown_on_gateway_exception(self, temp_telemetry_store, temp_jsonl_sink):
        """Verify that when gateway.cancel_order throws an unexpected exception during shutdown,
        orders are still cancelled locally fail-closed without leaving hanging orders.
        """
        gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)

        def broken_cancel(*args, **kwargs):
            raise RuntimeError("Gateway connection dropped during cancel")

        gateway.cancel_order = broken_cancel

        reconciler = ContinuousUserDataStreamReconciler(track_id="test_shutdown_exc")
        sequencer = ContinuousStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(
            server_time_ms=int(time.time() * 1000), latency_ms=5.0, track_id="test_shutdown_exc"
        )
        interlock = ContinuousOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
        )
        dispatcher = ContinuousMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=temp_telemetry_store,
            jsonl_sink=temp_jsonl_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="test_shutdown_exc",
        )

        cid = generate_canary_client_order_id("SOLUSDT", timestamp_ms=int(time.time() * 1000))
        rec = ContinuousOrderRecord(
            order_id="ord-shutdown-1",
            client_order_id=cid,
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force=TimeInForce.GTC.value,
            price="150.00",
            quantity="0.02",
            notional_usdt="3.00000000",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
            track_id="test_shutdown_exc",
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid] = rec

        daemon = ContinuousAutonomousDaemon(
            dispatcher=dispatcher,
            reconciler=reconciler,
            interlock=interlock,
            heartbeat_monitor=heartbeat_mon,
            telemetry_store=temp_telemetry_store,
            track_id="test_shutdown_exc",
        )

        cancelled = daemon.cancel_all_working_orders()
        assert cancelled == 1
        assert rec.status == OrderLifecycleState.CANCELLED
        assert dispatcher.orders_cancelled_count == 1

        cur = temp_telemetry_store.conn.cursor()
        cur.execute(
            "SELECT to_state, trigger_reason FROM lifecycle_transitions WHERE client_order_id = ?",
            (cid,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == OrderLifecycleState.CANCELLED.value
        assert row[1] == "DAEMON_SHUTDOWN_CLEANUP"

    def test_stream_sequencer_robustness_none_and_sequence_wrap(self):
        """Verify ContinuousStreamSequencer handles None payload defensively and handles
        sequence wrap heuristic seamlessly.
        """
        sequencer = ContinuousStreamSequencer()

        # Ingest malformed / None payload without error
        res_none = sequencer.sort_and_deduplicate_batch([{"o": None}], track_id="test")
        assert len(res_none) == 1

        # Sequence wrap heuristic:
        # 1. Establish high sequence number
        pkt_high = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1000,
            "T": 1000,
            "s_seq": 50,
            "o": {
                "s": "BTCUSDT",
                "c": "c1",
                "X": "NEW",
            },
        }
        res_high = sequencer.sort_and_deduplicate_batch([pkt_high], track_id="test")
        assert len(res_high) == 1
        assert sequencer.highest_arrival_sequence == 50
        epoch_before = sequencer.session_epoch

        # 2. Sequence drops to 1 with t_time advancing: wrap detected and epoch incremented
        pkt_low = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 2000,
            "T": 2000,
            "s_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": "c2",
                "X": "NEW",
            },
        }
        res_low = sequencer.sort_and_deduplicate_batch([pkt_low], track_id="test")
        assert len(res_low) == 1
        assert sequencer.session_epoch > epoch_before

    def test_stream_drain_fallback_trade_id_synthesis(self, temp_telemetry_store, temp_jsonl_sink):
        """Verify that execution reports with missing or zero trade ID (t=0 or t=None)
        synthesize a fallback deterministic trade ID and process the fill.
        """
        gateway = MockBinanceContinuousGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
        reconciler = ContinuousUserDataStreamReconciler(track_id="test_fallback_tid")
        sequencer = ContinuousStreamSequencer()
        heartbeat_mon = GatewayHeartbeatMonitor()
        heartbeat_mon.record_heartbeat(
            server_time_ms=int(time.time() * 1000), latency_ms=5.0, track_id="test_fallback_tid"
        )
        interlock = ContinuousOrderDispatchInterlock(
            heartbeat_monitor=heartbeat_mon,
            reconciler=reconciler,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
        )
        dispatcher = ContinuousMicroOrderDispatcher(
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=temp_telemetry_store,
            jsonl_sink=temp_jsonl_sink,
            heartbeat_monitor=heartbeat_mon,
            interlock=interlock,
            track_id="test_fallback_tid",
        )

        cid = generate_canary_client_order_id("BTCUSDT", timestamp_ms=int(time.time() * 1000))
        rec = ContinuousOrderRecord(
            order_id="ord-fallback-1",
            client_order_id=cid,
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force=TimeInForce.GTC.value,
            price="60000.00",
            quantity="0.00008",
            notional_usdt="4.80000000",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
            track_id="test_fallback_tid",
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
        dispatcher.orders[cid] = rec
        gateway.orders[cid] = {"orderId": "4001", "status": "NEW", "symbol": "BTCUSDT"}

        # WebSocket ORDER_TRADE_UPDATE with t=0 (no trade ID specified)
        ws_event = {
            "e": "ORDER_TRADE_UPDATE",
            "E": int(time.time() * 1000),
            "T": int(time.time() * 1000),
            "s_seq": 1,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "o": "LIMIT",
                "X": "FILLED",
                "i": 4001,
                "l": "0.00008",
                "z": "0.00008",
                "L": "60000.00",
                "n": "0.0024",
                "T": int(time.time() * 1000),
                "t": 0,
            },
        }
        gateway.push_user_data_event(ws_event)
        dispatcher.drain_and_reconcile_stream()

        assert rec.status == OrderLifecycleState.FILLED
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
        assert reconciler.verify_zero_balance_drift()

        marks = temp_telemetry_store.get_execution_marks(track_id="test_fallback_tid")
        assert len(marks) == 1
        assert marks[0].trade_id.startswith(f"tr-ws-{cid}-")

    def test_telemetry_store_query_methods_and_context_manager(self, tmp_path: Path):
        """Verify context manager support and query methods on
        SqliteCanaryContinuousDaemonTelemetryStore.
        """
        db_path = tmp_path / "test_store_cm.sqlite3"
        with SqliteCanaryContinuousDaemonTelemetryStore(db_path) as store:
            track_result = ContinuousDaemonTrackResult(
                track_id="t1",
                track_name="Track 1",
                status="COMPLETED",
                starting_equity_usdt="1000.00",
                final_cash_usdt="1000.00",
                allocated_margin_usdt="0",
                unrealized_pnl_usdt="0",
                realized_pnl_usdt="0",
                total_fees_usdt="0",
                total_slippage_usdt="0",
                drift_usdt="0",
                zero_balance_drift=True,
                orders_placed_count=2,
                orders_filled_count=2,
                orders_cancelled_count=0,
                orders_rejected_count=0,
                interlock_blocks_count=0,
                heartbeat_events_count=10,
                stale_heartbeat_count=0,
                stream_events_count=5,
                deduplicated_events_count=0,
                out_of_order_events_count=0,
                final_circuit_state="NORMAL",
                final_expansion_stage="STAGE_1_CONCURRENT_MICRO",
                success=True,
            )
            store.record_daemon_track(track_result)

            snap = BalanceSnapshot(
                track_id="t1",
                cash_usdt="1000.00",
                allocated_margin_usdt="0",
                unrealized_pnl_usdt="0",
                realized_pnl_usdt="0",
                equity_usdt="1000.00",
                drift_usdt="0",
            )
            store.record_balance_snapshot(snap)

            cid = generate_canary_client_order_id("BTCUSDT", timestamp_ms=int(time.time() * 1000))
            ord_rec = ContinuousOrderRecord(
                order_id="ord-query-1",
                client_order_id=cid,
                candidate_id="cand-1",
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                time_in_force=TimeInForce.GTC.value,
                price="60000.00",
                quantity="0.00008",
                notional_usdt="4.80000000",
                status=OrderLifecycleState.FILLED,
                expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
                track_id="t1",
                created_at_utc=datetime.now(UTC).isoformat(),
                updated_at_utc=datetime.now(UTC).isoformat(),
            )
            store.record_order(ord_rec)

            tr_list = store.get_track_results("t1")
            assert len(tr_list) == 1
            assert tr_list[0].track_id == "t1"

            snap_list = store.get_balance_snapshots("t1")
            assert len(snap_list) == 1
            assert snap_list[0].track_id == "t1"

            ord_list = store.get_orders("t1")
            assert len(ord_list) == 1
            assert ord_list[0].client_order_id == cid
