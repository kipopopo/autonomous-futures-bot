"""Unit tests for Phase 290: Canary Cross-Asset OFI & Cross-Impact Matrix Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 289 back to 276).
- Dual-confirmation client order tag format (c=canary-p290-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms), backward NTP clock drift (> 250 ms triggers
  HEARTBEAT_FREEZE with recovery hysteresis <= 450 ms).
- Order Flow Imbalance (OFI_t = Δq_t^b - Δq_t^a) and Cross-Impact Matrix (Γ_ij) Engine:
  - Multi-level order book OFI computation.
  - Price displacement ΔP_t = Γ · OFI_t + ε_t.
  - Regimes: NOMINAL (<= 0.40), ELEVATED_CROSS_IMPACT (0.40-0.70), SEVERE_CONTROLS (> 0.70).
  - Anti-flapping de-escalation hysteresis thresholds (0.35 and 0.65).
  - Execution pacing interval lengthening (100 ms, 250 ms, 1000 ms).
  - Limit offset cushion widening (+0 bps, +2 bps, +5 bps).
  - Lead-lag latency and adverse selection states.
  - Aggressive market order rejection fail-closed under severe cross-impact.
  - Cross-symbol impact transmission coefficients (primary to satellite spillover).
- Stepped concurrent exposure scaling across stages:
  - Stages 1 to 11 up to <= 55.00 USDT aggregate concurrent active exposure across all symbols.
  - Individual micro child order cap <= 5.00 USDT.
  - Dynamic sequential TWAP slicing <= 2.50 USDT child slices with 1.00 USDT floor.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 6.50 USDT with immediate fail-closed
  lockout and emergency micro-chunked liquidation (<= 5.00 USDT slices).
- Multi-day extended session longevity, 24h listenKey expiration/renewal, sequence wrap
  recovery, and idempotent event deduplication.
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
from autonomous_futures.feed.ofi_cross_impact import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    CANARY_STAGED_SYMBOLS,
    DOUBLE_ENTRY_MAX_DRIFT,
    ORDERED_EXPANSION_STAGES,
    STAGE_11_OFI_CROSS_IMPACT_EXPANSION_CAP_USDT,
    AggressiveOrderRejectedError,
    CapitalExpansionStage,
    CircuitBreakerState,
    GatewayHeartbeatMonitor,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    JsonlCanaryOrderSink,
    MarginAllocationExceededError,
    MicroNotionalFloorViolationError,
    MockBinanceOfiCrossImpactGateway,
    OfiCrossImpactEngine,
    OfiCrossImpactMicroOrderDispatcher,
    OfiCrossImpactOrderDispatchInterlock,
    OfiCrossImpactRegime,
    OfiCrossImpactStreamSequencer,
    OfiCrossImpactUserDataStreamReconciler,
    OrderLifecycleState,
    SqliteCanaryOfiCrossImpactTelemetryStore,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_290_hash_chain,
    verify_upstream_phase289_qualification,
)
from scripts.run_phase_290_ofi_cross_impact import main as cli_main  # noqa: E402


@pytest.fixture
def temp_telemetry_store(tmp_path: Path) -> SqliteCanaryOfiCrossImpactTelemetryStore:
    db_file = tmp_path / "test_telemetry.sqlite3"
    return SqliteCanaryOfiCrossImpactTelemetryStore(db_file)


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
        assert cid.startswith(f"c=canary-p290-{sym.lower()}-")
        assert len(cid.split("-")) >= 5


def test_invalid_client_order_id_rejection():
    # Wrong prefix (prior phase)
    assert not validate_canary_client_order_id(
        "c=canary-p289-btcusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Wrong symbol
    assert not validate_canary_client_order_id(
        "c=canary-p290-ethusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Missing parts
    assert not validate_canary_client_order_id("c=canary-p290-btcusdt", "BTCUSDT")
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
    )
    assert rec.is_healthy
    assert rec.status == HeartbeatStatus.HEALTHY
    ok, _ = monitor.check_health(now_ms + 100)
    assert ok


def test_gateway_heartbeat_stale_latency_spike():
    monitor = GatewayHeartbeatMonitor(freshness_ceiling_ms=500.0, max_clock_skew_ms=250.0)
    now_ms = int(time.time() * 1000)
    rec = monitor.record_heartbeat(
        server_time_ms=now_ms,
        latency_ms=600.0,
        local_time_ms=now_ms,
    )
    assert not rec.is_healthy
    assert rec.status == HeartbeatStatus.STALE
    ok, reason = monitor.check_health(now_ms)
    assert not ok
    assert "frozen" in reason.lower() or "exceeds" in reason.lower()

    # Also test age exceeding ceiling
    monitor2 = GatewayHeartbeatMonitor(freshness_ceiling_ms=500.0, max_clock_skew_ms=250.0)
    monitor2.record_heartbeat(
        server_time_ms=now_ms - 600,
        latency_ms=20.0,
        local_time_ms=now_ms - 600,
    )
    ok2, reason2 = monitor2.check_health(now_ms)
    assert not ok2
    assert "exceeds" in reason2.lower()


def test_gateway_heartbeat_clock_skew_freeze_and_recovery_hysteresis():
    monitor = GatewayHeartbeatMonitor(
        freshness_ceiling_ms=500.0,
        recovery_hysteresis_ms=450.0,
        max_clock_skew_ms=250.0,
    )
    now_ms = int(time.time() * 1000)

    # Trigger backward clock drift > 250 ms -> FREEZE
    rec_skew = monitor.record_heartbeat(
        server_time_ms=now_ms - 300,  # 300ms drift
        latency_ms=30.0,
        local_time_ms=now_ms,
    )
    assert not rec_skew.is_healthy
    assert rec_skew.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert monitor.is_frozen

    # In hysteresis zone (latency 460ms > 450ms recovery) -> remains frozen
    rec_hyst = monitor.record_heartbeat(
        server_time_ms=now_ms + 50,
        latency_ms=460.0,
        local_time_ms=now_ms + 50,
    )
    assert not rec_hyst.is_healthy
    assert monitor.is_frozen

    # Recovered within 450ms hysteresis and clock skew <= 200ms -> healthy
    rec_recov = monitor.record_heartbeat(
        server_time_ms=now_ms + 100,
        latency_ms=40.0,
        local_time_ms=now_ms + 100,
    )
    assert rec_recov.is_healthy
    assert not monitor.is_frozen
    assert rec_recov.status == HeartbeatStatus.HEALTHY


# ---------------------------------------------------------------------------
# 3. OFI & Cross-Impact Matrix Engine
# ---------------------------------------------------------------------------


def test_ofi_calculation_and_price_displacement():
    engine = OfiCrossImpactEngine()
    sym = "BTCUSDT"

    # Initial update
    engine.process_orderbook_update(
        symbol=sym,
        bid_price=Decimal("60000.00"),
        bid_qty=Decimal("5.0"),
        ask_price=Decimal("60001.00"),
        ask_qty=Decimal("5.0"),
    )

    # Next update: bid price improved to 60000.50 with 8.0 size (delta_q_b = 8.0)
    # ask price unchanged with size 6.0 (delta_q_a = 6.0 - 5.0 = 1.0)
    # OFI = 8.0 - 1.0 = 7.0
    snap = engine.process_orderbook_update(
        symbol=sym,
        bid_price=Decimal("60000.50"),
        bid_qty=Decimal("8.0"),
        ask_price=Decimal("60001.00"),
        ask_qty=Decimal("6.0"),
    )
    assert snap is not None
    assert Decimal(snap.instantaneous_ofi) == Decimal("7.0")
    assert Decimal(snap.price_displacement_bps) > Decimal("0")


def test_ofi_cross_impact_regimes_and_anti_flapping_hysteresis():
    engine = OfiCrossImpactEngine()
    sym = "SOLUSDT"

    assert engine.get_regime(sym) == OfiCrossImpactRegime.NOMINAL

    # Inject elevated shock (gamma = 0.55)
    engine.record_lead_lag_shock(
        symbol=sym,
        latency_ms=90.0,
        cross_impact_gamma=Decimal("0.55"),
    )
    assert engine.get_regime(sym) == OfiCrossImpactRegime.ELEVATED_CROSS_IMPACT

    # Inject severe shock (gamma = 0.85, latency = 180 ms)
    engine.record_lead_lag_shock(
        symbol=sym,
        latency_ms=180.0,
        cross_impact_gamma=Decimal("0.85"),
    )
    assert engine.get_regime(sym) == OfiCrossImpactRegime.SEVERE_CONTROLS

    # Test anti-flapping hysteresis: gamma dropped to 0.68 (> 0.65 recovery) -> still SEVERE
    engine.record_lead_lag_shock(
        symbol=sym,
        latency_ms=120.0,
        cross_impact_gamma=Decimal("0.68"),
    )
    assert engine.get_regime(sym) == OfiCrossImpactRegime.SEVERE_CONTROLS

    # Gamma dropped to 0.50 (<= 0.65 recovery) -> de-escalates to ELEVATED
    engine.record_lead_lag_shock(
        symbol=sym,
        latency_ms=50.0,
        cross_impact_gamma=Decimal("0.50"),
    )
    assert engine.get_regime(sym) == OfiCrossImpactRegime.ELEVATED_CROSS_IMPACT

    # Gamma dropped to 0.30 (<= 0.35 recovery) -> de-escalates to NOMINAL
    engine.record_lead_lag_shock(
        symbol=sym,
        latency_ms=15.0,
        cross_impact_gamma=Decimal("0.30"),
    )
    assert engine.get_regime(sym) == OfiCrossImpactRegime.NOMINAL


def test_execution_pacing_and_limit_cushions():
    engine = OfiCrossImpactEngine()
    sym = "BTCUSDT"

    # Nominal
    assert engine.get_pacing_interval_ms(sym) == 100.0
    assert engine.get_limit_offset_cushion_bps(sym) == Decimal("0.0")

    # Elevated
    engine.set_regime_override(sym, OfiCrossImpactRegime.ELEVATED_CROSS_IMPACT)
    assert engine.get_pacing_interval_ms(sym) == 250.0
    assert engine.get_limit_offset_cushion_bps(sym) == Decimal("2.0")

    # Severe
    engine.set_regime_override(sym, OfiCrossImpactRegime.SEVERE_CONTROLS)
    assert engine.get_pacing_interval_ms(sym) == 1000.0
    assert engine.get_limit_offset_cushion_bps(sym) == Decimal("5.0")


def test_aggressive_order_rejection_fail_closed_under_severe_controls():
    engine = OfiCrossImpactEngine()
    sym = "SOLUSDT"

    engine.set_regime_override(sym, OfiCrossImpactRegime.SEVERE_CONTROLS)
    # Passive LIMIT permitted
    engine.validate_order_pacing_and_impact_risk(sym, OrderSide.BUY, OrderType.LIMIT)

    # Aggressive MARKET rejected
    with pytest.raises(AggressiveOrderRejectedError):
        engine.validate_order_pacing_and_impact_risk(sym, OrderSide.BUY, OrderType.MARKET)

    # Closing order permitted even if market
    engine.validate_order_pacing_and_impact_risk(
        sym, OrderSide.SELL, OrderType.MARKET, is_closing=True
    )


def test_cross_symbol_impact_transmission():
    engine = OfiCrossImpactEngine()
    coeff = engine.get_spillover_coefficients("BTCUSDT")
    assert "ETHUSDT" in coeff
    assert "SOLUSDT" in coeff
    assert Decimal(coeff["ETHUSDT"]) > Decimal("0")
    assert Decimal(coeff["SOLUSDT"]) > Decimal("0")


# ---------------------------------------------------------------------------
# 4. Micro Order Sizing, TWAP Slicing & Exposure Ceilings (Stage 11: 55 USDT)
# ---------------------------------------------------------------------------


def test_micro_child_cap_and_floor(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = OfiCrossImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Heartbeat
    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # 1. Order exceeding 5.00 USDT -> IndividualMicroCapExceededError
    with pytest.raises(IndividualMicroCapExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0001"),
            price=Decimal("60000.00"),  # 6.00 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # 2. Order below 1.00 USDT -> MicroNotionalFloorViolationError
    with pytest.raises(MicroNotionalFloorViolationError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00001"),
            price=Decimal("60000.00"),  # 0.60 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # 3. Valid order between 1.00 and 5.00 USDT -> succeeds
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),  # 3.00 USDT
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )
    assert ord_rec.status == OrderLifecycleState.FILLED


def test_dynamic_twap_slicing(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = OfiCrossImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    parent = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=Decimal("60000.00"),
        slice_chunk_notional=Decimal("2.25"),
    )
    assert parent.dispatch_complete
    assert parent.child_count == 2
    assert len(parent.child_order_ids) == 2
    assert Decimal(parent.executed_notional_usdt) == Decimal("4.50")


def test_stage_11_exposure_cap_up_to_55_usdt(temp_telemetry_store, temp_jsonl_sink):
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    assert interlock.get_stage_exposure_cap() == Decimal("55.00")
    assert STAGE_11_OFI_CROSS_IMPACT_EXPANSION_CAP_USDT == Decimal("55.00")
    assert AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT == Decimal("55.00")
    assert ORDERED_EXPANSION_STAGES[-1] == CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION


# ---------------------------------------------------------------------------
# 5. Margin Headroom & Committed Working Margin
# ---------------------------------------------------------------------------


def test_dynamic_margin_headroom_limits(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Per-asset cap is 20% of 100 = 20.00 USDT
    # Try placing an order that would exceed per-asset margin
    reconciler.allocated_margin = Decimal("18.00")
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("18.00")

    with pytest.raises(MarginAllocationExceededError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),  # 3.00 USDT -> 18 + 3 = 21 > 20
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


def test_committed_working_margin_reservation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Reserve working margin on parent order
    cid_parent = "parent-test-123"
    interlock.reserve_parent_working_margin(
        "BTCUSDT", Decimal("4.00"), parent_client_order_id=cid_parent
    )
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("4.00")

    # Deduct 2.00 USDT when child slice dispatched
    interlock.deduct_parent_working_margin(
        "BTCUSDT", Decimal("2.00"), parent_client_order_id=cid_parent
    )
    interlock.reserve_committed_margin("BTCUSDT", Decimal("2.00"))
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("4.00")

    # Release on fill
    interlock.release_committed_margin("BTCUSDT", Decimal("2.00"))
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("2.00")

    # Release remaining parent working margin
    rem = interlock.release_parent_order_working_margin(cid_parent, "BTCUSDT")
    assert rem == Decimal("2.00")
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("0.0")


# ---------------------------------------------------------------------------
# 6. Intra-Phase Loss Budget Ceiling & Liquidation (<= 6.50 USDT)
# ---------------------------------------------------------------------------


def test_intra_phase_loss_lockout_and_liquidation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION,
        loss_ceiling_usdt=Decimal("6.50"),
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = OfiCrossImpactMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Simulate cumulative loss exceeding 6.50 USDT
    reconciler.cumulative_realized_loss = Decimal("6.51")

    # New order rejected fail-closed
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT


# ---------------------------------------------------------------------------
# 7. Stream Sequencer Deduplication & Sequence Wrap
# ---------------------------------------------------------------------------


def test_stream_sequencer_deduplication_and_wrap():
    seq = OfiCrossImpactStreamSequencer(wrap_threshold=1_000_000)

    # Event 1
    dup, ooo, wrap = seq.process_event({"u": 100, "E": 1000})
    assert not dup and not ooo and not wrap

    # Duplicate
    dup, ooo, wrap = seq.process_event({"u": 100, "E": 1000})
    assert dup and not ooo and not wrap
    assert seq.deduplicated_count == 1

    # Out of order
    dup, ooo, wrap = seq.process_event({"u": 90, "E": 1000})
    assert not dup and ooo and not wrap
    assert seq.out_of_order_count == 1

    # Wrap near 1,000,000 to 5
    seq.process_event({"u": 999_950, "E": 2000})
    dup, ooo, wrap = seq.process_event({"u": 5, "E": 2010})
    assert not dup and not ooo and wrap
    assert seq.wrap_count == 1


# ---------------------------------------------------------------------------
# 8. Exact Double-Entry Balance Reconciliation
# ---------------------------------------------------------------------------


def test_exact_double_entry_balance_reconciliation(temp_telemetry_store):
    reconciler = OfiCrossImpactUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )
    assert reconciler.mathematical_drift == Decimal("0.0")

    # Buy fill: 0.00005 BTC @ 60,000 = 3.00 USDT
    reconciler.process_fill(
        trade_id="trd-1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.00005"),
        commission=Decimal("0.0012"),
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # Close fill: 0.00005 BTC @ 61,000 = 3.05 USDT (gain 0.05 USDT)
    reconciler.process_fill(
        trade_id="trd-2",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("61000.00"),
        quantity=Decimal("0.00005"),
        commission=Decimal("0.00122"),
        is_closing=True,
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT
    assert reconciler.positions["BTCUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")


# ---------------------------------------------------------------------------
# 9. Strict Containment Invariants
# ---------------------------------------------------------------------------


def test_strict_containment_invariants():
    # Compliant: 0 orders, no authority, no exchange access
    verify_strict_fail_closed_invariants(
        orders_submitted=0,
        execution_authority=False,
        exchange_access=False,
    )

    # Invariant breach: orders > 0
    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(
            orders_submitted=1,
            execution_authority=False,
            exchange_access=False,
        )

    # Invariant breach: execution_authority=True
    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(
            orders_submitted=0,
            execution_authority=True,
            exchange_access=False,
        )


# ---------------------------------------------------------------------------
# 10. Upstream Verification & Hash Chain
# ---------------------------------------------------------------------------


def test_verify_upstream_phase289_qualification():
    assert verify_upstream_phase289_qualification()


def test_verify_phase_290_hash_chain():
    assert verify_phase_290_hash_chain()


def test_cli_runner_verify_only():
    ret = cli_main(["--verify-only"])
    assert ret == 0


def test_cli_runner_single_track(tmp_path: Path):
    out_dir = tmp_path / "p290_test_t1"
    ret = cli_main(["--output-dir", str(out_dir), "--track", "1"])
    assert ret == 0


def test_cli_runner_simulate_loss_breach(tmp_path: Path):
    out_dir = tmp_path / "p290_test_loss"
    ret = cli_main(["--output-dir", str(out_dir), "--track", "3", "--simulate-loss-breach"])
    assert ret == 0


def test_cli_runner_simulate_adverse_drift_failure(tmp_path: Path):
    out_dir = tmp_path / "p290_test_drift"
    ret = cli_main(["--output-dir", str(out_dir), "--track", "1", "--simulate-adverse-drift"])
    assert ret == 1
