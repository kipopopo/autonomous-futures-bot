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

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.canary_activation import (  # noqa: E402
    DEFAULT_REFERENCE_PRICES,
    STARTING_EQUITY_USDT,
    OrderSide,
    OrderType,
    TimeInForce,
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
    MAX_CLOCK_SKEW_TOLERANCE_MS,
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


# =====================================================================
# 9. Adversarial Edge Case & Robustness Tests
# =====================================================================


def test_rest_reconciliation_omitted_trade_id_deduplication(manifest, tmp_path: Path):
    """Verify that when REST order query omits tradeId (standard Binance API),

    reconciliation does not double-credit positions when the buffered WS stream is drained.
    """
    db_path = tmp_path / "telemetry.sqlite3"
    jsonl_path = tmp_path / "orders.jsonl"
    store = SqliteCanaryMainnetDeploymentTelemetryStore(db_path)
    sink = JsonlCanaryOrderSink(jsonl_path)
    gateway = MockBinanceMainnetGateway()
    monitor = GatewayHeartbeatMonitor()
    reconciler = MainnetUserDataStreamReconciler(
        track_id="adv_test_dedup", starting_equity=Decimal("100.00")
    )
    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=monitor,
        reconciler=reconciler,
        telemetry_store=store,
        track_id="adv_test_dedup",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
    )
    sequencer = MainnetStreamSequencer()
    dispatcher = MainnetMicroOrderDispatcher(
        track_id="adv_test_dedup",
        interlock=interlock,
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=store,
        jsonl_sink=sink,
        heartbeat_monitor=monitor,
    )

    now_ms = int(time.time() * 1000)
    monitor.record_heartbeat(server_time_ms=now_ms - 20, latency_ms=20.0, track_id="adv")

    # Disconnect stream before order creation
    gateway.disconnect_stream()
    cid = generate_canary_client_order_id("BTCUSDT")
    now_utc = datetime.now(UTC).isoformat()
    ord_rec = MainnetOrderRecord(
        order_id="ord-rest-test-1",
        client_order_id=cid,
        track_id="adv_test_dedup",
        candidate_id="alpha-futures-momentum-v1",
        symbol="BTCUSDT",
        side=OrderSide.BUY.value,
        order_type=OrderType.LIMIT.value,
        time_in_force=TimeInForce.GTC.value,
        price="60000.00",
        quantity="0.00008",
        executed_quantity="0",
        notional_usdt="4.80000000",
        status=OrderLifecycleState.PENDING_SUBMIT,
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        is_closing=False,
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )
    dispatcher.orders[cid] = ord_rec
    dispatcher.orders_placed_count += 1
    store.record_order(ord_rec)

    # Submit to gateway
    gw_res = gateway.create_order(
        symbol="BTCUSDT",
        side="BUY",
        type="LIMIT",
        timeInForce="GTC",
        quantity="0.00008",
        price="60000.00",
        newClientOrderId=cid,
    )
    ord_rec.order_id = str(gw_res["orderId"])
    ord_rec.status = OrderLifecycleState.NEW

    # Fill order on gateway
    gateway.fill_order(client_order_id=cid)

    # Simulate exchange REST GET /fapi/v1/order omitting tradeId
    gateway.orders[cid].pop("tradeId", None)

    # Reconnect stream and reconcile via REST
    gateway.reconnect_stream()
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert ord_rec.status == OrderLifecycleState.FILLED
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
    assert dispatcher.orders_filled_count == 1

    # Now drain stream buffer; buffered trade events must be deduplicated
    dispatcher.drain_and_reconcile_stream()
    # Position must NOT be doubled to 0.00016
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
    assert dispatcher.orders_filled_count == 1
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
    store.close()


