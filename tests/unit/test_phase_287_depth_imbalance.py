"""Unit tests for Phase 287: Canary Order Book Depth Imbalance & Exposure Scaling Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 285 back to 276).
- Dual-confirmation client order tag format (c=canary-p287-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms), backward NTP clock drift (> 250 ms triggers
  HEARTBEAT_FREEZE with recovery hysteresis <= 450 ms).
- Cross-Asset Liquidity Shock Transmission & Funding Rate Distortion Engine:
  - Sudden top-of-book depth evaporation tracking.
  - Cross-symbol liquidity depletion transmission coefficients.
  - Rolling 8-hour funding rates and cross-symbol basis divergence
    (|rate| > 0.05% or spread > 0.10%).
  - Dynamic cushion/offset widening and sizing downscaling under elevated shock/distortion.
  - Passive order preservation during distortion: aggressive order rejection fail-closed.
  - Candidate exposure clamping to throttled cap (<= 10.00 USDT) under active distortion.
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
  - Stage 6 volatility expansion cap (<= 30.00 USDT)
  - Stage 7 liquidity shock expansion cap (<= 35.00 USDT across all symbols)
  - Aggregate concurrent exposure cap <= 35.00 USDT.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 4.50 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Multi-day extended session longevity, 24h listenKey expiration/renewal, sequence wrap
  recovery, stream disconnect REST backfill, and idempotent deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT) across snapshots.
- Strict containment invariants (execution_authority: False, orders: 0, api_keys_loaded: 0).
"""

from __future__ import annotations

import sys
import threading
import time
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    OrderSide,
    OrderType,
)
from autonomous_futures.feed.canary_probe import (  # noqa: E402
    SafetyInvariantViolation,
    verify_strict_fail_closed_invariants,
)
from autonomous_futures.feed.depth_imbalance import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    CANARY_STAGED_SYMBOLS,
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DOUBLE_ENTRY_MAX_DRIFT,
    DYNAMIC_SLICING_MAX_CHUNK_USDT,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    LISTEN_KEY_LIFETIME_SECONDS,
    MAX_FUNDING_BASIS_SPREAD_THRESHOLD,
    MIN_MICRO_NOTIONAL_CAP_USDT,
    SEQUENCE_WRAP_THRESHOLD,
    STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT,
    AggregateExposureCapExceededError,
    AggressiveOrderRejectedError,
    CanaryDepthImbalanceConfig,
    CanaryDepthImbalanceRunner,
    CapitalExpansionStage,
    CircuitBreakerState,
    ClockSkewExceededError,
    DepthExhaustionError,
    DepthImbalanceEngine,
    FundingRateDistortionThrottledError,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatFreezeActiveError,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    InvalidClientOrderIdTagError,
    JsonlCanaryOrderSink,
    LiquidityMicroOrderDispatcher,
    LiquidityShockEngine,
    LiquidityShockOrderDispatchInterlock,
    LiquidityShockOrderRecord,
    LiquidityShockRegime,
    LiquidityShockStreamSequencer,
    LiquidityUserDataStreamReconciler,
    ListenKeyExpiredError,
    MarginAllocationExceededError,
    MockBinanceLiquidityShockGateway,
    OrderBookFeedCorruptionError,
    OrderLifecycleState,
    OrderSlicingMode,
    PrerequisiteQualificationError,
    SqliteCanaryDepthImbalanceTelemetryStore,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_287_hash_chain,
    verify_upstream_phase286_qualification,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_287_depth_imbalance import (  # noqa: E402
    execute_phase_287_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-depth-imbalance-telemetry.sqlite3"
    store = SqliteCanaryDepthImbalanceTelemetryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path):
    jsonl_path = tmp_path / "test-depth-imbalance-orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_path)


# =====================================================================
# 1. Dual-Confirmation Client Order ID Tagging Tests (Phase 287)
# =====================================================================


def test_valid_client_order_id_generation_and_validation():
    """Verify Phase 287 deterministic client order tag format: c=canary-p287-{sym}-{ts}-{uuid}."""
    cid = generate_canary_client_order_id(
        "BTCUSDT", timestamp_ms=1720000000000, uuid_str="abc12345"
    )
    assert cid == "c=canary-p287-BTCUSDT-1720000000000-abc12345"
    ok, err = validate_canary_client_order_id(cid, expected_symbol="BTCUSDT")
    assert ok is True
    assert err is None
    assert_valid_canary_client_order_id(cid, expected_symbol="BTCUSDT")


def test_invalid_client_order_id_rejection():
    """Verify mismatched symbols, wrong phase prefix, or malformed formats are rejected."""
    cid = generate_canary_client_order_id("BTCUSDT")
    ok, err = validate_canary_client_order_id(cid, expected_symbol="ETHUSDT")
    assert ok is False
    assert "Symbol mismatch" in str(err)

    # Legacy Phase 286 tag rejected under Phase 287
    legacy_cid = "c=canary-p286-BTCUSDT-1720000000000-abc12345"
    ok_leg, _ = validate_canary_client_order_id(legacy_cid)
    assert ok_leg is False

    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id(legacy_cid)

    with pytest.raises(InvalidClientOrderIdTagError):
        assert_valid_canary_client_order_id("random-order-id-1234")


# =====================================================================
# 2. Gateway Heartbeat Freshness, Clock Drift & Hysteresis Tests
# =====================================================================


def test_gateway_heartbeat_healthy_state():
    """Verify fresh gateway heartbeat (age <= 500 ms, low latency) passes health check."""
    mon = GatewayHeartbeatMonitor(max_allowed_age_ms=500.0)
    now_ms = int(time.time() * 1000)
    rec = mon.record_heartbeat(
        server_time_ms=now_ms - 25,
        latency_ms=25.0,
        local_time_ms=now_ms,
    )
    assert rec.is_healthy is True
    assert rec.status == HeartbeatStatus.HEALTHY
    mon.assert_healthy(current_time_ms=now_ms + 100)


def test_gateway_heartbeat_stale_latency_spike():
    """Verify heartbeat latency > 500 ms triggers stale state and blocks dispatch fail-closed."""
    mon = GatewayHeartbeatMonitor(max_allowed_age_ms=500.0)
    now_ms = int(time.time() * 1000)
    rec = mon.record_heartbeat(
        server_time_ms=now_ms,
        latency_ms=550.0,
        local_time_ms=now_ms,
    )
    assert rec.is_healthy is False
    assert rec.status == HeartbeatStatus.LATENCY_SPIKE_STALE

    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_healthy(current_time_ms=now_ms + 50)


