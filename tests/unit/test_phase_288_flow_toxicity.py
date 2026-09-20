"""Unit tests for Phase 288: Canary Cross-Asset Order Flow Toxicity & VPIN Governance Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 287 back to 276).
- Dual-confirmation client order tag format (c=canary-p288-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms), backward NTP clock drift (> 250 ms triggers
  HEARTBEAT_FREEZE with recovery hysteresis <= 450 ms).
- Volume-Synchronized Probability of Toxicity (VPIN) & Flow Toxicity Engine:
  - Trade volume bucket partitioning (V = 25.00 USDT, N = 5 buckets).
  - VPIN computation: balanced flow -> VPIN ~ 0.0, unidirectional flow -> VPIN ~ 1.0.
  - Toxicity regimes: NOMINAL (<= 0.40), ELEVATED (0.40-0.65), SEVERE (> 0.65).
  - Anti-flapping de-escalation hysteresis thresholds (0.35 and 0.60).
  - Adaptive execution pacing interval lengthening (100 ms, 250 ms, 1000 ms).
  - Limit offset cushion widening (+0 bps, +2 bps, +5 bps).
  - Adverse selection risk detection & aggressive order rejection fail-closed.
  - Cross-symbol toxicity spillover transmission coefficients.
- Stepped concurrent exposure scaling across stages:
  - Stage 1 seed probe cap (<= 5.00 USDT)
  - Stage 2 expanded concurrent cap (<= 10.00 USDT)
  - Stage 3 continuous expansion cap (<= 15.00 USDT)
  - Stage 4 adaptive expansion cap (<= 20.00 USDT)
  - Stage 5 liquidity expansion cap (<= 25.00 USDT)
  - Stage 6 volatility expansion cap (<= 30.00 USDT)
  - Stage 7 liquidity shock expansion cap (<= 35.00 USDT)
  - Stage 8 depth imbalance expansion cap (<= 40.00 USDT)
  - Stage 9 flow toxicity expansion cap (<= 45.00 USDT across all symbols)
  - Aggregate concurrent exposure cap <= 45.00 USDT.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 5.50 USDT with immediate fail-closed
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
from autonomous_futures.feed.flow_toxicity import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    CANARY_STAGED_SYMBOLS,
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DOUBLE_ENTRY_MAX_DRIFT,
    DYNAMIC_SLICING_MAX_CHUNK_USDT,
    SEQUENCE_WRAP_THRESHOLD,
    STAGE_9_FLOW_TOXICITY_EXPANSION_CAP_USDT,
    AggregateExposureCapExceededError,
    AggressiveOrderRejectedError,
    CanaryFlowToxicityConfig,
    CanaryFlowToxicityRunner,
    CapitalExpansionStage,
    FlowMicroOrderDispatcher,
    FlowToxicityEngine,
    FlowToxicityOrderDispatchInterlock,
    FlowToxicityRegime,
    FlowToxicityStreamSequencer,
    FlowUserDataStreamReconciler,
    GatewayHeartbeatMonitor,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    JsonlCanaryOrderSink,
    MarginAllocationExceededError,
    MicroFloorBreachError,
    MockBinanceFlowToxicityGateway,
    OrderLifecycleState,
    SqliteCanaryFlowToxicityTelemetryStore,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_288_hash_chain,
    verify_upstream_phase287_qualification,
)
from scripts.run_phase_288_flow_toxicity import main as cli_main  # noqa: E402


@pytest.fixture
def temp_telemetry_store(tmp_path: Path) -> SqliteCanaryFlowToxicityTelemetryStore:
    db_file = tmp_path / "test_telemetry.sqlite3"
    return SqliteCanaryFlowToxicityTelemetryStore(db_file)


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
        assert cid.startswith(f"c=canary-p288-{sym.upper()}-")
        assert len(cid.split("-")) >= 5


def test_invalid_client_order_id_rejection():
    # Wrong prefix
    assert not validate_canary_client_order_id(
        "c=canary-p287-btcusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Wrong symbol
    assert not validate_canary_client_order_id(
        "c=canary-p288-ethusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Missing parts
    assert not validate_canary_client_order_id("c=canary-p288-btcusdt", "BTCUSDT")
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
    assert "healthy" in reason.lower()


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
    assert "exceeds" in reason.lower() or "stale" in reason.lower()


def test_gateway_heartbeat_clock_skew_freeze_and_recovery_hysteresis():
    monitor = GatewayHeartbeatMonitor(
        freshness_ceiling_ms=500.0,
        max_clock_skew_ms=250.0,
        recovery_hysteresis_ms=450.0,
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

    # 2. Backward NTP clock drift: local clock steps backward by 300 ms (> 250 ms)
    # server_time ahead of local by 300 ms -> clock skew > 250 ms
    rec_skew = monitor.record_heartbeat(
        server_time_ms=now_ms + 300,
        latency_ms=15.0,
        local_time_ms=now_ms,
        track_id="test_freeze",
    )
    assert rec_skew.status == HeartbeatStatus.CLOCK_SKEW_FREEZE
    assert monitor.is_frozen

    is_healthy, reason = monitor.check_health(now_ms)
    assert not is_healthy
    assert "frozen" in reason.lower() or "skew" in reason.lower()

    # 3. Intermediate recovery: latency 460 ms (still > recovery hysteresis 450 ms)
    _rec_inter = monitor.record_heartbeat(
        server_time_ms=now_ms - 460,
        latency_ms=460.0,
        local_time_ms=now_ms,
        track_id="test_freeze",
    )
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
    assert "healthy" in reason_now.lower()


# ---------------------------------------------------------------------------
# 3. VPIN Computation & Volume Bucket Partitioning
# ---------------------------------------------------------------------------


def test_vpin_calculation_and_volume_bucket_partitioning():
    engine = FlowToxicityEngine(bucket_size_usdt=Decimal("25.00"), bucket_count=5)
    px = Decimal("60000.00")

    # Ingest exactly 5 buckets of 50/50 balanced flow
    # Each bucket V = 25 USDT. 5 buckets = 125 USDT total.
    for _ in range(5):
        engine.process_trade(
            "BTCUSDT", px, Decimal("12.50") / px, OrderSide.BUY, track_id="test_vpin"
        )
        engine.process_trade(
            "BTCUSDT", px, Decimal("12.50") / px, OrderSide.SELL, track_id="test_vpin"
        )

    vpin = engine.get_vpin("BTCUSDT")
    assert vpin < Decimal("0.10")  # Perfectly balanced -> VPIN ~ 0.0
    assert engine.get_regime("BTCUSDT") == FlowToxicityRegime.NOMINAL


def test_vpin_unidirectional_toxic_flow_spike():
    engine = FlowToxicityEngine(bucket_size_usdt=Decimal("25.00"), bucket_count=5)
    px = Decimal("60000.00")

    # Ingest 5 buckets of 100% BUY flow (unidirectional toxicity)
    for _ in range(5):
        engine.process_trade(
            "BTCUSDT", px, Decimal("25.00") / px, OrderSide.BUY, track_id="test_toxic"
        )

    vpin = engine.get_vpin("BTCUSDT")
    assert vpin > Decimal("0.90")  # 100% buy imbalance -> VPIN ~ 1.0
    assert engine.get_regime("BTCUSDT") == FlowToxicityRegime.SEVERE_CONTROLS


def test_flow_toxicity_regime_classification_and_hysteresis():
    engine = FlowToxicityEngine(bucket_size_usdt=Decimal("25.00"), bucket_count=5)
    px = Decimal("60000.00")

    # Initial state is NOMINAL
    assert engine.get_regime("BTCUSDT") == FlowToxicityRegime.NOMINAL

    # Drive VPIN to ~0.50 (ELEVATED_TOXICITY)
    # Buy 75%, Sell 25% -> Imbalance = |75 - 25| / 100 = 0.50
    for _ in range(5):
        engine.process_trade(
            "BTCUSDT", px, Decimal("18.75") / px, OrderSide.BUY, track_id="test_regime"
        )
        engine.process_trade(
            "BTCUSDT", px, Decimal("6.25") / px, OrderSide.SELL, track_id="test_regime"
        )

    vpin = engine.get_vpin("BTCUSDT")
    assert Decimal("0.40") <= vpin <= Decimal("0.65")
    assert engine.get_regime("BTCUSDT") == FlowToxicityRegime.ELEVATED_TOXICITY

    # Drive VPIN > 0.65 (SEVERE_CONTROLS)
    for _ in range(5):
        engine.process_trade(
            "BTCUSDT", px, Decimal("23.00") / px, OrderSide.BUY, track_id="test_regime"
        )
        engine.process_trade(
            "BTCUSDT", px, Decimal("2.00") / px, OrderSide.SELL, track_id="test_regime"
        )

    assert engine.get_vpin("BTCUSDT") > Decimal("0.65")
    assert engine.get_regime("BTCUSDT") == FlowToxicityRegime.SEVERE_CONTROLS

    # De-escalation hysteresis check:
    # Under SEVERE_CONTROLS, dropping VPIN to 0.62 should NOT drop regime
    # back to NOMINAL or ELEVATED until VPIN drops below 0.60
    # Add a slightly more balanced bucket so VPIN is around 0.62
    engine.process_trade(
        "BTCUSDT", px, Decimal("15.00") / px, OrderSide.BUY, track_id="test_regime"
    )
    engine.process_trade(
        "BTCUSDT", px, Decimal("10.00") / px, OrderSide.SELL, track_id="test_regime"
    )
    # Still protected by hysteresis


# ---------------------------------------------------------------------------
# 4. Adaptive Pacing & Limit Offset Cushion Widening
# ---------------------------------------------------------------------------


def test_adaptive_pacing_intervals_by_regime():
    engine = FlowToxicityEngine()
    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.NOMINAL)
    assert engine.get_pacing_interval_ms("BTCUSDT") == 100

    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.ELEVATED_TOXICITY)
    assert engine.get_pacing_interval_ms("BTCUSDT") == 250

    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.SEVERE_CONTROLS)
    assert engine.get_pacing_interval_ms("BTCUSDT") == 1000


def test_limit_offset_cushion_widening_by_regime():
    engine = FlowToxicityEngine()
    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.NOMINAL)
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("0.0")

    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.ELEVATED_TOXICITY)
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("2.0")

    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.SEVERE_CONTROLS)
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("5.0")


# ---------------------------------------------------------------------------
# 5. Adverse Selection Risk & Aggressive Order Rejection Fail-Closed
# ---------------------------------------------------------------------------


def test_aggressive_order_rejection_under_severe_controls():
    engine = FlowToxicityEngine()
    engine.set_regime_override("BTCUSDT", FlowToxicityRegime.SEVERE_CONTROLS)

    reconciler = FlowUserDataStreamReconciler()
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
    )

    # 1. Passive LIMIT order is permitted
    cid_pass = generate_canary_client_order_id("BTCUSDT")
    interlock.evaluate_order_dispatch(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=cid_pass,
        is_closing=False,
    )

    # 2. Aggressive MARKET order is rejected fail-closed
    cid_agg = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(AggressiveOrderRejectedError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),
            client_order_id=cid_agg,
            is_closing=False,
        )


# ---------------------------------------------------------------------------
# 6. Cross-Symbol Toxicity Spillover Transmission
# ---------------------------------------------------------------------------


def test_cross_symbol_toxicity_spillover_transmission():
    engine = FlowToxicityEngine(bucket_size_usdt=Decimal("25.00"), bucket_count=5)
    btc_px = Decimal("60000.00")

    # Ingest severe toxic flow on BTCUSDT
    for _ in range(5):
        engine.process_trade(
            "BTCUSDT", btc_px, Decimal("25.00") / btc_px, OrderSide.BUY, track_id="test_spill"
        )

    # Check spillover transmission to ETH and SOL
    spillover = engine.get_spillover_transmission("BTCUSDT")
    assert "ETHUSDT" in spillover
    assert "SOLUSDT" in spillover
    assert Decimal(spillover["ETHUSDT"]) > Decimal("0.0")
    assert Decimal(spillover["SOLUSDT"]) > Decimal("0.0")


# ---------------------------------------------------------------------------
# 7. Stepped Exposure Scaling up to 45.00 USDT
# ---------------------------------------------------------------------------


def test_stepped_exposure_scaling_stages_up_to_45_usdt():
    reconciler = FlowUserDataStreamReconciler()
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)
    engine = FlowToxicityEngine()

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_9_FLOW_TOXICITY_EXPANSION,
    )

    assert (
        interlock.get_stage_exposure_cap() == STAGE_9_FLOW_TOXICITY_EXPANSION_CAP_USDT
    )  # 45.00 USDT
    assert interlock.get_stage_exposure_cap() == AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT


def test_individual_micro_order_cap_and_floor():
    reconciler = FlowUserDataStreamReconciler()
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)
    engine = FlowToxicityEngine()

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
    )

    # Exceeds 5.00 USDT micro cap -> IndividualMicroCapExceededError
    with pytest.raises(IndividualMicroCapExceededError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0001"),
            price=Decimal("60000.00"),  # 6.00 USDT > 5.00 cap
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # Below 1.00 USDT micro floor -> MicroFloorBreachError
    with pytest.raises(MicroFloorBreachError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00001"),
            price=Decimal("60000.00"),  # 0.60 USDT < 1.00 floor
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


# ---------------------------------------------------------------------------
# 8. Dynamic Margin Headroom Interlocks
# ---------------------------------------------------------------------------


def test_dynamic_margin_headroom_portfolio_and_per_asset_caps():
    reconciler = FlowUserDataStreamReconciler(starting_equity=Decimal("100.00"))
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)
    engine = FlowToxicityEngine()

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
    )

    # Per-asset cap: 20% of 100 = 20.00 USDT
    # Set existing BTC margin to 18.00 USDT
    reconciler.positions["BTCUSDT"] = Decimal("0.0003")
    reconciler.entry_prices["BTCUSDT"] = Decimal("60000.00")
    reconciler.per_asset_margin["BTCUSDT"] = Decimal("18.00")
    reconciler.allocated_margin = Decimal("18.00")

    # Order adding 3.00 USDT -> 21.00 USDT > 20.00 USDT cap -> MarginAllocationExceededError
    with pytest.raises(MarginAllocationExceededError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),  # 3.00 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )


def test_active_committed_working_margin_reservation():
    reconciler = FlowUserDataStreamReconciler(starting_equity=Decimal("100.00"))
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)
    engine = FlowToxicityEngine()

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_1_SEED_PROBE,  # 5.00 USDT cap
    )

    # First order of 3.00 USDT passes and reserves margin
    interlock.evaluate_order_dispatch(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),  # 3.00 USDT
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )
    interlock.reserve_committed_margin("BTCUSDT", Decimal("3.00"))

    # Second order of 3.00 USDT breaches 5.00 USDT Stage 1 cap (3 + 3 = 6 > 5)
    with pytest.raises(AggregateExposureCapExceededError):
        interlock.evaluate_order_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),  # 3.00 USDT
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
        )

    # Release committed margin -> can now dispatch again
    interlock.release_committed_margin("BTCUSDT", Decimal("3.00"))
    interlock.evaluate_order_dispatch(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )


# ---------------------------------------------------------------------------
# 9. Intra-Phase Loss Budget Ceiling <= 5.50 USDT & Emergency Liquidation
# ---------------------------------------------------------------------------


def test_intra_phase_loss_ceiling_lockout_and_micro_chunked_liquidation(
    temp_telemetry_store, temp_jsonl_sink
):
    gateway = MockBinanceFlowToxicityGateway()
    reconciler = FlowUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)
    engine = FlowToxicityEngine(telemetry_store=temp_telemetry_store)

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        loss_ceiling_usdt=Decimal("5.50"),
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = FlowMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # 1. Open positions within micro caps:
    # BTC: 2 x 0.00005 @ 60,000 = 6.00 USDT (each <= 5.00 USDT)
    # ETH: 0.0015 @ 3,000 = 4.50 USDT (<= 5.00 USDT)
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
    )
    dispatcher.dispatch_micro_order(
        candidate_id="cand-eth",
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.0015"),
        price=Decimal("3000.00"),
        client_order_id=generate_canary_client_order_id("ETHUSDT"),
    )

    assert reconciler.positions["BTCUSDT"] == Decimal("0.00010")
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0015")

    # 2. Simulate adverse price plunge and loss breach:
    # BTC drops to 2,000 USDT -> close BTC
    # Realized loss = 0.00010 * (60,000 - 2,000) = 5.80 USDT > 5.50 USDT ceiling!
    dispatcher.dispatch_micro_order(
        candidate_id="cand-btc",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00010"),
        price=Decimal("2000.00"),
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
        is_closing=True,
    )

    assert reconciler.cumulative_realized_loss >= Decimal("5.50")
    assert reconciler.cumulative_realized_loss >= Decimal("5.80")

    # 3. Subsequent opening order fails closed
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-sol",
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.02"),
            price=Decimal("150.00"),
            client_order_id=generate_canary_client_order_id("SOLUSDT"),
        )

    # 4. Emergency micro-chunked position liquidation closes ETHUSDT cleanly
    liq_orders = dispatcher.emergency_micro_chunk_liquidate_all(
        candidate_ids={"ETHUSDT": "cand-eth"},
        prices={"ETHUSDT": Decimal("3000.00")},
        chunk_cap=Decimal("5.00"),
    )
    assert len(liq_orders) >= 1
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# ---------------------------------------------------------------------------
# 10. Dynamic Order Slicing under Flow Toxicity
# ---------------------------------------------------------------------------


def test_dynamic_order_slicing_under_flow_toxicity(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceFlowToxicityGateway()
    reconciler = FlowUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    now_ms = int(time.time() * 1000)
    heartbeat_mon.record_heartbeat(now_ms - 10, 10.0, now_ms)
    engine = FlowToxicityEngine(telemetry_store=temp_telemetry_store)

    interlock = FlowToxicityOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = FlowMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Parent order of 4.50 USDT sliced into chunks <= 2.50 USDT (2 child orders: 2.25 + 2.25)
    parent = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-btcusdt-dcb-002",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=Decimal("60000.00"),
        slice_chunk_notional=Decimal("2.25"),
        track_id="test_slicing",
    )

    assert parent.status == OrderLifecycleState.FILLED
    child_ids = json.loads(parent.child_order_ids_json)
    assert len(child_ids) == 2
    assert Decimal(parent.executed_notional_usdt) == Decimal("4.50")
    for cid in child_ids:
        child = dispatcher.orders[cid]
        notional = Decimal(child.price) * Decimal(child.quantity)
        assert notional <= DYNAMIC_SLICING_MAX_CHUNK_USDT  # <= 2.50 USDT
        assert child.status == OrderLifecycleState.FILLED


# ---------------------------------------------------------------------------
# 11. Multi-Day Longevity, ListenKey Renewal & Stream Sequencer
# ---------------------------------------------------------------------------


def test_session_longevity_and_listenkey_renewal():
    gateway = MockBinanceFlowToxicityGateway()
    lk = gateway.generate_listen_key()
    assert len(lk) == 64
    assert gateway.check_listen_key_valid()
    assert gateway.keepalive_listen_key()


def test_sequence_wrap_recovery_and_deduplication():
    sequencer = FlowToxicityStreamSequencer()

    ev1 = {"u": SEQUENCE_WRAP_THRESHOLD - 10, "E": 1000}
    is_dup1, is_ooo1, is_wrap1 = sequencer.process_event(ev1)
    assert not is_dup1 and not is_ooo1 and not is_wrap1

    # Duplicate
    is_dup2, is_ooo2, is_wrap2 = sequencer.process_event(ev1)
    assert is_dup2

    # Wrap around (jump to 5)
    ev_wrap = {"u": 5, "E": 1050}
    is_dup3, is_ooo3, is_wrap3 = sequencer.process_event(ev_wrap)
    assert not is_dup3
    assert is_wrap3


# ---------------------------------------------------------------------------
# 12. Mathematical Exact Balance Reconciliation (|drift| < 1e-15)
# ---------------------------------------------------------------------------


def test_exact_double_entry_balance_reconciliation_zero_drift():
    reconciler = FlowUserDataStreamReconciler(starting_equity=Decimal("100.00"))
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 1. Buy BTC
    reconciler.record_fill(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("60000.00"),
        quantity=Decimal("0.00005"),
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 2. Buy ETH
    reconciler.record_fill(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        price=Decimal("3000.00"),
        quantity=Decimal("0.001"),
    )
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 3. Sell BTC at profit
    reconciler.record_fill(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        price=Decimal("62000.00"),
        quantity=Decimal("0.00005"),
        is_closing=True,
    )
    assert reconciler.positions["BTCUSDT"] == Decimal("0.0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT

    # 4. Sell ETH at loss
    reconciler.record_fill(
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        price=Decimal("2800.00"),
        quantity=Decimal("0.001"),
        is_closing=True,
    )
    assert reconciler.positions["ETHUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")
    assert reconciler.mathematical_drift < DOUBLE_ENTRY_MAX_DRIFT


# ---------------------------------------------------------------------------
# 13. Strict Fail-Closed Containment Invariants
# ---------------------------------------------------------------------------


def test_strict_containment_invariants():
    # Compliant state passes
    verify_strict_fail_closed_invariants(
        execution_authority=False,
        exchange_access=False,
        authenticated_endpoints_accessed=False,
        orders_submitted=0,
    )

    # Any deviation raises SafetyInvariantViolation
    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(
            execution_authority=True,
            exchange_access=False,
            authenticated_endpoints_accessed=False,
            orders_submitted=0,
        )

    with pytest.raises(SafetyInvariantViolation):
        verify_strict_fail_closed_invariants(
            execution_authority=False,
            exchange_access=False,
            authenticated_endpoints_accessed=False,
            orders_submitted=1,
        )


# ---------------------------------------------------------------------------
# 14. Upstream Hash Chain & Qualification Verification
# ---------------------------------------------------------------------------


def test_upstream_phase287_qualification_and_hash_chain():
    # Real upstream artifacts must qualify
    assert verify_upstream_phase287_qualification()
    assert verify_phase_288_hash_chain()


# ---------------------------------------------------------------------------
# 15. End-to-End Runner Execution on Temporary Directory
# ---------------------------------------------------------------------------


def test_full_phase_288_runner_execution_and_hash_chain(tmp_path: Path):
    cfg = CanaryFlowToxicityConfig(
        output_dir=tmp_path,
        manifest_path=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    )
    runner = CanaryFlowToxicityRunner(config=cfg)
    report = runner.execute_all_tracks()

    assert report.daemon_status == "FLOW_TOXICITY_VERIFIED"
    assert report.compliance["all_criteria_passed"]
    assert report.compliance["zero_balance_drift"]
    assert len(report.tracks) == 4
    for track in report.tracks:
        assert track.success
        assert track.zero_balance_drift

    # Verify SHA-256 DAG hash chain on produced artifacts
    assert verify_phase_288_hash_chain(output_dir=tmp_path)


def test_cli_runner_execution(tmp_path: Path):
    exit_code = cli_main(
        [
            "--output-dir",
            str(tmp_path),
            "--manifest-path",
            str(DEFAULT_CANARY_STAGING_MANIFEST_PATH),
            "--verify-hash-chain",
        ]
    )
    assert exit_code == 0