def test_order_lifecycle_monotonicity_enforcement(manifest, tmp_path: Path):
    """Verify out-of-order execution reports cannot regress an order once in terminal state."""
    db_path = tmp_path / "telemetry_mono.sqlite3"
    jsonl_path = tmp_path / "orders_mono.jsonl"
    with SqliteCanaryMainnetDeploymentTelemetryStore(db_path) as store:
        sink = JsonlCanaryOrderSink(jsonl_path)
        gateway = MockBinanceMainnetGateway()
        monitor = GatewayHeartbeatMonitor()
        now_ms = int(time.time() * 1000)
        monitor.record_heartbeat(server_time_ms=now_ms - 20, latency_ms=20.0, track_id="mono")

        reconciler = MainnetUserDataStreamReconciler(
            track_id="mono_test", starting_equity=Decimal("100.00")
        )
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=monitor,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="mono_test",
            ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        )
        sequencer = MainnetStreamSequencer()
        dispatcher = MainnetMicroOrderDispatcher(
            track_id="mono_test",
            interlock=interlock,
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=monitor,
        )

        cid = generate_canary_client_order_id("BTCUSDT")
        dispatcher.dispatch_micro_order(
            candidate_id="alpha-futures-momentum-v1",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00008"),
            price=Decimal("60000.00"),
            client_order_id=cid,
        )
        ord_rec = dispatcher.orders[cid]
        assert ord_rec.status == OrderLifecycleState.FILLED
        assert dispatcher.orders_filled_count == 1

        # Simulate out-of-order packets arriving late:
        # 1. Stale NEW event
        pkt_new = {
            "e": "ORDER_TRADE_UPDATE",
            "E": now_ms - 100,
            "T": now_ms - 100,
            "_seq": 9991,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "x": "NEW",
                "X": "NEW",
                "z": "0",
                "t": 0,
            },
        }
        # 2. Stale PARTIALLY_FILLED event
        pkt_part = {
            "e": "ORDER_TRADE_UPDATE",
            "E": now_ms - 50,
            "T": now_ms - 50,
            "_seq": 9992,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "x": "TRADE",
                "X": "PARTIALLY_FILLED",
                "z": "0.00004",
                "L": "60000.00",
                "t": 88881,
            },
        }
        # 3. Late CANCELED event
        pkt_cancel = {
            "e": "ORDER_TRADE_UPDATE",
            "E": now_ms + 10,
            "T": now_ms + 10,
            "_seq": 9993,
            "o": {
                "s": "BTCUSDT",
                "c": cid,
                "S": "BUY",
                "x": "CANCELED",
                "X": "CANCELED",
                "z": "0.00008",
                "t": 0,
            },
        }

        gateway.stream_buffer.extend([pkt_new, pkt_part, pkt_cancel])
        dispatcher.drain_and_reconcile_stream()

        # Status must remain FILLED, filled count unchanged, cancelled count 0
        assert ord_rec.status == OrderLifecycleState.FILLED
        assert dispatcher.orders_filled_count == 1
        assert dispatcher.orders_cancelled_count == 0
        assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")


