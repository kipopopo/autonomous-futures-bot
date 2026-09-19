"""Unit tests for Phase 280: Production Canary Live Mainnet Micro-Execution Deployment Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 279, 278, 277, 276).
- Graduated capital ingress governance (Stage 1 seed <= 1.00 USDT, Stage 2 micro <= 5.00 USDT).
- Gateway heartbeat freshness monitoring (<= 500 ms) with 50 ms recovery hysteresis (<= 450 ms).
- Margin & reserve allocation ceilings (<= 20% asset, <= 60% portfolio, >= 40% reserve).
- Active working committed margin tracking across working and partially filled orders.
- Intra-phase cumulative loss ceiling (<= 1.50 USDT) and emergency micro-chunked liquidation.
- Dual-confirmation client order tagging format (c=canary-p280-{sym}-{ts}-{uuid}).
- WebSocket network flap & automatic reconnect with REST order state reconciliation.
- Monotonic order lifecycle state transitions and trade ID / fingerprint deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT).
- Strict fail-closed containment invariants (execution_authority: False, orders: 0, keys: 0).
"""

from __future__ import annotations

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
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
)
from autonomous_futures.feed.mainnet_deployment import (  # noqa: E402
    DEFAULT_PHASE280_OUTPUT_DIR,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    CanaryMainnetDeploymentConfig,
    CanaryMainnetDeploymentRunner,
    CircuitBreakerState,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    GraduatedIngressStage,
    HeartbeatStatus,
    IntraPhaseLossCeilingExceededError,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    MainnetExecutionMark,
    MainnetMicroOrderDispatcher,
    MainnetOrderDispatchInterlock,
    MainnetOrderRecord,
    MainnetStreamSequencer,
    MainnetUserDataStreamReconciler,
    MarginAllocationExceededError,
    MockBinanceMainnetGateway,
    NotionalCapExceededError,
    OrderLifecycleState,
    SeedProbeCapExceededError,
    SqliteCanaryMainnetDeploymentTelemetryStore,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_280_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_280_mainnet_deployment import (  # noqa: E402
    execute_phase_280_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-telemetry.sqlite3"
    store = SqliteCanaryMainnetDeploymentTelemetryStore(db_path)
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
    assert cid == "c=canary-p280-BTCUSDT-1700000000000-abc12345"

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

    # Invalid prefix format
    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id("c=canary-p279-BTCUSDT-1700000000000-abc12345")

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

    # Recovery hysteresis: 480 ms is <= 500 ms but > 450 ms recovery ceiling!
    mon.set_simulated_stale_age(480.0)
    assert mon.is_fresh() is False  # Must remain stale due to 50 ms recovery hysteresis

    # Recover when age <= 450 ms
    mon.set_simulated_stale_age(440.0)
    assert mon.is_fresh() is True


# =====================================================================
# 3. Graduated Capital Ingress Governance Tests
# =====================================================================


def test_graduated_ingress_stage_1_seed_probe_cap(temp_telemetry_store):
    reconciler = MainnetUserDataStreamReconciler(track_id="test_probe")
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_probe",
        ingress_stage=GraduatedIngressStage.STAGE_1_SEED_PROBE,
    )

    # Valid Stage 1 order <= 1.00 USDT (0.000015 @ 60,000 = 0.90 USDT)
    cid_valid = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.000015"),
        client_order_id=cid_valid,
    )

    # Invalid Stage 1 order > 1.00 USDT (0.000020 @ 60,000 = 1.20 USDT)
    cid_exceed = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(SeedProbeCapExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.000020"),
            client_order_id=cid_exceed,
        )
    assert "exceeds Stage 1 seed probe cap of 1.00 USDT" in str(exc_info.value)

    # Once graduated to Stage 2, order > 1.00 USDT but <= 5.00 USDT is permitted
    interlock.ingress_stage = GraduatedIngressStage.STAGE_2_STEPPED_MICRO
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.000020"),
        client_order_id=cid_exceed,
    )


