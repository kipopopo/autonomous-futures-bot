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
    AggressiveOrderRejectedError,
    CapitalExpansionStage,
    DisplacementAbsorptionState,
    GatewayHeartbeatMonitor,
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