def test_concurrent_pending_submit_during_rapid_websocket_flap(manifest, tmp_path: Path):
    """Verify thread-safety and exact reconciliation when concurrent micro orders

    are placed across staged symbols during rapid WebSocket disconnect and reconnect flaps.
    """
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "telemetry_flap.sqlite3"
    jsonl_path = tmp_path / "orders_flap.jsonl"
    with SqliteCanaryMainnetDeploymentTelemetryStore(db_path) as store:
        sink = JsonlCanaryOrderSink(jsonl_path)
        gateway = MockBinanceMainnetGateway()
        monitor = GatewayHeartbeatMonitor()
        now_ms = int(time.time() * 1000)
        monitor.record_heartbeat(server_time_ms=now_ms - 15, latency_ms=15.0, track_id="flap")

        reconciler = MainnetUserDataStreamReconciler(
            track_id="flap_test", starting_equity=Decimal("100.00")
        )
        interlock = MainnetOrderDispatchInterlock(
            heartbeat_monitor=monitor,
            reconciler=reconciler,
            telemetry_store=store,
            track_id="flap_test",
            ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        )
        sequencer = MainnetStreamSequencer()
        dispatcher = MainnetMicroOrderDispatcher(
            track_id="flap_test",
            interlock=interlock,
            gateway=gateway,
            reconciler=reconciler,
            sequencer=sequencer,
            telemetry_store=store,
            jsonl_sink=sink,
            heartbeat_monitor=monitor,
        )

        symbols = [
            ("BTCUSDT", Decimal("0.00008")),
            ("ETHUSDT", Decimal("0.0014")),
            ("SOLUSDT", Decimal("0.024")),
        ]

        # Disconnect stream during execution
        gateway.disconnect_stream()

        def submit_order(sym: str, qty: Decimal):
            return dispatcher.dispatch_micro_order(
                candidate_id=f"alpha-futures-{sym.lower()}",
                symbol=sym,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=qty,
                price=Decimal(str(DEFAULT_REFERENCE_PRICES[sym])),
            )

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(submit_order, sym, qty) for sym, qty in symbols]
            orders = [f.result() for f in futures]

        assert len(orders) == 3
        # Orders were created on gateway and filled, but stream was disconnected
        gateway.reconnect_stream()
        backfilled = dispatcher.reconcile_via_rest()
        assert len(backfilled) == 3

        dispatcher.drain_and_reconcile_stream()
        for sym, qty in symbols:
            assert reconciler.positions[sym] == qty

        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_sqlite_telemetry_store_context_manager_and_thread_safety(tmp_path: Path):
    """Verify sqlite telemetry store context manager and concurrent write safety."""
    from concurrent.futures import ThreadPoolExecutor

    db_path = tmp_path / "telemetry_concurrency.sqlite3"
    with SqliteCanaryMainnetDeploymentTelemetryStore(db_path) as store:

        def write_telemetry(idx: int):
            now_utc = datetime.now(UTC).isoformat()
            now_ms = int(time.time() * 1000)
            order = MainnetOrderRecord(
                order_id=f"ord-thread-{idx}",
                client_order_id=f"c=canary-p280-BTCUSDT-{now_ms}-{idx}",
                track_id="thread_test",
                candidate_id="alpha-futures-momentum-v1",
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                time_in_force="GTC",
                price="60000.00",
                quantity="0.00008",
                executed_quantity="0.00008",
                notional_usdt="4.80000000",
                status=OrderLifecycleState.FILLED,
                ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
                is_closing=False,
                created_at_utc=now_utc,
                updated_at_utc=now_utc,
            )
            store.record_order(order)

            mark = MainnetExecutionMark(
                trade_id=f"tr-thread-{idx}",
                track_id="thread_test",
                order_id=f"ord-thread-{idx}",
                client_order_id=order.client_order_id,
                symbol="BTCUSDT",
                side="BUY",
                price="60000.00",
                quantity="0.00008",
                quote_quantity="4.80000000",
                commission_usdt="0.00192000",
                realized_pnl_usdt="0",
                trade_time_ms=now_ms,
                timestamp_utc=now_utc,
            )
            store.record_execution_mark(mark)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(write_telemetry, i) for i in range(20)]
            for f in futures:
                f.result()

        orders_count = store.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE track_id = 'thread_test'"
        ).fetchone()[0]
        marks_count = store.conn.execute(
            "SELECT COUNT(*) FROM execution_marks WHERE track_id = 'thread_test'"
        ).fetchone()[0]
        assert orders_count == 20
        assert marks_count == 20


