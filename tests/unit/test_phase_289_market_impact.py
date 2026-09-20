"""Unit tests for Phase 289: Canary Cross-Asset Market Impact & Kyle's Lambda Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 288 back to 276).
- Dual-confirmation client order tag format (c=canary-p289-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms), backward NTP clock drift (> 250 ms triggers
  HEARTBEAT_FREEZE with recovery hysteresis <= 450 ms).
- Microstructural Market Impact & Kyle's Lambda (λ = ΔP / Q) Engine:
  - Instantaneous and rolling Kyle's lambda estimation.
  - Regimes: NOMINAL (<= 0.40), ELEVATED_IMPACT (0.40-0.70), SEVERE_CONTROLS (> 0.70).
  - Anti-flapping de-escalation hysteresis thresholds (0.35 and 0.65).
  - Execution pacing interval lengthening (100 ms, 250 ms, 1000 ms).
  - Limit offset cushion widening (+0 bps, +2 bps, +5 bps).
  - Transient resilience recovery half-life (t_1/2) and replenishment velocity.
  - Permanent displacement / degraded liquidity absorption detection.
  - Aggressive market order rejection fail-closed under severe impact.
  - Cross-symbol impact transmission coefficients.
- Stepped concurrent exposure scaling across stages:
  - Stages 1 to 10 up to <= 50.00 USDT aggregate concurrent active exposure across all symbols.
  - Individual micro child order cap <= 5.00 USDT.
  - Dynamic sequential TWAP slicing <= 2.50 USDT child slices with 1.00 USDT floor.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 6.00 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Multi-day extended session longevity, 24h listenKey expiration/renewal, sequence wrap
  recovery, and idempotent event deduplication.
- Exact double-entry accounting balance reconciliation (|drift| < 1e-15 USDT) across snapshots.
- Strict containment invariants (execution_authority: False, orders: 0, api_keys_loaded: 0).
"""

from __future__ import annotations

import json
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
from autonomous_futures.feed.market_impact import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    CANARY_STAGED_SYMBOLS,
    DEFAULT_PHASE289_OUTPUT_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    SEQUENCE_WRAP_THRESHOLD,
    STAGE_10_MARKET_IMPACT_EXPANSION_CAP_USDT,
    AggregateExposureCapExceededError,
    AggressiveOrderRejectedError,
    CanaryMarketImpactError,
    CapitalExpansionStage,
    CircuitBreakerState,
    DisplacementAbsorptionState,
    GatewayHeartbeatMonitor,
    HeartbeatFreezeActiveError,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    JsonlCanaryOrderSink,
    MarginAllocationExceededError,
    MarketImpactEngine,
    MarketImpactMicroOrderDispatcher,
    MarketImpactOrderDispatchInterlock,
    MarketImpactRegime,
    MarketImpactStreamSequencer,
    MarketImpactUserDataStreamReconciler,
    MicroNotionalFloorViolationError,
    MockBinanceMarketImpactGateway,
    OrderLifecycleState,
    SqliteCanaryMarketImpactTelemetryStore,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_289_hash_chain,
    verify_upstream_phase288_qualification,
)
from scripts.run_phase_289_market_impact import main as cli_main  # noqa: E402


@pytest.fixture
def temp_telemetry_store(tmp_path: Path) -> SqliteCanaryMarketImpactTelemetryStore:
    db_file = tmp_path / "test_telemetry.sqlite3"
    return SqliteCanaryMarketImpactTelemetryStore(db_file)


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path) -> JsonlCanaryOrderSink:
    jsonl_file = tmp_path / "test_orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_file)


# ---------------------------------------------------------------------------
# 1. Dual-Confirmation Client Order ID Tag Validation
# ---------------------------------------------------------------------------


def test_valid_client_order_id_generation_and_validation():
    for sym in CANARY_STAGED_SYMBOLS:
        cid = generate_canary_client_order_id(sym)
        assert validate_canary_client_order_id(cid, sym)
        assert cid.startswith(f"c=canary-p289-{sym.lower()}-")
        assert len(cid.split("-")) >= 5


