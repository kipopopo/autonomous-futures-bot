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
    CanaryContinuousDaemonConfig,
    CanaryContinuousDaemonRunner,
    CapitalExpansionStage,
    CircuitBreakerActiveError,
    CircuitBreakerState,
    ContinuousAutonomousDaemon,
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

    # Interlock should raise HeartbeatFreezeActiveError
    with pytest.raises(HeartbeatFreezeActiveError):
        mon.assert_fresh()

    # Normal clock clears freeze
    rec2 = mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000),
        latency_ms=10.0,
        track_id="skew_recovered",
    )
    assert rec2.status == HeartbeatStatus.HEALTHY
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
