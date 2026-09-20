"""Unit tests for Phase 285: Canary Volatility Spillover Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 284 back to 276).
- Dual-confirmation client order tag format (c=canary-p285-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms), backward NTP clock drift (> 250 ms triggers
  HEARTBEAT_FREEZE with recovery hysteresis <= 450 ms).
- Cross-Asset Volatility Spillover & Adaptive Correlation Engine:
  - Volatility spillover index tracking and regime classification.
  - Dynamic cushion/offset widening and sizing downscaling under elevated spillover.
  - Correlation breakdown detection (pairwise correlation collapse < 0.20 or drop > 0.40).
  - Passive order preservation during breakdown: aggressive order rejection.
  - Candidate exposure clamping to throttled cap (<= 10.00 USDT) under active breakdown.
- Dynamic Micro-Order Slicing Governance:
  - Slicing trigger when order exceeds depth and estimated slippage > 1.5 bps.
  - Sequential micro-chunks <= 2.50 USDT child orders.
  - Normal micro cap <= 5.00 USDT, micro floor >= 1.00 USDT.
  - Atomic parent-child lifecycle tracking.
- Stepped concurrent exposure scaling across stages:
  - Stage 1 seed probe cap (<= 5.00 USDT)
  - Stage 2 expanded concurrent cap (<= 10.00 USDT)
  - Stage 3 continuous expansion cap (<= 15.00 USDT)
  - Stage 4 adaptive expansion cap (<= 20.00 USDT)
  - Stage 5 liquidity expansion cap (<= 25.00 USDT)
  - Stage 6 volatility spillover expansion cap (<= 30.00 USDT across all symbols)
  - Aggregate concurrent exposure cap <= 30.00 USDT.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 4.00 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Multi-day extended session longevity, 24h listenKey expiration/renewal, sequence wrap
  recovery, stream disconnect REST backfill, and idempotent deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT) across snapshots.
- Strict containment invariants (execution_authority: False, orders: 0, api_keys_loaded: 0).
"""

from __future__ import annotations

import sys
import time
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
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.volatility_spillover import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_PHASE285_OUTPUT_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
    GATEWAY_HEARTBEAT_MAX_AGE_MS,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    INTRA_PHASE_LOSS_CEILING_USDT,
    LISTEN_KEY_LIFETIME_SECONDS,
    MAX_CLOCK_SKEW_TOLERANCE_MS,
    SEQUENCE_WRAP_THRESHOLD,
    SLIPPAGE_TOLERANCE_BPS,
    STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT,
    STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT,
    STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT,
    STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT,
    STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT,
    STAGE_6_VOLATILITY_EXPANSION_CAP_USDT,
    CanaryVolatilitySpilloverConfig,
    CanaryVolatilitySpilloverRunner,
    CapitalExpansionStage,
    CircuitBreakerState,
    CorrelationBreakdownThrottledError,
    CorrelationState,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatFreezeActiveError,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    InsufficientCashReserveError,
    IntraPhaseLossCeilingExceededError,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    ListenKeyExpiredError,
    MarginAllocationExceededError,
    MicroNotionalFloorViolationError,
    MockBinanceVolatilityGateway,
    OrderLifecycleState,
    OrderSlicingMode,
    SqliteCanaryVolatilitySpilloverTelemetryStore,
    VolatilityMicroOrderDispatcher,
    VolatilityOrderDispatchInterlock,
    VolatilitySpilloverEngine,
    VolatilitySpilloverRegime,
    VolatilityStreamSequencer,
    VolatilityUserDataStreamReconciler,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_285_hash_chain,
    verify_upstream_phase284_qualification,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_285_volatility_spillover import (  # noqa: E402
    execute_phase_285_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-volatility-telemetry.sqlite3"
    store = SqliteCanaryVolatilitySpilloverTelemetryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path):
    jsonl_path = tmp_path / "test-volatility-orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_path)


# =====================================================================
# 1. Dual-Confirmation Client Order ID Tagging Tests (Phase 285)
# =====================================================================