def test_graduated_ingress_stage_2_hard_micro_cap(temp_telemetry_store):
    reconciler = MainnetUserDataStreamReconciler(track_id="test_micro")
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_micro",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
    )

    # Valid Stage 2 order <= 5.00 USDT (0.00008 @ 60,000 = 4.80 USDT)
    cid_valid = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.00008"),
        client_order_id=cid_valid,
    )

    # Invalid Stage 2 order > 5.00 USDT (0.00010 @ 60,000 = 6.00 USDT)
    cid_invalid = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(NotionalCapExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00010"),
            client_order_id=cid_invalid,
        )
    assert "exceeds hard micro notional cap of 5.00 USDT" in str(exc_info.value)


# =====================================================================
# 4. Active Working Committed Margin & Reserve Buffer Tests
# =====================================================================


def test_active_working_committed_margin_and_reserve(temp_telemetry_store):
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_margin", starting_equity=Decimal("100.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    # Simulate existing active working order of 18.00 USDT on BTCUSDT
    mock_orders: dict[str, MainnetOrderRecord] = {
        "c=canary-p280-BTCUSDT-1-abc": MainnetOrderRecord(
            order_id="ord-1",
            client_order_id="c=canary-p280-BTCUSDT-1-abc",
            track_id="test_margin",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="60000.00",
            quantity="0.0003",  # 18.00 USDT
            executed_quantity="0",
            notional_usdt="18.00",
            status=OrderLifecycleState.NEW,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
    }

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_margin",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        orders_provider=lambda: mock_orders,
    )

    # Committed working margin for BTCUSDT is 18.00 USDT
    assert interlock.get_working_committed_margin("BTCUSDT") == Decimal("18.00000000")

    # Adding 4.80 USDT exceeds 20.00% asset cap (18.00 + 4.80 = 22.80 > 20.00)!
    cid_new = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MarginAllocationExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),
            client_order_id=cid_new,
        )
    assert "breaches per-asset cap" in str(exc_info.value)


# =====================================================================
# 5. Intra-Phase Loss Ceiling & Emergency Micro-Chunked Flattening
# =====================================================================


def test_intra_phase_loss_ceiling_and_flattening(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMainnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = MainnetUserDataStreamReconciler(track_id="test_loss")
    sequencer = MainnetStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_loss",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        intra_phase_loss_ceiling_usdt=Decimal("1.50"),
    )
    dispatcher = MainnetMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_loss",
    )

    # 1. Open 0.00016 BTCUSDT @ 60,000 (two orders)
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00016")

    # 2. Close 0.00008 BTCUSDT @ 40,000 -> loss = 1.60 USDT > 1.50 USDT ceiling!
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("40000.00"),
        is_closing=True,
    )
    assert reconciler.cumulative_realized_loss == Decimal("1.60000000")
    assert reconciler.cumulative_realized_loss > interlock.intra_phase_loss_ceiling_usdt

    # 3. Next dispatch attempt triggers fail-closed lockout
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.030"),
            price=Decimal("150.00"),
        )
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

    # 4. Emergency micro-chunked position liquidation
    flatten_orders = dispatcher.execute_emergency_flattening()
    assert len(flatten_orders) >= 1
    for fo in flatten_orders:
        assert Decimal(fo.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 6. WebSocket Flap & REST Order State Reconciliation Tests
# =====================================================================


def test_websocket_flap_and_rest_reconciliation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMainnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = MainnetUserDataStreamReconciler(track_id="test_flap")
    sequencer = MainnetStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_flap",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
    )
    dispatcher = MainnetMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_flap",
    )

    # Disconnect stream (network flap)
    gateway.disconnect_stream()
    cid = generate_canary_client_order_id("BTCUSDT")

    # Order dispatched while stream disconnected
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        client_order_id=cid,
    )
    # Order remains NEW locally because push events could not arrive via WS
    assert ord_rec.status == OrderLifecycleState.NEW

    # Reconnect stream & perform REST reconciliation
    gateway.reconnect_stream()
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert ord_rec.status == OrderLifecycleState.FILLED
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

    # Drain stream: buffered events deduplicated cleanly without error
    dispatcher.drain_and_reconcile_stream()
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")  # No double counting
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 7. Exact Double-Entry Balance Accounting Invariant Tests
# =====================================================================


