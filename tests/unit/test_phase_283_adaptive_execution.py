"""Unit tests for Phase 283: Canary Adaptive Execution Daemon Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 282 back to 276).
- Dual-confirmation client order tag format (c=canary-p283-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms) and backward NTP clock drift (> 250 ms
  triggers HEARTBEAT_FREEZE with 50 ms recovery hysteresis).
- Dynamic Volatility Adaptation (R2):
  - ATR volatility ratio tracking and micro notional scaling.
  - Clamping within [1.00, 5.00] USDT with ROUND_DOWN precision.
- Adaptive Spread Execution Governance (R2):
  - Passive limit offset calculation relative to spread and liquidity depth.
  - Depth exhaustion fail-closed abort on depleted order books (< 0.0001 depth).
  - Excessive spread protection (> 5% spread).
- Stepped concurrent exposure scaling across stages:
  - Stage 1 seed probe cap (<= 5.00 USDT)
  - Stage 2 expanded concurrent cap (<= 10.00 USDT)
  - Stage 3 continuous expansion cap (<= 15.00 USDT)
  - Stage 4 adaptive expansion cap (<= 20.00 USDT across all symbols)
  - Micro order cap <= 5.00 USDT and micro floor >= 1.00 USDT.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 3.00 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Multi-day extended session longevity, 24h listenKey expiration/renewal, sequence wrap
  recovery, stream disconnect REST backfill, and idempotent deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT) across snapshots.
- Strict containment invariants (execution_authority: False, orders: 0, api_keys_loaded: 0).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from autonomous_futures.feed.adaptive_execution import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_PHASE283_OUTPUT_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
    GATEWAY_HEARTBEAT_MAX_AGE_MS,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    INTRA_PHASE_LOSS_CEILING_USDT,
    MAX_CLOCK_SKEW_TOLERANCE_MS,
    MIN_MICRO_NOTIONAL_CAP_USDT,
    AdaptiveAutonomousDaemon,
    AdaptiveMicroOrderDispatcher,
    AdaptiveOrderDispatchInterlock,
    AdaptiveSpreadEngine,
    AdaptiveStreamSequencer,
    AdaptiveUserDataStreamReconciler,
    AggregateExposureCapExceededError,
    CanaryAdaptiveExecutionConfig,
    CanaryAdaptiveExecutionRunner,
    CapitalExpansionStage,
    CashReserveBufferBreachedError,
    CircuitBreakerState,
    ClockSkewExceededError,
    DaemonState,
    DepthExhaustionError,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatFreezeActiveError,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    ListenKeyExpiredError,
    MarginAllocationExceededError,
    MicroNotionalFloorViolationError,
    MockBinanceAdaptiveGateway,
    OrderLifecycleState,
    SpreadExceededError,
    SqliteCanaryAdaptiveExecutionTelemetryStore,
    VolatilityAdaptiveEngine,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_283_hash_chain,
    verify_upstream_phase282_qualification,
)
from autonomous_futures.feed.canary_activation import (  # noqa: E402
    STARTING_EQUITY_USDT,
    OrderSide,
    OrderType,
)
from autonomous_futures.feed.canary_probe import (  # noqa: E402
    SafetyInvariantViolation,
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.continuous_daemon import (  # noqa: E402
    DEFAULT_PHASE282_OUTPUT_DIR,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_283_adaptive_execution import (  # noqa: E402
    execute_phase_283_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-adaptive-telemetry.sqlite3"
    store = SqliteCanaryAdaptiveExecutionTelemetryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path):
    jsonl_path = tmp_path / "test-adaptive-orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_path)


# =====================================================================
# 1. Dual-Confirmation Client Order ID Tagging Tests
# =====================================================================


def test_generate_and_validate_canary_client_order_id():
    """Verify dual-confirmation client order tag generation and validation."""
    cid = generate_canary_client_order_id(
        "BTCUSDT", timestamp_ms=1700000000000, uuid_str="abc12345"
    )
    assert cid == "c=canary-p283-BTCUSDT-1700000000000-abc12345"

    ok, err = validate_canary_client_order_id(cid, expected_symbol="BTCUSDT")
    assert ok is True
    assert err is None

    # Symbol mismatch
    ok_bad_sym, err_bad_sym = validate_canary_client_order_id(cid, expected_symbol="ETHUSDT")
    assert ok_bad_sym is False
    assert "mismatch" in (err_bad_sym or "").lower()

    # Invalid pattern
    ok_inv, err_inv = validate_canary_client_order_id("invalid-tag", expected_symbol="BTCUSDT")
    assert ok_inv is False
    assert err_inv is not None

    # Empty or None
    ok_empty, _ = validate_canary_client_order_id("")
    assert ok_empty is False

    # Assert helper raises InvalidClientOrderIdTagError
    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id("bad-tag", "BTCUSDT")


# =====================================================================
# 2. Gateway Heartbeat Freshness, Clock Drift & Hysteresis Tests
# =====================================================================


def test_gateway_heartbeat_freshness_and_hysteresis():
    """Verify heartbeat age freshness <= 500 ms and 50 ms recovery hysteresis."""
    mon = GatewayHeartbeatMonitor(
        max_age_ms=GATEWAY_HEARTBEAT_MAX_AGE_MS,
        recovery_ceiling_ms=GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
    )
    now_ms = int(time.time() * 1000)

    # Fresh heartbeat
    rec = mon.record_heartbeat(
        server_time_ms=now_ms - 20, latency_ms=25.0, track_id="test", local_time_ms=now_ms
    )
    assert rec.status == HeartbeatStatus.HEALTHY
    assert mon.is_fresh() is True

    # Simulate stale heartbeat age > 500 ms (e.g. 520 ms)
    mon.set_simulated_stale_age(520.0)
    assert mon.is_fresh() is False
    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_fresh()

    # Recovery hysteresis: 480 ms is > recovery_ceiling (450 ms), remains frozen
    mon.set_simulated_stale_age(480.0)
    assert mon.is_fresh() is False
    with pytest.raises(HeartbeatFreezeActiveError):
        mon.assert_fresh()

    # Recovers at <= 450 ms (e.g. 440 ms)
    mon.set_simulated_stale_age(440.0)
    assert mon.is_fresh() is True
    mon.assert_fresh()  # No exception


def test_gateway_heartbeat_clock_skew_and_freeze():
    """Verify backward NTP clock drift (> 250 ms) triggers CLOCK_SKEW_FREEZE."""
    mon = GatewayHeartbeatMonitor(clock_skew_tolerance_ms=MAX_CLOCK_SKEW_TOLERANCE_MS)
    now_ms = int(time.time() * 1000)

    # Normal clock: server is 10 ms behind local
    rec1 = mon.record_heartbeat(
        server_time_ms=now_ms - 10, latency_ms=20.0, track_id="test", local_time_ms=now_ms
    )
    assert rec1.status == HeartbeatStatus.HEALTHY
    assert mon.is_clock_skew_frozen is False

    # Server drifts backwards by 300 ms (> 250 ms tolerance)
    rec2 = mon.record_heartbeat(
        server_time_ms=now_ms - 300, latency_ms=20.0, track_id="test", local_time_ms=now_ms
    )
    assert rec2.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_clock_skew_frozen is True
    with pytest.raises(ClockSkewExceededError):
        mon.assert_fresh()

    # Recovery hysteresis: recovers at <= 200 ms (250 - 50 ms)
    rec3 = mon.record_heartbeat(
        server_time_ms=now_ms - 180, latency_ms=20.0, track_id="test", local_time_ms=now_ms
    )
    assert rec3.status == HeartbeatStatus.RECOVERED
    assert mon.is_clock_skew_frozen is False
    assert mon.is_fresh() is True


# =====================================================================
# 3. Dynamic Volatility Adaptation Tests (R2)
# =====================================================================


def test_volatility_adaptive_engine():
    """Verify ATR-driven micro order sizing, scaling, and [1.00, 5.00] USDT bounds."""
    engine = VolatilityAdaptiveEngine()

    # 1. Baseline volatility (ratio = 1.0): returns base notional
    engine.update_atr("BTCUSDT", Decimal("100.0"))
    qty, notional, ratio = engine.calculate_order_sizing(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        base_notional=Decimal("4.80"),
    )
    assert ratio == Decimal("1.0")
    assert notional <= HARD_MICRO_NOTIONAL_CAP_USDT
    assert notional >= MIN_MICRO_NOTIONAL_CAP_USDT
    assert qty == Decimal("0.00008")  # 0.00008 @ 60000 = 4.80 USDT

    # 2. Elevated volatility (ATR doubles to 200.0 -> ratio = 2.0)
    engine.update_atr("BTCUSDT", Decimal("200.0"))
    qty2, notional2, ratio2 = engine.calculate_order_sizing(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        base_notional=Decimal("4.80"),
    )
    assert ratio2 == Decimal("2.0")
    assert notional2 == Decimal("2.40")  # 4.80 / 2.0 = 2.40 USDT
    assert qty2 == Decimal("0.00004")

    # 3. Extreme volatility spike (ATR = 1000.0 -> ratio = 10.0)
    # Target = 4.80 / 10 = 0.48, clamped to MIN_MICRO_NOTIONAL_CAP_USDT (1.00 USDT)
    engine.update_atr("BTCUSDT", Decimal("1000.0"))
    qty3, notional3, ratio3 = engine.calculate_order_sizing(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        base_notional=Decimal("4.80"),
    )
    assert ratio3 == Decimal("10.0")
    assert notional3 >= MIN_MICRO_NOTIONAL_CAP_USDT

    # 4. Below baseline volatility (ATR = 50.0 -> ratio = 0.5)
    # Does not expand beyond hard cap of 5.00 USDT
    engine.update_atr("BTCUSDT", Decimal("50.0"))
    qty4, notional4, ratio4 = engine.calculate_order_sizing(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        base_notional=Decimal("5.00"),
    )
    assert ratio4 == Decimal("0.5")
    assert notional4 <= HARD_MICRO_NOTIONAL_CAP_USDT


# =====================================================================
# 4. Adaptive Spread Execution Governance Tests (R2)
# =====================================================================


def test_adaptive_spread_engine():
    """Verify passive limit offset inside spread and depth exhaustion fail-closed drill."""
    engine = AdaptiveSpreadEngine()

    # Normal book
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60010.00"),
        bid_depth=Decimal("2.0"),
        ask_depth=Decimal("2.0"),
    )
    limit_px, offset = engine.calculate_adaptive_limit_price(
        "BTCUSDT", OrderSide.BUY, Decimal("60000.00")
    )
    assert limit_px >= Decimal("60000.00")
    assert limit_px < Decimal("60010.00")
    assert offset == Decimal("2.50")  # 25% of 10.00 spread = 2.50 for deep book
    assert limit_px == Decimal("60002.50")

    # Sell side inside spread
    limit_sell, offset_sell = engine.calculate_adaptive_limit_price(
        "BTCUSDT", OrderSide.SELL, Decimal("60010.00")
    )
    assert limit_sell <= Decimal("60010.00")
    assert limit_sell > Decimal("60000.00")
    assert offset_sell == Decimal("2.50")
    assert limit_sell == Decimal("60007.50")

    # Depth exhaustion error: depth collapses below threshold
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60010.00"),
        bid_depth=Decimal("0.00001"),  # < 0.0001 threshold
        ask_depth=Decimal("0.00001"),
    )
    with pytest.raises(DepthExhaustionError):
        engine.calculate_adaptive_limit_price("BTCUSDT", OrderSide.BUY, Decimal("60000.00"))

    # Excessive spread error: spread > 5%
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("50000.00"),
        ask_price=Decimal("60000.00"),  # 20% spread
        bid_depth=Decimal("2.0"),
        ask_depth=Decimal("2.0"),
    )
    with pytest.raises(SpreadExceededError):
        engine.calculate_adaptive_limit_price("BTCUSDT", OrderSide.BUY, Decimal("50000.00"))


# =====================================================================
# 5. Stepped Concurrent Exposure Scaling & Micro Caps
# =====================================================================


def test_stepped_concurrent_exposure_limits(temp_telemetry_store):
    """Verify stepped exposure scaling across Stages 1-4 and individual micro caps."""
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(server_time_ms=int(time.time() * 1000), latency_ms=30.0, track_id="test")
    reconciler = AdaptiveUserDataStreamReconciler(
        track_id="test", starting_equity=STARTING_EQUITY_USDT
    )
    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
    )

    # 1. Individual micro order cap (<= 5.00 USDT)
    cid_large = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00010"),  # 6.00 USDT > 5.00 USDT cap
            client_order_id=cid_large,
        )

    # 2. Micro order floor (>= 1.00 USDT)
    cid_small = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MicroNotionalFloorViolationError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00001"),  # 0.60 USDT < 1.00 USDT floor
            client_order_id=cid_small,
        )

    # 3. Stage 1 limit: <= 5.00 USDT total aggregate exposure
    cid_valid = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.00008"),  # 4.80 USDT <= 5.00 USDT
        client_order_id=cid_valid,
    )
    # Simulate fill
    reconciler.apply_fill(
        "BTCUSDT", OrderSide.BUY, Decimal("60000.00"), Decimal("0.00008"), fee=Decimal("0")
    )

    # Next order pushing aggregate exposure to 4.80 + 1.20 = 6.00 > 5.00 USDT cap
    cid_blocked = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.0004"),  # 1.20 USDT
            client_order_id=cid_blocked,
        )

    # Promote to Stage 2 (<= 10.00 USDT): now succeeds!
    interlock.expansion_stage = CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT
    interlock.validate_dispatch(
        symbol="ETHUSDT",
        price=Decimal("3000.00"),
        quantity=Decimal("0.0004"),
        client_order_id=cid_blocked,
    )


# =====================================================================
# 6. Dynamic Margin Headroom Interlock Tests
# =====================================================================


def test_dynamic_margin_headroom_interlocks(temp_telemetry_store):
    """Verify aggregate margin <= 60%, per-asset <= 20%, and cash reserve >= 40%."""
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(server_time_ms=int(time.time() * 1000), latency_ms=30.0, track_id="test")
    # Low equity account to test percentage ceilings: 20.00 USDT starting equity
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test", starting_equity=Decimal("20.00"))
    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )

    # Per-asset ceiling: <= 20% of 20.00 = 4.00 USDT max per asset
    # Attempt 4.80 USDT BTC order -> exceeds 20% per-asset ceiling
    cid = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MarginAllocationExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00008"),  # 4.80 USDT > 4.00 USDT (20%)
            client_order_id=cid,
        )

    # 3.00 USDT order is 15% <= 20% per-asset: succeeds
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.00005"),  # 3.00 USDT
        client_order_id=cid,
    )


# =====================================================================
# 7. Intra-Phase Cumulative Loss Budget Ceiling & Emergency Flattening
# =====================================================================


def test_intra_phase_loss_ceiling_and_flattening(temp_telemetry_store, temp_jsonl_sink):
    """Verify realized loss >= 3.00 USDT triggers fail-closed lockout and liquidation."""
    gateway = MockBinanceAdaptiveGateway(initial_balance_usdt=Decimal("100.00"))
    reconciler = AdaptiveUserDataStreamReconciler(
        track_id="test_lockout", starting_equity=Decimal("100.00")
    )
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_lockout"
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_lockout",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
        intra_phase_loss_ceiling_usdt=INTRA_PHASE_LOSS_CEILING_USDT,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_lockout",
    )

    # 1. Open BTC position: 0.00008 @ 60,000 = 4.80 USDT
    btc_buy = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
    )
    assert btc_buy.status == OrderLifecycleState.FILLED

    # 2. Close at 20,000 USDT -> realized loss = 3.20 USDT > 3.00 USDT ceiling!
    btc_close = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("20000.00"),
        is_closing=True,
    )
    assert btc_close.status == OrderLifecycleState.FILLED
    assert reconciler.cumulative_realized_loss >= Decimal("3.00")

    # 3. Subsequent order dispatch must be locked out immediately fail-closed
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0010"),
            price=Decimal("3000.00"),
        )
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

    # 4. Emergency flattening flattens remaining open positions in micro-chunks <= 5.00 USDT
    flattening_orders = dispatcher.execute_emergency_flattening()
    for fo in flattening_orders:
        assert Decimal(fo.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT


# =====================================================================
# 8. Multi-Day Session Longevity & WebSocket Recovery Tests (Track 4)
# =====================================================================


def test_session_longevity_listen_key_and_sequence_wrap(temp_telemetry_store, temp_jsonl_sink):
    """Verify 24h listenKey expiration, sequence wrap recovery, and idempotent deduplication."""
    gateway = MockBinanceAdaptiveGateway(initial_balance_usdt=Decimal("100.00"))
    reconciler = AdaptiveUserDataStreamReconciler(
        track_id="test_longevity", starting_equity=Decimal("100.00")
    )
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=30.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_longevity"
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_longevity",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_longevity",
    )

    # 1. ListenKey acquisition and expiration
    lk = gateway.create_listen_key()["listenKey"]
    gateway.advance_time(86401000)  # 24h+
    gateway.inject_listen_key_expired = True
    with pytest.raises(ListenKeyExpiredError):
        gateway.keepalive_listen_key(lk)

    # Reacquire new listenKey
    new_lk = gateway.create_listen_key()["listenKey"]
    assert new_lk != lk

    # 2. Sequence wrap recovery drill
    gateway.sequence_counter = 1_000_000
    sequencer.highest_arrival_sequence = 1_000_000
    gateway.inject_duplicate_events = True

    gateway.sequence_counter = 1  # Wrapped back to 1!
    ord_wrap = dispatcher.dispatch_micro_order(
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0010"),
        price=Decimal("3000.00"),
    )
    assert ord_wrap.status == OrderLifecycleState.FILLED
    assert sequencer.sequence_wrap_count >= 1
    assert sequencer.deduplicated_count >= 1

    # 3. Clean unwind and zero drift
    dispatcher.unwind_symbol_position_micro_chunked("cand-eth", "ETHUSDT", Decimal("3000.00"))
    assert reconciler.positions["ETHUSDT"] == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 9. Exact Double-Entry Accounting Balance Reconciliation
# =====================================================================


def test_exact_double_entry_balance_reconciliation():
    """Verify |cash + allocated + unrealized - (start + realized)| < 1e-15 USDT."""
    reconciler = AdaptiveUserDataStreamReconciler(
        track_id="test_double_entry", starting_equity=Decimal("100.00")
    )

    # Open BTC position: 0.00008 @ 60,000 = 4.80 USDT
    reconciler.apply_fill(
        "BTCUSDT", OrderSide.BUY, Decimal("60000.00"), Decimal("0.00008"), fee=Decimal("0.00192")
    )
    assert reconciler.allocated_margin == Decimal("4.80000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Mark price fluctuation -> unrealized PnL shifts
    reconciler.set_mark_price("BTCUSDT", Decimal("65000.00"))
    assert reconciler.unrealized_pnl > Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Partial close: 0.00004 @ 65,000 = 2.60 USDT
    reconciler.apply_fill(
        "BTCUSDT",
        OrderSide.SELL,
        Decimal("65000.00"),
        Decimal("0.00004"),
        fee=Decimal("0.00104"),
        is_closing=True,
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Complete close: 0.00004 @ 65,000
    reconciler.apply_fill(
        "BTCUSDT",
        OrderSide.SELL,
        Decimal("65000.00"),
        Decimal("0.00004"),
        fee=Decimal("0.00104"),
        is_closing=True,
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 10. Autonomous Daemon Lifecycle Engine
# =====================================================================


def test_daemon_lifecycle_and_graceful_shutdown(temp_telemetry_store, temp_jsonl_sink):
    """Verify INITIALIZING -> RUNNING -> DRAINING -> STOPPED daemon state transitions."""
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_daemon")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_daemon",
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_daemon",
    )
    daemon = AdaptiveAutonomousDaemon(
        dispatcher=dispatcher,
        reconciler=reconciler,
        interlock=interlock,
        heartbeat_monitor=heartbeat_mon,
        telemetry_store=temp_telemetry_store,
        track_id="test_daemon",
    )

    assert daemon.state == DaemonState.INITIALIZING
    daemon.start()
    assert daemon.state == DaemonState.RUNNING

    daemon.shutdown(graceful=True)
    assert daemon.state == DaemonState.STOPPED


# =====================================================================
# 11. Upstream Verification & Hash Chain Ingress
# =====================================================================


def test_upstream_phase282_verification_success():
    """Verify Phase 282 report and hash chain ingress pass against actual artifacts."""
    ok = verify_upstream_phase282_qualification(
        phase282_dir=DEFAULT_PHASE282_OUTPUT_DIR,
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    )
    assert ok is True


def test_upstream_phase282_verification_failure_on_corrupted_status(tmp_path: Path):
    """Verify upstream qualification fails closed if Phase 282 status is not verified."""
    corrupted_report = tmp_path / "canary-continuous-daemon-report.json"
    corrupted_report.write_text(
        json.dumps(
            {
                "daemon_status": "FAILED_DRIFT",
                "staged_manifest_hash": "dummy",
                "tracks": [],
                "compliance": {"zero_balance_drift": False, "all_criteria_passed": False},
            }
        ),
        encoding="utf-8",
    )
    from autonomous_futures.feed.adaptive_execution import PrerequisiteQualificationError

    with pytest.raises(PrerequisiteQualificationError):
        verify_upstream_phase282_qualification(
            phase282_dir=tmp_path,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        )


# =====================================================================
# 12. Full Simulation Runner & Cryptographic DAG Hash Chain
# =====================================================================


def test_full_phase_283_runner_and_hash_chain(tmp_path: Path):
    """Execute full Phase 283 runner and verify SHA-256 DAG hash chain across artifacts."""
    cfg = CanaryAdaptiveExecutionConfig(
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        output_dir=tmp_path,
        track="all",
    )
    runner = CanaryAdaptiveExecutionRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.daemon_status == "ADAPTIVE_EXECUTION_VERIFIED"
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True
    assert len(report.tracks) == 4
    assert all(t.success for t in report.tracks)

    # Verify cryptographic hash chain
    hash_ok = verify_phase_283_hash_chain(
        output_dir=tmp_path,
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    )
    assert hash_ok is True


def test_cli_execute_phase_283_runner_verify_only():
    """Verify CLI --verify-only succeeds against production Phase 283 artifacts."""
    exit_code = execute_phase_283_runner(
        output_dir=DEFAULT_PHASE283_OUTPUT_DIR,
        verify_only=True,
    )
    assert exit_code == 0


def test_strict_containment_invariants():
    """Verify strict fail-closed containment invariants: execution_authority=False, orders=0."""
    inv = verify_strict_fail_closed_invariants(
        orders_submitted=0,
        execution_authority=False,
    )
    assert inv["orders"] == 0
    assert inv["execution_authority"] is False
    assert inv["zero_secret_leakage"] is True

    # Breach orders submitted
    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(orders_submitted=1)

    # Breach execution authority
    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(execution_authority=True)


def test_all_database_balance_snapshots_zero_drift():
    """Verify every persisted balance snapshot in the telemetry database has zero balance drift."""
    db_path = DEFAULT_PHASE283_OUTPUT_DIR / "canary-adaptive-execution-telemetry.sqlite3"
    assert db_path.exists(), "Phase 283 telemetry database must exist"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT snapshot_id, track_id, drift_usdt FROM balance_snapshots")
    rows = cursor.fetchall()
    assert len(rows) > 0, "Telemetry database must contain balance snapshots"

    for snap_id, track_id, drift_str in rows:
        drift = Decimal(str(drift_str))
        assert drift < DOUBLE_ENTRY_MAX_DRIFT, (
            f"Snapshot {snap_id} in {track_id} has drift {drift} >= 1e-15"
        )
    conn.close()


def test_adverse_drift_detection_fail_closed(tmp_path: Path):
    """Verify synthetic adverse drift (> 1e-15 USDT) causes runner compliance to fail closed."""
    cfg = CanaryAdaptiveExecutionConfig(
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        output_dir=tmp_path,
        track="track_1",
        simulate_adverse_drift=True,
    )
    runner = CanaryAdaptiveExecutionRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.compliance["zero_balance_drift"] is False
    assert report.compliance["all_criteria_passed"] is False
    assert report.tracks[0].success is False


def test_working_orders_margin_reservation_and_cancellation(temp_telemetry_store, temp_jsonl_sink):
    """Verify working margin is reserved on unfilled orders and cancelled during daemon shutdown."""
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_working")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_working"
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_working",
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # 5.00 USDT cap
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_working",
    )
    daemon = AdaptiveAutonomousDaemon(
        dispatcher=dispatcher,
        reconciler=reconciler,
        interlock=interlock,
        heartbeat_monitor=heartbeat_mon,
        telemetry_store=temp_telemetry_store,
        track_id="test_working",
    )
    daemon.start()

    # Disconnect stream so order stays NEW / unfilled
    gateway.disconnect_stream()
    cid1 = generate_canary_client_order_id("BTCUSDT")
    ord1 = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        client_order_id=cid1,
    )
    assert ord1.status == OrderLifecycleState.NEW

    # Working margin reserved: 4.80 USDT
    assert interlock.get_working_committed_margin() == Decimal("4.80000000")

    # Second order would push active exposure to 4.80 + 2.40 = 7.20 > 5.00 USDT cap
    cid2 = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(AggregateExposureCapExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-eth",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0008"),
            price=Decimal("3000.00"),
            client_order_id=cid2,
        )

    # Shutdown daemon: cancels working order to prevent hanging exposure
    daemon.shutdown(graceful=True)
    assert dispatcher.orders[cid1].status == OrderLifecycleState.CANCELLED
    assert dispatcher.orders_cancelled_count >= 1
    assert interlock.get_working_committed_margin() == Decimal("0")


def test_stream_sequencer_out_of_order_resequencing():
    """Verify stream sequencer re-orders out-of-order packets by timestamp and priority."""
    sequencer = AdaptiveStreamSequencer()

    packets = [
        {
            "e": "ORDER_TRADE_UPDATE",
            "E": 100200,
            "T": 100200,
            "u": 2,
            "o": {"s": "BTCUSDT", "c": "c=canary-p283-BTCUSDT-100200-2", "X": "FILLED", "t": 101},
        },
        {
            "e": "ORDER_TRADE_UPDATE",
            "E": 100100,
            "T": 100100,
            "u": 1,
            "o": {"s": "BTCUSDT", "c": "c=canary-p283-BTCUSDT-100100-1", "X": "NEW", "t": 0},
        },
    ]

    sorted_batch = sequencer.sort_and_deduplicate_batch(packets, track_id="test_seq")
    assert len(sorted_batch) == 2
    assert sorted_batch[0]["u"] == 1  # Re-ordered chronologically!
    assert sorted_batch[1]["u"] == 2


def test_concurrent_order_dispatch_thread_safety(temp_telemetry_store, temp_jsonl_sink):
    """Verify thread-safe concurrent order dispatch under aggregate exposure caps."""
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_concurrency")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_concurrency"
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_concurrency",
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # 5.00 USDT cap
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_concurrency",
    )

    orders_to_dispatch = [
        ("cand-btc", "BTCUSDT", Decimal("0.00008"), Decimal("60000.00")),  # 4.80 USDT
        ("cand-eth", "ETHUSDT", Decimal("0.0010"), Decimal("3000.00")),  # 3.00 USDT
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


# =====================================================================
# 13. Adversarial Edge Case & Robustness Verification Tests
# =====================================================================


def test_clock_skew_exceeded_error_hierarchy():
    """Verify ClockSkewExceededError inherits from HeartbeatFreezeActiveError."""
    assert issubclass(ClockSkewExceededError, HeartbeatFreezeActiveError)
    assert issubclass(ClockSkewExceededError, GatewayHeartbeatStaleError)


def test_gateway_heartbeat_status_not_overwritten_when_skew_frozen():
    """Verify status is not overwritten to RECOVERED when clock skew is still frozen."""
    mon = GatewayHeartbeatMonitor(
        clock_skew_tolerance_ms=250.0, max_age_ms=500.0, recovery_ceiling_ms=450.0
    )
    now_ms = int(time.time() * 1000)

    # Trigger clock skew freeze: 300 ms backward drift
    rec1 = mon.record_heartbeat(
        server_time_ms=now_ms - 300, latency_ms=20.0, track_id="test", local_time_ms=now_ms
    )
    assert rec1.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_clock_skew_frozen is True

    # Next heartbeat has fresh age (20 ms) but clock drift is still 290 ms (> 250 ms)
    rec2 = mon.record_heartbeat(
        server_time_ms=now_ms + 100 - 290,
        latency_ms=20.0,
        track_id="test",
        local_time_ms=now_ms + 100,
    )
    assert rec2.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_clock_skew_frozen is True


def test_adaptive_spread_engine_rejects_crossed_and_invalid_book():
    """Verify AdaptiveSpreadEngine rejects crossed or non-positive order books fail-closed."""
    engine = AdaptiveSpreadEngine()

    # Crossed order book: ask (60000) <= bid (60010)
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60010.00"),
        ask_price=Decimal("60000.00"),
        bid_depth=Decimal("1.0"),
        ask_depth=Decimal("1.0"),
    )
    with pytest.raises(SpreadExceededError, match="Invalid or crossed order book"):
        engine.calculate_adaptive_limit_price("BTCUSDT", OrderSide.BUY, Decimal("60000.00"))

    # Non-positive prices
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("0.00"),
        ask_price=Decimal("60000.00"),
        bid_depth=Decimal("1.0"),
        ask_depth=Decimal("1.0"),
    )
    with pytest.raises(SpreadExceededError, match="Invalid or crossed order book"):
        engine.calculate_adaptive_limit_price("BTCUSDT", OrderSide.BUY, Decimal("60000.00"))


def test_volatility_adaptive_sizing_at_limit_price_prevents_cap_overrun(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify volatility sizing calculates notional at limit price, preventing cap breach."""
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_cap_overrun")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_cap_overrun"
    )

    spread_engine = AdaptiveSpreadEngine()
    # Wide book on SOLUSDT: bid 100.00, ask 104.00 -> limit buy at 101.00 (+25% spread)
    spread_engine.update_book(
        "SOLUSDT", Decimal("100.00"), Decimal("104.00"), Decimal("1.0"), Decimal("1.0")
    )
    gateway.set_book(
        "SOLUSDT", Decimal("100.00"), Decimal("104.00"), Decimal("1.0"), Decimal("1.0")
    )
    reconciler.set_mark_price("SOLUSDT", Decimal("100.00"))

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_cap_overrun",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
        spread_engine=spread_engine,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_cap_overrun",
        spread_engine=spread_engine,
    )

    # Base notional = 5.00 USDT at ref_price 100.00 would size 0.050 SOL.
    # At limit_price 101.00, 0.050 * 101 = 5.05 > 5.00 cap!
    # Sizing at limit_price must size 0.049 SOL -> 4.949 USDT <= 5.00 USDT.
    ord_rec = dispatcher.dispatch_volatility_adaptive_micro_order(
        candidate_id="cand-sol",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        base_notional=Decimal("5.00"),
    )
    assert ord_rec.status == OrderLifecycleState.FILLED
    assert Decimal(ord_rec.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT
    assert Decimal(ord_rec.notional_usdt) >= MIN_MICRO_NOTIONAL_CAP_USDT


def test_cash_reserve_buffer_breach_detected(temp_telemetry_store):
    """Verify CashReserveBufferBreachedError raised when unencumbered cash buffer falls < 40%."""
    mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    mon.record_heartbeat(server_time_ms=now_ms, latency_ms=20.0, track_id="test_cash_res")
    rec = AdaptiveUserDataStreamReconciler(
        track_id="test_cash_res", starting_equity=Decimal("100.00")
    )

    # Equity = cash (18) + margin (22) + unrealized (10) = 50.00 USDT
    # Margin ceiling: 60% = 30.00 USDT. Cash buffer requirement: 40% = 20.00 USDT.
    rec.cash = Decimal("18.00")
    rec.allocated_margin = Decimal("22.00")
    rec.per_asset_margin["BTCUSDT"] = Decimal("5.00")
    rec.positions["BTCUSDT"] = Decimal("0.0002")  # 12.00 USDT exposure
    rec.position_entry_prices["BTCUSDT"] = Decimal("10000.00")
    rec.set_mark_price("BTCUSDT", Decimal("60000.00"))  # Unrealized pnl = +10.00 USDT

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=rec,
        telemetry_store=temp_telemetry_store,
        track_id="test_cash_res",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )

    # Order notional = 2.00 USDT.
    # new_agg_margin = 22.00 + 2.00 = 24.00 <= 30.00 (passes 60% aggregate ceiling)
    # remaining_unencumbered_cash = 18.00 - 2.00 = 16.00 < 20.00 USDT (buffer breach!)
    cid = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(CashReserveBufferBreachedError, match="breaches required reserve buffer"):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("2000.00"),
            quantity=Decimal("0.0010"),
            client_order_id=cid,
        )