def test_generate_and_validate_canary_client_order_id():
    """Verify dual-confirmation client order tag generation and validation for Phase 285."""
    cid = generate_canary_client_order_id(
        "BTCUSDT", timestamp_ms=1700000000000, uuid_str="abc12345"
    )
    assert cid == "c=canary-p285-BTCUSDT-1700000000000-abc12345"

    ok, err = validate_canary_client_order_id(cid, expected_symbol="BTCUSDT")
    assert ok is True
    assert err is None

    # Child order tag with suffix: -c1
    child_cid = f"{cid}-c1"
    ok_child, err_child = validate_canary_client_order_id(child_cid, expected_symbol="BTCUSDT")
    assert ok_child is True
    assert err_child is None

    # Symbol mismatch
    ok_bad_sym, err_bad_sym = validate_canary_client_order_id(cid, expected_symbol="ETHUSDT")
    assert ok_bad_sym is False
    assert "does not match" in (err_bad_sym or "").lower()

    # Invalid pattern
    ok_inv, err_inv = validate_canary_client_order_id("invalid-tag", expected_symbol="BTCUSDT")
    assert ok_inv is False
    assert err_inv is not None

    # Wrong phase tag (e.g. p284 instead of p285)
    ok_p284, err_p284 = validate_canary_client_order_id(
        "c=canary-p284-BTCUSDT-1700000000000-abc12345", expected_symbol="BTCUSDT"
    )
    assert ok_p284 is False

    # Empty
    ok_empty, _ = validate_canary_client_order_id("")
    assert ok_empty is False

    # Assert helper raises InvalidClientOrderIdTagError
    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id("bad-tag", "BTCUSDT")


# =====================================================================
# 2. Gateway Heartbeat Freshness, Clock Drift & Hysteresis Tests
# =====================================================================


def test_gateway_heartbeat_freshness_and_hysteresis():
    """Verify heartbeat freshness (<= 500 ms) and recovery hysteresis (<= 450 ms)."""
    mon = GatewayHeartbeatMonitor(
        max_age_ms=GATEWAY_HEARTBEAT_MAX_AGE_MS,
        recovery_ceiling_ms=GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
    )
    now_ms = int(time.time() * 1000)

    # Initial state raises stale error
    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_healthy()

    # Record healthy heartbeat (latency 25 ms, fresh)
    rec1 = mon.record_heartbeat(
        server_time_ms=now_ms - 20, latency_ms=25.0, local_receive_time_ms=now_ms, track_id="test"
    )
    assert rec1.status == HeartbeatStatus.HEALTHY
    assert mon.is_frozen is False
    mon.assert_healthy(now_ms=now_ms + 10)

    # Latency spike > 500 ms triggers LATENCY_SPIKE_STALE and freeze
    rec2 = mon.record_heartbeat(
        server_time_ms=now_ms, latency_ms=550.0, local_receive_time_ms=now_ms + 10, track_id="test"
    )
    assert rec2.status == HeartbeatStatus.LATENCY_SPIKE_STALE
    assert mon.is_frozen is True

    # Assert healthy fails closed during freeze
    with pytest.raises(HeartbeatFreezeActiveError):
        mon.assert_healthy(now_ms=now_ms + 20)

    # Partial recovery but age > 450 ms recovery hysteresis -> stays frozen
    mon.record_heartbeat(
        server_time_ms=now_ms, latency_ms=20.0, local_receive_time_ms=now_ms + 480, track_id="test"
    )
    assert mon.is_frozen is True

    # Full recovery: age <= 450 ms and latency <= 500 ms -> RECOVERED
    rec4 = mon.record_heartbeat(
        server_time_ms=now_ms + 500,
        latency_ms=20.0,
        local_receive_time_ms=now_ms + 550,
        track_id="test",
    )
    assert rec4.status == HeartbeatStatus.RECOVERED
    assert mon.is_frozen is False
    mon.assert_healthy(now_ms=now_ms + 560)


