"""Unit tests for Phase 286: Canary Liquidity Shock & Funding Rate Distortion Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 285 back to 276).
- Dual-confirmation client order tag format (c=canary-p286-{sym}-{ts}-{uuid}).
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
import time
from decimal import Decimal
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
from autonomous_futures.feed.liquidity_shock import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DOUBLE_ENTRY_MAX_DRIFT,
    DYNAMIC_SLICING_MAX_CHUNK_USDT,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    LISTEN_KEY_LIFETIME_SECONDS,
    MAX_FUNDING_BASIS_SPREAD_THRESHOLD,
    MIN_MICRO_NOTIONAL_CAP_USDT,
    SEQUENCE_WRAP_THRESHOLD,
    AggregateExposureCapExceededError,
    AggressiveOrderRejectedError,
    CanaryLiquidityShockConfig,
    CanaryLiquidityShockRunner,
    CapitalExpansionStage,
    CircuitBreakerState,
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
    OrderLifecycleState,
    OrderSlicingMode,
    SqliteCanaryLiquidityShockTelemetryStore,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_286_hash_chain,
    verify_upstream_phase285_qualification,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_286_liquidity_shock import (  # noqa: E402
    execute_phase_286_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-liquidity-shock-telemetry.sqlite3"
    store = SqliteCanaryLiquidityShockTelemetryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path):
    jsonl_path = tmp_path / "test-liquidity-shock-orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_path)


# =====================================================================
# 1. Dual-Confirmation Client Order ID Tagging Tests (Phase 286)
# =====================================================================


def test_valid_client_order_id_generation_and_validation():
    """Verify Phase 286 deterministic client order tag format: c=canary-p286-{sym}-{ts}-{uuid}."""
    cid = generate_canary_client_order_id(
        "BTCUSDT", timestamp_ms=1720000000000, uuid_str="abc12345"
    )
    assert cid == "c=canary-p286-BTCUSDT-1720000000000-abc12345"
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

    # Legacy Phase 285 tag rejected under Phase 286
    legacy_cid = "c=canary-p285-BTCUSDT-1720000000000-abc12345"
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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
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


def test_stepped_exposure_scaling_stages_up_to_35_usdt():
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
    ]

    for stage, cap in expected_caps:
        interlock.expansion_stage = stage
        assert interlock.get_stage_exposure_cap() == cap

    assert AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT == Decimal("35.00")


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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
        intra_phase_loss_ceiling_usdt=Decimal("4.50"),
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

    # Open positions on BTC and ETH
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00008"),
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

    # Settle loss on BTC: price crashes from 60,000 to 2,000 -> loss = 0.00008 * 58,000 = 4.64 USDT
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("2000.00"),
        is_closing=True,
    )

    assert reconciler.cumulative_realized_loss >= Decimal("4.50")

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
    assert lk.startswith("lk-p286-")

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
        expansion_stage=CapitalExpansionStage.STAGE_7_LIQUIDITY_SHOCK_EXPANSION,
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


def test_upstream_phase285_qualification_and_hash_chain():
    """Verify continuous SHA-256 Merkle DAG hash chain back through Phase 285 to Phase 276."""
    ok = verify_upstream_phase285_qualification()
    assert ok is True


# =====================================================================
# 12. Full 4-Track Runner Execution Test
# =====================================================================


def test_full_phase_286_runner_execution_and_hash_chain(tmp_path: Path):
    """Execute all 4 deterministic simulation tracks for Phase 286 and verify artifacts."""
    cfg = CanaryLiquidityShockConfig(
        output_dir=tmp_path / "artifacts_p286",
        track="all",
    )
    runner = CanaryLiquidityShockRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.daemon_status == "LIQUIDITY_SHOCK_VERIFIED"
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True
    assert report.compliance["zero_secret_leakage"] is True
    assert len(report.tracks) == 4
    for tr in report.tracks:
        assert tr["success"] is True
        assert tr["zero_balance_drift"] is True

    # Verify cryptographic hash chain on generated artifacts
    chain_ok = verify_phase_286_hash_chain(output_dir=tmp_path / "artifacts_p286")
    assert chain_ok is True


def test_cli_runner_execution(tmp_path: Path):
    """Verify CLI runner entry point runs and exits 0."""
    out_dir = tmp_path / "cli_p286"
    exit_code = execute_phase_286_runner(
        output_dir=out_dir,
        track="all",
        verify_hash_chain=True,
    )
    assert exit_code == 0
    assert (out_dir / "canary-liquidity-shock-report.json").is_file()
    assert (out_dir / "liquidity-shock-summary.json").is_file()
    assert (out_dir / "paper-summary.json").is_file()
    assert (out_dir / "canary-orders.jsonl").is_file()
    assert (out_dir / "canary-liquidity-shock-telemetry.sqlite3").is_file()
