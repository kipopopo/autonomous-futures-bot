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
from uuid import uuid4

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    DEFAULT_REFERENCE_PRICES,
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
    AggregateExposureCapExceededError,
    AggressiveOrderRejectedError,
    CapitalExpansionStage,
    CashReserveBufferBreachedError,
    CircuitBreakerState,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    JsonlCanaryOrderSink,
    LeadLagAdverseSelectionThrottledError,
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


# ---------------------------------------------------------------------------
# 11. Adversarial & Edge Case Tests (Phase 290 Round 1 Reviewer)
# ---------------------------------------------------------------------------


def test_client_order_id_extended_uuid_formats():
    """Verify client order ID validation accepts 8-32 hex tags and standard RFC-4122 UUIDs."""
    now_ms = int(time.time() * 1000)
    # Standard 12-char hex
    assert validate_canary_client_order_id(
        f"c=canary-p290-btcusdt-{now_ms}-a1b2c3d4e5f6", "BTCUSDT"
    )
    # 8-char hex
    assert validate_canary_client_order_id(f"c=canary-p290-ethusdt-{now_ms}-12345678", "ETHUSDT")
    # 32-char hex (full uuid4().hex)
    hex32 = uuid4().hex
    assert validate_canary_client_order_id(f"c=canary-p290-solusdt-{now_ms}-{hex32}", "SOLUSDT")
    # Standard RFC-4122 36-char hyphenated UUID
    uuid_hyphenated = str(uuid4())
    assert validate_canary_client_order_id(
        f"c=canary-p290-btcusdt-{now_ms}-{uuid_hyphenated}", "BTCUSDT"
    )

    # Reject symbol mismatch
    assert not validate_canary_client_order_id(f"c=canary-p290-ethusdt-{now_ms}-{hex32}", "BTCUSDT")
    # Reject invalid prefix or malformed structure
    assert not validate_canary_client_order_id(f"c=prod-p290-btcusdt-{now_ms}-12345678", "BTCUSDT")
    assert not validate_canary_client_order_id("c=canary-p290-btcusdt", "BTCUSDT")
    assert not validate_canary_client_order_id("", "BTCUSDT")