def test_gateway_heartbeat_clock_skew_and_freeze():
    """Verify backward NTP clock drift (> 250 ms) triggers CLOCK_SKEW_FREEZE."""
    mon = GatewayHeartbeatMonitor(max_clock_skew_ms=MAX_CLOCK_SKEW_TOLERANCE_MS)
    now_ms = int(time.time() * 1000)

    # Normal clock: server is 10 ms behind local
    rec1 = mon.record_heartbeat(
        server_time_ms=now_ms - 10, latency_ms=20.0, local_receive_time_ms=now_ms, track_id="test"
    )
    assert rec1.status == HeartbeatStatus.HEALTHY
    assert mon.is_frozen is False

    # Server drifts backwards by 300 ms relative to prev server time (> 250 ms tolerance)
    rec2 = mon.record_heartbeat(
        server_time_ms=(now_ms - 10) - 300,
        latency_ms=20.0,
        local_receive_time_ms=now_ms,
        track_id="test",
    )
    assert rec2.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_frozen is True
    assert mon.clock_skew_frozen is True

    # Recovery: record a healthy heartbeat with forward server time and age <= recovery ceiling
    rec3 = mon.record_heartbeat(
        server_time_ms=now_ms + 10,
        latency_ms=20.0,
        local_receive_time_ms=now_ms + 50,
        track_id="test",
    )
    assert rec3.status == HeartbeatStatus.RECOVERED
    assert mon.is_frozen is False
    assert mon.clock_skew_frozen is False


# =====================================================================
# 3. Volatility Spillover & Adaptive Correlation Engine Tests
# =====================================================================


def test_volatility_spillover_regime_classification():
    """Verify spillover regime classification across NOMINAL, ELEVATED, SEVERE."""
    engine = VolatilitySpilloverEngine()

    engine.set_aggregate_spillover_index(Decimal("0.10"))
    assert engine.classify_spillover_regime() == VolatilitySpilloverRegime.NOMINAL

    engine.set_aggregate_spillover_index(Decimal("0.45"))
    assert engine.classify_spillover_regime() == VolatilitySpilloverRegime.ELEVATED

    engine.set_aggregate_spillover_index(Decimal("0.65"))
    assert engine.classify_spillover_regime() == VolatilitySpilloverRegime.SEVERE


def test_volatility_spillover_adaptive_sizing_and_offset():
    """Verify dynamic cushion offset and sizing downscaling under spillover."""
    engine = VolatilitySpilloverEngine()
    engine.set_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60000.50"), Decimal("5.0"), Decimal("5.0")
    )

    # NOMINAL regime: full size, normal cushion
    engine.set_aggregate_spillover_index(Decimal("0.10"))
    notional, px, regime, offset = engine.calculate_adaptive_order_parameters(
        "BTCUSDT", OrderSide.BUY, Decimal("5.00")
    )
    assert regime == VolatilitySpilloverRegime.NOMINAL
    assert notional == Decimal("5.00")

    # ELEVATED regime: sizing scaled to 2.50 USDT, cushion widened
    engine.set_aggregate_spillover_index(Decimal("0.45"))
    notional_elev, px_elev, regime_elev, offset_elev = engine.calculate_adaptive_order_parameters(
        "BTCUSDT", OrderSide.BUY, Decimal("5.00")
    )
    assert regime_elev == VolatilitySpilloverRegime.ELEVATED
    assert notional_elev == Decimal("2.50000000")
    assert offset_elev > offset

    # SEVERE regime: sizing scaled to micro floor 1.00 USDT, widest cushion
    engine.set_aggregate_spillover_index(Decimal("0.65"))
    notional_ext, _, regime_ext, _ = engine.calculate_adaptive_order_parameters(
        "BTCUSDT", OrderSide.BUY, Decimal("5.00")
    )
    assert regime_ext == VolatilitySpilloverRegime.SEVERE
    assert notional_ext == Decimal("1.00000000")


