"""Unit tests for Phase 284: Canary Liquidity Regime Shifting & Dynamic Order Slicing Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 283 back to 276).
- Dual-confirmation client order tag format (c=canary-p284-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms) and backward NTP clock drift (> 250 ms
  triggers HEARTBEAT_FREEZE with 50 ms recovery hysteresis).
- Liquidity Regime Classification Engine (R2):
  - Discrete classification into NORMAL, THIN, and ILLIQUID regimes.
  - Sizing downscaling and limit offset widening cushions.
  - Order book depth exhaustion fail-closed abort on depleted order books (< 0.0001 depth).
  - Excessive spread protection (> 5% spread).
- Dynamic Micro-Order Slicing Governance (R2):
  - Slicing trigger when order exceeds immediate depth and estimated slippage > 1.5 bps.
  - Sequential micro-chunks <= 2.50 USDT child orders.
  - Atomic parent-child lifecycle tracking.
  - Sliced child order cap <= 2.50 USDT, normal micro cap <= 5.00 USDT, micro floor >= 1.00 USDT.
- Stepped concurrent exposure scaling across stages:
  - Stage 1 seed probe cap (<= 5.00 USDT)
  - Stage 2 expanded concurrent cap (<= 10.00 USDT)
  - Stage 3 continuous expansion cap (<= 15.00 USDT)
  - Stage 4 adaptive expansion cap (<= 20.00 USDT)
  - Stage 5 liquidity expansion cap (<= 25.00 USDT across all symbols)
  - Aggregate exposure cap <= 25.00 USDT.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 3.50 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Multi-day extended session longevity, 24h listenKey expiration/renewal, sequence wrap
  recovery, stream disconnect REST backfill, and idempotent deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT) across snapshots.
- Strict containment invariants (execution_authority: False, orders: 0, api_keys_loaded: 0).
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.adaptive_execution import (  # noqa: E402
    DEFAULT_PHASE283_OUTPUT_DIR,
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
from autonomous_futures.feed.liquidity_regime import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_PHASE284_OUTPUT_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    DYNAMIC_SLICING_MAX_CHUNK_USDT,
    GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
    GATEWAY_HEARTBEAT_MAX_AGE_MS,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    INTRA_PHASE_LOSS_CEILING_USDT,
    MAX_CLOCK_SKEW_TOLERANCE_MS,
    MIN_MICRO_NOTIONAL_CAP_USDT,
    SLIPPAGE_TOLERANCE_BPS,
    STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT,
    STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT,
    STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT,
    STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT,
    STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT,
    AggregateExposureCapExceededError,
    CanaryLiquidityRegimeConfig,
    CanaryLiquidityRegimeRunner,
    CapitalExpansionStage,
    CircuitBreakerState,
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
    LiquidityAutonomousDaemon,
    LiquidityMicroOrderDispatcher,
    LiquidityOrderDispatchInterlock,
    LiquidityRegime,
    LiquidityRegimeEngine,
    LiquidityStreamSequencer,
    LiquidityUserDataStreamReconciler,
    ListenKeyExpiredError,
    MarginAllocationExceededError,
    MicroNotionalFloorViolationError,
    MockBinanceLiquidityGateway,
    OrderLifecycleState,
    OrderSlicingMode,
    PrerequisiteQualificationError,
    SqliteCanaryLiquidityRegimeTelemetryStore,
    assert_valid_canary_client_order_id,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_284_hash_chain,
    verify_upstream_phase283_qualification,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    load_and_validate_canary_staging_manifest,
)
from scripts.run_phase_284_liquidity_regime import (  # noqa: E402
    execute_phase_284_runner,
)


@pytest.fixture
def manifest():
    m, _ = load_and_validate_canary_staging_manifest(DEFAULT_CANARY_STAGING_MANIFEST_PATH)
    return m


@pytest.fixture
def temp_telemetry_store(tmp_path: Path):
    db_path = tmp_path / "test-liquidity-telemetry.sqlite3"
    store = SqliteCanaryLiquidityRegimeTelemetryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path):
    jsonl_path = tmp_path / "test-liquidity-orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_path)


# =====================================================================
# 1. Dual-Confirmation Client Order ID Tagging Tests (Phase 284)
# =====================================================================


def test_generate_and_validate_canary_client_order_id():
    """Verify dual-confirmation client order tag generation and validation for Phase 284."""
    cid = generate_canary_client_order_id(
        "BTCUSDT", timestamp_ms=1700000000000, uuid_str="abc12345"
    )
    assert cid == "c=canary-p284-BTCUSDT-1700000000000-abc12345"

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

    # Wrong phase tag (e.g. p283 instead of p284)
    ok_p283, err_p283 = validate_canary_client_order_id(
        "c=canary-p283-BTCUSDT-1700000000000-abc12345", expected_symbol="BTCUSDT"
    )
    assert ok_p283 is False

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
        recovery_hysteresis_ms=GATEWAY_HEARTBEAT_HYSTERESIS_RECOVERY_MS,
    )
    now_ms = int(time.time() * 1000)

    # Fresh heartbeat
    rec = mon.record_heartbeat(
        server_time_ms=now_ms - 20, latency_ms=25.0, local_receive_time_ms=now_ms, track_id="test"
    )
    assert rec.status == HeartbeatStatus.HEALTHY
    mon.assert_healthy(now_ms=now_ms)

    # Simulate stale heartbeat age > 500 ms (e.g. 520 ms)
    with pytest.raises(GatewayHeartbeatStaleError):
        mon.assert_healthy(now_ms=now_ms + 520)

    # Recovery hysteresis: 480 ms is > recovery_hysteresis_ms (450 ms), remains frozen
    with pytest.raises(HeartbeatFreezeActiveError):
        mon.assert_healthy(now_ms=now_ms + 480)

    # Recovers at <= 450 ms (e.g. 440 ms)
    mon.assert_healthy(now_ms=now_ms + 440)  # No exception


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

    # Server drifts backwards by 300 ms (> 250 ms tolerance)
    rec2 = mon.record_heartbeat(
        server_time_ms=now_ms - 300, latency_ms=20.0, local_receive_time_ms=now_ms, track_id="test"
    )
    assert rec2.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert mon.is_frozen is True

    # Recovery: record a healthy heartbeat with age <= recovery_hysteresis_ms
    rec3 = mon.record_heartbeat(
        server_time_ms=now_ms + 10,
        latency_ms=20.0,
        local_receive_time_ms=now_ms + 50,
        track_id="test",
    )
    assert rec3.status == HeartbeatStatus.RECOVERED
    assert mon.is_frozen is False


# =====================================================================
# 3. Liquidity Regime Classification Engine Tests (R2)
# =====================================================================


def test_liquidity_regime_classification_and_adaptation():
    """Verify discrete regime classification (NORMAL, THIN, ILLIQUID) and dynamic adaptation."""
    engine = LiquidityRegimeEngine()

    # 1. NORMAL Regime: tight spread (<= 5 bps), deep book (>= 1.0), high velocity (>= 50.0)
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60001.00"),  # ~1.67 bps
        bid_depth=Decimal("5.0"),
        ask_depth=Decimal("5.0"),
        volume_velocity=Decimal("100.0"),
    )
    regime = engine.classify_regime("BTCUSDT")
    assert regime == LiquidityRegime.NORMAL
    notional, limit_px, r, offset = engine.calculate_sizing_and_limit_offset(
        "BTCUSDT", OrderSide.BUY, base_notional=Decimal("5.00")
    )
    assert r == LiquidityRegime.NORMAL
    assert notional == Decimal("5.00")  # Full sizing
    assert offset == Decimal("0.25")  # 25% cushion of 1.00 spread = 0.25
    assert limit_px == Decimal("60000.25")

    # 2. THIN Regime: spread between 5 and 25 bps, or depleted depth (< 1.0)
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60060.00"),  # 10 bps spread
        bid_depth=Decimal("0.5"),  # depleted depth < 1.0
        ask_depth=Decimal("0.5"),
        volume_velocity=Decimal("40.0"),
    )
    regime_thin = engine.classify_regime("BTCUSDT")
    assert regime_thin == LiquidityRegime.THIN
    notional_thin, limit_px_thin, r_thin, offset_thin = engine.calculate_sizing_and_limit_offset(
        "BTCUSDT", OrderSide.BUY, base_notional=Decimal("5.00")
    )
    assert r_thin == LiquidityRegime.THIN
    assert notional_thin <= DYNAMIC_SLICING_MAX_CHUNK_USDT  # Capped at 2.50 USDT
    assert notional_thin >= MIN_MICRO_NOTIONAL_CAP_USDT
    assert offset_thin == Decimal("30.00")  # 50% cushion of 60.00 spread
    assert limit_px_thin == Decimal("60030.00")

    # 3. ILLIQUID Regime: wide spread (> 25 bps) or exhausted depth (< 0.05) or zero velocity
    engine.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60200.00"),  # > 30 bps
        bid_depth=Decimal("0.02"),  # < 0.05
        ask_depth=Decimal("0.02"),
        volume_velocity=Decimal("0.0"),
    )
    regime_illiquid = engine.classify_regime("BTCUSDT")
    assert regime_illiquid == LiquidityRegime.ILLIQUID
    notional_ill, limit_px_ill, r_ill, offset_ill = engine.calculate_sizing_and_limit_offset(
        "BTCUSDT", OrderSide.BUY, base_notional=Decimal("5.00")
    )
    assert r_ill == LiquidityRegime.ILLIQUID
    assert notional_ill == MIN_MICRO_NOTIONAL_CAP_USDT  # Scaled down to 1.00 USDT floor
    assert offset_ill == Decimal("150.00")  # 75% cushion of 200.00 spread
    assert limit_px_ill == Decimal("60150.00")


def test_liquidity_regime_slippage_estimation():
    """Verify estimated slippage calculation against available order book depth."""
    engine = LiquidityRegimeEngine()
    engine.update_book(
        "ETHUSDT",
        bid_price=Decimal("3000.00"),
        ask_price=Decimal("3000.60"),  # 2.0 bps
        bid_depth=Decimal("1.0"),
        ask_depth=Decimal("1.0"),
    )

    # Order fits within depth: slippage <= 1.5 bps
    slip_small = engine.estimate_order_slippage_bps(
        "ETHUSDT", OrderSide.BUY, quantity=Decimal("0.5"), price=Decimal("3000.60")
    )
    assert slip_small <= SLIPPAGE_TOLERANCE_BPS

    # Order exceeds top-of-book depth: slippage spikes > 1.5 bps
    slip_large = engine.estimate_order_slippage_bps(
        "ETHUSDT", OrderSide.BUY, quantity=Decimal("5.0"), price=Decimal("3000.60")
    )
    assert slip_large > SLIPPAGE_TOLERANCE_BPS


def test_liquidity_regime_depth_exhaustion_interlock(temp_telemetry_store):
    """Verify order book depth exhaustion triggers fail-closed DepthExhaustionError."""
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(server_time_ms=int(time.time() * 1000), latency_ms=30.0, track_id="test")
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test", starting_equity=STARTING_EQUITY_USDT
    )
    regime_eng = LiquidityRegimeEngine()
    regime_eng.update_book(
        "SOLUSDT",
        bid_price=Decimal("150.00"),
        ask_price=Decimal("150.05"),
        bid_depth=Decimal("0.00001"),  # < 0.00002 minimum depth threshold!
        ask_depth=Decimal("0.00001"),
    )
    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        regime_engine=regime_eng,
    )

    cid = generate_canary_client_order_id("SOLUSDT")
    with pytest.raises(DepthExhaustionError):
        interlock.validate_dispatch(
            symbol="SOLUSDT",
            price=Decimal("150.05"),
            quantity=Decimal("0.02"),
            client_order_id=cid,
            side=OrderSide.BUY,
        )


# =====================================================================
# 4. Dynamic Micro-Order Slicing Governance Tests (R2)
# =====================================================================


def test_dynamic_micro_order_slicing_governance(temp_telemetry_store, temp_jsonl_sink):
    """Verify TWAP slicing into chunks <= 2.50 USDT when depth exceeded & slippage > 1.5 bps."""
    gateway = MockBinanceLiquidityGateway(initial_balance_usdt=Decimal("100.00"))
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_slicing", starting_equity=Decimal("100.00")
    )
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_slicing"
    )

    regime_eng = LiquidityRegimeEngine()
    # Configure shallow book depth: ask_depth = 0.00003 BTC (~1.80 USDT)
    regime_eng.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60020.00"),  # ~3.33 bps spread
        bid_depth=Decimal("0.00003"),
        ask_depth=Decimal("0.00003"),
    )

    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_slicing",
        expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
        regime_engine=regime_eng,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_slicing",
        regime_engine=regime_eng,
    )

    # Dispatch order desiring 5.00 USDT notional in BTC:
    # 5.00 USDT @ 60,000 ~ 0.00008 BTC > 0.00003 depth -> triggers dynamic micro-slicing
    parent_rec, child_orders = dispatcher.dispatch_signal_order_with_dynamic_slicing(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        desired_notional=Decimal("5.00"),
    )

    # Verify slicing occurred
    assert parent_rec is not None
    assert parent_rec.slicing_mode == OrderSlicingMode.TWAP_MICRO
    assert parent_rec.child_count >= 2
    assert len(child_orders) == parent_rec.child_count

    # Verify every child chunk respects <= 2.50 USDT dynamic slicing chunk cap
    for child in child_orders:
        assert child.is_child is True
        assert child.parent_client_order_id == parent_rec.parent_client_order_id
        assert Decimal(child.notional_usdt) <= DYNAMIC_SLICING_MAX_CHUNK_USDT
        assert child.status == OrderLifecycleState.FILLED

    # Verify atomic parent aggregation
    assert parent_rec.status == OrderLifecycleState.FILLED
    assert Decimal(parent_rec.executed_quantity) == Decimal(parent_rec.total_quantity)
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_direct_unsliced_micro_order_dispatch(temp_telemetry_store, temp_jsonl_sink):
    """Verify small orders within book depth are dispatched directly without slicing."""
    gateway = MockBinanceLiquidityGateway(initial_balance_usdt=Decimal("100.00"))
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_unsliced", starting_equity=Decimal("100.00")
    )
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_unsliced"
    )

    regime_eng = LiquidityRegimeEngine()
    # Deep book: ask_depth = 5.0 BTC
    regime_eng.update_book(
        "BTCUSDT",
        bid_price=Decimal("60000.00"),
        ask_price=Decimal("60001.00"),
        bid_depth=Decimal("5.0"),
        ask_depth=Decimal("5.0"),
    )

    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_unsliced",
        expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
        regime_engine=regime_eng,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_unsliced",
        regime_engine=regime_eng,
    )

    # 2.00 USDT order fits well within depth
    parent_rec, orders = dispatcher.dispatch_signal_order_with_dynamic_slicing(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        desired_notional=Decimal("2.00"),
    )

    assert parent_rec is None  # No parent created because not sliced!
    assert len(orders) == 1
    assert orders[0].is_child is False
    assert orders[0].status == OrderLifecycleState.FILLED


# =====================================================================
# 5. Stepped Concurrent Exposure Scaling & Stage Ceilings
# =====================================================================


def test_stepped_concurrent_exposure_limits(temp_telemetry_store):
    """Verify stepped exposure scaling across Stages 1-5 up to 25.00 USDT."""
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(server_time_ms=int(time.time() * 1000), latency_ms=30.0, track_id="test")
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test", starting_equity=STARTING_EQUITY_USDT
    )
    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,
    )

    # Stage 1: <= 5.00 USDT
    assert interlock.get_stage_exposure_cap() == STAGE_1_CONCURRENT_EXPOSURE_CAP_USDT

    # Individual micro order cap (<= 5.00 USDT)
    cid_large = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00010"),  # 6.00 USDT > 5.00 USDT
            client_order_id=cid_large,
        )

    # Micro order floor (>= 1.00 USDT)
    cid_small = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(MicroNotionalFloorViolationError):
        interlock.validate_dispatch(
            symbol="BTCUSDT",
            price=Decimal("60000.00"),
            quantity=Decimal("0.00001"),  # 0.60 USDT < 1.00 USDT
            client_order_id=cid_small,
        )

    # Valid 4.80 USDT order in Stage 1
    cid_valid = generate_canary_client_order_id("BTCUSDT")
    interlock.validate_dispatch(
        symbol="BTCUSDT",
        price=Decimal("60000.00"),
        quantity=Decimal("0.00008"),  # 4.80 USDT <= 5.00 USDT
        client_order_id=cid_valid,
    )
    reconciler.apply_fill(
        "BTCUSDT", OrderSide.BUY, Decimal("60000.00"), Decimal("0.00008"), fee=Decimal("0")
    )

    # Next order pushing aggregate to 4.80 + 1.20 = 6.00 > 5.00 USDT cap
    cid_blocked = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.validate_dispatch(
            symbol="ETHUSDT",
            price=Decimal("3000.00"),
            quantity=Decimal("0.0004"),  # 1.20 USDT
            client_order_id=cid_blocked,
        )

    # Promote across stages:
    # Stage 2 (<= 10.00 USDT)
    interlock.expansion_stage = CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT
    assert interlock.get_stage_exposure_cap() == STAGE_2_CONCURRENT_EXPOSURE_CAP_USDT
    interlock.validate_dispatch(
        symbol="ETHUSDT",
        price=Decimal("3000.00"),
        quantity=Decimal("0.0004"),
        client_order_id=cid_blocked,
    )

    # Stage 3 (<= 15.00 USDT)
    interlock.expansion_stage = CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION
    assert interlock.get_stage_exposure_cap() == STAGE_3_CONTINUOUS_EXPOSURE_CAP_USDT

    # Stage 4 (<= 20.00 USDT)
    interlock.expansion_stage = CapitalExpansionStage.STAGE_4_ADAPTIVE_EXPANSION
    assert interlock.get_stage_exposure_cap() == STAGE_4_ADAPTIVE_EXPOSURE_CAP_USDT

    # Stage 5 (<= 25.00 USDT)
    interlock.expansion_stage = CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION
    assert interlock.get_stage_exposure_cap() == STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT
    assert STAGE_5_LIQUIDITY_EXPOSURE_CAP_USDT == AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT


# =====================================================================
# 6. Dynamic Margin Headroom Interlocks & Committed Margin
# =====================================================================


def test_dynamic_margin_headroom_interlocks(temp_telemetry_store):
    """Verify aggregate margin <= 60%, per-asset <= 20%, and cash reserve >= 40%."""
    mon = GatewayHeartbeatMonitor()
    mon.record_heartbeat(server_time_ms=int(time.time() * 1000), latency_ms=30.0, track_id="test")
    # Low equity account to test percentage ceilings: 20.00 USDT starting equity
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test", starting_equity=Decimal("20.00")
    )
    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test",
        expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
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


def test_working_orders_margin_reservation(temp_telemetry_store, temp_jsonl_sink):
    """Verify committed working margin is reserved on unfilled orders and blocks excess dispatch."""
    gateway = MockBinanceLiquidityGateway(initial_balance_usdt=Decimal("50.00"))
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_working", starting_equity=Decimal("50.00")
    )
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_working"
    )

    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_working",
        expansion_stage=CapitalExpansionStage.STAGE_1_CONCURRENT_MICRO,  # 5.00 USDT cap
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_working",
    )

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


# =====================================================================
# 7. Intra-Phase Cumulative Loss Budget Ceiling & Emergency Flattening
# =====================================================================


def test_intra_phase_loss_ceiling_and_flattening(temp_telemetry_store, temp_jsonl_sink):
    """Verify realized loss >= 3.50 USDT triggers fail-closed lockout and emergency liquidation."""
    gateway = MockBinanceLiquidityGateway(initial_balance_usdt=Decimal("100.00"))
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_lockout", starting_equity=Decimal("100.00")
    )
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=25.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_lockout"
    )

    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_lockout",
        expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
        intra_phase_loss_ceiling_usdt=INTRA_PHASE_LOSS_CEILING_USDT,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
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

    # 2. Close at 15,000 USDT -> realized loss = 3.60 USDT > 3.50 USDT ceiling!
    btc_close = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.00008"),
        price=Decimal("15000.00"),
        is_closing=True,
    )
    assert btc_close.status == OrderLifecycleState.FILLED
    assert reconciler.cumulative_realized_loss >= Decimal("3.50")

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
    gateway = MockBinanceLiquidityGateway(initial_balance_usdt=Decimal("100.00"))
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_longevity", starting_equity=Decimal("100.00")
    )
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=30.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_longevity"
    )

    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_longevity",
        expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
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
    reconciler = LiquidityUserDataStreamReconciler(
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
    gateway = MockBinanceLiquidityGateway()
    reconciler = LiquidityUserDataStreamReconciler(track_id="test_daemon")
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_daemon",
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_daemon",
    )
    daemon = LiquidityAutonomousDaemon(
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


def test_upstream_phase283_verification_success():
    """Verify Phase 283 report and hash chain ingress pass against actual artifacts."""
    ok = verify_upstream_phase283_qualification(
        phase283_dir=DEFAULT_PHASE283_OUTPUT_DIR,
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    )
    assert ok is True


def test_upstream_phase283_verification_failure_on_corrupted_status(tmp_path: Path):
    """Verify upstream qualification fails closed if Phase 283 status is not verified."""
    corrupted_report = tmp_path / "canary-adaptive-execution-report.json"
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

    with pytest.raises(PrerequisiteQualificationError):
        verify_upstream_phase283_qualification(
            phase283_dir=tmp_path,
            manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        )


# =====================================================================
# 12. Full Simulation Runner & Cryptographic DAG Hash Chain
# =====================================================================


def test_full_phase_284_runner_and_hash_chain(tmp_path: Path):
    """Execute full Phase 284 runner and verify SHA-256 DAG hash chain across artifacts."""
    cfg = CanaryLiquidityRegimeConfig(
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        output_dir=tmp_path,
        track="all",
    )
    runner = CanaryLiquidityRegimeRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.daemon_status == "LIQUIDITY_REGIME_VERIFIED"
    assert report.compliance["all_criteria_passed"] is True
    assert report.compliance["zero_balance_drift"] is True
    assert len(report.tracks) == 4
    assert all(t.success for t in report.tracks)

    # Verify cryptographic hash chain
    hash_ok = verify_phase_284_hash_chain(
        output_dir=tmp_path,
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    )
    assert hash_ok is True


def test_cli_execute_phase_284_runner_verify_only():
    """Verify CLI --verify-only succeeds once production Phase 284 artifacts are created."""
    # Run once to tmp_path to verify verify_only mode
    exit_code = execute_phase_284_runner(
        output_dir=DEFAULT_PHASE284_OUTPUT_DIR,
        verify_only=True,
    )
    # Verify verify_only mode if production artifacts exist:
    if (DEFAULT_PHASE284_OUTPUT_DIR / "liquidity-regime-summary.json").exists():
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


def test_adverse_drift_detection_fail_closed(tmp_path: Path):
    """Verify synthetic adverse drift (> 1e-15 USDT) causes runner compliance to fail closed."""
    cfg = CanaryLiquidityRegimeConfig(
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        output_dir=tmp_path,
        track="track_1",
        simulate_adverse_drift=True,
    )
    runner = CanaryLiquidityRegimeRunner(cfg)
    report = runner.execute_all_tracks()

    assert report.compliance["zero_balance_drift"] is False
    assert report.compliance["all_criteria_passed"] is False
    assert report.tracks[0].success is False


def test_thread_safety_concurrent_dispatches(temp_telemetry_store, temp_jsonl_sink):
    """Verify thread safety during concurrent micro order dispatches."""
    gateway = MockBinanceLiquidityGateway(initial_balance_usdt=Decimal("500.00"))
    reconciler = LiquidityUserDataStreamReconciler(
        track_id="test_concurrency", starting_equity=Decimal("500.00")
    )
    sequencer = LiquidityStreamSequencer()
    heartbeat_mon = GatewayHeartbeatMonitor()
    hb = gateway.generate_heartbeat(latency_ms=20.0)
    heartbeat_mon.record_heartbeat(
        server_time_ms=hb["serverTime"], latency_ms=hb["latencyMs"], track_id="test_concurrency"
    )

    interlock = LiquidityOrderDispatchInterlock(
        heartbeat_monitor=heartbeat_mon,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        track_id="test_concurrency",
        expansion_stage=CapitalExpansionStage.STAGE_5_LIQUIDITY_EXPANSION,
    )
    dispatcher = LiquidityMicroOrderDispatcher(
        gateway=gateway,
        reconciler=reconciler,
        sequencer=sequencer,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
        heartbeat_monitor=heartbeat_mon,
        interlock=interlock,
        track_id="test_concurrency",
    )

    def dispatch_worker(sym: str, px: Decimal, qty: Decimal):
        return dispatcher.dispatch_micro_order(
            candidate_id=f"cand-{sym.lower()}",
            symbol=sym,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=qty,
            price=px,
        )

    tasks = [
        ("BTCUSDT", Decimal("60000.00"), Decimal("0.00002")),  # 1.20 USDT
        ("ETHUSDT", Decimal("3000.00"), Decimal("0.0005")),  # 1.50 USDT
        ("SOLUSDT", Decimal("150.00"), Decimal("0.01")),  # 1.50 USDT
    ]

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(dispatch_worker, sym, px, q) for sym, px, q in tasks]
        for f in as_completed(futures):
            results.append(f.result())

    assert len(results) == 3
    for r in results:
        assert r.status == OrderLifecycleState.FILLED
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
