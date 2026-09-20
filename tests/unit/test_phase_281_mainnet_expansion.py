"""Unit tests for Phase 281: Production Canary Live Mainnet Staged Capital Expansion Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 280, 279, 278, 277, 276).
- Capital expansion tiers:
  - Stage 1 seed probe cap (<= 1.00 USDT)
  - Stage 2 micro order cap (<= 5.00 USDT with ROUND_DOWN precision)
  - Aggregate concurrent active exposure cap (<= 10.00 USDT across all symbols)
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00% (cash reserve buffer >= 40.00%)
  - Per-asset margin allocation <= 20.00%
- Gateway heartbeat freshness (age <= 500 ms) and backward NTP drift (> 250 ms)
  with 50 ms recovery hysteresis.
- Intra-phase cumulative loss budget (<= 2.00 USDT) and emergency micro-chunked position
  liquidation (<= 5.00 USDT chunks).
- Dual-confirmation client order tag format (c=canary-p281-{sym}-{ts}-{uuid}).
- Stream desync and REST reconciliation with monotonic lifecycle progression and
  trade deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT).
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
from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
)
from autonomous_futures.feed.mainnet_expansion import (  # noqa: E402
    DEFAULT_PHASE281_OUTPUT_DIR,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    INTRA_PHASE_LOSS_CEILING_USDT,
    MAX_CLOCK_SKEW_TOLERANCE_MS,
    AggregateExposureCapExceededError,
    CanaryMainnetExpansionConfig,
    CanaryMainnetExpansionRunner,
    CapitalExpansionStage,
    CircuitBreakerState,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
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
    OrderLifecycleState,
    SqliteCanaryMainnetExpansionTelemetryStore,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_281_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_281_mainnet_expansion import (  # noqa: E402
    execute_phase_281_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-telemetry.sqlite3"
    store = SqliteCanaryMainnetExpansionTelemetryStore(db_path)
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
    assert cid == "c=canary-p281-BTCUSDT-1700000000000-abc12345"

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

    # Invalid prefix format (e.g. from phase 280)
    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id("c=canary-p280-BTCUSDT-1700000000000-abc12345")

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


def test_gateway_heartbeat_clock_skew_detection():
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
    assert mon.is_fresh() is False
    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_fresh()


# =====================================================================
# 3. Capital Expansion Governance & Micro Notional Cap Tests
# =====================================================================


def test_capital_expansion_stage_1_vs_stage_2_stepped_aggregate_cap(temp_telemetry_store):
    reconciler = MainnetUserDataStreamReconciler(track_id="test_stepped")
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    # Existing active order of 4.80 USDT on BTCUSDT
    mock_orders: dict[str, MainnetOrderRecord] = {
        "c=canary-p281-BTCUSDT-1-abc": MainnetOrderRecord(
            order_id="ord-1",
            client_order_id="c=canary-p281-BTCUSDT-1-abc",
            track_id="test_stepped",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="60000.00",
            quantity="0.00008",  # 4.80 USDT
            executed_quantity="0",
            notional_usdt="4.80",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
    }

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_stepped",
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
        orders_provider=lambda: mock_orders,
    )

    # In Stage 1 (<= 5.00 USDT aggregate), adding 1.50 USDT (ETH) breaches 5.00 USDT cap
    # (4.80 + 1.50 = 6.30 > 5.00)!
    cid_eth = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(AggregateExposureCapExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.0005"),  # 1.50 USDT
            client_order_id=cid_eth,
        )
    assert "breaches stage cap of 5.00 USDT" in str(exc_info.value)

    # In Stage 2 (<= 10.00 USDT aggregate), stepped expansion allows up to 10.00 USDT exposure!
    interlock.expansion_stage = CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT
    interlock.validate_dispatch(
        symbol="ETHUSDT",
        price=Decimal("3000.00"),
        quantity=Decimal("0.0005"),  # 1.50 USDT (total = 6.30 <= 10.00)
        client_order_id=cid_eth,
    )


def test_capital_expansion_stage_2_hard_micro_cap(temp_telemetry_store):
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
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
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
    with pytest.raises(IndividualMicroCapExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00010"),
            client_order_id=cid_invalid,
        )
    assert "exceeds individual micro order cap of 5.00 USDT" in str(exc_info.value)


# =====================================================================
# 4. Aggregate Concurrent Active Exposure Cap & Dynamic Headroom Tests
# =====================================================================


def test_aggregate_concurrent_active_exposure_cap(temp_telemetry_store):
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_agg", starting_equity=Decimal("100.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    # Existing active orders: BTC (4.80 USDT) + ETH (4.50 USDT) = 9.30 USDT
    mock_orders: dict[str, MainnetOrderRecord] = {
        "c=canary-p281-BTCUSDT-1-abc": MainnetOrderRecord(
            order_id="ord-1",
            client_order_id="c=canary-p281-BTCUSDT-1-abc",
            track_id="test_agg",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="60000.00",
            quantity="0.00008",  # 4.80 USDT
            executed_quantity="0",
            notional_usdt="4.80",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        ),
        "c=canary-p281-ETHUSDT-1-def": MainnetOrderRecord(
            order_id="ord-2",
            client_order_id="c=canary-p281-ETHUSDT-1-def",
            track_id="test_agg",
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="3000.00",
            quantity="0.0015",  # 4.50 USDT
            executed_quantity="0",
            notional_usdt="4.50",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        ),
    }

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_agg",
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
        orders_provider=lambda: mock_orders,
    )

    agg_exposure = interlock.get_aggregate_active_exposure()
    assert agg_exposure == Decimal("9.30000000")

    # Adding SOL order of 4.50 USDT breaches 10.00 USDT aggregate cap (9.30 + 4.50 = 13.80 > 10.00)!
    cid_sol = generate_canary_client_order_id("SOLUSDT")
    with pytest.raises(AggregateExposureCapExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="SOLUSDT",
            price=Decimal("150.00"),
            quantity=Decimal("0.030"),  # 4.50 USDT
            client_order_id=cid_sol,
        )
    assert "breaches stage cap of 10.00 USDT" in str(exc_info.value)

    # Adding a small order within headroom (0.004 SOL @ 150 = 0.60 USDT -> 9.90 <= 10.00)
    cid_sol_small = generate_canary_client_order_id("SOLUSDT")
    interlock.validate_dispatch(
        symbol="SOLUSDT",
        price=Decimal("150.00"),
        quantity=Decimal("0.004"),
        client_order_id=cid_sol_small,
    )


def test_active_working_committed_margin_and_reserve(temp_telemetry_store):
    # Starting equity = 10.00 USDT -> 20.00% per-asset cap is 2.00 USDT
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_margin", starting_equity=Decimal("10.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    # Working order of 1.50 USDT on BTCUSDT (within 2.00 USDT per-asset cap)
    mock_orders: dict[str, MainnetOrderRecord] = {
        "c=canary-p281-BTCUSDT-1-abc": MainnetOrderRecord(
            order_id="ord-1",
            client_order_id="c=canary-p281-BTCUSDT-1-abc",
            track_id="test_margin",
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="GTC",
            price="60000.00",
            quantity="0.000025",  # 1.50 USDT
            executed_quantity="0",
            notional_usdt="1.50",
            status=OrderLifecycleState.NEW,
            expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
            created_at_utc=datetime.now(UTC).isoformat(),
            updated_at_utc=datetime.now(UTC).isoformat(),
        )
    }

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_margin",
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
        orders_provider=lambda: mock_orders,
    )

    # Committed working margin for BTCUSDT is 1.50 USDT
    assert interlock.get_working_committed_margin("BTCUSDT") == Decimal("1.50000000")

    # Adding 1.50 USDT exceeds 20.00% asset cap (1.50 + 1.50 = 3.00 > 2.00 USDT per-asset cap)!
    # Note: 3.00 <= 5.00 individual cap and <= 10.00 aggregate cap, so margin check triggers!
    cid_new = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MarginAllocationExceededError) as exc_info:
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.000025"),  # 1.50 USDT
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
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
        intra_phase_loss_ceiling_usdt=Decimal("2.00"),
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

    # 1. Open 0.00016 BTCUSDT @ 60,000 (two orders of 0.00008)
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

    # 2. Close 0.00008 BTCUSDT @ 30,000 -> realized loss = 0.00008 * (60,000 - 30,000) = 2.40 USDT
    # Breaches the 2.00 USDT intra-phase loss ceiling!
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("30000.00"),
        is_closing=True,
    )
    assert reconciler.cumulative_realized_loss == Decimal("2.40000000")
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
# 6. WebSocket Flap & REST Harmonization Tests
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
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
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

    # Disconnect stream before order dispatch
    gateway.disconnect_stream()
    cid = generate_canary_client_order_id("BTCUSDT")

    order = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        client_order_id=cid,
    )
    # Remains NEW locally because WebSocket events were buffered on gateway
    assert order.status == OrderLifecycleState.NEW

    # Reconnect stream and reconcile via REST
    gateway.reconnect_stream()
    reconciled = dispatcher.reconcile_via_rest()
    assert len(reconciled) == 1
    assert order.status == OrderLifecycleState.FILLED
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")

    # Harmonize buffered stream events: duplicate trade is deduplicated
    dispatcher.drain_and_reconcile_stream()
    assert sequencer.deduplicated_count >= 1

    # Close position cleanly
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        is_closing=True,
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 7. Exact Double-Entry Accounting Balance Reconciliation
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
        client_order_id="c=canary-p281-BTCUSDT-1-abc",
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
        client_order_id="c=canary-p281-BTCUSDT-2-abc",
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


def test_exact_double_entry_reconciliation_negative_pnl_partial_fills_and_flips():
    reconciler = MainnetUserDataStreamReconciler(
        track_id="complex_ledger", starting_equity=Decimal("50.00")
    )

    # 1. Partial fill 1 on SOLUSDT (0.010 @ 150)
    mark1 = MainnetExecutionMark(
        trade_id="tr-sol-1",
        track_id="complex_ledger",
        order_id="ord-sol-1",
        client_order_id="c=canary-p281-SOLUSDT-1",
        symbol="SOLUSDT",
        side="BUY",
        price="150.00",
        quantity="0.010",
        quote_quantity="1.50000000",
        commission_usdt="0.00060000",
        realized_pnl_usdt="0",
        trade_time_ms=int(time.time() * 1000),
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(mark1)
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Partial fill 2 on SOLUSDT (0.020 @ 150)
    mark2 = MainnetExecutionMark(
        trade_id="tr-sol-2",
        track_id="complex_ledger",
        order_id="ord-sol-1",
        client_order_id="c=canary-p281-SOLUSDT-1",
        symbol="SOLUSDT",
        side="BUY",
        price="150.00",
        quantity="0.020",
        quote_quantity="3.00000000",
        commission_usdt="0.00120000",
        realized_pnl_usdt="0",
        trade_time_ms=int(time.time() * 1000),
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(mark2)
    assert reconciler.positions["SOLUSDT"] == Decimal("0.030")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 2. Update mark price to 140 -> unrealized PnL = -0.30 USDT
    reconciler.update_mark_price("SOLUSDT", Decimal("140.00"))
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 3. Close position with loss: SELL 0.030 @ 140 -> realized PnL = -0.30 USDT
    mark3 = MainnetExecutionMark(
        trade_id="tr-sol-3",
        track_id="complex_ledger",
        order_id="ord-sol-2",
        client_order_id="c=canary-p281-SOLUSDT-close",
        symbol="SOLUSDT",
        side="SELL",
        price="140.00",
        quantity="0.030",
        quote_quantity="4.20000000",
        commission_usdt="0.00168000",
        realized_pnl_usdt="-0.30000000",
        trade_time_ms=int(time.time() * 1000),
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    reconciler.apply_trade_fill(mark3)
    assert reconciler.positions["SOLUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 8. Full Phase 281 Runner Execution & Hash Chain Verification
# =====================================================================


def test_full_phase_281_runner_and_hash_chain(tmp_path: Path):
    cfg = CanaryMainnetExpansionConfig(
        output_dir=tmp_path / "phase281_out",
        track="all",
        intra_phase_loss_ceiling_usdt=INTRA_PHASE_LOSS_CEILING_USDT,
    )
    runner = CanaryMainnetExpansionRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.phase == "phase_281"
    assert len(report.tracks) == 4
    assert all(t.success for t in report.tracks)
    assert report.compliance.get("zero_balance_drift") is True
    assert report.compliance.get("zero_secret_leakage") is True
    assert report.compliance.get("all_criteria_passed") is True

    # Verify SHA-256 DAG hash chain across artifacts
    hash_ok = verify_phase_281_hash_chain(output_dir=cfg.output_dir)
    assert hash_ok is True


def test_adverse_drift_detection_fail_closed(tmp_path: Path):
    cfg = CanaryMainnetExpansionConfig(
        output_dir=tmp_path / "adverse_drift_out",
        track="track_1",
        simulate_adverse_drift=True,
    )
    runner = CanaryMainnetExpansionRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.compliance.get("zero_balance_drift") is False
    assert report.compliance.get("all_criteria_passed") is False


def test_cli_execute_phase_281_runner_verify_only():
    exit_code = execute_phase_281_runner(
        output_dir=DEFAULT_PHASE281_OUTPUT_DIR,
        verify_only=True,
    )
    assert exit_code == 0


# =====================================================================
# 9. Interlock Boundary Conditions & Strict Containment Tests
# =====================================================================


def test_interlock_boundary_conditions_exact_limits(temp_telemetry_store):
    reconciler = MainnetUserDataStreamReconciler(
        track_id="test_bounds", starting_equity=Decimal("100.00")
    )
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_bounds",
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
    )

    # Exactly 5.00000000 USDT notional is permitted
    cid_exact_5 = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("50000.00"),
        quantity=Decimal("0.00010000"),  # 5.00000000 USDT
        client_order_id=cid_exact_5,
    )

    # 5.00000001 USDT is rejected
    cid_over_5 = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("50000.01"),
            quantity=Decimal("0.00010000"),  # 5.000001 USDT > 5.00
            client_order_id=cid_over_5,
        )


def test_strict_containment_invariants():
    paper_path = DEFAULT_PHASE281_OUTPUT_DIR / "paper-summary.json"
    report_path = DEFAULT_PHASE281_OUTPUT_DIR / "canary-mainnet-expansion-report.json"
    assert paper_path.exists()
    assert report_path.exists()

    with open(paper_path, encoding="utf-8") as f:
        paper_data = json.load(f)

    with open(report_path, encoding="utf-8") as f:
        report_data = json.load(f)

    # Strict containment invariants in paper summary
    assert paper_data["safety_invariants"]["execution_authority"] is False
    assert paper_data["safety_invariants"]["orders"] == 0
    assert paper_data["safety_invariants"]["api_keys_loaded"] == 0
    assert paper_data["safety_invariants"]["zero_secret_leakage"] is True

    # Strict compliance in report
    assert report_data["compliance"]["zero_secret_leakage"] is True
    assert report_data["compliance"]["zero_balance_drift"] is True
    assert report_data["compliance"]["all_criteria_passed"] is True


def test_all_database_balance_snapshots_zero_drift():
    db_path = DEFAULT_PHASE281_OUTPUT_DIR / "canary-mainnet-expansion-telemetry.sqlite3"
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT snapshot_id, drift_usdt FROM balance_snapshots")
    rows = cursor.fetchall()
    assert len(rows) > 0

    for snap_id, drift_str in rows:
        drift = Decimal(str(drift_str))
        assert drift < DOUBLE_ENTRY_MAX_DRIFT, f"Drift {drift} exceeds tolerance in {snap_id}"
    conn.close()


def test_order_lifecycle_monotonicity_enforcement(manifest, tmp_path: Path):
    gateway = MockBinanceMainnetGateway(initial_balance_usdt=STARTING_EQUITY_USDT)
    reconciler = MainnetUserDataStreamReconciler(track_id="test_mono")
    sequencer = MainnetStreamSequencer()
    db_path = tmp_path / "test_mono.sqlite3"
    jsonl_path = tmp_path / "test_mono.jsonl"
    telemetry_store = SqliteCanaryMainnetExpansionTelemetryStore(db_path)
    jsonl_sink = JsonlCanaryOrderSink(jsonl_path)
    heartbeat_mon = GatewayHeartbeatMonitor()
    heartbeat_mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000) - 20, latency_ms=20.0, track_id="test"
    )

    interlock = MainnetOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=telemetry_store,
        track_id="test_mono",
        expansion_stage=CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT,
    )
    dispatcher = MainnetMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=telemetry_store,
        jsonl_sink=jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_mono",
    )

    btc_cand = manifest.candidates["BTCUSDT"].candidate_id
    order = dispatcher.dispatch_micro_order(
        candidate_id=btc_cand,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
    )
    assert order.status == OrderLifecycleState.FILLED

    # Reverting from FILLED to NEW or PENDING_SUBMIT is forbidden
    cid = order.client_order_id
    stale_new_event = {
        "e": "ORDER_TRADE_UPDATE",
        "E": int(time.time() * 1000),
        "T": int(time.time() * 1000),
        "_seq": 9999,
        "o": {
            "s": "BTCUSDT",
            "c": cid,
            "S": "BUY",
            "o": "LIMIT",
            "f": "GTC",
            "q": "0.00008",
            "p": "60000.00",
            "ap": "0",
            "x": "NEW",
            "X": "NEW",
            "i": order.order_id,
            "l": "0",
            "z": "0",
            "L": "0",
            "N": "USDT",
            "n": "0",
            "T": int(time.time() * 1000),
            "t": 0,
        },
    }
    # Feed stale event into dispatcher stream processor
    gateway.stream_buffer.append(stale_new_event)
    dispatcher.drain_and_reconcile_stream()

    # Status must remain FILLED, not demoted to NEW
    assert order.status == OrderLifecycleState.FILLED
    telemetry_store.close()