def test_upstream_phase282_corrupted_report_fails_closed(tmp_path: Path):
    """Verify upstream qualification fails closed if report has corrupted daemon_status."""
    summary = tmp_path / "continuous-daemon-summary.json"
    summary.write_text(
        json.dumps(
            {
                "daemon_status": "CONTINUOUS_DAEMON_VERIFIED",
                "staged_manifest_hash": "dummy",
                "candidates": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "compliance": {
                    "all_criteria_passed": True,
                    "zero_balance_drift": True,
                    "continuous_daemon_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "canary-continuous-daemon-report.json"
    report.write_text(
        json.dumps(
            {
                "daemon_status": "CORRUPTED_STATUS",
                "staged_manifest_hash": "dummy",
            }
        ),
        encoding="utf-8",
    )
    from autonomous_futures.feed.adaptive_execution import PrerequisiteQualificationError

    with pytest.raises(PrerequisiteQualificationError, match="expected CONTINUOUS_DAEMON_VERIFIED"):
        verify_upstream_phase282_qualification(
            phase282_dir=tmp_path,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        )


def test_gateway_heartbeat_assert_fresh_specific_error_types():
    """Verify assert_fresh raises GatewayHeartbeatStaleError on age > max_age_ms (520 ms)
    and HeartbeatFreezeActiveError within hysteresis window (480 ms).
    """
    mon = GatewayHeartbeatMonitor(max_age_ms=500.0, recovery_ceiling_ms=450.0)
    now_ms = int(time.time() * 1000)
    mon.record_heartbeat(
        server_time_ms=now_ms - 10, latency_ms=20.0, track_id="test", local_time_ms=now_ms
    )

    # 1. At 520 ms, raises GatewayHeartbeatStaleError specifically
    mon.set_simulated_stale_age(520.0)
    assert mon.is_fresh() is False
    with pytest.raises(GatewayHeartbeatStaleError) as exc_info:
        mon.assert_fresh()
    assert type(exc_info.value) is GatewayHeartbeatStaleError

    # 2. At 480 ms (in hysteresis recovery window), raises HeartbeatFreezeActiveError specifically
    mon.set_simulated_stale_age(480.0)
    assert mon.is_fresh() is False
    with pytest.raises(HeartbeatFreezeActiveError) as exc_info2:
        mon.assert_fresh()
    assert type(exc_info2.value) is HeartbeatFreezeActiveError


def test_adaptive_spread_engine_invalid_side_and_finiteness():
    """Verify AdaptiveSpreadEngine rejects invalid order sides and non-finite inputs."""
    engine = AdaptiveSpreadEngine()
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60010.00"),
        bid_depth=Decimal("1.0"),
        ask_depth=Decimal("1.0"),
    )

    # Invalid side rejected with DomainViolation
    with pytest.raises(DomainViolation, match="Invalid order side"):
        engine.calculate_adaptive_limit_price("BTCUSDT", "INVALID_SIDE", Decimal("60000.00"))

    # Non-finite fallback price rejected
    with pytest.raises(DomainViolation, match="Fallback price"):
        engine.calculate_adaptive_limit_price("BTCUSDT", OrderSide.BUY, Decimal("NaN"))

    with pytest.raises(DomainViolation, match="Fallback price"):
        engine.calculate_adaptive_limit_price("BTCUSDT", OrderSide.BUY, Decimal("-10.00"))


def test_adaptive_spread_engine_limit_price_bounds_and_tight_spread():
    """Verify limit price is strictly bounded inside [bid_px, ask_px] even on tight spread."""
    engine = AdaptiveSpreadEngine()

    # Tight spread: 100.00 to 100.01 (spread = 0.01)
    engine.update_book(
        "SOLUSDT",
        bid_price=Decimal("100.00"),
        ask_price=Decimal("100.01"),
        bid_depth=Decimal("10.0"),
        ask_depth=Decimal("10.0"),
    )
    buy_px, _ = engine.calculate_adaptive_limit_price("SOLUSDT", OrderSide.BUY, Decimal("100.00"))
    assert buy_px >= Decimal("100.00")
    assert buy_px < Decimal("100.01")

    sell_px, _ = engine.calculate_adaptive_limit_price("SOLUSDT", OrderSide.SELL, Decimal("100.01"))
    assert sell_px > Decimal("100.00")
    assert sell_px <= Decimal("100.01")


def test_volatility_adaptive_engine_robust_to_nan_inf_and_zero():
    """Verify VolatilityAdaptiveEngine sanitizes NaN/Inf/0 ATRs and validates pricing."""
    engine = VolatilityAdaptiveEngine(baseline_atrs={"BTCUSDT": Decimal("0")})
    # Sanitized baseline
    assert engine.baseline_atrs["BTCUSDT"] > Decimal("0")

    # Update with NaN -> falls back to default fallback
    engine.update_atr("BTCUSDT", Decimal("NaN"))
    ratio_nan = engine.get_volatility_ratio("BTCUSDT")
    assert ratio_nan.is_finite()
    assert ratio_nan > Decimal("0")

    # Update with negative -> falls back to default fallback
    engine.update_atr("BTCUSDT", Decimal("-50.0"))
    ratio_neg = engine.get_volatility_ratio("BTCUSDT")
    assert ratio_neg.is_finite()
    assert ratio_neg > Decimal("0")

    # Non-positive or non-finite price in calculate_order_sizing raises DomainViolation
    with pytest.raises(DomainViolation, match="Order price"):
        engine.calculate_order_sizing("BTCUSDT", Decimal("0.00"))

    with pytest.raises(DomainViolation, match="Order price"):
        engine.calculate_order_sizing("BTCUSDT", Decimal("-100.00"))

    with pytest.raises(DomainViolation, match="Order price"):
        engine.calculate_order_sizing("BTCUSDT", Decimal("NaN"))

    # Non-positive or non-finite base_notional raises DomainViolation
    with pytest.raises(DomainViolation, match="Base notional"):
        engine.calculate_order_sizing("BTCUSDT", Decimal("60000.00"), base_notional=Decimal("0"))


def test_interlock_unknown_expansion_stage_fails_closed(temp_telemetry_store):
    """Verify unknown expansion_stage defaults fail-closed to Stage 1 cap (5.00 USDT)."""
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(
        server_time_ms=int(time.time() * 1000), latency_ms=20.0, track_id="test_stage"
    )
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_stage")
    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_stage",
        expansion_stage="INVALID_STAGE",  # type: ignore[arg-type]
    )

    # 4.80 USDT passes Stage 1 cap
    cid = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch("BTCUSDT", Decimal("60000.00"), Decimal("0.00008"), cid)

    # Simulated fill of 4.80 USDT
    reconciler.apply_fill(
        "BTCUSDT", OrderSide.BUY, Decimal("60000.00"), Decimal("0.00008"), fee=Decimal("0")
    )

    # Next order of 1.20 USDT breaches Stage 1 cap (4.80 + 1.20 = 6.00 > 5.00)
    cid2 = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.validate_dispatch("ETHUSDT", Decimal("3000.00"), Decimal("0.0004"), cid2)


def test_rest_backfill_stream_reconnect_double_fill_prevention(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify order filled via REST backfill does NOT get filled again
    when stream delivers late event.
    """
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_double_fill")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"],
        latency_ms=hb["latencyMs"],
        track_id="test_double_fill",
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_double_fill",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_double_fill",
    )

    # 1. Place order while stream is disconnected
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

    # 2. Reconcile via REST -> marks FILLED and applies fill once
    gateway.reconnect_stream()
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED
    assert dispatcher.orders_filled_count == 1
    initial_cash = reconciler.cash
    initial_margin = reconciler.allocated_margin

    # 3. Simulate delayed WebSocket fill packet arriving after REST backfill
    delayed_pkt = {
        "e": "ORDER_TRADE_UPDATE",
        "E": gateway.server_time_ms,
        "T": gateway.server_time_ms,
        "u": 10,
        "o": {
            "s": "BTCUSDT",
            "c": cid,
            "i": 100001,
            "S": "BUY",
            "o": "LIMIT",
            "f": "GTC",
            "q": "0.00008",
            "p": "60000.00",
            "ap": "60000.00",
            "sp": "0",
            "x": "TRADE",
            "X": "FILLED",
            "l": "0.00008",
            "z": "0.00008",
            "L": "60000.00",
            "n": "0.00192",
            "N": "USDT",
            "T": gateway.server_time_ms,
            "t": 500001,
            "b": "0",
            "a": "0",
            "m": False,
            "R": False,
            "wt": "CONTRACT_PRICE",
            "ot": "LIMIT",
            "ps": "BOTH",
            "cp": False,
            "rp": "0",
        },
    }
    gateway.ws_event_queue.append(delayed_pkt)
    dispatcher.drain_and_reconcile_stream()

    # 4. Assert fill was NOT double-applied
    assert dispatcher.orders_filled_count == 1
    assert reconciler.cash == initial_cash
    assert reconciler.allocated_margin == initial_margin
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert sequencer.deduplicated_count >= 1


def test_rest_reconcile_handles_canceled_and_rejected_orders(temp_telemetry_store, temp_jsonl_sink):
    """Verify REST reconciliation recognizes CANCELED and REJECTED states
    and frees working margin.
    """
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_rest_term")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"],
        latency_ms=hb["latencyMs"],
        track_id="test_rest_term",
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_rest_term",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_rest_term",
    )

    # Disconnect stream, place order
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
    assert interlock.get_working_committed_margin() > Decimal("0")

    # Exchange marks order CANCELED
    gateway.orders[cid]["status"] = "CANCELED"

    # Reconcile via REST
    gateway.reconnect_stream()
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.CANCELLED
    assert dispatcher.orders_cancelled_count == 1
    # Committed working margin is released
    assert interlock.get_working_committed_margin() == Decimal("0")


def test_backward_local_clock_drift_detection_and_freeze():
    """Adversarial check: backward local clock drift (> 250 ms) must trigger
    CLOCK_SKEW_FREEZE rather than cloaking the drift as 0 ms age.
    """
    monitor = GatewayHeartbeatMonitor()
    t_base = 1000000
    monitor.record_heartbeat(
        server_time_ms=t_base,
        latency_ms=15.0,
        track_id="test_drift",
        local_time_ms=t_base,
    )
    assert monitor.is_fresh(now_local=t_base + 50) is True

    # 1. Backward clock jump by 300 ms (t_base - 300)
    now_jumped = t_base - 300
    age = monitor.get_heartbeat_age_ms(now_local=now_jumped)
    assert age == 0.0
    assert monitor.is_clock_skew_frozen is True
    assert monitor.is_fresh(now_local=now_jumped) is False
    with pytest.raises(ClockSkewExceededError):
        monitor.assert_fresh(now_local=now_jumped)

    # 2. Time advances slightly, but remains within recovery hysteresis (< 200 ms)
    now_recovering = t_base - 220
    assert monitor.is_fresh(now_local=now_recovering) is False
    with pytest.raises(ClockSkewExceededError):
        monitor.assert_fresh(now_local=now_recovering)

    # 3. Time advances beyond recovery threshold (backward drift 190 ms <= 200 ms)
    now_recovered = t_base - 190
    _ = monitor.get_heartbeat_age_ms(now_local=now_recovered)
    assert monitor.is_clock_skew_frozen is False
    assert monitor.is_fresh(now_local=t_base + 50) is True
    monitor.assert_fresh(now_local=t_base + 50)


def test_rest_reconcile_partial_fill_incremental_accounting(temp_telemetry_store, temp_jsonl_sink):
    """Adversarial check: partial fills via REST backfill must only book incremental
    quantities and fees, preventing double-fill and balance drift.
    """
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_rest_partial")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"],
        latency_ms=hb["latencyMs"],
        track_id="test_rest_partial",
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_rest_partial",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_rest_partial",
    )

    # Disconnect stream and dispatch an order for 0.00010 BTC @ 50,000 USDT (5.00 USDT notional)
    gateway.disconnect_stream()
    cid = generate_canary_client_order_id("BTCUSDT")
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00010"),
        price=Decimal("50000.00"),
        client_order_id=cid,
    )
    assert ord_rec.status == OrderLifecycleState.NEW

    # 1. Exchange reports PARTIALLY_FILLED for 0.00004 BTC
    gateway.orders[cid]["status"] = "PARTIALLY_FILLED"
    gateway.orders[cid]["executedQty"] = "0.00004"
    gateway.orders[cid]["cummulativeQuoteQty"] = "2.00000000"

    gateway.reconnect_stream()
    backfilled_1 = dispatcher.reconcile_via_rest()
    assert len(backfilled_1) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.PARTIALLY_FILLED
    assert dispatcher.orders[cid].executed_quantity == "0.00004"
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00004")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Working committed margin reduced by the partial fill: 0.00006 * 50000 = 3.00 USDT
    assert interlock.get_working_committed_margin() == Decimal("3.00000000")

    # 2. Exchange reports FILLED with total cum_qty 0.00010 BTC
    gateway.orders[cid]["status"] = "FILLED"
    gateway.orders[cid]["executedQty"] = "0.00010"
    gateway.orders[cid]["cummulativeQuoteQty"] = "5.00000000"

    backfilled_2 = dispatcher.reconcile_via_rest()
    assert len(backfilled_2) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED
    assert dispatcher.orders[cid].executed_quantity == "0.00010"
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00010")
    # Total fill count is 1 completed order
    assert dispatcher.orders_filled_count == 1
    # Working committed margin is fully released
    assert interlock.get_working_committed_margin() == Decimal("0.00000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_stream_drain_handles_partial_fill_and_cancellations(temp_telemetry_store, temp_jsonl_sink):
    """Verify WebSocket stream handler accurately processes PARTIALLY_FILLED,
    CANCELED, REJECTED and EXPIRED events with zero drift.
    """
    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_stream_events")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"],
        latency_ms=hb["latencyMs"],
        track_id="test_stream_events",
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_stream_events",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_stream_events",
    )

    gateway.disconnect_stream()
    cid = generate_canary_client_order_id("BTCUSDT")
    _ = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("50000.00"),
        client_order_id=cid,
    )
    gateway.reconnect_stream()
    gateway.ws_event_queue.clear()

    # 1. Push PARTIALLY_FILLED WebSocket packet
    pkt_partial = {
        "e": "ORDER_TRADE_UPDATE",
        "E": gateway.server_time_ms,
        "T": gateway.server_time_ms,
        "o": {
            "s": "BTCUSDT",
            "c": cid,
            "S": "BUY",
            "o": "LIMIT",
            "f": "GTC",
            "q": "0.00008",
            "p": "50000.00",
            "ap": "50000.00",
            "sp": "0",
            "x": "TRADE",
            "X": "PARTIALLY_FILLED",
            "l": "0.00003",
            "z": "0.00003",
            "L": "50000.00",
            "n": "0.00060",
            "N": "USDT",
            "T": gateway.server_time_ms,
            "t": 700001,
            "b": "0",
            "a": "0",
            "m": False,
            "R": False,
            "wt": "CONTRACT_PRICE",
            "ot": "LIMIT",
            "ps": "BOTH",
            "cp": False,
            "rp": "0",
        },
    }
    gateway.ws_event_queue.append(pkt_partial)
    events = dispatcher.drain_and_reconcile_stream()
    assert len(events) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.PARTIALLY_FILLED
    assert dispatcher.orders[cid].executed_quantity == "0.00003"
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00003")

    # 2. Push CANCELED WebSocket packet for remaining quantity
    pkt_cancel = {
        "e": "ORDER_TRADE_UPDATE",
        "E": gateway.server_time_ms,
        "T": gateway.server_time_ms,
        "o": {
            "s": "BTCUSDT",
            "c": cid,
            "S": "BUY",
            "o": "LIMIT",
            "f": "GTC",
            "q": "0.00008",
            "p": "50000.00",
            "ap": "50000.00",
            "sp": "0",
            "x": "CANCELED",
            "X": "CANCELED",
            "l": "0",
            "z": "0.00003",
            "L": "0",
            "n": "0",
            "N": "USDT",
            "T": gateway.server_time_ms,
            "t": 700002,
            "b": "0",
            "a": "0",
            "m": False,
            "R": False,
            "wt": "CONTRACT_PRICE",
            "ot": "LIMIT",
            "ps": "BOTH",
            "cp": False,
            "rp": "0",
        },
    }
    gateway.ws_event_queue.append(pkt_cancel)
    events_c = dispatcher.drain_and_reconcile_stream()
    assert len(events_c) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.CANCELLED
    assert dispatcher.orders_cancelled_count == 1
    assert interlock.get_working_committed_margin() == Decimal("0")


def test_apply_fill_safety_validations():
    """Adversarial check: apply_fill must enforce strict positive finite validation
    and prevent position sign flipping via excess closing fills.
    """
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_fill_safety")
    # Initial balance 100 USDT
    assert reconciler.cash == Decimal("100.00000000")

    # 1. Reject negative or non-finite price/quantity
    with pytest.raises(DomainViolation, match="must be strictly positive and finite"):
        reconciler.apply_fill(
            "BTCUSDT", "BUY", Decimal("-50000"), Decimal("0.0001"), Decimal("0.001")
        )
    with pytest.raises(DomainViolation, match="must be strictly positive and finite"):
        reconciler.apply_fill("BTCUSDT", "BUY", Decimal("50000"), Decimal("0"), Decimal("0.001"))
    with pytest.raises(DomainViolation, match="must be non-negative and finite"):
        reconciler.apply_fill(
            "BTCUSDT", "BUY", Decimal("50000"), Decimal("0.0001"), Decimal("-0.01")
        )
    with pytest.raises(DomainViolation, match="Invalid order side"):
        reconciler.apply_fill(
            "BTCUSDT", "INVALID_SIDE", Decimal("50000"), Decimal("0.0001"), Decimal("0.001")
        )

    # 2. Open long position of 0.00005 BTC
    reconciler.apply_fill("BTCUSDT", "BUY", Decimal("50000"), Decimal("0.00005"), Decimal("0.001"))
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00005")

    # 3. Attempt excess closing fill: selling 0.00010 BTC when only 0.00005 is held
    with pytest.raises(DomainViolation, match="exceeds current open position"):
        reconciler.apply_fill(
            "BTCUSDT", "SELL", Decimal("50000"), Decimal("0.00010"), Decimal("0.001")
        )


def test_symbol_normalization_and_dispatcher_coercion(temp_telemetry_store, temp_jsonl_sink):
    """Adversarial check: ensure case insensitivity in volatility engine
    and string coercion in order dispatcher.
    """
    vol_engine = VolatilityAdaptiveEngine()
    # Lowercase symbol should resolve correct BTC step size (0.00001), not fallback 0.001
    qty, actual_notional, ratio = vol_engine.calculate_order_sizing(
        symbol="btcusdt",
        price=Decimal("60000.00"),
        base_notional=Decimal("4.50"),
    )
    # 4.50 / 60000 = 0.000075 -> rounded down to 0.00001 step is 0.00007
    assert qty == Decimal("0.00007")
    assert actual_notional == Decimal("4.20000000")

    gateway = MockBinanceAdaptiveGateway()
    reconciler = AdaptiveUserDataStreamReconciler(track_id="test_coercion")
    sequencer = AdaptiveStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"],
        latency_ms=hb["latencyMs"],
        track_id="test_coercion",
    )

    interlock = AdaptiveOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_coercion",
        expansion_stage=CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION,
    )
    dispatcher = AdaptiveMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_coercion",
    )

    # Dispatch passing side and order_type as raw strings
    cid = generate_canary_client_order_id("BTCUSDT")
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",  # type: ignore[arg-type]
        order_type="LIMIT",  # type: ignore[arg-type]
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=cid,
    )
    assert ord_rec.side == OrderSide.BUY
    assert ord_rec.order_type == OrderType.LIMIT