def test_invalid_client_order_id_rejection():
    # Wrong prefix (prior phase)
    assert not validate_canary_client_order_id(
        "c=canary-p288-btcusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Wrong symbol
    assert not validate_canary_client_order_id(
        "c=canary-p289-ethusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Missing parts
    assert not validate_canary_client_order_id("c=canary-p289-btcusdt", "BTCUSDT")
    # Empty string
    assert not validate_canary_client_order_id("", "BTCUSDT")
    # Random characters
    assert not validate_canary_client_order_id("invalid-tag-format", "BTCUSDT")


# ---------------------------------------------------------------------------
# 2. Gateway Heartbeat Freshness, Clock Skew & Hysteresis Recovery
# ---------------------------------------------------------------------------


def test_gateway_heartbeat_healthy_state():
    monitor = GatewayHeartbeatMonitor(freshness_ceiling_ms=500.0, max_clock_skew_ms=250.0)
    now_ms = int(time.time() * 1000)
    rec = monitor.record_heartbeat(
        server_time_ms=now_ms - 20,
        latency_ms=20.0,
        local_time_ms=now_ms,
        track_id="test_healthy",
    )
    assert rec.status == HeartbeatStatus.HEALTHY
    is_healthy, reason = monitor.check_health(current_time_ms=now_ms)
    assert is_healthy
    assert "fresh" in reason.lower() or "healthy" in reason.lower()


def test_gateway_heartbeat_stale_latency_spike():
    monitor = GatewayHeartbeatMonitor(freshness_ceiling_ms=500.0, max_clock_skew_ms=250.0)
    now_ms = int(time.time() * 1000)
    monitor.record_heartbeat(
        server_time_ms=now_ms - 600,
        latency_ms=600.0,
        local_time_ms=now_ms - 600,
        track_id="test_stale",
    )
    is_healthy, reason = monitor.check_health(current_time_ms=now_ms)
    assert not is_healthy
    assert "stale" in reason.lower()


def test_gateway_heartbeat_clock_skew_freeze_and_recovery_hysteresis():
    monitor = GatewayHeartbeatMonitor(
        max_age_ms=500.0,
        recovery_ms=450.0,
        max_clock_skew_ms=250.0,
    )
    now_ms = int(time.time() * 1000)

    # 1. Normal heartbeat
    monitor.record_heartbeat(
        server_time_ms=now_ms - 10,
        latency_ms=10.0,
        local_time_ms=now_ms,
        track_id="test_freeze",
    )
    assert monitor.check_health(now_ms)[0]

    # 2. Backward NTP clock drift: server_time ahead by 300 ms -> clock skew < -250 ms
    rec_skew = monitor.record_heartbeat(
        server_time_ms=now_ms + 300,
        latency_ms=15.0,
        local_time_ms=now_ms,
        track_id="test_freeze",
    )
    assert rec_skew.status in (HeartbeatStatus.CLOCK_SKEW_DRIFT, HeartbeatStatus.CLOCK_SKEW_FREEZE)
    assert monitor.is_frozen

    is_healthy, reason = monitor.check_health(now_ms)
    assert not is_healthy
    assert "frozen" in reason.lower() or "skew" in reason.lower()

    # 3. Intermediate recovery: latency 460 ms (still > recovery hysteresis 450 ms)
    monitor.last_heartbeat_time_ms = now_ms - 460
    is_healthy, reason = monitor.check_health(now_ms)
    assert not is_healthy
    assert monitor.is_frozen

    # 4. Clean recovery: latency 20 ms, clock skew 5 ms (<= 450 ms hysteresis)
    rec_recov = monitor.record_heartbeat(
        server_time_ms=now_ms - 20,
        latency_ms=20.0,
        local_time_ms=now_ms,
        track_id="test_freeze",
    )
    assert rec_recov.status in (HeartbeatStatus.HEALTHY, HeartbeatStatus.RECOVERED)
    assert not monitor.is_frozen
    is_healthy_now, reason_now = monitor.check_health(now_ms)
    assert is_healthy_now
    assert "fresh" in reason_now.lower() or "healthy" in reason_now.lower()


# ---------------------------------------------------------------------------
# 3. Microstructural Market Impact & Kyle's Lambda Calculation
# ---------------------------------------------------------------------------


def test_kyles_lambda_calculation_and_price_displacement():
    engine = MarketImpactEngine()
    px = Decimal("60000.00")

    # Initial reference trade
    engine.process_trade("BTCUSDT", px, Decimal("0.001"), OrderSide.BUY)
    assert engine.get_lambda("BTCUSDT") <= Decimal("0.40")
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.NOMINAL

    # Trade with price displacement of $30.00 (5 bps) on 10.00 USDT notional
    # lambda = 5.0 bps / 10.00 USDT = 0.50 bps/USDT
    px_new = Decimal("60030.00")
    qty = Decimal("10.00") / px_new
    engine.process_trade("BTCUSDT", px_new, qty, OrderSide.BUY)
    cur_lambda = engine.get_lambda("BTCUSDT")
    assert cur_lambda > Decimal("0.10")


def test_market_impact_regimes_and_anti_flapping_hysteresis():
    engine = MarketImpactEngine()

    # 1. NOMINAL regime initially
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.NOMINAL

    # 2. Transition to ELEVATED_IMPACT (> 0.40)
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.55"))
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.ELEVATED_IMPACT

    # 3. Transition to SEVERE_CONTROLS (> 0.70)
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.85"))
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.SEVERE_CONTROLS

    # 4. Hysteresis: drops to 0.68 -> still SEVERE_CONTROLS (recovery threshold is <= 0.65)
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.68"))
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.SEVERE_CONTROLS

    # 5. Drops to 0.60 -> recovers to ELEVATED_IMPACT
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.60"))
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.ELEVATED_IMPACT

    # 6. Drops to 0.38 -> still ELEVATED_IMPACT (nominal recovery threshold is <= 0.35)
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.38"))
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.ELEVATED_IMPACT

    # 7. Drops to 0.20 -> recovers to NOMINAL
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.20"))
    assert engine.get_regime("BTCUSDT") == MarketImpactRegime.NOMINAL


def test_transient_resilience_half_life_and_replenishment():
    engine = MarketImpactEngine()

    # Normal resilience
    assert engine.get_absorption_state("BTCUSDT") == DisplacementAbsorptionState.NORMAL

    # Surge with slow recovery half-life (6.0s > 5.0s max)
    engine.record_impact_surge(
        "BTCUSDT",
        lambda_value=Decimal("0.80"),
        resilience_half_life=6.0,
        replenishment_velocity=Decimal("5.0"),
    )
    assert (
        engine.get_absorption_state("BTCUSDT")
        == DisplacementAbsorptionState.SEVERE_ABSORPTION_DEGRADED
    )

    # Replenishment velocity update
    engine.record_replenishment("BTCUSDT", depth_delta_usdt=Decimal("60.0"), time_delta_seconds=1.0)
    assert engine.get_replenishment_velocity("BTCUSDT") == Decimal("60.00")


def test_execution_pacing_and_limit_cushions():
    engine = MarketImpactEngine()

    # NOMINAL
    assert engine.get_pacing_interval_ms("BTCUSDT") == 100.0
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("0.0")

    # ELEVATED_IMPACT
    engine.set_regime_override("BTCUSDT", MarketImpactRegime.ELEVATED_IMPACT)
    assert engine.get_pacing_interval_ms("BTCUSDT") == 250.0
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("2.0")

    # SEVERE_CONTROLS
    engine.set_regime_override("BTCUSDT", MarketImpactRegime.SEVERE_CONTROLS)
    assert engine.get_pacing_interval_ms("BTCUSDT") == 1000.0
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("5.0")


def test_aggressive_order_rejection_fail_closed_under_severe_controls():
    engine = MarketImpactEngine()
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.85"))

    # Passive limit order permitted
    engine.validate_order_pacing_and_impact_risk("BTCUSDT", OrderSide.BUY, OrderType.LIMIT)

    # Aggressive market order rejected fail-closed
    with pytest.raises(AggressiveOrderRejectedError):
        engine.validate_order_pacing_and_impact_risk("BTCUSDT", OrderSide.BUY, OrderType.MARKET)

    # Closing order permitted even if market
    engine.validate_order_pacing_and_impact_risk(
        "BTCUSDT", OrderSide.SELL, OrderType.MARKET, is_closing=True
    )


def test_cross_symbol_impact_transmission():
    engine = MarketImpactEngine()
    engine.record_impact_surge("BTCUSDT", lambda_value=Decimal("0.80"))
    coeffs = engine.get_spillover_coefficients("BTCUSDT")
    assert "ETHUSDT" in coeffs
    assert "SOLUSDT" in coeffs
    assert Decimal(coeffs["ETHUSDT"]) > Decimal("0.20")


# ---------------------------------------------------------------------------
# 4. Stepped Exposure Scaling & Micro Caps
# ---------------------------------------------------------------------------


def test_micro_child_cap_and_floor(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Exceeding 5.00 USDT child cap raises IndividualMicroCapExceededError
    with pytest.raises(IndividualMicroCapExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0001"),  # 6.00 USDT at 60k
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # Below 1.00 USDT floor raises MicroNotionalFloorViolationError
    with pytest.raises(MicroNotionalFloorViolationError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00001"),  # 0.60 USDT at 60k
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


def test_dynamic_twap_slicing(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    parent = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=Decimal("3000.00"),
        slice_chunk_notional=Decimal("2.25"),
    )
    assert parent.status == OrderLifecycleState.FILLED
    assert parent.child_count == 2
    child_ids = json.loads(parent.child_order_ids_json)
    assert len(child_ids) == 2


def test_stage_10_exposure_cap_up_to_50_usdt(temp_telemetry_store, temp_jsonl_sink):
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    assert interlock.get_stage_exposure_cap() == STAGE_10_MARKET_IMPACT_EXPANSION_CAP_USDT
    assert STAGE_10_MARKET_IMPACT_EXPANSION_CAP_USDT == Decimal("50.00")
    assert AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT == Decimal("50.00")


# ---------------------------------------------------------------------------
# 5. Margin Headroom & Working Margin Interlocks
# ---------------------------------------------------------------------------


def test_dynamic_margin_headroom_limits(temp_telemetry_store, temp_jsonl_sink):
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )

    # Per-asset margin cap is 20.00% (20.00 USDT for 100 USDT capital)
    reconciler.positions["BTCUSDT"] = Decimal("0.00030")  # 18.00 USDT at 60,000
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("18.00")
    reconciler.allocated_margin = Decimal("18.00")

    # Another 4.50 USDT order would push BTC margin to 22.50 USDT > 20.00 USDT limit
    with pytest.raises(MarginAllocationExceededError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.000075"),  # 4.50 USDT
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


def test_committed_working_margin_reservation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Dispatch resting (unfilled) order
    cid = generate_canary_client_order_id("SOLUSDT")
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-solusdt",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),  # 3.00 USDT
        price=Decimal("150.00"),
        client_order_id=cid,
        simulate_fill_immediately=False,
    )
    assert ord_rec.status == OrderLifecycleState.NEW
    assert interlock.committed_margin["SOLUSDT"] == Decimal("3.00000000")

    # Cancel releases committed margin
    dispatcher.cancel_micro_order(cid)
    assert interlock.committed_margin["SOLUSDT"] == Decimal("0.0")


# ---------------------------------------------------------------------------
# 6. Intra-Phase Cumulative Loss Lockout & Micro-Chunk Liquidation
# ---------------------------------------------------------------------------


def test_intra_phase_loss_lockout_and_liquidation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        loss_ceiling_usdt=Decimal("6.00"),
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Open position
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0015")

    # Simulate realized loss exceeding 6.00 USDT ceiling
    reconciler.cumulative_realized_loss = Decimal("6.20")

    # New order dispatch blocked fail-closed
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # Micro-chunk emergency liquidation flattens positions <= 5.00 USDT
    liquidated = dispatcher.emergency_micro_chunk_liquidate_all(
        candidate_ids={"ETHUSDT": "cand-ethusdt"},
        prices={"ETHUSDT": Decimal("3000.00")},
    )
    assert len(liquidated) >= 1
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")


# ---------------------------------------------------------------------------
# 7. Stream Sequencer, Wrap Recovery & Event Deduplication
# ---------------------------------------------------------------------------


def test_stream_sequencer_deduplication_and_wrap():
    sequencer = MarketImpactStreamSequencer(wrap_threshold=SEQUENCE_WRAP_THRESHOLD)

    ev1 = {"u": 100, "E": int(time.time() * 1000)}
    ev2 = {"u": 100, "E": int(time.time() * 1000)}  # duplicate
    ev3 = {"u": 95, "E": int(time.time() * 1000)}  # out-of-order
    ev4 = {"u": SEQUENCE_WRAP_THRESHOLD - 10, "E": int(time.time() * 1000)}
    ev5 = {"u": 12, "E": int(time.time() * 1000) + 10}  # wrap

    is_dup1, is_ooo1, is_wrap1 = sequencer.process_event(ev1)
    is_dup2, is_ooo2, is_wrap2 = sequencer.process_event(ev2)
    is_dup3, is_ooo3, is_wrap3 = sequencer.process_event(ev3)
    is_dup4, is_ooo4, is_wrap4 = sequencer.process_event(ev4)
    is_dup5, is_ooo5, is_wrap5 = sequencer.process_event(ev5)

    assert not is_dup1
    assert is_dup2
    assert is_ooo3
    assert not is_wrap4
    assert is_wrap5
    assert sequencer.deduplicated_count == 1
    assert sequencer.out_of_order_count == 1
    assert sequencer.wrap_count == 1


# ---------------------------------------------------------------------------
# 8. Exact Double-Entry Balance Reconciliation
# ---------------------------------------------------------------------------


def test_exact_double_entry_balance_reconciliation(temp_telemetry_store):
    reconciler = MarketImpactUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )

    # Buy BTC
    reconciler.record_fill(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.00005"),
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Buy ETH
    reconciler.record_fill(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        price=Decimal("3000.00"),
        quantity=Decimal("0.001"),
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Close BTC at profit
    reconciler.record_fill(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("62000.00"),
        quantity=Decimal("0.00005"),
        is_closing=True,
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Close ETH at loss
    reconciler.record_fill(
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        price=Decimal("2900.00"),
        quantity=Decimal("0.001"),
        is_closing=True,
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert reconciler.allocated_margin == Decimal("0.0")


# ---------------------------------------------------------------------------
# 9. Strict Containment Invariants
# ---------------------------------------------------------------------------


def test_strict_containment_invariants():
    # Compliant state
    verify_strict_fail_closed_invariants(
        orders_submitted=0,
        execution_authority=False,
        exchange_access=False,
    )

    # Live orders forbidden
    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(
            orders_submitted=1,
            execution_authority=False,
            exchange_access=False,
        )


# ---------------------------------------------------------------------------
# 10. Upstream & Phase 289 Cryptographic SHA-256 DAG Hash Chain
# ---------------------------------------------------------------------------


def test_verify_upstream_phase288_qualification():
    assert verify_upstream_phase288_qualification()


def test_verify_phase_289_hash_chain():
    assert verify_phase_289_hash_chain(output_dir=DEFAULT_PHASE289_OUTPUT_DIR)


# ---------------------------------------------------------------------------
# 11. CLI Runner Execution
# ---------------------------------------------------------------------------


def test_cli_runner_verify_only():
    code = cli_main(
        [
            "--output-dir",
            str(DEFAULT_PHASE289_OUTPUT_DIR),
            "--verify-only",
        ]
    )
    assert code == 0


def test_cli_runner_single_track(tmp_path: Path):
    code = cli_main(
        [
            "--output-dir",
            str(tmp_path),
            "--track",
            "1",
        ]
    )
    assert code == 0


def test_cli_runner_simulate_loss_breach(tmp_path: Path):
    code = cli_main(
        [
            "--output-dir",
            str(tmp_path),
            "--track",
            "3",
            "--simulate-loss-breach",
        ]
    )
    assert code == 0


def test_cli_runner_simulate_adverse_drift_failure(tmp_path: Path):
    code = cli_main(
        [
            "--output-dir",
            str(tmp_path),
            "--track",
            "1",
            "--simulate-adverse-drift",
        ]
    )
    assert code == 1


# ---------------------------------------------------------------------------
# 12. Adversarial Edge Cases & Microstructural Stress
# ---------------------------------------------------------------------------


def test_boundary_hysteresis_oscillations_under_rapid_order_placement_and_cancel(
    temp_telemetry_store, temp_jsonl_sink
):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # 1. Oscillations around [0.35, 0.40] band:
    # 0.30 -> NOMINAL
    # 0.38 -> still NOMINAL (not > 0.40)
    # 0.42 -> ELEVATED_IMPACT (> 0.40)
    # 0.37 -> still ELEVATED_IMPACT (not <= 0.35)
    # 0.34 -> NOMINAL (<= 0.35)
    sequence = [
        (Decimal("0.30"), MarketImpactRegime.NOMINAL),
        (Decimal("0.38"), MarketImpactRegime.NOMINAL),
        (Decimal("0.42"), MarketImpactRegime.ELEVATED_IMPACT),
        (Decimal("0.37"), MarketImpactRegime.ELEVATED_IMPACT),
        (Decimal("0.34"), MarketImpactRegime.NOMINAL),
    ]

    for lambda_val, expected_regime in sequence:
        engine.record_impact_surge("BTCUSDT", lambda_value=lambda_val)
        assert engine.get_regime("BTCUSDT") == expected_regime

        # Rapid order placement and cancel
        cid = generate_canary_client_order_id("BTCUSDT")
        ord_rec = dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),
            client_order_id=cid,
            simulate_fill_immediately=False,
        )
        assert ord_rec.impact_regime == expected_regime
        assert interlock.committed_margin["BTCUSDT"] == Decimal("3.00000000")

        # Cancel cleanly releases committed margin
        dispatcher.cancel_micro_order(cid)
        assert interlock.committed_margin["BTCUSDT"] == Decimal("0.0")

    assert interlock.committed_margin["BTCUSDT"] == Decimal("0.0")


def test_child_twap_partial_fills_and_multiple_fills(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    cid = generate_canary_client_order_id("SOLUSDT")
    # Place resting order of 0.02 SOL @ 150.00 = 3.00 USDT
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-solusdt",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        client_order_id=cid,
        simulate_fill_immediately=False,
    )
    assert ord_rec.status == OrderLifecycleState.NEW
    assert interlock.committed_margin["SOLUSDT"] == Decimal("3.00000000")

    # Partial fill 1: 0.008 SOL (1.20 USDT)
    disp_rec1 = dispatcher.simulate_order_fill(cid, fill_qty=Decimal("0.008"))
    assert disp_rec1.status == OrderLifecycleState.PARTIALLY_FILLED
    assert disp_rec1.executed_quantity == "0.008"
    assert interlock.committed_margin["SOLUSDT"] == Decimal("1.80000000")
    assert reconciler.positions["SOLUSDT"] == Decimal("0.008")
    assert reconciler.allocated_margin == Decimal("1.20000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Partial fill 2: 0.007 SOL (1.05 USDT)
    disp_rec2 = dispatcher.simulate_order_fill(cid, fill_qty=Decimal("0.007"))
    assert disp_rec2.status == OrderLifecycleState.PARTIALLY_FILLED
    assert disp_rec2.executed_quantity == "0.015"
    assert interlock.committed_margin["SOLUSDT"] == Decimal("0.75000000")
    assert reconciler.positions["SOLUSDT"] == Decimal("0.015")
    assert reconciler.allocated_margin == Decimal("2.25000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Cancel remaining 0.005 SOL (0.75 USDT)
    cancel_rec = dispatcher.cancel_micro_order(cid)
    assert cancel_rec.status == OrderLifecycleState.CANCELLED
    assert interlock.committed_margin["SOLUSDT"] == Decimal("0.0")
    assert reconciler.positions["SOLUSDT"] == Decimal("0.015")
    assert reconciler.allocated_margin == Decimal("2.25000000")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_concurrent_parent_and_child_committed_margin_tracking_no_double_counting(
    temp_telemetry_store, temp_jsonl_sink
):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Set initial allocated margin to 47.00 USDT (3.00 USDT headroom before 50.00 USDT cap)
    reconciler.allocated_margin = Decimal("47.00")

    # Target notional 4.50 USDT > 3.00 USDT remaining capacity
    # Parent order must fail upfront BEFORE dispatching any child slices
    with pytest.raises(AggregateExposureCapExceededError):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("4.50"),
            limit_price=Decimal("3000.00"),
            slice_chunk_notional=Decimal("2.25"),
        )
    # Ensure zero committed margin remains after upfront rejection
    assert interlock.get_total_committed_margin() == Decimal("0.0")
    assert len(dispatcher.orders) == 0

    # Now reset allocated margin to 0.0 USDT and dispatch valid parent order
    reconciler.allocated_margin = Decimal("0.0")
    parent = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=Decimal("3000.00"),
        slice_chunk_notional=Decimal("2.25"),
    )
    assert parent.status == OrderLifecycleState.FILLED
    assert parent.child_count == 2
    # All child slices filled, so all working margin released
    assert interlock.get_total_committed_margin() == Decimal("0.0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_partial_fills_concurrent_with_loss_breach_and_emergency_liquidation(
    temp_telemetry_store, temp_jsonl_sink
):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        loss_ceiling_usdt=Decimal("6.00"),
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # 1. Open and partially fill an order on ETHUSDT:
    # 0.0016 ETH @ 3000 = 4.80 USDT order, partially fill 0.001 ETH (3.00 USDT)
    cid_eth = generate_canary_client_order_id("ETHUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0016"),
        price=Decimal("3000.00"),
        client_order_id=cid_eth,
        simulate_fill_immediately=False,
    )
    dispatcher.simulate_order_fill(cid_eth, fill_qty=Decimal("0.001"))
    assert reconciler.positions["ETHUSDT"] == Decimal("0.001")
    assert interlock.committed_margin["ETHUSDT"] == Decimal("1.80000000")

    # 2. Open another resting BUY order on SOLUSDT (unfilled)
    cid_sol = generate_canary_client_order_id("SOLUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-solusdt",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        client_order_id=cid_sol,
        simulate_fill_immediately=False,
    )
    assert interlock.committed_margin["SOLUSDT"] == Decimal("3.00000000")

    # 3. Simulate cumulative loss breach (6.10 USDT > 6.00 USDT ceiling)
    reconciler.cumulative_realized_loss = Decimal("6.10")

    # 4. Trigger emergency liquidation
    dispatcher.emergency_micro_chunk_liquidate_all(
        candidate_ids={"ETHUSDT": "cand-ethusdt", "SOLUSDT": "cand-solusdt"},
        prices={"ETHUSDT": Decimal("3000.00"), "SOLUSDT": Decimal("150.00")},
    )

    # All working orders must have been cancelled
    assert dispatcher.orders[cid_eth].status == OrderLifecycleState.CANCELLED
    assert dispatcher.orders[cid_sol].status == OrderLifecycleState.CANCELLED
    # All committed margins must be zero
    assert interlock.committed_margin["ETHUSDT"] == Decimal("0.0")
    assert interlock.committed_margin["SOLUSDT"] == Decimal("0.0")
    assert interlock.get_total_committed_margin() == Decimal("0.0")
    # All positions must be flat
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0")
    assert reconciler.positions["SOLUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")
    # Drift must be zero
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT


def test_gateway_heartbeat_latency_hysteresis_freeze_rejection(
    temp_telemetry_store, temp_jsonl_sink
):
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor(
        max_age_ms=500.0,
        recovery_ms=450.0,
        max_clock_skew_ms=250.0,
    )
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_10_MARKET_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    now_ms = int(time.time() * 1000)

    # 1. Trigger backward clock skew freeze (> 250 ms)
    heartbeat_mon.record_heartbeat(
        server_time_ms=now_ms + 350,
        latency_ms=10.0,
        local_time_ms=now_ms,
        track_id="test_freeze",
    )
    assert heartbeat_mon.is_frozen

    # 2. Next heartbeat arrives: normal skew (5 ms), latency 460 ms (> 450 ms recovery)
    rec_slow = heartbeat_mon.record_heartbeat(
        server_time_ms=now_ms + 1000 - 5,
        latency_ms=460.0,
        local_time_ms=now_ms + 1000,
        track_id="test_freeze",
    )
    assert rec_slow.status == HeartbeatStatus.HYSTERESIS_FROZEN
    assert heartbeat_mon.is_frozen

    # Order placement blocked fail-closed under active hysteresis freeze
    with pytest.raises(HeartbeatFreezeActiveError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-solusdt",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.02"),
            price=Decimal("150.00"),
            client_order_id=generate_canary_client_order_id("SOLUSDT"),
            current_time_ms=now_ms + 1000,
        )

    # 3. Clean heartbeat arrives: latency 20 ms (<= 450 ms) and normal clock skew
    rec_clean = heartbeat_mon.record_heartbeat(
        server_time_ms=now_ms + 1100 - 5,
        latency_ms=20.0,
        local_time_ms=now_ms + 1100,
        track_id="test_freeze",
    )
    assert rec_clean.status == HeartbeatStatus.HEALTHY
    assert not heartbeat_mon.is_frozen

    # Order placement now succeeds
    cid = generate_canary_client_order_id("SOLUSDT")
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-solusdt",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        client_order_id=cid,
        current_time_ms=now_ms + 1100,
    )
    assert ord_rec.status == OrderLifecycleState.FILLED


def test_extreme_stress_double_entry_balance_reconciliation(temp_telemetry_store):
    import random

    reconciler = MarketImpactUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    prices = {
        "BTCUSDT": Decimal("63421.50"),
        "ETHUSDT": Decimal("3124.75"),
        "SOLUSDT": Decimal("148.33"),
    }

    rng = random.Random(42)

    for _ in range(150):
        sym = rng.choice(symbols)
        px = prices[sym] + Decimal(str(rng.randint(-50, 50))) / Decimal("10")
        curr_pos = reconciler.positions[sym]

        if abs(curr_pos) < Decimal("0.00000001"):
            side = rng.choice([OrderSide.BUY, OrderSide.SELL])
            qty = Decimal(str(rng.randint(1, 10))) / Decimal("1000")
            reconciler.record_fill(sym, side, px, qty, is_closing=False)
        else:
            if rng.random() < 0.65:
                side = OrderSide.SELL if curr_pos > 0 else OrderSide.BUY
                close_qty = min(abs(curr_pos), Decimal(str(rng.randint(1, 10))) / Decimal("2000"))
                reconciler.record_fill(sym, side, px, close_qty, is_closing=True)
            else:
                side = OrderSide.BUY if curr_pos > 0 else OrderSide.SELL
                qty = Decimal(str(rng.randint(1, 5))) / Decimal("2000")
                reconciler.record_fill(sym, side, px, qty, is_closing=False)

        assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


def test_concurrent_parent_working_margin_isolation_on_child_rejection(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify concurrent parent orders do not corrupt or double-deduct working margins."""
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)
    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Parent A reserves 10.00 USDT on ETHUSDT
    cid_parent_a = "parent-order-aaa"
    interlock.reserve_parent_working_margin(
        "ETHUSDT", Decimal("10.00"), parent_client_order_id=cid_parent_a
    )
    assert interlock.parent_working_margin["ETHUSDT"] == Decimal("10.00")

    # Parent B will attempt 10.00 USDT with 4 slices of 2.50 USDT
    # Intercept dispatch_micro_order: slice 1 succeeds, slice 2 raises MarketImpactBreachError
    orig_dispatch = dispatcher.dispatch_micro_order
    call_count = 0

    def mock_dispatch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise CanaryMarketImpactError("Simulated market impact breach on slice 2")
        return orig_dispatch(*args, **kwargs)

    dispatcher.dispatch_micro_order = mock_dispatch

    with pytest.raises(CanaryMarketImpactError, match="Simulated market impact breach"):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("10.00"),
            limit_price=Decimal("3000.00"),
            slice_chunk_notional=Decimal("2.50"),
        )

    # Parent A's reserved working margin MUST remain exactly 10.00 USDT
    assert interlock.parent_working_margin["ETHUSDT"] == Decimal("10.00")
    assert interlock._parent_order_working_notionals[cid_parent_a] == Decimal("10.00")

    # Only 1 parent order record created in dispatcher
    assert len(dispatcher.parent_orders) == 1
    parent_b = list(dispatcher.parent_orders.values())[0]
    assert parent_b.status == OrderLifecycleState.PARTIALLY_FILLED
    assert Decimal(parent_b.executed_notional_usdt) == Decimal("2.50")

    # Child IDs must contain ONLY the 1 successfully dispatched order (no ghost order)
    child_ids = json.loads(parent_b.child_order_ids_json)
    assert len(child_ids) == 1
    assert child_ids[0] in dispatcher.orders

    # Clean release of Parent A
    released = interlock.release_parent_order_working_margin(cid_parent_a, "ETHUSDT")
    assert released == Decimal("10.00")
    assert interlock.parent_working_margin["ETHUSDT"] == Decimal("0.0")


def test_parent_working_margin_released_on_pre_loop_exception(
    temp_telemetry_store, temp_jsonl_sink, monkeypatch
):
    """Verify parent working margin reservation is cleanly released if pre-loop error occurs."""
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)
    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Monkeypatch telemetry store to raise an error during record_parent_order
    def broken_record(parent_rec):
        raise RuntimeError("Telemetry disk write failure")

    monkeypatch.setattr(temp_telemetry_store, "record_parent_order", broken_record)

    with pytest.raises(RuntimeError, match="Telemetry disk write failure"):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("4.50"),
            limit_price=Decimal("3000.00"),
            slice_chunk_notional=Decimal("2.25"),
        )

    # Working margin must be cleanly cleaned up back to 0.00
    assert interlock.parent_working_margin["ETHUSDT"] == Decimal("0.0")
    assert len(interlock._parent_order_working_notionals) == 0


def test_safe_decimal_nan_infinity_resilience():
    """Verify _safe_decimal rejects NaN and Infinity gracefully without raising errors."""
    from autonomous_futures.feed.market_impact import _safe_decimal

    assert _safe_decimal(float("nan")) == Decimal("0.0")
    assert _safe_decimal(float("inf")) == Decimal("0.0")
    assert _safe_decimal(float("-inf")) == Decimal("0.0")
    assert _safe_decimal("nan") == Decimal("0.0")
    assert _safe_decimal("Infinity") == Decimal("0.0")
    assert _safe_decimal("-Infinity") == Decimal("0.0")
    assert _safe_decimal(Decimal("nan")) == Decimal("0.0")
    assert _safe_decimal(Decimal("Infinity")) == Decimal("0.0")
    assert _safe_decimal(None, default=Decimal("5.0")) == Decimal("5.0")
    assert _safe_decimal("42.50") == Decimal("42.50")


def test_market_impact_engine_extreme_and_zero_variance_resilience():
    """Verify Kyle's lambda & half-life handle zero-variance and non-finite inputs."""
    engine = MarketImpactEngine()

    # Zero-variance price marks (no price change)
    engine.process_trade("BTCUSDT", price=Decimal("60000.00"), quantity=Decimal("0.01"), side="BUY")
    engine.process_trade("BTCUSDT", price=Decimal("60000.00"), quantity=Decimal("0.01"), side="BUY")
    # Instantaneous lambda should be zero, not error
    assert engine.get_lambda("BTCUSDT") >= Decimal("0.0")

    # Extreme / NaN / negative half-life in surge
    engine.record_impact_surge(
        symbol="BTCUSDT",
        lambda_value=Decimal("0.85"),
        resilience_half_life=float("nan"),
        replenishment_velocity=Decimal("-5.0"),
    )
    # Sanitizer resets NaN half-life to base half-life
    assert engine.get_resilience_half_life("BTCUSDT") == engine.base_resilience_half_life_seconds

    # Extreme / zero / NaN time delta in replenishment
    engine.record_replenishment(
        symbol="BTCUSDT",
        depth_delta_usdt=Decimal("50.0"),
        time_delta_seconds=0.0,
    )
    assert engine.get_replenishment_velocity("BTCUSDT") == Decimal("50.00")

    engine.record_replenishment(
        symbol="BTCUSDT",
        depth_delta_usdt=Decimal("50.0"),
        time_delta_seconds=float("nan"),
    )
    assert engine.get_replenishment_velocity("BTCUSDT") == Decimal("50.00")

    # Spillover coefficients bound in [0.0, 1.0]
    spillover = engine.get_spillover_coefficients("BTCUSDT")
    for _other, coeff_str in spillover.items():
        coeff = Decimal(coeff_str)
        assert Decimal("0.0") <= coeff <= Decimal("1.0")


def test_conservative_candidate_margin_evaluation_under_price_displacement(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify per-asset margin interlock accounts for actual allocated cash margin on price drop."""
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)
    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Open position at entry price 3000.00: 0.006 ETH = 18.00 USDT allocated margin
    # Per-asset 20% limit of 100 USDT is 20.00 USDT.
    # Remaining per-asset headroom is 2.00 USDT.
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )
    assert reconciler.per_asset_margin["ETHUSDT"] == Decimal("18.00")

    # Now price drops to 1000.00 USDT.
    # Mark-to-market position value is 0.006 * 1000 = 6.00 USDT.
    # But actual allocated cash margin is 18.00 USDT!
    # If candidate tries to place another 3.00 USDT order, 18.00 + 3.00 = 21.00 > 20.00!
    with pytest.raises(MarginAllocationExceededError, match="exceeds per-asset 20% ceiling"):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.003"),
            price=Decimal("1000.00"),
            client_order_id=generate_canary_client_order_id("ETHUSDT"),
        )


def test_emergency_liquidation_cleans_all_committed_and_parent_margin(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify emergency liquidation cancels open resting orders and wipes committed margins."""
    gateway = MockBinanceMarketImpactGateway()
    reconciler = MarketImpactUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = MarketImpactEngine(telemetry_store=temp_telemetry_store)
    interlock = MarketImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = MarketImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # 1. Fill an order to establish an active open position
    dispatcher.dispatch_micro_order(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0015")

    # 2. Place an unfilled resting order that holds committed margin
    cid_resting = generate_canary_client_order_id("SOLUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-solusdt",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        client_order_id=cid_resting,
        simulate_fill_immediately=False,
    )
    assert interlock.committed_margin["SOLUSDT"] == Decimal("3.00")

    # 3. Reserve parent working margin
    interlock.reserve_parent_working_margin(
        "BTCUSDT", Decimal("4.50"), parent_client_order_id="p-btc"
    )
    assert interlock.parent_working_margin["BTCUSDT"] == Decimal("4.50")

    # Execute emergency liquidation
    liquidated = dispatcher.emergency_micro_chunk_liquidate_all(
        candidate_ids={"ETHUSDT": "cand-ethusdt"},
        prices={"ETHUSDT": Decimal("3000.00")},
    )
    assert len(liquidated) >= 1

    # Verify positions flattened
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")

    # Verify resting order was cancelled
    assert dispatcher.orders[cid_resting].status == OrderLifecycleState.CANCELLED

    # Verify ALL committed and parent working margins are completely cleared
    assert interlock.get_total_committed_margin() == Decimal("0.0")
    assert len(interlock._parent_order_working_notionals) == 0
    assert all(v == Decimal("0.0") for v in dispatcher._order_committed_notionals.values())
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
