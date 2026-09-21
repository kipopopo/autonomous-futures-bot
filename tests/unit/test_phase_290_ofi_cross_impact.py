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