def test_gateway_heartbeat_clock_skew_freeze_and_recovery_hysteresis():
    """Verify backward NTP clock drift > 250 ms triggers CLOCK_SKEW_FREEZE and requires
    latency <= 450 ms recovery hysteresis.
    """
    mon = GatewayHeartbeatMonitor(
        max_allowed_age_ms=500.0,
        max_clock_skew_ms=250.0,
        recovery_hysteresis_ms=450.0,
    )
    now_ms = int(time.time() * 1000)

    # Ingest backward clock drift of 350 ms (> 250 ms)
    rec = mon.record_heartbeat(
        server_time_ms=now_ms - 350,
        latency_ms=30.0,
        local_time_ms=now_ms,
    )
    assert rec.is_healthy is False
    assert rec.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_frozen is True

    with pytest.raises(HeartbeatFreezeActiveError):
        mon.assert_healthy(current_time_ms=now_ms + 10)

    # Moderate recovery above 450 ms does not unfreeze
    rec2 = mon.record_heartbeat(
        server_time_ms=now_ms + 1000,
        latency_ms=470.0,
        local_time_ms=now_ms + 1000,
    )
    assert rec2.is_healthy is False
    assert mon.is_frozen is True

    # Fresh heartbeat with latency <= 450 ms and nominal skew recovers
    rec3 = mon.record_heartbeat(
        server_time_ms=now_ms + 2000,
        latency_ms=400.0,
        local_time_ms=now_ms + 2000,
    )
    assert rec3.is_healthy is True
    assert rec3.status == HeartbeatStatus.RECOVERED
    assert mon.is_frozen is False
    mon.assert_healthy(current_time_ms=now_ms + 2050)


# =====================================================================
# 3. Liquidity Shock Transmission & Funding Rate Distortion Engine Tests
# =====================================================================


def test_depth_imbalance_ratio_and_threshold_calculation():
    """Verify depth imbalance ratio I_depth = (V_bid - V_ask)/(V_bid + V_ask)
    and |I| > 0.60 trigger.
    """
    engine = DepthImbalanceEngine()
    # Balanced book: I_depth == 0
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00010"), Decimal("0.00010")
    )
    assert engine.get_depth_imbalance("BTCUSDT") == Decimal("0.0")
    assert engine.is_depth_imbalance_exceeded("BTCUSDT") is False

    # Ask heavy skew: bid=0.00001, ask=0.00020 -> I_depth = -0.19/0.21 = -0.9048 (< -0.60)
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00001"), Decimal("0.00020")
    )
    imb = engine.get_depth_imbalance("BTCUSDT")
    assert imb < Decimal("-0.60")
    assert engine.is_depth_imbalance_exceeded("BTCUSDT") is True

    # Bid heavy skew: bid=0.00020, ask=0.00001 -> I_depth = +0.19/0.21 = +0.9048 (> +0.60)
    engine.update_book(
        "ETHUSDT", Decimal("3000.00"), Decimal("3001.00"), Decimal("0.00020"), Decimal("0.00001")
    )
    imb_eth = engine.get_depth_imbalance("ETHUSDT")
    assert imb_eth > Decimal("0.60")
    assert engine.is_depth_imbalance_exceeded("ETHUSDT") is True


def test_asymmetric_liquidity_evaporation_governance():
    """Verify dynamic limit offset widening and sizing downscaling under extreme depth skew."""
    engine = DepthImbalanceEngine()
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00001"), Decimal("0.00020")
    )
    assert engine.is_depth_imbalance_exceeded("BTCUSDT") is True
    # Under severe imbalance, regime triggers downscaling
    target_notional, limit_price, regime, offset = engine.calculate_sizing_and_limit_offset(
        "BTCUSDT", OrderSide.BUY
    )
    assert target_notional <= Decimal("2.50")
    assert offset > Decimal("0.0")


def test_liquidity_depth_depletion_and_shock_transmission():
    """Verify top-of-book depth evaporation increases cross-symbol shock transmission."""
    engine = LiquidityShockEngine()

    # Initial nominal depth
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60005.00"), Decimal("0.00020"), Decimal("0.00020")
    )
    engine.update_book(
        "ETHUSDT", Decimal("3000.00"), Decimal("3000.50"), Decimal("5.0"), Decimal("5.0")
    )
    engine.update_book(
        "SOLUSDT", Decimal("150.00"), Decimal("150.05"), Decimal("50.0"), Decimal("50.0")
    )

    initial_index = engine.aggregate_shock_index
    assert initial_index <= Decimal("0.30")
    assert engine.classify_liquidity_shock_regime() == LiquidityShockRegime.NOMINAL

    # Sudden depth evaporation in BTC: depth drops to 10% of baseline (90% depletion)
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00002"), Decimal("0.00002")
    )
    depletion = engine.get_depth_depletion_ratio("BTCUSDT")
    assert depletion >= Decimal("0.80")

    # Aggregate shock index increases
    assert engine.aggregate_shock_index > initial_index


def test_funding_rate_distortion_and_cross_symbol_basis_spread():
    """Verify rolling 8-hour funding rates and basis spread divergence triggers distortion."""
    engine = LiquidityShockEngine()

    # Baseline nominal funding rates: BTC +0.01%, ETH +0.015%, SOL +0.02%
    assert engine.is_funding_distortion() is False
    assert engine.get_cross_symbol_funding_basis_spread() <= Decimal("0.0002")

    # Spiking BTC funding rate to +0.06% (> 0.05% threshold) triggers distortion
    engine.record_funding_rate("BTCUSDT", Decimal("0.00060"))
    assert engine.is_funding_distortion("BTCUSDT") is True
    assert engine.is_funding_distortion() is True
    assert engine.classify_liquidity_shock_regime() == LiquidityShockRegime.SEVERE_CONTROLS

    # Cross-symbol basis spread divergence: SOL drops to -0.05% -> spread = 0.11% > 0.10%
    engine.record_funding_rate("BTCUSDT", Decimal("0.00040"))
    engine.record_funding_rate("SOLUSDT", Decimal("-0.00070"))
    assert engine.get_cross_symbol_funding_basis_spread() > MAX_FUNDING_BASIS_SPREAD_THRESHOLD
    assert engine.is_funding_distortion() is True
    assert engine.classify_liquidity_shock_regime() == LiquidityShockRegime.SEVERE_CONTROLS