def test_gateway_heartbeat_uninitialized_fail_closed(temp_telemetry_store, temp_jsonl_sink):
    """Verify heartbeat monitor fails closed when 0 heartbeats recorded."""
    monitor = GatewayHeartbeatMonitor()
    # Before any heartbeat is recorded, health check must be False
    ok, reason = monitor.check_health()
    assert not ok
    assert "no gateway heartbeat" in reason.lower()

    # Pre-dispatch evaluation must block order fail-closed
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)
    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=monitor,
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

    with pytest.raises(GatewayHeartbeatStaleError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btc",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


def test_rolling_cross_impact_matrix_ridge_regression():
    """Verify regularized ridge regression estimation of Gamma (ΔP = Γ · OFI + ε)."""
    engine = OfiCrossImpactEngine()

    # Synthetic observations: 20 samples across BTC, ETH, SOL
    np.random.seed(42)
    ofi_btc = np.array(
        [
            2.0,
            3.5,
            -1.0,
            4.0,
            1.5,
            -2.0,
            5.0,
            0.5,
            -1.5,
            3.0,
            2.5,
            4.0,
            -0.5,
            3.0,
            1.0,
            -3.0,
            4.5,
            0.0,
            -2.0,
            3.5,
        ]
    )
    ofi_eth = np.array(
        [
            1.5,
            2.0,
            -0.5,
            2.5,
            1.0,
            -1.0,
            3.0,
            0.2,
            -1.0,
            2.0,
            1.8,
            2.5,
            -0.2,
            2.0,
            0.8,
            -2.0,
            3.0,
            0.1,
            -1.2,
            2.2,
        ]
    )
    ofi_sol = np.array(
        [
            0.5,
            1.0,
            -0.2,
            1.2,
            0.5,
            -0.5,
            1.5,
            0.1,
            -0.5,
            1.0,
            0.8,
            1.2,
            -0.1,
            1.0,
            0.4,
            -1.0,
            1.5,
            0.0,
            -0.6,
            1.1,
        ]
    )
    X = np.column_stack([ofi_btc, ofi_eth, ofi_sol])

    # Price displacements with BTC -> SOL spillover transmission
    dp_btc = 0.40 * ofi_btc + 0.15 * ofi_eth + np.random.normal(0, 0.02, 20)
    dp_eth = 0.20 * ofi_btc + 0.35 * ofi_eth + np.random.normal(0, 0.02, 20)
    dp_sol = 0.60 * ofi_btc + 0.25 * ofi_eth + 0.45 * ofi_sol + np.random.normal(0, 0.02, 20)
    Y = np.column_stack([dp_btc, dp_eth, dp_sol])

    gamma_dict = engine.estimate_cross_impact_matrix(
        ofi_matrix=X,
        displacement_matrix=Y,
        lambda_reg=0.05,
        ewma_weight=1.0,  # full update
    )

    # Self-impact on diagonal must be positive and within [0.01, 10.0]
    for sym in CANARY_STAGED_SYMBOLS:
        assert Decimal("0.01") <= gamma_dict[(sym, sym)] <= Decimal("10.0")

    # Cross-impact must be within [-2.0, 2.0]
    for s1 in CANARY_STAGED_SYMBOLS:
        for s2 in CANARY_STAGED_SYMBOLS:
            if s1 != s2:
                assert Decimal("-2.0") <= gamma_dict[(s1, s2)] <= Decimal("2.0")

    # Primary BTC -> Satellite SOL spillover coefficient should be elevated
    gamma_sol_btc = engine.get_gamma("SOLUSDT", "BTCUSDT")
    assert gamma_sol_btc > Decimal("0.40")


def test_collinear_and_singular_ofi_regression_stability():
    """Attack regularized ridge regression under collinear and all-zero OFI flow (ISSUE-03)."""
    engine = OfiCrossImpactEngine()

    # 1. Perfectly collinear OFI: rank(X) = 1 (ETH = 2*BTC, SOL = 0.5*BTC)
    btc_flow = np.linspace(-5.0, 5.0, 25)
    X_collinear = np.column_stack([btc_flow, 2.0 * btc_flow, 0.5 * btc_flow])
    Y_displacements = np.column_stack([0.3 * btc_flow, 0.5 * btc_flow, 0.4 * btc_flow])

    # Must solve stably via L2 regularizer lambda=0.05 without LinAlgError
    gamma_collinear = engine.estimate_cross_impact_matrix(
        ofi_matrix=X_collinear,
        displacement_matrix=Y_displacements,
        lambda_reg=0.05,
    )
    for v in gamma_collinear.values():
        assert not v.is_nan()
        assert not v.is_infinite()
        assert Decimal("-2.0") <= v <= Decimal("10.0")

    # 2. All-zero singular OFI: X = 0
    X_zero = np.zeros((10, 3))
    Y_zero = np.zeros((10, 3))
    gamma_zero = engine.estimate_cross_impact_matrix(
        ofi_matrix=X_zero,
        displacement_matrix=Y_zero,
        lambda_reg=0.05,
    )
    for v in gamma_zero.values():
        assert not v.is_nan()
        assert not v.is_infinite()


def test_twap_prevalidation_and_lead_lag_downscaling(temp_telemetry_store, temp_jsonl_sink):
    """Verify TWAP pre-validations and dynamic child slice downscaling under adverse selection."""
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

    # 1. Pre-validation rejects aggressive MARKET order under SEVERE_CONTROLS
    engine.record_lead_lag_shock(
        symbol="SOLUSDT",
        latency_ms=180.0,
        cross_impact_gamma=Decimal("0.85"),
    )
    with pytest.raises(AggressiveOrderRejectedError):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            target_notional=Decimal("4.50"),
            limit_price=DEFAULT_REFERENCE_PRICES["SOLUSDT"],
        )

    # 2. Pre-validation rejects parent order under INTRA_PHASE_LOSS_LOCKOUT
    interlock.circuit_state = CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("4.50"),
            limit_price=DEFAULT_REFERENCE_PRICES["SOLUSDT"],
        )
    interlock.circuit_state = CircuitBreakerState.NORMAL

    # 3. Pre-validation rejects parent order when cash reserve buffer (< 40%) would be breached
    # Starting equity is 100 USDT, 40% reserve buffer is 40 USDT
    # Set cash to 42 USDT -> 4.50 USDT parent order would leave 37.50 < 40
    reconciler.cash = Decimal("42.00")
    with pytest.raises(CashReserveBufferBreachedError):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("4.50"),
            limit_price=DEFAULT_REFERENCE_PRICES["SOLUSDT"],
        )
    reconciler.cash = Decimal("100.00")

    # 4. Dynamic slicing downscaling under SEVERE_FRONT_RUNNING_RISK:
    # 4.50 USDT parent order sliced into chunks <= 1.25 USDT (min 4 slices)
    parent = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-sol",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=DEFAULT_REFERENCE_PRICES["SOLUSDT"],
        slice_chunk_notional=Decimal("2.50"),  # requested 2.50, but clamped to 1.25
    )
    assert parent.dispatch_complete
    assert parent.child_count >= 4  # 4.50 / 1.25 = 3.6 -> 4 child slices