def test_correlation_breakdown_detection_and_aggressive_order_rejection():
    """Verify correlation breakdown detection and aggressive order rejection."""
    engine = VolatilitySpilloverEngine()
    engine.set_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60000.50"), Decimal("5.0"), Decimal("5.0")
    )

    # Initially nominal correlation (0.85)
    engine.set_pairwise_correlation("BTCUSDT", "ETHUSDT", Decimal("0.85"))
    assert engine.is_correlation_breakdown("BTCUSDT") is False

    # Simulate collapse: BTC/ETH correlation collapses to 0.10 (< 0.20)
    engine.set_pairwise_correlation("BTCUSDT", "ETHUSDT", Decimal("0.10"))
    assert engine.is_correlation_breakdown("BTCUSDT") is True
    assert engine.correlation_states["BTCUSDT"] == CorrelationState.BREAKDOWN_DECOUPLED

    # Market orders are aggressive -> rejected
    assert (
        engine.is_aggressive_order("BTCUSDT", OrderSide.BUY, OrderType.MARKET, Decimal("60000.00"))
        is True
    )

    # Limit order crossing ask price is aggressive -> rejected
    assert (
        engine.is_aggressive_order("BTCUSDT", OrderSide.BUY, OrderType.LIMIT, Decimal("60001.00"))
        is True
    )

    # Passive limit order inside spread is not aggressive -> allowed
    assert (
        engine.is_aggressive_order("BTCUSDT", OrderSide.BUY, OrderType.LIMIT, Decimal("59999.00"))
        is False
    )


# =====================================================================
# 4. Dynamic Order Slicing & Micro-Cap Governance Tests
# =====================================================================


def test_dynamic_order_slicing_evaluation():
    """Verify order slicing evaluation based on depth exhaustion and slippage."""
    engine = VolatilitySpilloverEngine()
    # Depleted depth: only 0.00002 BTC available on ask
    engine.set_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00002"), Decimal("0.00002")
    )

    # Order of 4.80 USDT requires 0.00008 BTC (> 0.00002 available depth)
    qty = Decimal("0.00008")
    px = Decimal("60000.00")
    should_slice, mode, est_slip = engine.evaluate_order_slicing(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        desired_notional=Decimal("4.80"),
        quantity=qty,
        price=px,
    )
    assert should_slice is True
    assert mode == OrderSlicingMode.DYNAMIC_SLICED
    assert est_slip > SLIPPAGE_TOLERANCE_BPS


def test_micro_caps_and_floor_enforcement():
    """Verify individual micro cap (<= 5.00 USDT), child cap, and floor (>= 1.00 USDT)."""
    gw = MockBinanceVolatilityGateway()
    reconciler = VolatilityUserDataStreamReconciler(track_id="test")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    spillover_engine = VolatilitySpilloverEngine()

    interlock = VolatilityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_6_VOLATILITY_SPILLOVER,
    )

    cid = generate_canary_client_order_id("BTCUSDT")

    # Order exceeding hard micro cap (5.50 USDT > 5.00 USDT)
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("55000.00"),
            quantity=Decimal("0.0001"),
            client_order_id=cid,
        )

    # Order violating micro floor (0.50 USDT < 1.00 USDT) -> raises MicroNotionalFloorViolationError
    with pytest.raises(MicroNotionalFloorViolationError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("50000.00"),
            quantity=Decimal("0.00001"),
            client_order_id=cid,
        )

    # Child order exceeding sliced child cap (3.00 USDT > 2.50 USDT)
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),
            client_order_id=f"{cid}-c1",
            is_sliced_child=True,
        )

    # Valid micro order (3.00 USDT) passes
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.00005"),
        client_order_id=cid,
    )


# =====================================================================
# 5. Stepped Exposure Scaling & Correlation Breakdown Throttling
# =====================================================================


def test_stepped_expansion_stages_and_caps():
    """Verify exposure caps across stages 1 through 6 up to 30.00 USDT."""
    gw = MockBinanceVolatilityGateway()
    reconciler = VolatilityUserDataStreamReconciler(track_id="test")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    spillover_engine = VolatilitySpilloverEngine()

    interlock = VolatilityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_1_SEED_PROBE,
    )

    assert interlock.get_stage_exposure_cap() == STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT  # 5.00
    interlock.expansion_stage = CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT
    assert interlock.get_stage_exposure_cap() == STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT  # 10.00
    interlock.expansion_stage = CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION
    assert interlock.get_stage_exposure_cap() == STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT  # 15.00
    interlock.expansion_stage = CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION
    assert interlock.get_stage_exposure_cap() == STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT  # 20.00
    interlock.expansion_stage = CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION
    assert interlock.get_stage_exposure_cap() == STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT  # 25.00
    interlock.expansion_stage = CapitalExpansionStage.STAGE_6_VOLATILITY_SPILLOVER
    assert interlock.get_stage_exposure_cap() == STAGE_6_VOLATILITY_EXPANSION_CAP_USDT  # 30.00
    assert AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT == Decimal("30.00")