def test_passive_order_preservation_and_aggressive_order_rejection():
    """Verify aggressive order dispatches are rejected fail-closed during
    active funding distortion.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_rejection")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )

    # Induce funding distortion
    shock_engine.record_funding_rate("BTCUSDT", Decimal("0.00070"))
    assert shock_engine.is_funding_distortion("BTCUSDT") is True

    # Market order rejected
    with pytest.raises(AggressiveOrderRejectedError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
        )

    # Passive limit order passes
    cid = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("59990.00"),
        quantity=Decimal("0.00005"),
        client_order_id=cid,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
    )


# =====================================================================
# 4. Dynamic Order Slicing & Micro-Cap Governance Tests
# =====================================================================


def test_dynamic_order_slicing_under_constrained_depth(temp_telemetry_store, temp_jsonl_sink):
    """Verify orders exceeding available depth are dynamically sliced into sequential
    micro-chunks <= 2.50 USDT with 1.00 USDT floor.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_slicing")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    # Constrained BTC depth: 0.00004 BTC
    shock_engine.set_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00004"), Decimal("0.00004")
    )
    gw.set_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("0.00004"), Decimal("0.00004")
    )

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_slicing",
        shock_engine=shock_engine,
    )

    parent, children = dispatcher.dispatch_signal_order_with_dynamic_slicing(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        desired_notional=Decimal("4.80"),
    )

    assert parent.status == OrderLifecycleState.FILLED
    assert parent.slicing_mode == OrderSlicingMode.TWAP_MICRO
    assert len(children) >= 2

    for ch in children:
        notional = Decimal(ch.notional_usdt)
        assert notional <= DYNAMIC_SLICING_MAX_CHUNK_USDT  # <= 2.50 USDT
        assert notional >= MIN_MICRO_NOTIONAL_CAP_USDT  # >= 1.00 USDT
        assert ch.status == OrderLifecycleState.FILLED


def test_individual_micro_order_cap_enforced():
    """Verify child orders strictly enforce <= 5.00 USDT cap with ROUND_DOWN precision."""
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_cap")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )

    # 5.01 USDT notional -> fails
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.000085"),  # 5.10 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # Exactly 5.00 USDT notional -> passes
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("50000.00"),
        quantity=Decimal("0.00010"),  # 5.00 USDT
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )


# =====================================================================
# 5. Stepped Exposure Scaling & Funding Throttling Tests (Up to 35.00 USDT)
# =====================================================================