def test_process_orderbook_rolling_estimation_trigger():
    """Verify that multi-symbol orderbook updates register observations and update Gamma."""
    engine = OfiCrossImpactEngine()

    for step in range(8):
        for sym in CANARY_STAGED_SYMBOLS:
            base_px = DEFAULT_REFERENCE_PRICES[sym]
            step_dec = Decimal(str(step + 1))
            engine.process_orderbook_update(
                symbol=sym,
                bid_price=base_px + step_dec * Decimal("0.05"),
                bid_qty=Decimal("5.0") + step_dec,
                ask_price=base_px + step_dec * Decimal("0.06"),
                ask_qty=Decimal("4.0"),
            )

    assert len(engine._observation_history) >= 5
    # Verify Gamma matrix reflects multi-asset updates
    for sym in CANARY_STAGED_SYMBOLS:
        assert engine.get_gamma(sym, sym) > Decimal("0.0")


def test_backward_clock_jump_check_health_fail_closed():
    """Verify that local backward clock drift > 250 ms in check_health triggers

    freeze fail-closed.
    """
    monitor = GatewayHeartbeatMonitor(freshness_ceiling_ms=500.0, max_clock_skew_ms=250.0)
    now_ms = 1_000_000
    monitor.record_heartbeat(
        server_time_ms=now_ms,
        latency_ms=20.0,
        local_time_ms=now_ms,
    )
    assert not monitor.is_frozen
    # Healthy before backward jump
    ok, _ = monitor.check_health(current_time_ms=now_ms + 100)
    assert ok

    # Simulate backward NTP clock jump by 300 ms (< -250 ms threshold)
    ok_skew, reason = monitor.check_health(current_time_ms=now_ms - 300)
    assert not ok_skew
    assert monitor.is_frozen
    assert monitor.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert "backward ntp clock drift" in reason.lower()


def test_crossed_orderbook_rejection():
    """Verify that crossed or locked order book updates (bid >= ask) are rejected fail-closed."""
    engine = OfiCrossImpactEngine()
    snap_valid = engine.process_orderbook_update(
        symbol="BTCUSDT",
        bid_price=Decimal("60000.00"),
        bid_qty=Decimal("1.0"),
        ask_price=Decimal("60001.00"),
        ask_qty=Decimal("1.0"),
    )
    assert snap_valid is not None

    # Crossed book: bid > ask
    snap_crossed = engine.process_orderbook_update(
        symbol="BTCUSDT",
        bid_price=Decimal("60005.00"),
        bid_qty=Decimal("1.0"),
        ask_price=Decimal("60000.00"),
        ask_qty=Decimal("1.0"),
    )
    assert snap_crossed is None

    # Locked book: bid == ask
    snap_locked = engine.process_orderbook_update(
        symbol="BTCUSDT",
        bid_price=Decimal("60000.00"),
        bid_qty=Decimal("1.0"),
        ask_price=Decimal("60000.00"),
        ask_qty=Decimal("1.0"),
    )
    assert snap_locked is None