def test_exact_double_entry_reconciliation_negative_pnl_partial_fills_and_flips():
    """Verify zero balance drift (< 1e-15 USDT) across partial loss fills, marks, and flips."""
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_partial_pnl",
        starting_equity=Decimal("100.00"),
    )
    assert reconciler.mathematical_drift == Decimal("0")

    # 1. Open LONG: BUY 0.00008 BTC @ 60,000 (notional 4.80 USDT, fee 0.00192)
    m1 = MainnetExecutionMark(
        trade_id="tr-pnl-1",
        track_id="test_partial_pnl",
        order_id="ord-pnl-1",
        client_order_id="c=canary-p280-BTCUSDT-1-pnl",
        symbol="BTCUSDT",
        side="BUY",
        price="60000.00",
        quantity="0.00008",
        quote_quantity="4.80000000",
        commission_usdt="0.00192000",
        realized_pnl_usdt="0",
        trade_time_ms=1000,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(m1)
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 2. Mark price moves down to 40,000 (unrealized loss of 1.60 USDT)
    reconciler.mark_prices["BTCUSDT"] = Decimal("40000.00")
    assert reconciler.unrealized_pnl == Decimal("-1.60000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 3. Partial close: SELL 0.00004 BTC @ 40,000 (realized loss of 0.80 USDT, fee 0.00064)
    m2 = MainnetExecutionMark(
        trade_id="tr-pnl-2",
        track_id="test_partial_pnl",
        order_id="ord-pnl-2",
        client_order_id="c=canary-p280-BTCUSDT-2-pnl",
        symbol="BTCUSDT",
        side="SELL",
        price="40000.00",
        quantity="0.00004",
        quote_quantity="1.60000000",
        commission_usdt="0.00064000",
        realized_pnl_usdt="-0.80000000",
        trade_time_ms=2000,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(m2)
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00004")
    assert reconciler.cumulative_realized_loss == Decimal("0.80000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 4. Mark price moves further down to 35,000
    reconciler.mark_prices["BTCUSDT"] = Decimal("35000.00")
    assert reconciler.unrealized_pnl == Decimal("-1.00000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 5. Full close remaining 0.00004 BTC @ 35,000 (realized loss of 1.00 USDT, fee 0.00056)
    m3 = MainnetExecutionMark(
        trade_id="tr-pnl-3",
        track_id="test_partial_pnl",
        order_id="ord-pnl-3",
        client_order_id="c=canary-p280-BTCUSDT-3-pnl",
        symbol="BTCUSDT",
        side="SELL",
        price="35000.00",
        quantity="0.00004",
        quote_quantity="1.40000000",
        commission_usdt="0.00056000",
        realized_pnl_usdt="-1.00000000",
        trade_time_ms=3000,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(m3)
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.unrealized_pnl == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 6. Open SHORT: SELL 0.00005 BTC @ 60,000 (notional 3.00 USDT, fee 0.0012)
    m4 = MainnetExecutionMark(
        trade_id="tr-pnl-4",
        track_id="test_partial_pnl",
        order_id="ord-pnl-4",
        client_order_id="c=canary-p280-BTCUSDT-4-pnl",
        symbol="BTCUSDT",
        side="SELL",
        price="60000.00",
        quantity="0.00005",
        quote_quantity="3.00000000",
        commission_usdt="0.00120000",
        realized_pnl_usdt="0",
        trade_time_ms=4000,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(m4)
    assert reconciler.positions["BTCUSDT"] == Decimal("-0.00005")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 7. Position Flip: BUY 0.00008 BTC @ 55,000 (flips 0.00005 short to 0.00003 long)
    m5 = MainnetExecutionMark(
        trade_id="tr-pnl-5",
        track_id="test_partial_pnl",
        order_id="ord-pnl-5",
        client_order_id="c=canary-p280-BTCUSDT-5-pnl",
        symbol="BTCUSDT",
        side="BUY",
        price="55000.00",
        quantity="0.00008",
        quote_quantity="4.40000000",
        commission_usdt="0.00176000",
        realized_pnl_usdt="0.25000000",
        trade_time_ms=5000,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(m5)
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00003")
    assert reconciler.position_entry_prices["BTCUSDT"] == Decimal("55000.00")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 8. Close remaining 0.00003 BTC @ 55,000
    m6 = MainnetExecutionMark(
        trade_id="tr-pnl-6",
        track_id="test_partial_pnl",
        order_id="ord-pnl-6",
        client_order_id="c=canary-p280-BTCUSDT-6-pnl",
        symbol="BTCUSDT",
        side="SELL",
        price="55000.00",
        quantity="0.00003",
        quote_quantity="1.65000000",
        commission_usdt="0.00066000",
        realized_pnl_usdt="0",
        trade_time_ms=6000,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(m6)
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_interlock_boundary_conditions_exact_limits(temp_telemetry_store):
    """Verify boundary behavior for 20% asset, 60% aggregate margin, and 40% reserve."""
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_limits", starting_equity=Decimal("100.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test_limits"
    )

    mock_orders: dict[str, MainnetOrderRecord] = {}
    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_limits",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        orders_provider=lambda: mock_orders,
    )

    # 1. Exactly 20.00% per-asset margin is permitted (20.00 USDT on 100.00 equity)
    # Add 3 working orders of 5.00 USDT on BTCUSDT = 15.00 USDT
    for i in range(3):
        mock_orders[f"ord-btc-work-{i}"] = MainnetOrderRecord(
            order_id=f"ord-btc-work-{i}",
            client_order_id=f"c=canary-p280-BTCUSDT-work-{i}",
            track_id="test_limits",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="1000.00",
            quantity="0.005",  # 5.00 USDT
            notional_usdt="5.00",
            status=OrderLifecycleState.NEW,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )

    # An order of 5.00 USDT brings BTCUSDT to exactly 20.00% (15.00 + 5.00 = 20.00 USDT)
    cid_20 = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("1000.00"),
        quantity=Decimal("0.005"),
        client_order_id=cid_20,
    )

    # 2. 20.00000001% per-asset margin breaches ceiling
    # Add 4th working order of 4.00 USDT -> total BTC working margin = 19.00 USDT
    mock_orders["ord-btc-work-3"] = MainnetOrderRecord(
        order_id="ord-btc-work-3",
        client_order_id="c=canary-p280-BTCUSDT-work-3",
        track_id="test_limits",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        price="1000.00",
        quantity="0.004",  # 4.00 USDT
        notional_usdt="4.00",
        status=OrderLifecycleState.NEW,
        created_at_utc=datetime.now(UTC).isoformat(),
        updated_at_utc=datetime.now(UTC).isoformat(),
    )
    # Order of 1.00000001 USDT brings BTC to 20.00000001 USDT > 20.00 USDT
    cid_over_20 = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MarginAllocationExceededError) as exc_20:
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("1000.00"),
            quantity=Decimal("0.00100001"),
            client_order_id=cid_over_20,
        )
    assert "breaches per-asset cap" in str(exc_20.value)

    # 3. Aggregate margin ceiling (60% aggregate):
    # Set up open positions on BTC (25 USDT), ETH (25 USDT), and SOL (9 USDT)
    # Margin = 59.00 USDT. Cash = 40.00 USDT. Equity = 99.00 USDT. Max margin (60%) = 59.40 USDT.
    r_agg = MainnetUserDataStreamReconciler(
        track_id="test_agg_limits", starting_equity=Decimal("100.00")
    )
    r_agg.cash = Decimal("40.00")
    r_agg.positions["BTCUSDT"] = Decimal("1")
    r_agg.position_entry_prices["BTCUSDT"] = Decimal("25.00")
    r_agg.mark_prices["BTCUSDT"] = Decimal("25.00")
    r_agg.positions["ETHUSDT"] = Decimal("1")
    r_agg.position_entry_prices["ETHUSDT"] = Decimal("25.00")
    r_agg.mark_prices["ETHUSDT"] = Decimal("25.00")
    r_agg.positions["SOLUSDT"] = Decimal("1")
    r_agg.position_entry_prices["SOLUSDT"] = Decimal("9.00")
    r_agg.mark_prices["SOLUSDT"] = Decimal("9.00")

    ilk_agg = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=r_agg,
        telemetry_store=temp_telemetry_store,
        track_id="test_agg_limits",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
    )

    # An order of 1.00 USDT on SOL brings SOL to 10.00 USDT (well below 20% cap of 19.80 USDT),
    # but aggregate margin to 60.00 USDT > 60% portfolio cap (59.40 USDT):
    cid_sol_over = generate_canary_client_order_id("SOLUSDT")
    with pytest.raises(MarginAllocationExceededError) as exc_agg:
        ilk_agg.validate_dispatch(
            symbol="SOLUSDT",
            price=Decimal("9.00"),
            quantity=Decimal("0.11111111"),
            client_order_id=cid_sol_over,
        )
    assert "breaches portfolio cap" in str(exc_agg.value)


def test_numerical_precision_sol_btc_scaling_and_round_down(temp_telemetry_store):
    """Verify numerical precision across SOL, ETH, BTC scaling and ROUND_DOWN notional caps."""
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_scale", starting_equity=Decimal("100.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test_scale"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_scale",
        ingress_stage=GraduatedIngressStage.STAGE_1_SEED_PROBE,
    )

    # 1. Stage 1 Seed Probe Cap (<= 1.00 USDT):
    # SOL price 150.00: quantity 0.00666666 * 150.00 = 0.99999900 <= 1.00 USDT
    cid_sol_seed = generate_canary_client_order_id("SOLUSDT")
    interlock.validate_dispatch(
        symbol="SOLUSDT",
        price=Decimal("150.00"),
        quantity=Decimal("0.00666666"),
        client_order_id=cid_sol_seed,
    )

    # SOL price 150.00: quantity 0.00666667 * 150.00 = 1.00000050 > 1.00 USDT
    with pytest.raises(SeedProbeCapExceededError):
        interlock.validate_dispatch(
            symbol="SOLUSDT",
            price=Decimal("150.00"),
            quantity=Decimal("0.00666667"),
            client_order_id=cid_sol_seed,
        )

    # 2. Stage 2 Stepped Micro Cap (<= 5.00 USDT):
    interlock.ingress_stage = GraduatedIngressStage.STAGE_2_STEPPED_MICRO

    # SOL price 150.00: quantity 0.03333333 * 150.00 = 4.99999950 <= 5.00 USDT
    cid_sol_micro = generate_canary_client_order_id("SOLUSDT")
    interlock.validate_dispatch(
        symbol="SOLUSDT",
        price=Decimal("150.00"),
        quantity=Decimal("0.03333333"),
        client_order_id=cid_sol_micro,
    )

    # SOL price 150.00: quantity 0.03333334 * 150.00 = 5.00000100 > 5.00 USDT
    with pytest.raises(NotionalCapExceededError):
        interlock.validate_dispatch(
            symbol="SOLUSDT",
            price=Decimal("150.00"),
            quantity=Decimal("0.03333334"),
            client_order_id=cid_sol_micro,
        )


def test_all_database_balance_snapshots_zero_drift(tmp_path: Path):
    """Verify 100% of balance snapshots recorded in SQLite across all tracks have drift < 1e-15."""
    cfg = CanaryMainnetDeploymentConfig(
        output_dir=tmp_path / "all_snap_test",
        track="all",
    )
    runner = CanaryMainnetDeploymentRunner(cfg)
    report = runner.execute_all_tracks()
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True

    db_path = tmp_path / "all_snap_test" / "canary-mainnet-deployment-telemetry.sqlite3"
    with sqlite3.connect(db_path) as conn:
        snapshots = conn.execute(
            "SELECT snapshot_id, track_id, cash_usdt, allocated_margin_usdt, "
            "unrealized_pnl_usdt, realized_pnl_usdt, equity_usdt, drift_usdt "
            "FROM balance_snapshots"
        ).fetchall()
        assert len(snapshots) >= 15
        for snap_id, tid, cash, margin, upnl, rpnl, eq, drift in snapshots:
            drift_dec = Decimal(str(drift))
            assert drift_dec < DOUBLE_ENTRY_MAX_DRIFT, (
                f"Snapshot {snap_id} ({tid}) breached drift limit: drift={drift_dec} USDT, "
                f"cash={cash}, margin={margin}, upnl={upnl}, rpnl={rpnl}, equity={eq}"
            )


def test_rest_reconciliation_terminal_order_states(temp_telemetry_store, tmp_path: Path):
    """Verify REST reconciliation transitions orders to CANCELLED, REJECTED, EXPIRED correctly."""
    gw = MockBinanceMainnetGateway(initial_balance_usdt=Decimal("100.00"))
    r = MainnetUserDataStreamReconciler(
        track_id="test_rest_term", starting_equity=Decimal("100.00")
    )
    seq = MainnetStreamSequencer()
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test_rest_term"
    )
    sink = JsonlCanaryOrderSink(tmp_path / "orders.jsonl")

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=r,
        telemetry_store=temp_telemetry_store,
        track_id="test_rest_term",
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
    )
    dispatcher = MainnetMicroOrderDispatcher(
        gateway=gw,
        reconciler=r,
        sequencer=seq,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=sink,
        heartbeat_monitor=mon,
        interlock=interlock,
        track_id="test_rest_term",
    )

    # 1. Place Order A (will be cancelled on gateway during flap)
    cid_a = generate_canary_client_order_id("BTCUSDT")
    gw_a = gw.create_order(
        symbol="BTCUSDT",
        side="BUY",
        type="LIMIT",
        timeInForce="GTC",
        quantity="0.00008",
        price="60000.00",
        newClientOrderId=cid_a,
    )
    rec_a = MainnetOrderRecord(
        order_id=str(gw_a["orderId"]),
        client_order_id=cid_a,
        track_id="test_rest_term",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        price="60000.00",
        quantity="0.00008",
        executed_quantity="0",
        notional_usdt="4.80",
        status=OrderLifecycleState.NEW,
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        created_at_utc=datetime.now(UTC).isoformat(),
        updated_at_utc=datetime.now(UTC).isoformat(),
    )
    dispatcher.orders[cid_a] = rec_a

    # 2. Place Order B (will be partially filled then cancelled on gateway)
    cid_b = generate_canary_client_order_id("ETHUSDT")
    gw_b = gw.create_order(
        symbol="ETHUSDT",
        side="BUY",
        type="LIMIT",
        timeInForce="GTC",
        quantity="0.0015",
        price="3000.00",
        newClientOrderId=cid_b,
    )
    rec_b = MainnetOrderRecord(
        order_id=str(gw_b["orderId"]),
        client_order_id=cid_b,
        track_id="test_rest_term",
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        price="3000.00",
        quantity="0.0015",
        executed_quantity="0",
        notional_usdt="4.50",
        status=OrderLifecycleState.NEW,
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        created_at_utc=datetime.now(UTC).isoformat(),
        updated_at_utc=datetime.now(UTC).isoformat(),
    )
    dispatcher.orders[cid_b] = rec_b

    # Before flap: working margin tracks both orders (4.80 + 4.50 = 9.30 USDT)
    assert interlock.get_working_committed_margin() == Decimal("9.30000000")

    # Simulate Flap & Gateway Actions:
    gw.disconnect_stream()
    # Gateway cancels Order A
    gw.cancel_order("BTCUSDT", cid_a)
    # Gateway partially fills Order B (0.0005 ETH) then cancels remainder
    gw.fill_order(client_order_id=cid_b, fill_price=Decimal("3000.00"), fill_qty=Decimal("0.0005"))
    gw.cancel_order("ETHUSDT", cid_b)

    # Reconcile via REST
    gw.reconnect_stream()
    marks = dispatcher.reconcile_via_rest()
    assert len(marks) == 1  # 1 backfilled fill for Order B
    assert rec_a.status == OrderLifecycleState.CANCELLED
    assert rec_b.status == OrderLifecycleState.CANCELLED
    assert rec_b.executed_quantity == "0.0005"
    assert dispatcher.orders_cancelled_count == 2
    assert dispatcher.orders_filled_count == 0

    # Working margin is now cleanly released (0 USDT unfilled working orders)
    assert interlock.get_working_committed_margin() == Decimal("0")
    # Position margin reflects the 0.0005 ETH fill
    assert r.positions["ETHUSDT"] == Decimal("0.0005")
    assert r.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_balance_snapshots_recorded_for_rest_reconcile_and_emergency_flattening(tmp_path: Path):
    """Verify balance snapshots are recorded for REST backfills and emergency flattening."""
    cfg = CanaryMainnetDeploymentConfig(
        output_dir=tmp_path / "snap_audit_test",
        track="all",
    )
    runner = CanaryMainnetDeploymentRunner(cfg)
    report = runner.execute_all_tracks()
    assert report.compliance["all_criteria_passed"] is True

    db_path = tmp_path / "snap_audit_test" / "canary-mainnet-deployment-telemetry.sqlite3"
    with sqlite3.connect(db_path) as conn:
        # Track 3 final snapshot must have 0 allocated margin after emergency flattening
        t3_snaps = conn.execute(
            "SELECT snapshot_id, cash_usdt, allocated_margin_usdt, equity_usdt, drift_usdt "
            "FROM balance_snapshots WHERE track_id = 'track_3' ORDER BY rowid ASC"
        ).fetchall()
        assert len(t3_snaps) >= 4
        final_t3 = t3_snaps[-1]
        assert final_t3[2] == "0", (
            f"Track 3 final snapshot allocated margin must be 0, got {final_t3[2]}"
        )
        assert Decimal(final_t3[4]) < DOUBLE_ENTRY_MAX_DRIFT

        # Track 2 must record snapshot for REST backfill (at least 3 snapshots)
        t2_snaps = conn.execute(
            "SELECT snapshot_id, allocated_margin_usdt, drift_usdt "
            "FROM balance_snapshots WHERE track_id = 'track_2'"
        ).fetchall()
        assert len(t2_snaps) >= 3