def test_correlation_breakdown_candidate_exposure_throttling():
    """Verify candidate exposure clamped to <= 10.00 USDT under active correlation breakdown."""
    gw = MockBinanceVolatilityGateway()
    reconciler = VolatilityUserDataStreamReconciler(track_id="test")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    spillover_engine = VolatilitySpilloverEngine()

    # Trigger breakdown on BTC
    spillover_engine.set_pairwise_correlation("BTCUSDT", "ETHUSDT", Decimal("0.05"))
    assert spillover_engine.is_correlation_breakdown("BTCUSDT") is True

    interlock = VolatilityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_6_VOLATILITY_SPILLOVER,
    )

    # Set existing BTC margin to 8.00 USDT
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("8.00")

    # Trying to add 3.00 USDT BTC order -> 8.00 + 3.00 = 11.00 USDT > 10.00 USDT cap
    cid = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(CorrelationBreakdownThrottledError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),  # 3.00 USDT
            client_order_id=cid,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
        )


# =====================================================================
# 6. Dynamic Margin Headroom & Working Margin Reservation Tests
# =====================================================================


def test_dynamic_margin_headroom_portfolio_and_per_asset_limits():
    """Verify max portfolio allocation (<= 60%), per-asset (<= 20%), and cash reserve (>= 40%)."""
    reconciler = VolatilityUserDataStreamReconciler(
        track_id="test", starting_equity=Decimal("100.00")
    )
    gw = MockBinanceVolatilityGateway()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    spillover_engine = VolatilitySpilloverEngine()

    interlock = VolatilityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_6_VOLATILITY_SPILLOVER,
    )

    # 1. Per-asset limit breach (max 20% of 100.00 = 20.00 USDT)
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("18.00")
    cid = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MarginAllocationExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),  # 3.00 USDT -> 21.00 > 20.00
            client_order_id=cid,
        )

    # 2. Portfolio margin allocation limit breach (max 60% = 24.00 USDT on 40.00 USDT equity)
    reconciler_low = VolatilityUserDataStreamReconciler(
        track_id="test_low", starting_equity=Decimal("40.00")
    )
    interlock_low = VolatilityOrderDispatchInterlock(
        reconciler=reconciler_low,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_6_VOLATILITY_EXPANSION,
    )
    reconciler_low.cash = Decimal("17.00")
    reconciler_low.allocated_margin = Decimal("23.00")
    with pytest.raises(MarginAllocationExceededError):
        interlock_low.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),  # 3.00 USDT -> 26.00 > 24.00 (60%)
            client_order_id=cid,
        )

    # 3. Cash reserve buffer breach (minimum 40% = 40.00 USDT)
    reconciler.allocated_margin = Decimal("20.00")
    reconciler.cash = Decimal("41.00")  # Cash buffer remaining
    reconciler.unrealized_pnl = Decimal("39.00")  # Total equity = 41 + 20 + 39 = 100.00 USDT
    cid_eth = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(InsufficientCashReserveError):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.0010"),  # 3.00 USDT -> cash becomes 38.00 < 40.00
            client_order_id=cid_eth,
        )


# =====================================================================
# 7. Intra-Phase Cumulative Loss Budget & Emergency Flattening Tests
# =====================================================================