def test_multi_level_ofi_computation():
    """Verify multi-level OFI computation across 3 depth levels with decreasing level weights."""
    engine = OfiCrossImpactEngine()
    # Level 1, 2, 3 quotes:
    # Bids: (59990, 2.0), (59980, 5.0), (59970, 10.0)
    # Asks: (60010, 2.0), (60020, 5.0), (60030, 10.0)
    bids_t0 = [
        (Decimal("59990"), Decimal("2.0")),
        (Decimal("59980"), Decimal("5.0")),
        (Decimal("59970"), Decimal("10.0")),
    ]
    asks_t0 = [
        (Decimal("60010"), Decimal("2.0")),
        (Decimal("60020"), Decimal("5.0")),
        (Decimal("60030"), Decimal("10.0")),
    ]
    snap0 = engine.process_multi_level_orderbook_update(
        symbol="BTCUSDT",
        bids=bids_t0,
        asks=asks_t0,
        level_weights=[1.0, 0.5, 0.25],
    )
    assert snap0 is not None

    # Update at t1:
    # Level 1: bid size increases by +1.0 (delta_q_b = 1.0, w1=1.0 -> +1.0)
    # Level 2: bid price increases to 59985, size 4.0 (delta_q_b = 4.0, w2=0.5 -> +2.0)
    # Level 3: ask size increases by +2.0 (delta_q_a = 2.0, w3=0.25 -> -0.5)
    # Total multi-level OFI = 1.0*(1.0-0) + 0.5*(4.0-0) + 0.25*(0-2.0)
    # = 1.0 + 2.0 - 0.5 = 2.50
    bids_t1 = [
        (Decimal("59990"), Decimal("3.0")),
        (Decimal("59985"), Decimal("4.0")),
        (Decimal("59970"), Decimal("10.0")),
    ]
    asks_t1 = [
        (Decimal("60010"), Decimal("2.0")),
        (Decimal("60020"), Decimal("5.0")),
        (Decimal("60030"), Decimal("12.0")),
    ]
    snap1 = engine.process_multi_level_orderbook_update(
        symbol="BTCUSDT",
        bids=bids_t1,
        asks=asks_t1,
        level_weights=[1.0, 0.5, 0.25],
    )
    assert snap1 is not None
    assert Decimal(snap1.instantaneous_ofi) == Decimal("2.5000")


def test_no_phantom_cross_impact_when_single_asset_moves():
    """Verify that consecutive price movements in asset A do NOT pollute asset B displacement."""
    engine = OfiCrossImpactEngine()
    for s in CANARY_STAGED_SYMBOLS:
        p = DEFAULT_REFERENCE_PRICES[s]
        engine.process_orderbook_update(s, p, Decimal("10.0"), p + Decimal("1.0"), Decimal("10.0"))

    # Now move BTC 10 times with large price jumps
    for step in range(10):
        p = DEFAULT_REFERENCE_PRICES["BTCUSDT"] + Decimal(str((step + 1) * 20))
        engine.process_orderbook_update(
            "BTCUSDT", p, Decimal("10.0"), p + Decimal("1.0"), Decimal("10.0")
        )

    # For recent observations generated by BTC updates, verify ETH instantaneous displacement is 0.0
    recent_obs = list(engine._observation_history)[-5:]
    for obs in recent_obs:
        # ETH did not move during these BTC updates, so its displacement in obs must be 0.0 bps
        assert obs["ETHUSDT"][1] == Decimal("0.0")
        assert obs["SOLUSDT"][1] == Decimal("0.0")


def test_twap_prevalidation_throttled_candidate_cap(temp_telemetry_store, temp_jsonl_sink):
    """Verify that dispatch_twap_sliced_parent enforces THROTTLED_PER_CANDIDATE_CAP_USDT upfront."""
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

    # Set SOLUSDT to SEVERE_CONTROLS
    engine.set_regime_override("SOLUSDT", OfiCrossImpactRegime.SEVERE_CONTROLS)

    # Attempt to dispatch parent order with 12.00 USDT target notional (> 10.00 USDT throttled cap)
    with pytest.raises(LeadLagAdverseSelectionThrottledError) as exc_info:
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("12.00"),
            limit_price=DEFAULT_REFERENCE_PRICES["SOLUSDT"],
        )
    assert "throttled cap" in str(exc_info.value).lower()
    # Ensure working margin was not leaked
    assert interlock.get_total_committed_margin("SOLUSDT") == Decimal("0.0")