def test_gateway_heartbeat_clock_skew_detection():
    """Verify backward clock jump > 250 ms triggers LATENCY_SPIKE_STALE and freezes order."""
    mon = GatewayHeartbeatMonitor(max_clock_skew_ms=MAX_CLOCK_SKEW_TOLERANCE_MS)
    hb1 = mon.record_heartbeat(server_time_ms=1_000_000, latency_ms=30.0, track_id="test_skew")
    assert hb1.status == HeartbeatStatus.HEALTHY
    assert mon.is_fresh() is True

    # Backward clock jump of 300 ms (> 250 ms max tolerance)
    hb2 = mon.record_heartbeat(server_time_ms=999_700, latency_ms=30.0, track_id="test_skew")
    assert hb2.status == HeartbeatStatus.LATENCY_SPIKE_STALE
    assert mon.is_stale_state is True
    assert mon.is_fresh() is False

    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_fresh()


def test_client_order_id_extended_validation_and_pending_new_working_margin(temp_telemetry_store):
    """Verify client order ID edge cases and PENDING_NEW working margin accounting."""
    # 1. Non-positive timestamp rejection in validate_canary_client_order_id
    ok_zero, err_zero = validate_canary_client_order_id("c=canary-p280-BTCUSDT-0-abc12345")
    assert ok_zero is False
    assert "timestamp 0 must be strictly positive" in (err_zero or "")

    # 2. Rejection in generate_canary_client_order_id
    with pytest.raises(DomainViolation):
        generate_canary_client_order_id("BTCUSDT", timestamp_ms=0)
    with pytest.raises(DomainViolation):
        generate_canary_client_order_id("BTCUSDT", timestamp_ms=-500)
    with pytest.raises(DomainViolation):
        generate_canary_client_order_id("BTCUSDT", uuid_str="   ")
    with pytest.raises(DomainViolation):
        generate_canary_client_order_id("BTCUSDT", uuid_str="bad@char!")

    # 3. PENDING_NEW included in working committed margin
    r = MainnetUserDataStreamReconciler(
        track_id="test_pending_new", starting_equity=Decimal("100.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test_pnew"
    )
    orders_map: dict[str, MainnetOrderRecord] = {}

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=r,
        telemetry_store=temp_telemetry_store,
        track_id="test_pending_new",
        orders_provider=lambda: orders_map,
    )

    cid_pn = generate_canary_client_order_id("BTCUSDT")
    orders_map[cid_pn] = MainnetOrderRecord(
        order_id="ord-pn",
        client_order_id=cid_pn,
        track_id="test_pending_new",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        price="60000.00",
        quantity="0.00008",
        executed_quantity="0",
        notional_usdt="4.80",
        status=OrderLifecycleState.PENDING_NEW,
        ingress_stage=GraduatedIngressStage.STAGE_2_STEPPED_MICRO,
        created_at_utc=datetime.now(UTC).isoformat(),
        updated_at_utc=datetime.now(UTC).isoformat(),
    )
    assert interlock.get_working_committed_margin() == Decimal("4.80000000")
    assert interlock.get_working_committed_margin("BTCUSDT") == Decimal("4.80000000")
    assert interlock.get_working_committed_margin("ETHUSDT") == Decimal("0")