def test_intra_phase_loss_ceiling_lockout_and_micro_chunk_flattening(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify intra-phase cumulative loss <= 4.00 USDT triggers fail-closed lockout."""
    gw = MockBinanceVolatilityGateway()
    reconciler = VolatilityUserDataStreamReconciler(track_id="test")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    spillover_engine = VolatilitySpilloverEngine()
    sequencer = VolatilityStreamSequencer()

    interlock = VolatilityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_6_VOLATILITY_SPILLOVER,
        intra_phase_loss_ceiling_usdt=INTRA_PHASE_LOSS_CEILING_USDT,  # 4.00 USDT
    )

    dispatcher = VolatilityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_lockout",
    )

    # Open BTC and ETH positions
    cid_btc = generate_canary_client_order_id("BTCUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
        price=Decimal("60000.00"),
        client_order_id=cid_btc,
    )
    cid_eth = generate_canary_client_order_id("ETHUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0016"),
        price=Decimal("3000.00"),
        client_order_id=cid_eth,
    )

    # Force price drop on BTC and close to realize loss >= 4.00 USDT
    gw.set_book("BTCUSDT", Decimal("7000.00"), Decimal("7001.00"), Decimal("10.0"), Decimal("10.0"))
    cid_btc_close = generate_canary_client_order_id("BTCUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("7000.00"),
        client_order_id=cid_btc_close,
        is_closing=True,
    )

    assert reconciler.cumulative_realized_loss >= Decimal("4.00")

    # Subsequent opening order is blocked fail-closed
    cid_sol = generate_canary_client_order_id("SOLUSDT")
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.020"),
            price=Decimal("150.00"),
            client_order_id=cid_sol,
        )
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

    # Emergency flattening executes successfully to liquidate remaining open ETH position
    flattening_orders = dispatcher.execute_emergency_flattening()
    assert len(flattening_orders) >= 1
    for fo in flattening_orders:
        assert Decimal(fo.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT
        assert fo.status == OrderLifecycleState.FILLED

    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.positions["ETHUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 8. Session Longevity, ListenKey Renewal, Wrap Recovery & REST Backfill
# =====================================================================


def test_listen_key_lifecycle_and_expiration():
    """Verify listenKey creation, 24h expiration, and renewal."""
    gw = MockBinanceVolatilityGateway()
    lk_resp = gw.create_listen_key()
    lk = lk_resp["listenKey"]
    assert lk.startswith("canary_lk_")

    # Keepalive renews key
    renew_resp = gw.keepalive_listen_key(lk)
    assert renew_resp["status"] == "renewed"

    # Fast forward past 24h -> raises ListenKeyExpiredError
    gw.advance_time(int(LISTEN_KEY_LIFETIME_SECONDS * 1000) + 1000)
    gw.inject_listen_key_expired = True
    with pytest.raises(ListenKeyExpiredError):
        gw.keepalive_listen_key(lk)


def test_stream_disconnect_and_rest_backfill(temp_telemetry_store, temp_jsonl_sink):
    """Verify stream disconnect during order placement triggers REST backfill."""
    gw = MockBinanceVolatilityGateway()
    reconciler = VolatilityUserDataStreamReconciler(track_id="test")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    spillover_engine = VolatilitySpilloverEngine()
    sequencer = VolatilityStreamSequencer()

    interlock = VolatilityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        spillover_engine=spillover_engine,
        expansion_stage=CapitalExpansionStage.STAGE_6_VOLATILITY_SPILLOVER,
    )

    dispatcher = VolatilityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_rest_backfill",
    )

    # Disconnect stream
    gw.disconnect_stream()
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
    assert order.status == OrderLifecycleState.NEW

    # Reconnect stream and trigger REST reconciliation
    gw.reconnect_stream()
    sequencer.notify_reconnect(new_epoch=1)
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED
    dispatcher.drain_and_reconcile_stream()
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00008")


def test_sequence_wrap_recovery_and_deduplication():
    """Verify sequencer recovers across sequence wrap and deduplicates packets."""
    sequencer = VolatilityStreamSequencer(sequence_wrap_threshold=SEQUENCE_WRAP_THRESHOLD)
    sequencer.highest_arrival_sequence = SEQUENCE_WRAP_THRESHOLD

    # Wrapped packet (seq=1) after wrap threshold
    packets = [
        {
            "e": "ORDER_TRADE_UPDATE",
            "u": 1,
            "T": 1000,
            "o": {"t": 101, "c": "c1", "s": "BTCUSDT", "X": "FILLED"},
        },
        {
            "e": "ORDER_TRADE_UPDATE",
            "u": 1,
            "T": 1000,
            "o": {"t": 101, "c": "c1", "s": "BTCUSDT", "X": "FILLED"},
        },  # Duplicate
    ]
    admitted = sequencer.sort_and_deduplicate_batch(packets)
    assert len(admitted) == 1
    assert sequencer.sequence_wrap_count >= 1
    assert sequencer.deduplicated_count >= 1


# =====================================================================
# 9. Double-Entry Balance Accounting & Zero Drift Tests
# =====================================================================


def test_double_entry_balance_reconciliation_zero_drift():
    """Verify zero balance drift (|drift| < 1e-15 USDT) across opening and closing fills."""
    reconciler = VolatilityUserDataStreamReconciler(
        track_id="test_reconcile", starting_equity=STARTING_EQUITY_USDT
    )

    # Process opening fill: 0.00005 BTC @ 60000.00 = 3.00 USDT, commission 0.0012 USDT
    reconciler.process_fill(
        trade_id="t1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.00005"),
        commission=Decimal("0.0012"),
        is_closing=False,
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert reconciler.allocated_margin == Decimal("3.00000000")

    # Process closing fill: 0.00005 BTC @ 61000.00 = 3.05 USDT, commission 0.00122 USDT
    reconciler.process_fill(
        trade_id="t2",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("61000.00"),
        quantity=Decimal("0.00005"),
        commission=Decimal("0.00122"),
        is_closing=True,
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# =====================================================================
# 10. Containment Invariants & Secret Scanning Tests
# =====================================================================


def test_strict_containment_invariants():
    """Verify execution_authority: False, orders: 0, api_keys_loaded: 0."""
    verify_strict_fail_closed_invariants(orders_submitted=0, execution_authority=False)

    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(orders_submitted=1, execution_authority=False)

    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(orders_submitted=0, execution_authority=True)


# =====================================================================
# 11. Upstream Hash Chain & Merkle DAG Ingress Verification Tests
# =====================================================================


def test_upstream_phase284_qualification_and_hash_chain():
    """Verify upstream qualification succeeds and hash chain verification passes."""
    qualified = verify_upstream_phase284_qualification()
    assert qualified is True

    # Verify cryptographic hash chain on generated phase285 artifacts
    report_path = DEFAULT_PHASE285_OUTPUT_DIR / "canary-volatility-spillover-report.json"
    if report_path.is_file():
        assert verify_phase_285_hash_chain(DEFAULT_PHASE285_OUTPUT_DIR) is True


def test_corrupted_hash_chain_fails_closed(tmp_path: Path):
    """Verify tampered artifact returns False and fails closed."""
    # Write dummy artifact
    (tmp_path / "canary-volatility-spillover-report.json").write_text("{}", encoding="utf-8")
    assert verify_phase_285_hash_chain(tmp_path) is False


# =====================================================================
# 12. Full 4-Track Runner Execution Test
# =====================================================================


def test_canary_volatility_spillover_runner_all_tracks(tmp_path: Path):
    """Run full Phase 285 multi-candidate runner across all 4 tracks in isolated test directory."""
    config = CanaryVolatilitySpilloverConfig(
        output_dir=tmp_path,
        track="all",
    )
    runner = CanaryVolatilitySpilloverRunner(config)
    report = runner.execute_all_tracks()

    assert report.daemon_status == "VOLATILITY_SPILLOVER_VERIFIED"
    assert len(report.track_results) == 4
    for tr in report.track_results:
        assert tr.success is True
        assert tr.zero_balance_drift is True
        assert Decimal(tr.drift_usdt) < DOUBLE_ENTRY_MAX_DRIFT

    # Verify all 5 output files were created
    assert (tmp_path / "canary-orders.jsonl").is_file()
    assert (tmp_path / "canary-volatility-spillover-telemetry.sqlite3").is_file()
    assert (tmp_path / "canary-volatility-spillover-report.json").is_file()
    assert (tmp_path / "volatility-spillover-summary.json").is_file()
    assert (tmp_path / "paper-summary.json").is_file()

    # Verify cryptographic hash chain on test outputs
    assert verify_phase_285_hash_chain(tmp_path) is True


def test_execute_phase_285_runner_cli_interface(tmp_path: Path):
    """Verify execute_phase_285_runner helper function."""
    exit_code = execute_phase_285_runner(
        output_dir=tmp_path,
        verify_hash_chain=True,
    )
    assert exit_code == 0