def test_execution_mark_client_order_id_linking(temp_telemetry_store, temp_jsonl_sink):
    """Verify that ExecutionMark records in reconciler and telemetry link to client_order_id."""
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
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

    cid = generate_canary_client_order_id("BTCUSDT")
    ord_rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=cid,
        simulate_fill_immediately=True,
    )
    assert ord_rec.status == OrderLifecycleState.FILLED

    # Query execution marks from telemetry database
    cursor = temp_telemetry_store.conn.cursor()
    cursor.execute(
        "SELECT client_order_id, order_id, symbol FROM execution_marks WHERE client_order_id = ?;",
        (cid,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["client_order_id"] == cid
    assert row["order_id"] == ord_rec.order_id
    assert row["symbol"] == "BTCUSDT"


def test_concurrent_orderbook_updates_no_deque_mutation_crash():
    """Verify thread-safe concurrent order book updates and absence of deque mutation crashes."""
    import threading

    engine = OfiCrossImpactEngine()
    errors: list[Exception] = []

    def worker(sym: str, count: int):
        base_px = DEFAULT_REFERENCE_PRICES[sym]
        for i in range(count):
            try:
                engine.process_orderbook_update(
                    symbol=sym,
                    bid_price=base_px + Decimal(str(i * 0.01)),
                    bid_qty=Decimal("5.0"),
                    ask_price=base_px + Decimal(str(i * 0.01 + 0.5)),
                    ask_qty=Decimal("5.0"),
                )
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(sym, 30)) for sym in CANARY_STAGED_SYMBOLS * 2]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent orderbook updates produced errors: {errors}"
    assert len(engine._observation_history) >= 5


def test_sequential_expansion_stage_transitions(temp_telemetry_store):
    """Verify transition_to_stage sequence from Stage 1 up to Stage 11 and

    exposure downscale blocks.
    """
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_1_SEED_PROBE,
        telemetry_store=temp_telemetry_store,
    )

    # Step through all 11 stages up to STAGE_11
    for st in ORDERED_EXPANSION_STAGES:
        cap = interlock.transition_to_stage(st)
        assert interlock.expansion_stage == st
        assert cap == interlock.get_stage_exposure_cap()

    assert interlock.expansion_stage == CapitalExpansionStage.STAGE_11_OFI_CROSS_IMPACT_EXPANSION
    assert interlock.get_stage_exposure_cap() == Decimal("55.00")

    # Allocate 12.00 USDT exposure
    reconciler.allocated_margin = Decimal("12.00")

    # Attempting to downscale to Stage 1 (cap 5.00) or Stage 2 (cap 10.00) must fail closed
    assert not interlock.can_transition_to(CapitalExpansionStage.STAGE_1_SEED_PROBE)
    assert not interlock.can_transition_to(CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT)
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.transition_to_stage(CapitalExpansionStage.STAGE_2_EXPANDED_CONCURRENT)

    # Can transition to Stage 3 (cap 15.00 >= 12.00)
    assert interlock.can_transition_to(CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION)
    cap3 = interlock.transition_to_stage(CapitalExpansionStage.STAGE_3_CONTINUOUS_EXPANSION)
    assert cap3 == Decimal("15.00")


# ---------------------------------------------------------------------------
# 11. Adversarial Edge Cases & Microstructure Boundary Hardening (Round 3)
# ---------------------------------------------------------------------------