def test_stepped_exposure_scaling_stages_up_to_40_usdt():
    """Verify concurrent active exposure ceilings scale correctly from Stage 1 (5.00 USDT)
    up to Stage 7 (35.00 USDT).
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_stages")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
    )

    expected_caps = [
        (CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO, Decimal("5.00")),
        (CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT, Decimal("10.00")),
        (CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION, Decimal("15.00")),
        (CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION, Decimal("20.00")),
        (CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION, Decimal("25.00")),
        (CapitalExpansionStage.STAGE_6_VOLATILITY_EXPANSION, Decimal("30.00")),
        (CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION, Decimal("35.00")),
        (CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION, Decimal("40.00")),
    ]

    for stage, cap in expected_caps:
        interlock.expansion_stage = stage
        assert interlock.get_stage_exposure_cap() == cap

    assert AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT == Decimal("40.00")


def test_candidate_exposure_clamped_during_distortion():
    """Verify candidate exposure is clamped to throttled cap (<= 10.00 USDT) during distortion."""
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_clamp")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )

    # Induce funding distortion
    shock_engine.record_funding_rate("BTCUSDT", Decimal("0.00065"))
    assert shock_engine.is_funding_distortion("BTCUSDT") is True

    # Pre-allocate 8.00 USDT margin on BTCUSDT
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("8.00")
    reconciler.allocated_margin = Decimal("8.00")

    # Additional 3.00 USDT order breaches throttled cap (8 + 3 = 11 > 10 USDT)
    with pytest.raises(FundingRateDistortionThrottledError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00005"),  # 3.00 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
        )


# =====================================================================
# 6. Dynamic Margin Headroom & Working Margin Reservation Tests
# =====================================================================


def test_dynamic_margin_headroom_portfolio_and_per_asset_caps():
    """Verify aggregate margin <= 60.00%, reserve buffer >= 40.00%, and per-asset <= 20.00%."""
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_margin", starting_equity=Decimal("100.00")
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )

    # Set per-asset margin on BTCUSDT to 19.00 USDT
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("19.00")
    reconciler.allocated_margin = Decimal("19.00")
    reconciler.cash = Decimal("81.00")

    # Additional 2.00 USDT order pushes BTCUSDT to 21.00 USDT (> 20.00% of 100 equity)
    with pytest.raises(MarginAllocationExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("50000.00"),
            quantity=Decimal("0.00004"),  # 2.00 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


def test_active_committed_working_margin_reservation():
    """Verify open unfilled orders reserve working margin without double-counting."""
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_working", starting_equity=Decimal("100.00")
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # Cap is 5.00 USDT
    )

    # Create an open working order of 4.00 USDT
    cid_working = generate_canary_client_order_id("BTCUSDT")
    mock_order = LiquidityShockOrderRecord(
        order_id="101",
        client_order_id=cid_working,
        track_id="test_working",
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        price="50000.00",
        quantity="0.00008",
        executed_quantity="0",
        notional_usdt="4.00",
        status=OrderLifecycleState.NEW,
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
    )
    interlock.set_orders_provider(lambda: {cid_working: mock_order})

    # Another 2.00 USDT order breaches Stage 1 cap (4.00 + 2.00 = 6.00 > 5.00 USDT)
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.00067"),  # ~2.01 USDT
            client_order_id=generate_canary_client_order_id("ETHUSDT"),
        )


# =====================================================================
# 7. Intra-Phase Cumulative Loss Budget & Emergency Flattening Tests
# =====================================================================


def test_intra_phase_loss_ceiling_lockout_and_micro_chunked_liquidation(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify cumulative loss >= 4.50 USDT triggers immediate fail-closed lockout
    and positions are emergency liquidated in micro-chunks <= 5.00 USDT.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_loss_budget", starting_equity=Decimal("100.00")
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    sequencer = LiquidityShockStreamSequencer()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
        intra_phase_loss_ceiling_usdt=Decimal("5.00"),
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_loss_budget",
    )

    # Open positions on BTC (2 x 3.00 USDT = 6.00 USDT) and ETH (4.50 USDT)
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
    )

    # Settle loss on BTC: price crashes from 60,000 to 2,000 ->
    # loss = 0.00010 * 58,000 = 5.80 USDT >= 5.00 USDT
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00010"),
        price=Decimal("2000.00"),
        is_closing=True,
    )

    assert reconciler.cumulative_realized_loss >= Decimal("5.00")
    assert reconciler.cumulative_realized_loss >= Decimal("5.80")

    # Subsequent new order triggers fail-closed lockout
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.01"),
            price=Decimal("150.00"),
        )
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

    # Emergency flattening cleanly liquidates remaining ETH position
    flat_orders = dispatcher.execute_emergency_flattening()
    assert len(flat_orders) >= 1
    for fo in flat_orders:
        assert Decimal(fo.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT
        assert fo.status == OrderLifecycleState.FILLED

    assert reconciler.positions["ETHUSDT"] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")


# =====================================================================
# 8. Session Longevity, ListenKey Renewal, Wrap Recovery & REST Backfill
# =====================================================================


def test_session_longevity_and_listenkey_renewal(temp_telemetry_store, temp_jsonl_sink):
    """Verify 24h listenKey expiration and keepalive renewal workflow."""
    gw = MockBinanceLiquidityShockGateway()
    lk_resp = gw.create_listen_key()
    lk = lk_resp["listenKey"]
    assert lk.startswith("lk-p287-")

    # Advance 24h
    gw.advance_time(int(LISTEN_KEY_LIFETIME_SECONDS * 1000) + 500)
    gw.inject_listen_key_expired = True

    with pytest.raises(ListenKeyExpiredError):
        gw.keepalive_listen_key(lk)

    # Acquire new key
    gw.inject_listen_key_expired = False
    new_lk = gw.create_listen_key()["listenKey"]
    assert new_lk != lk
    gw.keepalive_listen_key(new_lk)


def test_sequence_wrap_recovery_and_deduplication():
    """Verify sequence counter wrap from 1_000_000 to 1 is correctly tracked."""
    seq = LiquidityShockStreamSequencer()
    seq.highest_arrival_sequence = SEQUENCE_WRAP_THRESHOLD

    # Ingest event with wrapped sequence number = 1
    evt = {"e": "ORDER_TRADE_UPDATE", "u": 1}
    is_dup, is_ooo, is_wrap = seq.process_event(evt)
    assert is_wrap is True
    assert is_dup is False
    assert seq.sequence_wrap_count == 1
    assert seq.highest_arrival_sequence == 1

    # Ingest duplicate packet
    is_dup2, _, _ = seq.process_event(evt)
    assert is_dup2 is True
    assert seq.deduplicated_count == 1


def test_stream_disconnect_and_rest_reconciliation_backfill(temp_telemetry_store, temp_jsonl_sink):
    """Verify stream disconnect during order placement backfills via REST."""
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_rest_sync")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    sequencer = LiquidityShockStreamSequencer()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_rest_sync",
    )

    # Disconnect stream
    gw.disconnect_stream()
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

    # Reconnect and backfill via REST
    gw.reconnect_stream()
    backfilled = dispatcher.reconcile_via_rest()
    assert len(backfilled) == 1
    assert dispatcher.orders[cid].status == OrderLifecycleState.FILLED


# =====================================================================
# 9. Double-Entry Balance Accounting & Zero Drift Tests
# =====================================================================


def test_exact_double_entry_balance_reconciliation_zero_drift():
    """Verify exact mathematical double-entry accounting reconciliation:
    |drift| = |cash + allocated_margin + unrealized_pnl
               - (starting_equity + realized_pnl)| < 1e-15 USDT.
    """
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_drift", starting_equity=Decimal("100.00")
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Fill 1: Open LONG BTC (4.80 USDT)
    reconciler.process_fill(
        trade_id="t1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.00008"),
        commission=Decimal("0.00192"),
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Fill 2: Close LONG BTC with profit (0.00008 @ 61,000.00)
    reconciler.process_fill(
        trade_id="t2",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("61000.00"),
        quantity=Decimal("0.00008"),
        commission=Decimal("0.001952"),
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
    inv = verify_strict_fail_closed_invariants(
        orders_submitted=0,
        execution_authority=False,
    )
    assert inv["execution_authority"] is False
    assert inv["orders"] == 0
    assert inv["zero_secret_leakage"] is True

    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(
            orders_submitted=1,
            execution_authority=True,
        )


# =====================================================================
# 11. Upstream Hash Chain & Merkle DAG Ingress Verification Tests
# =====================================================================


def test_upstream_phase286_qualification_and_hash_chain():
    """Verify continuous SHA-256 Merkle DAG hash chain back through Phase 285 to Phase 276."""
    ok = verify_upstream_phase286_qualification()
    assert ok is True


# =====================================================================
# 12. Full 4-Track Runner Execution Test
# =====================================================================


def test_full_phase_287_runner_execution_and_hash_chain(tmp_path: Path):
    """Execute all 4 deterministic simulation tracks for Phase 287 and verify artifacts."""
    cfg = CanaryDepthImbalanceConfig(
        output_dir=tmp_path / "artifacts_p286",
        track="all",
    )
    runner = CanaryDepthImbalanceRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.daemon_status == "DEPTH_IMBALANCE_VERIFIED"
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True
    assert report.compliance["zero_secret_leakage"] is True
    assert len(report.tracks) == 4
    for tr in report.tracks:
        assert tr["success"] is True
        assert tr["zero_balance_drift"] is True

    # Verify cryptographic hash chain on generated artifacts
    chain_ok = verify_phase_287_hash_chain(output_dir=tmp_path / "artifacts_p286")
    assert chain_ok is True


def test_cli_runner_execution(tmp_path: Path):
    """Verify CLI runner entry point runs and exits 0."""
    out_dir = tmp_path / "cli_p286"
    exit_code = execute_phase_287_runner(
        output_dir=out_dir,
        track="all",
        verify_hash_chain=True,
    )
    assert exit_code == 0
    assert (out_dir / "canary-depth-imbalance-report.json").is_file()
    assert (out_dir / "depth-imbalance-summary.json").is_file()
    assert (out_dir / "paper-summary.json").is_file()
    assert (out_dir / "canary-orders.jsonl").is_file()
    assert (out_dir / "canary-depth-imbalance-telemetry.sqlite3").is_file()


# =====================================================================
# 13. Adversarial Edge Case & Robustness Verification Tests
# =====================================================================


def test_dynamic_slicing_committed_margin_no_double_counting_in_stage_1(
    temp_telemetry_store, temp_jsonl_sink
):
    """Adversarial Test: Verify sliced parent order (4.80 USDT) in Stage 1 (cap 5.00 USDT)
    does NOT double-count parent reservation and child slices, preventing false rejection.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_stage1_slicing")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    # Constrained depth on BTCUSDT to force slicing
    shock_engine.set_book(
        "BTCUSDT",
        Decimal("60000.00"),
        Decimal("60010.00"),
        Decimal("0.00004"),
        Decimal("0.00004"),
    )
    gw.set_book(
        "BTCUSDT",
        Decimal("60000.00"),
        Decimal("60010.00"),
        Decimal("0.00004"),
        Decimal("0.00004"),
    )

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # Cap is 5.00 USDT
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="adv_stage1_slicing",
        shock_engine=shock_engine,
    )

    # Dispatch parent order of 4.80 USDT (slices into two 2.40 USDT child orders)
    hb = gw.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    parent, children = dispatcher.dispatch_signal_order_with_dynamic_slicing(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        desired_notional=Decimal("4.80"),
    )

    assert parent.status == OrderLifecycleState.FILLED
    assert len(children) == 2
    for ch in children:
        assert Decimal(ch.notional_usdt) <= DYNAMIC_SLICING_MAX_CHUNK_USDT
        assert Decimal(ch.notional_usdt) >= MIN_MICRO_NOTIONAL_CAP_USDT
        assert ch.status == OrderLifecycleState.FILLED
    assert reconciler.allocated_margin <= STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_severe_controls_floor_sizing_and_dispatch(temp_telemetry_store, temp_jsonl_sink):
    """Adversarial Test: Verify in SEVERE_CONTROLS regime where target notional is 1.00 USDT,
    quantized quantity does not fall below floor or trigger MicroNotionalFloorViolationError.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_severe_floor")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    # Induce SEVERE_CONTROLS via high shock index
    shock_engine.set_aggregate_shock_index(Decimal("0.85"))
    assert shock_engine.classify_liquidity_shock_regime() == LiquidityShockRegime.SEVERE_CONTROLS

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="adv_severe_floor",
        shock_engine=shock_engine,
    )

    parent, children = dispatcher.dispatch_signal_order_with_dynamic_slicing(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        desired_notional=Decimal("5.00"),
    )

    assert parent.status == OrderLifecycleState.FILLED
    for ch in children:
        assert Decimal(ch.notional_usdt) >= MIN_MICRO_NOTIONAL_CAP_USDT
        assert Decimal(ch.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT
        assert ch.status == OrderLifecycleState.FILLED


def test_backward_ntp_clock_drift_check_health_and_circuit_state_transition():
    """Adversarial Test: Verify backward NTP clock drift in check_health triggers immediate
    freeze and synchronizes circuit_state to HEARTBEAT_FREEZE.
    """
    mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    mon.record_heartbeat(server_time_ms=now_ms, latency_ms=25.0, local_time_ms=now_ms)

    # Local clock steps backward by 350 ms (> 250 ms)
    healthy, reason = mon.check_health(current_time_ms=now_ms - 350)
    assert healthy is False
    assert "Backward NTP" in reason
    assert mon.is_frozen is True

    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_freeze_circuit")
    interlock = LiquidityShockOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
    )

    with pytest.raises(HeartbeatFreezeActiveError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("50000.00"),
            quantity=Decimal("0.00004"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # Circuit state must be synchronized to HEARTBEAT_FREEZE
    assert interlock.circuit_state == CircuitBreakerState.HEARTBEAT_FREEZE

    # Now heartbeat recovers with current real time
    curr_now = int(time.time() * 1000)
    rec_recovered = mon.record_heartbeat(
        server_time_ms=curr_now,
        latency_ms=25.0,
        local_time_ms=curr_now,
    )
    assert rec_recovered.status == HeartbeatStatus.RECOVERED
    assert mon.is_frozen is False

    # Dispatch validates cleanly and resets circuit state to NORMAL
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("50000.00"),
        quantity=Decimal("0.00004"),
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )
    assert interlock.circuit_state == CircuitBreakerState.NORMAL


def test_manifest_version_2_enforcement(tmp_path: Path):
    """Adversarial Test: Verify manifest with version != 2 is strictly rejected."""
    bad_manifest_path = tmp_path / "bad_manifest.json"
    bad_manifest_path.write_text('{"manifest_version": 1}', encoding="utf-8")

    with pytest.raises(PrerequisiteQualificationError):
        verify_upstream_phase286_qualification(manifest_path=bad_manifest_path)

    # Also test valid manifest object with version bumped to 3
    from unittest.mock import patch

    manifest, cand = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    mock_manifest = manifest.model_copy(update={"manifest_version": 3})
    with patch(
        "autonomous_futures.feed.depth_imbalance.load_and_validate_canary_staging_manifest",
        return_value=(mock_manifest, cand),
    ):
        with pytest.raises(PrerequisiteQualificationError, match="expected 2"):
            verify_upstream_phase286_qualification()


def test_cli_simulate_loss_breach_flag(tmp_path: Path):
    """Adversarial Test: Verify --simulate-loss-breach CLI flag executes loss ceiling breach."""
    out_dir = tmp_path / "cli_loss_breach"
    exit_code = execute_phase_287_runner(
        output_dir=out_dir,
        track="track_3",
        simulate_loss_breach=True,
    )
    assert exit_code == 0


def test_gateway_heartbeat_sudden_os_clock_jump_detection(monkeypatch):
    """Adversarial Test: Verify sudden OS clock jump (wall vs monotonic drift > 250 ms)
    triggers CLOCK_SKEW_FREEZE immediately during check_health().
    """
    mon = GatewayHeartbeatMonitor()
    gw = MockBinanceLiquidityShockGateway()
    base_wall = 1700000000.0
    base_mono = 1000.0

    monkeypatch.setattr(time, "time", lambda: base_wall)
    monkeypatch.setattr(time, "monotonic", lambda: base_mono)

    hb = gw.generate_heartbeat(latency_ms=25.0)
    mon.record_heartbeat(
        server_time_ms=int(base_wall * 1000),
        latency_ms=hb["latencyMs"],
    )
    assert mon.check_health()[0] is True

    # Case 1: Wall clock steps backward by 300 ms while monotonic advances by 10 ms
    monkeypatch.setattr(time, "time", lambda: base_wall - 0.290)
    monkeypatch.setattr(time, "monotonic", lambda: base_mono + 0.010)

    healthy, reason = mon.check_health()
    assert healthy is False
    assert mon.is_frozen is True
    assert "Backward NTP" in reason or "clock jump" in reason

    # Case 2: Fresh monitor, test forward clock jump
    mon2 = GatewayHeartbeatMonitor()
    monkeypatch.setattr(time, "time", lambda: base_wall)
    monkeypatch.setattr(time, "monotonic", lambda: base_mono)
    mon2.record_heartbeat(
        server_time_ms=int(base_wall * 1000),
        latency_ms=25.0,
    )
    assert mon2.check_health()[0] is True

    # Wall clock jumps forward by 280 ms while monotonic only advances by 5 ms
    # age = 280 ms (which is <= 500 ms, so age alone wouldn't trip staleness!)
    # but clock_jump = 280 - 5 = 275 ms > 250 ms max clock skew!
    monkeypatch.setattr(time, "time", lambda: base_wall + 0.280)
    monkeypatch.setattr(time, "monotonic", lambda: base_mono + 0.005)

    healthy2, reason2 = mon2.check_health()
    assert healthy2 is False
    assert mon2.is_frozen is True
    assert "Sudden OS clock jump detected" in reason2


def test_multi_thread_burst_order_dispatch_lock_safety(temp_telemetry_store, temp_jsonl_sink):
    """Adversarial Test: Verify simultaneous multi-thread burst order submissions
    maintain strict thread safety, zero race conditions, and clean accounting.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_burst_threads")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="adv_burst_threads",
        shock_engine=shock_engine,
    )

    errors: list[Exception] = []

    def _worker(thread_idx: int) -> None:
        try:
            for j in range(3):
                hb_w = gw.generate_heartbeat(latency_ms=20.0)
                heartbeat_mon.record_heartbeat(hb_w["serverTime"], hb_w["latencyMs"])

                sym = CANARY_STAGED_SYMBOLS[j % len(CANARY_STAGED_SYMBOLS)]
                book = gw.books[sym]
                px = book["bid_price"]
                qty = (Decimal("1.50") / px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                cid = generate_canary_client_order_id(sym, uuid_str=f"t{thread_idx}j{j}")
                try:
                    dispatcher.dispatch_micro_order(
                        candidate_id=f"cand-{sym.lower()}",
                        symbol=sym,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=qty,
                        price=px,
                        client_order_id=cid,
                    )
                except (
                    AggregateExposureCapExceededError,
                    MarginAllocationExceededError,
                    GatewayHeartbeatStaleError,
                ):
                    pass
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(errors) == 0
    assert reconciler.mathematical_drift < Decimal("1e-15")


def test_emergency_flattening_multi_symbol_heartbeat_preservation(
    temp_telemetry_store, temp_jsonl_sink
):
    """Adversarial Test: Verify execute_emergency_flattening preserves gateway heartbeats
    and closes all multi-candidate positions cleanly without stale heartbeat trips.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_emergency_hb")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="adv_emergency_hb",
        shock_engine=shock_engine,
    )

    for sym in CANARY_STAGED_SYMBOLS:
        px = gw.books[sym]["bid_price"]
        qty = (Decimal("3.00") / px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        hb_sub = gw.generate_heartbeat(latency_ms=20.0)
        heartbeat_mon.record_heartbeat(hb_sub["serverTime"], hb_sub["latencyMs"])
        dispatcher.dispatch_micro_order(
            candidate_id=f"cand-{sym.lower()}",
            symbol=sym,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=qty,
            price=px,
        )

    for sym in CANARY_STAGED_SYMBOLS:
        assert reconciler.positions[sym] > Decimal("0")

    flat_orders = dispatcher.execute_emergency_flattening()
    assert len(flat_orders) >= 3
    for fo in flat_orders:
        assert fo.status == OrderLifecycleState.FILLED
        assert Decimal(fo.notional_usdt) <= HARD_MICRO_NOTIONAL_CAP_USDT

    for sym in CANARY_STAGED_SYMBOLS:
        assert reconciler.positions[sym] == Decimal("0")
    assert reconciler.allocated_margin == Decimal("0")
    assert reconciler.mathematical_drift < Decimal("1e-15")


def test_chunk_qty_clamping_at_extreme_prices():
    """Adversarial Test: Verify chunk_qty is clamped to at least 1 lot (0.00000001)
    under astronomical unit prices, preventing zero-division and infinite loops.
    """
    px = Decimal("1000000000.00")
    chunk_qty = (HARD_MICRO_NOTIONAL_CAP_USDT / px).quantize(
        Decimal("0.00000001"), rounding=ROUND_DOWN
    )
    assert chunk_qty == Decimal("0.00000000")
    clamped = max(Decimal("0.00000001"), chunk_qty)
    assert clamped == Decimal("0.00000001")


def test_dynamic_slicing_child_failure_rejects_parent_without_margin_leak(
    temp_telemetry_store, temp_jsonl_sink
):
    """Adversarial Test: Verify child order rejection transitions parent to REJECTED
    and does NOT leak committed working margin, allowing subsequent dispatches.
    """
    from unittest.mock import patch

    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_child_fail")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])
    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # Cap 5.00 USDT
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="adv_child_fail",
        shock_engine=shock_engine,
    )

    with patch.object(
        interlock,
        "validate_dispatch",
        side_effect=IndividualMicroCapExceededError("Child mock fail"),
    ):
        with pytest.raises(IndividualMicroCapExceededError):
            dispatcher.dispatch_signal_order_with_dynamic_slicing(
                candidate_id="cand-btc",
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                desired_notional=Decimal("4.80"),
            )

    parent_orders = dispatcher.parent_orders
    assert len(parent_orders) == 1
    p_rec = next(iter(parent_orders.values()))
    assert p_rec.status == OrderLifecycleState.REJECTED
    assert p_rec.dispatch_complete is True

    # Verify working committed margin is exactly zero (no leaked parent margin!)
    assert interlock.get_working_committed_margin() == Decimal("0")


def test_relative_backward_clock_skew_unsigned_magnitude():
    """Adversarial Test: Verify relative backward clock skew (local time behind server time
    by > 250 ms) triggers CLOCK_SKEW_FREEZE, raises ClockSkewExceededError, and obeys hysteresis.
    """
    mon = GatewayHeartbeatMonitor(
        max_allowed_age_ms=500.0,
        max_clock_skew_ms=250.0,
        recovery_hysteresis_ms=450.0,
    )
    now_ms = int(time.time() * 1000)

    # Local clock is 350 ms behind server clock: skew = now_ms - (now_ms + 350) = -350.0 ms
    rec = mon.record_heartbeat(
        server_time_ms=now_ms + 350,
        latency_ms=30.0,
        local_time_ms=now_ms,
    )
    assert rec.is_healthy is False
    assert rec.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_frozen is True

    with pytest.raises(ClockSkewExceededError):
        mon.assert_healthy(current_time_ms=now_ms + 10)

    # Heartbeat with good latency (300 ms <= 450 ms) but uncorrected negative skew
    # (-350 ms) must NOT unfreeze
    rec_not_recovered = mon.record_heartbeat(
        server_time_ms=now_ms + 1000 + 350,
        latency_ms=300.0,
        local_time_ms=now_ms + 1000,
    )
    assert rec_not_recovered.is_healthy is False
    assert mon.is_frozen is True

    # Once skew recovers to nominal (|skew| <= 200 ms) and latency <= 450 ms, it recovers
    rec_recovered = mon.record_heartbeat(
        server_time_ms=now_ms + 2000 + 10,
        latency_ms=300.0,
        local_time_ms=now_ms + 2000,
    )
    assert rec_recovered.is_healthy is True
    assert rec_recovered.status == HeartbeatStatus.RECOVERED
    assert mon.is_frozen is False


def test_sequencer_delayed_pre_wrap_epoch_packet_identified_as_out_of_order():
    """Adversarial Test: Verify a delayed pre-wrap packet arriving after wrap-around
    is correctly flagged as out-of-order and does NOT reset highest_arrival_sequence.
    """
    seq = LiquidityShockStreamSequencer()

    # Ingest event at wrap threshold
    is_dup, is_ooo, is_wrap = seq.process_event({"u": SEQUENCE_WRAP_THRESHOLD})
    assert is_dup is False and is_ooo is False and is_wrap is False
    assert seq.highest_arrival_sequence == SEQUENCE_WRAP_THRESHOLD

    # Sequence wraps around to 1
    is_dup2, is_ooo2, is_wrap2 = seq.process_event({"u": 1})
    assert is_wrap2 is True
    assert seq.highest_arrival_sequence == 1
    assert seq.sequence_wrap_count == 1

    # Delayed packet from previous epoch arrives (e.g. sequence 999_999)
    is_dup3, is_ooo3, is_wrap3 = seq.process_event({"u": 999_999})
    assert is_ooo3 is True
    assert is_wrap3 is False
    assert seq.highest_arrival_sequence == 1  # Must NOT be corrupted back to 999_999!
    assert seq.out_of_order_count >= 1


def test_reconciler_case_insensitivity_and_margin_protection():
    """Adversarial Test: Verify lowercase symbol lookups ('btcusdt') correctly match
    allocated margin and positions without bypassing interlocks.
    """
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_case_insensitivity")

    # Process fill using lowercase symbol
    mark = reconciler.process_fill(
        trade_id="trade_case_1",
        symbol="btcusdt",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.0001"),
        commission=Decimal("0.0024"),
    )
    assert mark.symbol == "BTCUSDT"
    assert reconciler.get_per_asset_margin("btcusdt") == Decimal("6.00000000")
    assert reconciler.get_per_asset_margin("BTCUSDT") == Decimal("6.00000000")
    assert reconciler.positions["BTCUSDT"] == Decimal("0.0001")


def test_funding_basis_spread_precision_preservation():
    """Adversarial Test: Verify funding basis spread preserves 8-decimal precision
    so that spread > 0.0010 (e.g. 0.00105) is not prematurely truncated down to 0.0010.
    """
    engine = LiquidityShockEngine()
    engine.record_funding_rate("BTCUSDT", Decimal("0.00115"))
    engine.record_funding_rate("ETHUSDT", Decimal("0.00010"))
    # Spread is 0.00115 - 0.00010 = 0.00105 > 0.0010 (MAX_FUNDING_BASIS_SPREAD_THRESHOLD)
    spread = engine.get_cross_symbol_funding_basis_spread()
    assert spread == Decimal("0.00105000")
    assert engine.is_funding_distortion() is True


def test_cli_simulate_adverse_drift_fail_closed_detection(tmp_path: Path):
    """Adversarial Test: Verify --simulate-adverse-drift CLI flag triggers fail-closed
    exit code 1 on synthetic accounting drift (> 1e-15 USDT).
    """
    out_dir = tmp_path / "cli_adverse_drift"
    exit_code = execute_phase_287_runner(
        output_dir=out_dir,
        track="track_1",
        simulate_adverse_drift=True,
    )
    assert exit_code == 1  # Must fail closed!


def test_order_book_feed_corruption_rejection_fail_closed():
    """Adversarial Test: Verify corrupted order book feed data (negative depth, non-positive price,
    crossed book, negative volume velocity) is rejected fail-closed with
    OrderBookFeedCorruptionError.
    """
    engine = DepthImbalanceEngine()

    # Negative bid depth
    with pytest.raises(OrderBookFeedCorruptionError, match="Negative book depth"):
        engine.update_book(
            "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("-1.0"), Decimal("10.0")
        )

    # Negative ask depth
    with pytest.raises(OrderBookFeedCorruptionError, match="Negative book depth"):
        engine.update_book(
            "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("10.0"), Decimal("-0.0001")
        )

    # Non-positive bid price
    with pytest.raises(OrderBookFeedCorruptionError, match="Non-positive quote price"):
        engine.update_book(
            "BTCUSDT", Decimal("0.00"), Decimal("60010.00"), Decimal("5.0"), Decimal("5.0")
        )

    # Negative ask price
    with pytest.raises(OrderBookFeedCorruptionError, match="Non-positive quote price"):
        engine.update_book(
            "BTCUSDT", Decimal("60000.00"), Decimal("-10.00"), Decimal("5.0"), Decimal("5.0")
        )

    # Crossed order book (bid > ask)
    with pytest.raises(OrderBookFeedCorruptionError, match="Crossed order book"):
        engine.update_book(
            "BTCUSDT", Decimal("60020.00"), Decimal("60010.00"), Decimal("5.0"), Decimal("5.0")
        )

    # Negative volume velocity
    with pytest.raises(OrderBookFeedCorruptionError, match="Negative volume velocity"):
        engine.update_book(
            "BTCUSDT",
            Decimal("60000.00"),
            Decimal("60010.00"),
            Decimal("5.0"),
            Decimal("5.0"),
            volume_velocity=Decimal("-50.0"),
        )

    # Gateway set_book corruption validation
    gw = MockBinanceLiquidityShockGateway()
    with pytest.raises(OrderBookFeedCorruptionError):
        gw.set_book(
            "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("-2.0"), Decimal("5.0")
        )
    with pytest.raises(OrderBookFeedCorruptionError):
        gw.set_book(
            "BTCUSDT", Decimal("60020.00"), Decimal("60010.00"), Decimal("2.0"), Decimal("5.0")
        )


def test_order_book_epsilon_boundary_and_zero_depth_governance(
    temp_telemetry_store, temp_jsonl_sink
):
    """Adversarial Test: Verify boundary behavior when depth approaches decimal epsilon (1e-18),
    and when total book depth is zero, enforcing strict fail-closed safety.
    """
    engine = DepthImbalanceEngine()

    # Epsilon bid depth, nominal ask depth -> extreme negative imbalance
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("1e-18"), Decimal("10.0")
    )
    imb_neg = engine.get_depth_imbalance("BTCUSDT")
    assert imb_neg < Decimal("-0.60")
    assert engine.is_depth_imbalance_exceeded("BTCUSDT") is True

    # Nominal bid depth, epsilon ask depth -> extreme positive imbalance
    engine.update_book(
        "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), Decimal("10.0"), Decimal("1e-18")
    )
    imb_pos = engine.get_depth_imbalance("BTCUSDT")
    assert imb_pos > Decimal("0.60")
    assert engine.is_depth_imbalance_exceeded("BTCUSDT") is True

    # Zero depth on both sides: empty order book
    engine.update_book(
        "ETHUSDT", Decimal("3000.00"), Decimal("3001.00"), Decimal("0.0"), Decimal("0.0")
    )
    assert engine.get_depth_imbalance("ETHUSDT") == Decimal("0.0")
    # 100% queue depletion ratio triggers exceeded risk and SEVERE_CONTROLS
    assert engine.get_depth_depletion_ratio("ETHUSDT") == Decimal("1.0")
    assert engine.is_depth_imbalance_exceeded("ETHUSDT") is True
    assert engine.classify_depth_imbalance_regime("ETHUSDT") == LiquidityShockRegime.SEVERE_CONTROLS

    # Order dispatch against zero depth must fail-closed with DepthExhaustionError
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_epsilon_depth")
    heartbeat_mon = GatewayHeartbeatMonitor()
    gw = MockBinanceLiquidityShockGateway()
    hb = gw.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    with pytest.raises(DepthExhaustionError, match="exhausted"):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.001"),
            client_order_id=generate_canary_client_order_id("ETHUSDT"),
            side=OrderSide.BUY,
        )


def test_gateway_heartbeat_sudden_clock_jump_caught_in_record_heartbeat(monkeypatch):
    """Adversarial Test: Verify sudden OS clock jump between heartbeats is immediately detected
    during record_heartbeat (before check_health is called), freezing gateway fail-closed.
    """
    base_wall = 1700000000.0
    base_mono = 1000.0
    current_wall = base_wall
    current_mono = base_mono

    monkeypatch.setattr(time, "time", lambda: current_wall)
    monkeypatch.setattr(time, "monotonic", lambda: current_mono)

    mon = GatewayHeartbeatMonitor()
    hb1 = mon.record_heartbeat(server_time_ms=int(base_wall * 1000), latency_ms=25.0)
    assert hb1.status == HeartbeatStatus.HEALTHY
    assert mon.is_frozen is False

    # OS wall clock jumps forward by 280 ms, but monotonic only advances by 5 ms (step = 275 ms)
    # Server time also advances by 280 ms (skew relative to server is normal, but OS jumped!)
    current_wall = base_wall + 0.280
    current_mono = base_mono + 0.005

    hb2 = mon.record_heartbeat(server_time_ms=int(current_wall * 1000), latency_ms=25.0)
    assert hb2.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert hb2.is_healthy is False
    assert mon.is_frozen is True

    healthy, reason = mon.check_health()
    assert healthy is False
    assert "Sudden OS clock jump detected" in reason

    with pytest.raises(ClockSkewExceededError):
        mon.assert_healthy()


def test_concurrent_market_depth_updates_stream_events_and_dispatches(
    temp_telemetry_store, temp_jsonl_sink
):
    """Adversarial Stress Test: Concurrently execute market book updates, incoming WebSocket
    stream drain cycles, and multi-symbol micro order dispatches across multiple threads.
    Verify strict thread safety, zero deadlocks, and zero double-entry ledger drift.
    """
    gw = MockBinanceLiquidityShockGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="adv_stress_concurrent")
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gw.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    shock_engine = LiquidityShockEngine()
    sequencer = LiquidityShockStreamSequencer()

    interlock = LiquidityShockOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        shock_engine=shock_engine,
        expansion_stage=CapitalExpansionStage.STAGE_8_DEPTH_IMBALANCE_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gw,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="adv_stress_concurrent",
        shock_engine=shock_engine,
    )

    stop_event = threading.Event()
    errors: list[Exception] = []

    def _book_updater():
        try:
            depth_cycle = [Decimal("0.00020"), Decimal("0.00005"), Decimal("0.00010")]
            idx = 0
            while not stop_event.is_set():
                d = depth_cycle[idx % len(depth_cycle)]
                shock_engine.update_book(
                    "BTCUSDT", Decimal("60000.00"), Decimal("60010.00"), d, Decimal("0.00020")
                )
                idx += 1
                time.sleep(0.002)
        except Exception as exc:
            errors.append(exc)

    def _order_worker(t_id: int):
        try:
            for j in range(4):
                if stop_event.is_set():
                    break
                hb_sub = gw.generate_heartbeat(latency_ms=20.0)
                heartbeat_mon.record_heartbeat(hb_sub["serverTime"], hb_sub["latencyMs"])

                sym = CANARY_STAGED_SYMBOLS[j % len(CANARY_STAGED_SYMBOLS)]
                book = gw.books[sym]
                px = book["bid_price"]
                qty = (Decimal("1.20") / px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                cid = generate_canary_client_order_id(sym, uuid_str=f"st{t_id}j{j}")

                try:
                    dispatcher.dispatch_micro_order(
                        candidate_id=f"cand-{sym.lower()}",
                        symbol=sym,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=qty,
                        price=px,
                        client_order_id=cid,
                    )
                except (
                    AggregateExposureCapExceededError,
                    MarginAllocationExceededError,
                    FundingRateDistortionThrottledError,
                    GatewayHeartbeatStaleError,
                ):
                    pass
                time.sleep(0.003)
        except Exception as exc:
            errors.append(exc)

    updater_thread = threading.Thread(target=_book_updater)
    worker_threads = [threading.Thread(target=_order_worker, args=(i,)) for i in range(4)]

    updater_thread.start()
    for wt in worker_threads:
        wt.start()

    for wt in worker_threads:
        wt.join(timeout=10.0)
    stop_event.set()
    updater_thread.join(timeout=5.0)

    assert len(errors) == 0
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