def test_exact_double_entry_balance_reconciliation():
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_ledger",
        starting_equity=Decimal("100.00"),
    )
    assert reconciler.mathematical_drift == Decimal("0")

    # 1. Simulate BUY fill of 0.00008 BTC @ 60,000 (notional 4.80 USDT, taker fee 0.00192 USDT)
    mark_buy = MainnetExecutionMark(
        trade_id="tr-1",
        track_id="test_ledger",
        order_id="ord-1",
        client_order_id="c=canary-p280-BTCUSDT-1-abc",
        symbol="BTCUSDT",
        side="BUY",
        price="60000.00",
        quantity="0.00008",
        quote_quantity="4.80000000",
        commission_usdt="0.00192000",
        realized_pnl_usdt="0",
        trade_time_ms=int(time.time() * 1000),
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(mark_buy)
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
    assert reconciler.allocated_margin == Decimal("4.80000000")
    assert reconciler.cash == Decimal("95.19808000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 2. Simulate SELL fill of 0.00008 BTC @ 65,000 (gain 0.40 USDT, fee 0.00208 USDT)
    mark_sell = MainnetExecutionMark(
        trade_id="tr-2",
        track_id="test_ledger",
        order_id="ord-2",
        client_order_id="c=canary-p280-BTCUSDT-2-abc",
        symbol="BTCUSDT",
        side="SELL",
        price="65000.00",
        quantity="0.00008",
        quote_quantity="5.20000000",
        commission_usdt="0.00208000",
        realized_pnl_usdt="0.40000000",
        trade_time_ms=int(time.time() * 1000),
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(mark_sell)
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 8. Full Runner & Merkle DAG Hash Chain Ingress Tests
# =====================================================================


def test_full_phase_280_runner_and_hash_chain(tmp_path: Path):
    cfg = CanaryMainnetDeploymentConfig(
        output_dir=tmp_path / "artifacts_p280",
        track="all",
    )
    runner = CanaryMainnetDeploymentRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.phase == "phase_280"
    assert len(report.tracks) == 4
    assert all(t.success for t in report.tracks)
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True
    assert report.compliance["mainnet_deployment_verified"] is True
    assert report.compliance["graduated_ingress_governance_verified"] is True

    # Verify cryptographic SHA-256 DAG hash chain
    hash_ok = verify_phase_280_hash_chain(
        output_dir=cfg.output_dir,
        manifest_path=cfg.manifest_path,
        phase276_dir=cfg.phase276_input_dir,
        phase277_dir=cfg.phase277_input_dir,
        phase278_dir=cfg.phase278_input_dir,
        phase279_dir=cfg.phase279_input_dir,
    )
    assert hash_ok is True


def test_adverse_drift_detection_fail_closed(tmp_path: Path):
    cfg = CanaryMainnetDeploymentConfig(
        output_dir=tmp_path / "drift_fail",
        track="track_1",
        simulate_adverse_drift=True,
    )
    runner = CanaryMainnetDeploymentRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.tracks[0].success is False
    assert report.tracks[0].zero_balance_drift is False
    assert report.compliance["all_criteria_passed"] is False


def test_cli_execute_phase_280_runner_verify_only():
    # Verify execution against default artifacts directory
    exit_code = execute_phase_280_runner(
        output_dir=DEFAULT_PHASE280_OUTPUT_DIR,
        verify_only=True,
    )
    assert exit_code == 0