def test_twap_child_orders_properly_tagged_in_jsonl_and_sqlite(
    temp_telemetry_store, temp_jsonl_sink
):
    """Verify child orders dispatched via TWAP are tagged with is_child=True, parent ID,

    and child index in BOTH SQLite and JSONL audit logs.
    """
    import json

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
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=DEFAULT_REFERENCE_PRICES["ETHUSDT"],
        slice_chunk_notional=Decimal("2.25"),
    )
    assert len(parent.child_order_ids) == 2

    # Check SQLite orders table
    cursor = temp_telemetry_store.conn.cursor()
    cursor.execute(
        "SELECT client_order_id, parent_client_order_id, is_child, child_index "
        "FROM orders WHERE is_child = 1;"
    )
    db_rows = cursor.fetchall()
    assert len(db_rows) == 2
    for r in db_rows:
        assert r["parent_client_order_id"] == parent.parent_client_order_id
        assert r["is_child"] == 1
        assert r["client_order_id"] in parent.child_order_ids

    # Check JSONL file content
    jsonl_lines = temp_jsonl_sink.file_path.read_text(encoding="utf-8").strip().splitlines()
    child_json_records = [
        json.loads(line) for line in jsonl_lines if json.loads(line).get("is_child") is True
    ]
    assert len(child_json_records) >= 2
    for c_rec in child_json_records:
        assert c_rec["parent_client_order_id"] == parent.parent_client_order_id
        assert c_rec["is_child"] is True
        assert c_rec["child_index"] in (0, 1)


def test_parent_working_margin_memory_leak_prevention(temp_telemetry_store, temp_jsonl_sink):
    """Verify that completing a TWAP parent order cleans up parent working margin mapping."""
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
        limit_price=DEFAULT_REFERENCE_PRICES["BTCUSDT"],
        slice_chunk_notional=Decimal("2.25"),
    )
    p_cid = parent.parent_client_order_id

    # Verify that working margin mappings are empty and not retaining references
    assert p_cid not in interlock._parent_order_working_notionals
    assert p_cid not in interlock._parent_order_symbols
    assert interlock.parent_working_margin["BTCUSDT"] == Decimal("0.0")


def test_multi_level_orderbook_negative_and_non_monotonic_prices_rejected():
    """Verify that multi-level depth updates with non-positive prices, negative quantities,

    or non-monotonic ladder levels are strictly rejected fail-closed.
    """
    engine = OfiCrossImpactEngine()

    # Case 1: Negative price at level 1
    bad_bids_neg_px = [
        (Decimal("100.0"), Decimal("1.0")),
        (Decimal("-50.0"), Decimal("2.0")),
    ]
    asks = [(Decimal("101.0"), Decimal("1.0")), (Decimal("102.0"), Decimal("2.0"))]
    assert engine.process_multi_level_orderbook_update("SOLUSDT", bad_bids_neg_px, asks) is None

    # Case 2: Negative quantity at level 1
    bad_bids_neg_qty = [
        (Decimal("100.0"), Decimal("1.0")),
        (Decimal("99.0"), Decimal("-2.0")),
    ]
    assert engine.process_multi_level_orderbook_update("SOLUSDT", bad_bids_neg_qty, asks) is None

    # Case 3: Inverted / non-monotonic bids (level 1 price >= level 0 price)
    bad_bids_inverted = [
        (Decimal("100.0"), Decimal("1.0")),
        (Decimal("105.0"), Decimal("2.0")),
    ]
    assert engine.process_multi_level_orderbook_update("SOLUSDT", bad_bids_inverted, asks) is None

    # Case 4: Inverted / non-monotonic asks (level 1 price <= level 0 price)
    bad_asks_inverted = [
        (Decimal("101.0"), Decimal("1.0")),
        (Decimal("100.5"), Decimal("2.0")),
    ]
    bids = [(Decimal("100.0"), Decimal("1.0")), (Decimal("99.0"), Decimal("2.0"))]
    assert engine.process_multi_level_orderbook_update("SOLUSDT", bids, bad_asks_inverted) is None


def test_cross_impact_matrix_nan_inf_poisoning_defense():
    """Verify that NaN or Inf in regression matrices does not poison cross-impact."""
    engine = OfiCrossImpactEngine()

    # Input matrix containing NaN
    X_nan = np.array([[1.0, 2.0, float("nan")], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
    Y_clean = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]])
    res = engine.estimate_cross_impact_matrix(ofi_matrix=X_nan, displacement_matrix=Y_clean)

    # Matrix must retain clean numeric Decimal values without NaN
    for k, v in res.items():
        assert not v.is_nan(), f"Gamma matrix element {k} poisoned with NaN: {v}"
        assert not v.is_infinite()

    # Input matrix containing Inf
    X_inf = np.array([[1.0, 2.0, float("inf")], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
    res_inf = engine.estimate_cross_impact_matrix(ofi_matrix=X_inf, displacement_matrix=Y_clean)
    for _k, v in res_inf.items():
        assert not v.is_nan()
        assert not v.is_infinite()


def test_emergency_liquidation_chunk_cap_boundaries(temp_telemetry_store, temp_jsonl_sink):
    """Verify that emergency liquidation chunk cap is bounded between 1.00 and 5.00 USDT."""
    gateway = MockBinanceOfiCrossImpactGateway()
    reconciler = OfiCrossImpactUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = OfiCrossImpactEngine(telemetry_store=temp_telemetry_store)

    interlock = OfiCrossImpactOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
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

    # Open position in SOLUSDT: 0.04 SOL @ 150.00 = 6.00 USDT
    cid1 = generate_canary_client_order_id("SOLUSDT")
    cid2 = generate_canary_client_order_id("SOLUSDT")
    dispatcher.dispatch_micro_order(
        candidate_id="cand-sol",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        client_order_id=cid1,
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-sol",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        client_order_id=cid2,
    )
    assert reconciler.positions["SOLUSDT"] == Decimal("0.04")

    # Liquidate with chunk_cap = 0 (must floor at 1.00 USDT and not hang or error)
    cand_map = {"SOLUSDT": "cand-sol", "BTCUSDT": "cand-btc", "ETHUSDT": "cand-eth"}
    orders = dispatcher.emergency_micro_chunk_liquidate_all(
        candidate_ids=cand_map,
        prices={"SOLUSDT": Decimal("150.00")},
        chunk_cap=Decimal("0.0"),
    )
    assert len(orders) >= 1
    assert reconciler.positions["SOLUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT


def test_cancelled_order_cannot_be_filled_in_gateway():
    """Verify that an order cancelled on mock gateway cannot receive simulated fills."""
    gateway = MockBinanceOfiCrossImpactGateway()
    cid = "c=canary-p290-btcusdt-12345-abcdef12"
    gateway.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0001"),
        price=Decimal("60000.00"),
        client_order_id=cid,
    )
    assert gateway.cancel_order(cid) is True

    # Attempting to fill cancelled order must return None
    fill = gateway.simulate_fill(cid)
    assert fill is None


def test_gateway_heartbeat_staleness_freezes_monitor():
    """Verify that heartbeat age > 500 ms freezes monitor and requires hysteresis recovery."""
    monitor = GatewayHeartbeatMonitor(freshness_ceiling_ms=500.0, recovery_hysteresis_ms=450.0)
    t0 = 1700000000000
    monitor.record_heartbeat(server_time_ms=t0, latency_ms=20.0, local_time_ms=t0)

    # Health check at t0 + 600 ms (> 500 ms ceiling)
    ok, reason = monitor.check_health(current_time_ms=t0 + 600)
    assert ok is False
    assert monitor.is_frozen is True
    assert monitor.status == HeartbeatStatus.STALE

    # Record heartbeat with latency 480 ms (> 450 ms recovery hysteresis)
    rec1 = monitor.record_heartbeat(
        server_time_ms=t0 + 610, latency_ms=480.0, local_time_ms=t0 + 610
    )
    assert rec1.is_healthy is False
    assert monitor.is_frozen is True

    # Record heartbeat with latency 400 ms (<= 450 ms recovery hysteresis)
    rec2 = monitor.record_heartbeat(
        server_time_ms=t0 + 620, latency_ms=400.0, local_time_ms=t0 + 620
    )
    assert rec2.is_healthy is True
    assert monitor.is_frozen is False
    assert monitor.status == HeartbeatStatus.HEALTHY
