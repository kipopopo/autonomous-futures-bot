"""Unit tests for Phase 291: Canary Cross-Asset Hawkes Process Jump Intensity Runner.

Validates:
- Upstream verification & SHA-256 Merkle DAG hash chain ingress (Phase 290 back to 276).
- Dual-confirmation client order tag format (c=canary-p291-{sym}-{ts}-{uuid}).
- Gateway heartbeat freshness (age <= 500 ms), backward NTP clock drift (> 250 ms triggers
  HEARTBEAT_FREEZE with recovery hysteresis <= 450 ms).
- Multivariate Mutually Exciting Hawkes Process Engine:
  - Jump intensity lambda_i(t) = mu_i + sum_j sum_k alpha_ij * e^(-beta_ij * (t - t_jk)).
  - Branching ratio matrix Gamma_Hawkes = [alpha_ij / beta_ij] in R^(3x3).
  - Rolling spectral radius rho(Gamma_Hawkes) calculation and cascade regimes:
    - NOMINAL (rho <= 0.50)
    - ELEVATED_INTENSITY (0.50 < rho <= 0.85)
    - SEVERE_HAWKES_CONTROLS (rho > 0.85)
    - SUPERCRITICAL_CASCADE (rho >= 1.00)
  - Anti-flapping de-escalation hysteresis thresholds (0.45 and 0.80).
  - Execution pacing interval lengthening (100 ms, 250 ms, 1000 ms).
  - Limit offset cushion widening (+0 bps, +2 bps, +5 bps).
  - Dynamic TWAP child slice downscaling (2.50 USDT down to 1.25 USDT under rho >= 0.85).
  - Aggressive market order rejection fail-closed under severe hawkes controls.
  - Cross-symbol jump contagion & spillover (primary BTC/ETH to satellite SOL).
- Stepped concurrent exposure scaling across stages:
  - Stages 1 to 12 up to <= 60.00 USDT aggregate concurrent active exposure across all symbols.
  - Individual micro child order cap <= 5.00 USDT with 1.00 USDT floor.
  - Sequential TWAP slicing <= 2.50 USDT child slices.
- Dynamic margin headroom interlock:
  - Active portfolio margin allocation <= 60.00%
  - Per-asset margin allocation <= 20.00%
  - Cash reserve buffer >= 40.00%
  - Active committed working margin reservation on unfilled orders.
- Intra-phase cumulative loss budget ceiling <= 7.00 USDT with immediate fail-closed
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
from autonomous_futures.feed.hawkes_cascades import (  # noqa: E402
    AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT,
    CANARY_STAGED_SYMBOLS,
    CRITICAL_STABILITY_BRANCHING_RATIO,
    DOUBLE_ENTRY_MAX_DRIFT,
    DYNAMIC_SLICING_DOWNSCALED_CHUNK_USDT,
    DYNAMIC_SLICING_MAX_CHUNK_USDT,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    ORDERED_EXPANSION_STAGES,
    STAGE_12_HAWKES_CASCADE_EXPANSION_CAP_USDT,
    SUPERCRITICAL_BRANCHING_RATIO,
    AggressiveOrderRejectedError,
    CanaryHawkesCascadeError,
    CapitalExpansionStage,
    CascadeEndogenousState,
    CircuitBreakerState,
    EndogenousCascadeThrottledError,
    GatewayHeartbeatMonitor,
    GatewayHeartbeatStaleError,
    HawkesCascadeAutonomousDaemon,
    HawkesCascadeEngine,
    HawkesCascadeMicroOrderDispatcher,
    HawkesCascadeOrderDispatchInterlock,
    HawkesCascadeStreamSequencer,
    HawkesCascadeUserDataStreamReconciler,
    HawkesRegime,
    HeartbeatStatus,
    IndividualMicroCapExceededError,
    IntraPhaseLossCeilingExceededError,
    JsonlCanaryOrderSink,
    MarginAllocationExceededError,
    MicroNotionalFloorViolationError,
    MockBinanceHawkesCascadeGateway,
    OrderLifecycleState,
    SqliteCanaryHawkesTelemetryStore,
    generate_canary_client_order_id,
    validate_canary_client_order_id,
    verify_phase_291_hash_chain,
    verify_upstream_phase290_qualification,
)
from scripts.run_phase_291_hawkes_cascades import main as cli_main  # noqa: E402


@pytest.fixture
def temp_telemetry_store(tmp_path: Path) -> SqliteCanaryHawkesTelemetryStore:
    db_file = tmp_path / "test_hawkes_telemetry.sqlite3"
    return SqliteCanaryHawkesTelemetryStore(db_file)


@pytest.fixture
def temp_jsonl_sink(tmp_path: Path) -> JsonlCanaryOrderSink:
    jsonl_file = tmp_path / "test_hawkes_orders.jsonl"
    return JsonlCanaryOrderSink(jsonl_file)


# ---------------------------------------------------------------------------
# 1. Dual-Confirmation Client Order ID Tag Validation
# ---------------------------------------------------------------------------


def test_valid_client_order_id_generation_and_validation():
    for sym in CANARY_STAGED_SYMBOLS:
        cid = generate_canary_client_order_id(sym)
        assert validate_canary_client_order_id(cid, sym)
        assert cid.startswith(f"c=canary-p291-{sym.lower()}-")
        assert len(cid.split("-")) >= 5


def test_invalid_client_order_id_rejection():
    # Wrong prefix (prior phase)
    assert not validate_canary_client_order_id(
        "c=canary-p290-btcusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Wrong symbol
    assert not validate_canary_client_order_id(
        "c=canary-p291-ethusdt-1700000000-abcdef123456", "BTCUSDT"
    )
    # Missing parts
    assert not validate_canary_client_order_id("c=canary-p291-btcusdt", "BTCUSDT")
    # Empty string
    assert not validate_canary_client_order_id("", "BTCUSDT")
    # Random characters
    assert not validate_canary_client_order_id("invalid-tag-format", "BTCUSDT")


def test_client_order_id_extended_uuid_formats():
    """Verify client order ID validation accepts 8-32 hex tags and standard RFC-4122 UUIDs."""
    now_ms = int(time.time() * 1000)
    # Standard 12-char hex
    assert validate_canary_client_order_id(
        f"c=canary-p291-btcusdt-{now_ms}-a1b2c3d4e5f6", "BTCUSDT"
    )
    # 8-char hex
    assert validate_canary_client_order_id(f"c=canary-p291-ethusdt-{now_ms}-12345678", "ETHUSDT")
    # 32-char hex (full uuid4().hex)
    hex32 = uuid4().hex
    assert validate_canary_client_order_id(f"c=canary-p291-solusdt-{now_ms}-{hex32}", "SOLUSDT")
    # Standard RFC-4122 36-char hyphenated UUID
    uuid_hyphenated = str(uuid4())
    assert validate_canary_client_order_id(
        f"c=canary-p291-btcusdt-{now_ms}-{uuid_hyphenated}", "BTCUSDT"
    )

    # Reject symbol mismatch
    assert not validate_canary_client_order_id(f"c=canary-p291-ethusdt-{now_ms}-{hex32}", "BTCUSDT")
    # Reject invalid prefix or malformed structure
    assert not validate_canary_client_order_id(f"c=prod-p291-btcusdt-{now_ms}-12345678", "BTCUSDT")
    assert not validate_canary_client_order_id("c=canary-p291-btcusdt", "BTCUSDT")
    assert not validate_canary_client_order_id("", "BTCUSDT")


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

    # Age exceeding ceiling
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
        clock_skew_hysteresis_ms=200.0,
    )
    now_ms = int(time.time() * 1000)

    # Trigger backward clock drift > 250 ms -> DRIFT_FREEZE
    rec_skew = monitor.record_heartbeat(
        server_time_ms=now_ms - 300,  # 300ms drift
        latency_ms=30.0,
        local_time_ms=now_ms,
    )
    assert not rec_skew.is_healthy
    assert rec_skew.status in (HeartbeatStatus.DRIFT_FREEZE, HeartbeatStatus.CLOCK_SKEW_FREEZE)
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


def test_gateway_heartbeat_uninitialized_fail_closed(temp_telemetry_store, temp_jsonl_sink):
    """Verify heartbeat monitor fails closed when 0 heartbeats recorded."""
    monitor = GatewayHeartbeatMonitor()
    ok, reason = monitor.check_health()
    assert not ok
    assert "no gateway heartbeat" in reason.lower()

    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=monitor,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
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


# ---------------------------------------------------------------------------
# 3. Hawkes Process Jump Intensity & Cascades Governance Engine
# ---------------------------------------------------------------------------


def test_hawkes_spectral_radius_nominal():
    """Verify default nominal spectral radius of the 3x3 branching matrix is < 0.50."""
    engine = HawkesCascadeEngine()
    rho = engine.get_spectral_radius()
    assert rho < Decimal("0.50")
    for sym in CANARY_STAGED_SYMBOLS:
        assert engine.get_regime(sym) == HawkesRegime.NOMINAL
        assert engine.get_cascade_state(sym) == CascadeEndogenousState.NORMAL


def test_hawkes_event_arrival_intensity_update():
    """Verify jump intensity increases on event arrival and decays over lookback."""
    engine = HawkesCascadeEngine()
    t0 = 1000.0

    # Initial baseline
    lambda_sol_0 = engine.get_jump_intensity("SOLUSDT")
    assert lambda_sol_0 == Decimal("0.15")

    # Ingest event on BTC -> should cross-excite SOL (alpha_sol_btc = 0.18)
    _ = engine.record_event_arrival("BTCUSDT", timestamp_sec=t0 + 0.1)
    lambda_sol_1 = engine.get_jump_intensity("SOLUSDT")
    assert lambda_sol_1 > lambda_sol_0

    # Ingest event on SOL -> self-excite SOL (alpha_sol_sol = 0.35)
    engine.record_event_arrival("SOLUSDT", timestamp_sec=t0 + 0.2)
    lambda_sol_2 = engine.get_jump_intensity("SOLUSDT")
    assert lambda_sol_2 > lambda_sol_1


def test_hawkes_branching_ratio_and_regimes_hysteresis():
    """Verify regime transitions (NOMINAL -> ELEVATED -> SEVERE -> SUPERCRITICAL) and hysteresis."""
    engine = HawkesCascadeEngine()
    sym = "SOLUSDT"

    assert engine.get_regime(sym) == HawkesRegime.NOMINAL

    # Inject jump burst on SOL: alpha_self=0.80, alpha_btc=0.30, alpha_eth=0.25 -> rho >= 0.85
    snap = engine.record_jump_burst_shock(
        symbol=sym,
        alpha_self=0.80,
        alpha_cross_btc=0.30,
        alpha_cross_eth=0.25,
    )
    assert Decimal(snap.spectral_radius) >= CRITICAL_STABILITY_BRANCHING_RATIO
    assert engine.get_regime(sym) == HawkesRegime.SEVERE_HAWKES_CONTROLS
    assert engine.get_cascade_state(sym) == CascadeEndogenousState.SEVERE_PREDATORY_FRONT_RUNNING

    # De-escalation hysteresis check:
    # If rho drops to 0.82 (which is > 0.80 elevated recovery threshold), it must remain SEVERE
    with engine._global_lock:
        engine._alpha[(sym, sym)] = Decimal("0.65")
        engine._alpha[(sym, "BTCUSDT")] = Decimal("0.20")
        engine._alpha[(sym, "ETHUSDT")] = Decimal("0.15")
        engine._spectral_radius = engine._compute_spectral_radius()
    rho_mid = engine.get_spectral_radius()
    # If rho_mid is between 0.80 and 0.85, verify hysteresis holds SEVERE
    if Decimal("0.80") < rho_mid < Decimal("0.85"):
        # Trigger an event arrival to update regimes
        engine.record_event_arrival(sym, timestamp_sec=2000.0)
        assert engine.get_regime(sym) == HawkesRegime.SEVERE_HAWKES_CONTROLS

    # When rho drops below 0.80, it de-escalates to ELEVATED_INTENSITY
    with engine._global_lock:
        engine._alpha[(sym, sym)] = Decimal("0.50")
        engine._alpha[(sym, "BTCUSDT")] = Decimal("0.10")
        engine._alpha[(sym, "ETHUSDT")] = Decimal("0.10")
        engine._spectral_radius = engine._compute_spectral_radius()
    engine.record_event_arrival(sym, timestamp_sec=2010.0)
    assert engine.get_regime(sym) == HawkesRegime.ELEVATED_INTENSITY

    # When rho drops below 0.45 (nominal recovery), it de-escalates to NOMINAL
    with engine._global_lock:
        engine._alpha[(sym, sym)] = Decimal("0.25")
        engine._alpha[(sym, "BTCUSDT")] = Decimal("0.05")
        engine._alpha[(sym, "ETHUSDT")] = Decimal("0.05")
        engine._spectral_radius = engine._compute_spectral_radius()
    engine.record_event_arrival(sym, timestamp_sec=2020.0)
    assert engine.get_regime(sym) == HawkesRegime.NOMINAL


def test_hawkes_supercritical_collapse():
    """Verify supercritical cascade runaway (rho >= 1.0) is detected and flagged."""
    engine = HawkesCascadeEngine()
    snap = engine.record_supercritical_collapse(symbol="SOLUSDT")
    assert Decimal(snap.spectral_radius) >= SUPERCRITICAL_BRANCHING_RATIO
    assert engine.get_regime("SOLUSDT") == HawkesRegime.SUPERCRITICAL_CASCADE
    assert (
        engine.get_cascade_state("SOLUSDT") == CascadeEndogenousState.SEVERE_PREDATORY_FRONT_RUNNING
    )


def test_execution_pacing_and_limit_cushions_and_downscaling():
    """Verify execution pacing, passive limit cushions, and TWAP child downscaling."""
    engine = HawkesCascadeEngine()
    sym = "BTCUSDT"

    # Nominal
    assert engine.get_pacing_interval_ms(sym) == 100.0
    assert engine.get_limit_offset_cushion_bps(sym) == Decimal("0.0")
    assert engine.get_slice_chunk_cap(sym) == DYNAMIC_SLICING_MAX_CHUNK_USDT  # 2.50 USDT

    # Elevated
    with engine._get_symbol_lock(sym):
        engine._regimes[sym] = HawkesRegime.ELEVATED_INTENSITY
    assert engine.get_pacing_interval_ms(sym) == 250.0
    assert engine.get_limit_offset_cushion_bps(sym) == Decimal("2.0")
    assert engine.get_slice_chunk_cap(sym) == DYNAMIC_SLICING_MAX_CHUNK_USDT  # 2.50 USDT

    # Severe
    with engine._get_symbol_lock(sym):
        engine._regimes[sym] = HawkesRegime.SEVERE_HAWKES_CONTROLS
    assert engine.get_pacing_interval_ms(sym) == 1000.0
    assert engine.get_limit_offset_cushion_bps(sym) == Decimal("5.0")
    assert engine.get_slice_chunk_cap(sym) == DYNAMIC_SLICING_DOWNSCALED_CHUNK_USDT  # 1.25 USDT


def test_aggressive_order_rejection_fail_closed_under_severe_hawkes():
    """Verify aggressive MARKET orders are rejected fail-closed under severe hawkes regimes."""
    gateway = MockBinanceHawkesCascadeGateway()
    telemetry_store = SqliteCanaryHawkesTelemetryStore(Path(":memory:"))
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=telemetry_store,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Set severe controls on SOLUSDT
    engine.record_jump_burst_shock("SOLUSDT", alpha_self=0.85, alpha_cross_btc=0.35)

    # Passive LIMIT is permitted
    interlock.evaluate_order_pre_dispatch(
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),  # 3.00 USDT
    )

    # Aggressive MARKET is rejected fail-closed
    with pytest.raises(AggressiveOrderRejectedError):
        interlock.evaluate_order_pre_dispatch(
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.02"),
            price=Decimal("150.00"),  # 3.00 USDT
        )

    # Closing order permitted even if MARKET
    interlock.evaluate_order_pre_dispatch(
        symbol="SOLUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.02"),
        price=Decimal("150.00"),
        is_closing=True,
    )


def test_throttled_per_candidate_cap_under_severe_controls():
    """Verify per-candidate exposure cap of 10.00 USDT under active SEVERE_HAWKES_CONTROLS."""
    gateway = MockBinanceHawkesCascadeGateway()
    telemetry_store = SqliteCanaryHawkesTelemetryStore(Path(":memory:"))
    reconciler = HawkesCascadeUserDataStreamReconciler(
        starting_equity=Decimal("100.00"), telemetry_store=telemetry_store
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=telemetry_store,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Set severe controls on SOLUSDT
    engine.record_jump_burst_shock("SOLUSDT", alpha_self=0.85, alpha_cross_btc=0.35)

    # Simulate existing allocated candidate position of 8.00 USDT
    reconciler.positions["SOLUSDT"] = Decimal("0.05333333")  # ~8.00 USDT @ 150.00
    reconciler.allocated_margin = Decimal("8.00")

    # Order adding 3.00 USDT would bring candidate exposure to 11.00 > 10.00 USDT cap -> reject
    with pytest.raises(EndogenousCascadeThrottledError):
        interlock.evaluate_order_pre_dispatch(
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.02"),
            price=Decimal("150.00"),  # 3.00 USDT -> 8 + 3 = 11 > 10
        )


# ---------------------------------------------------------------------------
# 4. Micro Order Sizing, TWAP Slicing & Exposure Ceilings (Stage 12: 60 USDT)
# ---------------------------------------------------------------------------


def test_micro_child_cap_and_floor(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

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
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
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


def test_stage_12_exposure_cap_up_to_60_usdt(temp_telemetry_store):
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    assert interlock.get_stage_exposure_cap() == Decimal("60.00")
    assert STAGE_12_HAWKES_CASCADE_EXPANSION_CAP_USDT == Decimal("60.00")
    assert AGGREGATE_CONCURRENT_EXPOSURE_CAP_USDT == Decimal("60.00")
    assert ORDERED_EXPANSION_STAGES[-1] == CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION


# ---------------------------------------------------------------------------
# 5. Margin Headroom & Committed Working Margin
# ---------------------------------------------------------------------------


def test_dynamic_margin_headroom_limits(temp_telemetry_store):
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(
        starting_equity=Decimal("100.00"),
        telemetry_store=temp_telemetry_store,
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Per-asset cap is 20% of 100 = 20.00 USDT
    # Set existing allocated margin for BTC to 18.00 USDT
    reconciler.allocated_margin = Decimal("18.00")
    reconciler.positions["BTCUSDT"] = Decimal("0.0003")  # 0.0003 * 60,000 = 18.00 USDT

    # Order of 3.00 USDT would bring BTC margin to 21.00 > 20.00 USDT -> reject
    with pytest.raises(MarginAllocationExceededError):
        interlock.evaluate_order_pre_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),  # 3.00 USDT
        )


def test_committed_working_margin_reservation(temp_telemetry_store):
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Reserve working margin on parent order
    cid_parent = "parent-test-123"
    interlock.reserve_parent_order_working_margin(cid_parent, "BTCUSDT", Decimal("4.00"))
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("4.00")

    # Reserve child margin (2.00 USDT)
    interlock.reserve_committed_margin("BTCUSDT", Decimal("2.00"))
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("6.00")

    # Release child margin on fill
    interlock.release_committed_margin("BTCUSDT", Decimal("2.00"))
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("4.00")

    # Release parent order working margin
    interlock.release_parent_order_working_margin(cid_parent, "BTCUSDT")
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("0.0")


# ---------------------------------------------------------------------------
# 6. Intra-Phase Loss Budget Ceiling & Micro-Chunked Liquidation (<= 7.00 USDT)
# ---------------------------------------------------------------------------


def test_intra_phase_loss_lockout_and_liquidation(temp_telemetry_store, temp_jsonl_sink):
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        loss_ceiling_usdt=Decimal("7.00"),
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Simulate cumulative loss exceeding 7.00 USDT
    reconciler.realized_pnl = Decimal("-7.01")

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


def test_emergency_micro_chunk_liquidation(temp_telemetry_store, temp_jsonl_sink):
    """Verify emergency liquidation partitions open positions into slices <= 5.00 USDT."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(
        starting_equity=Decimal("100.00"), telemetry_store=temp_telemetry_store
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Simulate an open position in SOL: 0.08 SOL @ 150.00 = 12.00 USDT
    # Must be liquidated in chunks <= 5.00 USDT (e.g. 5.00 + 5.00 + 2.00 USDT slices)
    reconciler.positions["SOLUSDT"] = Decimal("0.08")
    reconciler.allocated_margin = Decimal("12.00")
    reconciler.cash = Decimal("88.00")

    liq_orders = dispatcher.emergency_micro_chunk_liquidate_all(
        candidate_ids={"SOLUSDT": "cand-sol"},
        prices={"SOLUSDT": Decimal("150.00")},
        chunk_cap=HARD_MICRO_NOTIONAL_CAP_USDT,
    )

    assert len(liq_orders) >= 3
    for ord_rec in liq_orders:
        notional = Decimal(ord_rec.notional_usdt)
        assert notional <= HARD_MICRO_NOTIONAL_CAP_USDT
        assert ord_rec.is_closing
        assert ord_rec.side == OrderSide.SELL

    assert reconciler.positions["SOLUSDT"] == Decimal("0.0")
    assert reconciler.allocated_margin == Decimal("0.0")
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT


# ---------------------------------------------------------------------------
# 7. Stream Sequencer Deduplication & Sequence Wrap
# ---------------------------------------------------------------------------


def test_stream_sequencer_deduplication_and_wrap():
    seq = HawkesCascadeStreamSequencer(wrap_threshold=1_000_000)

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
    reconciler = HawkesCascadeUserDataStreamReconciler(
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


def test_verify_upstream_phase290_qualification():
    assert verify_upstream_phase290_qualification()


def test_verify_phase_291_hash_chain():
    assert verify_phase_291_hash_chain()


def test_cli_runner_verify_only():
    ret = cli_main(["--verify-only"])
    assert ret == 0


def test_cli_runner_single_track(tmp_path: Path):
    out_dir = tmp_path / "p291_test_t1"
    ret = cli_main(["--output-dir", str(out_dir), "--track", "1"])
    assert ret == 0


def test_cli_runner_simulate_loss_breach(tmp_path: Path):
    out_dir = tmp_path / "p291_test_loss"
    ret = cli_main(["--output-dir", str(out_dir), "--track", "3", "--simulate-loss-breach"])
    assert ret == 0


def test_cli_runner_simulate_adverse_drift_failure(tmp_path: Path):
    out_dir = tmp_path / "p291_test_drift"
    ret = cli_main(["--output-dir", str(out_dir), "--track", "1", "--simulate-adverse-drift"])
    assert ret == 1


# ---------------------------------------------------------------------------
# 11. Adversarial Edge Cases & Invariant Hardening (Round 1 Review)
# ---------------------------------------------------------------------------


def test_twap_parent_committed_margin_deduction_near_cap(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that parent TWAP working margin does not double-count against child
    slice reservations, allowing valid orders to execute up to stage cap (60 USDT)."""
    hb = GatewayHeartbeatMonitor()
    hb.record_heartbeat(int(time.time() * 1000), 15.0)
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=hb,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        loss_ceiling_usdt=Decimal("7.00"),
        telemetry_store=temp_telemetry_store,
    )
    gw = MockBinanceHawkesCascadeGateway()
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gw,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Establish initial exposure across BTC & ETH: 54.00 USDT
    # BTC: 30.00 USDT position
    reconciler.positions["BTCUSDT"] = Decimal("0.0005")  # @ 60,000 = 30 USDT
    reconciler.allocated_margin += Decimal("30.00")
    # ETH: 24.00 USDT position
    reconciler.positions["ETHUSDT"] = Decimal("0.008")  # @ 3,000 = 24 USDT
    reconciler.allocated_margin += Decimal("24.00")

    # Current exposure is 54.00 USDT. Headroom to 60.00 USDT is 6.00 USDT.
    # Dispatch a TWAP parent order for 4.50 USDT on SOLUSDT (splits into 2.50 + 2.00 USDT).
    parent_rec = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-solusdt",
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.50"),
        limit_price=Decimal("150.00"),
        track_id="adversarial_review_t1",
    )
    assert parent_rec.status == OrderLifecycleState.FILLED
    assert len(parent_rec.child_order_ids) == 2
    assert Decimal(parent_rec.executed_notional_usdt) == Decimal("4.50")
    # Total committed working margin should be completely released after execution
    assert interlock.get_total_committed_margin() == Decimal("0.0")


def test_closing_order_invariants_and_direction_safety(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that closing orders are strictly validated for direction, position bounds,
    and individual micro cap (<= 5.00 USDT), eliminating bypasses."""
    hb = GatewayHeartbeatMonitor()
    hb.record_heartbeat(int(time.time() * 1000), 15.0)
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=hb,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    gw = MockBinanceHawkesCascadeGateway()
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gw,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Setup open LONG position: 0.0001 BTC @ 60,000 = 6.00 USDT
    reconciler.positions["BTCUSDT"] = Decimal("0.0001")
    reconciler.allocated_margin = Decimal("6.00")

    # 1. Closing LONG with BUY must fail
    with pytest.raises(CanaryHawkesCascadeError, match="Cannot close LONG position with BUY"):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
            is_closing=True,
        )

    # 2. Closing with quantity exceeding open position must fail
    with pytest.raises(CanaryHawkesCascadeError, match="exceeds open position"):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0002"),  # 0.0002 > 0.0001
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
            is_closing=True,
        )

    # 3. Closing order with notional > 5.00 USDT must fail (individual micro cap)
    with pytest.raises(IndividualMicroCapExceededError):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00009"),  # 0.00009 * 60,000 = 5.40 USDT > 5.00 USDT
            price=Decimal("60000.00"),
            client_order_id=generate_canary_client_order_id("BTCUSDT"),
            is_closing=True,
        )

    # 4. Closing order on symbol with NO open position must fail
    with pytest.raises(CanaryHawkesCascadeError, match="No open position exists"):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.001"),
            price=Decimal("3000.00"),
            client_order_id=generate_canary_client_order_id("ETHUSDT"),
            is_closing=True,
        )

    # 5. Valid closing order (0.00005 BTC = 3.00 USDT <= 5.00 USDT) succeeds
    rec = dispatcher.dispatch_micro_order(
        candidate_id="cand-btcusdt",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=generate_canary_client_order_id("BTCUSDT"),
        is_closing=True,
        simulate_fill_immediately=True,
    )
    assert rec.status == OrderLifecycleState.FILLED
    assert reconciler.positions["BTCUSDT"] == Decimal("0.00005")


def test_cumulative_gross_loss_intra_phase_budget(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that cumulative gross realized loss triggers fail-closed lockout
    even if current net realized PnL was offset by earlier gains."""
    hb = GatewayHeartbeatMonitor()
    hb.record_heartbeat(int(time.time() * 1000), 15.0)
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=hb,
        engine=engine,
        loss_ceiling_usdt=Decimal("7.00"),
        telemetry_store=temp_telemetry_store,
    )
    gw = MockBinanceHawkesCascadeGateway()
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gw,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Simulate gross loss reaching ceiling: cumulative_realized_loss = 7.00 USDT
    # But net realized_pnl is 0.00 (e.g. +7.00 followed by -7.00)
    reconciler.cumulative_realized_loss = Decimal("7.00")
    reconciler.realized_pnl = Decimal("0.00")

    # 1. Standalone micro order must be rejected
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
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT

    # 2. TWAP parent dispatch must also be rejected upfront when circuit_state is NORMAL
    interlock.circuit_state = CircuitBreakerState.NORMAL
    with pytest.raises(IntraPhaseLossCeilingExceededError):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("3.00"),
            limit_price=Decimal("3000.00"),
        )
    assert interlock.circuit_state == CircuitBreakerState.INTRA_PHASE_LOSS_LOCKOUT


def test_twap_limit_offset_cushion_applied_to_child_prices(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that passive limit offset cushion (+2 bps / +5 bps) is applied to
    effective child limit prices in TWAP slicing."""
    hb = GatewayHeartbeatMonitor()
    hb.record_heartbeat(int(time.time() * 1000), 15.0)
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=hb,
        engine=engine,
        telemetry_store=temp_telemetry_store,
    )
    gw = MockBinanceHawkesCascadeGateway()
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gw,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    # Transition engine into ELEVATED_INTENSITY regime (2.0 bps cushion)
    engine._regimes["BTCUSDT"] = HawkesRegime.ELEVATED_INTENSITY
    assert engine.get_limit_offset_cushion_bps("BTCUSDT") == Decimal("2.0")

    # Dispatch TWAP BUY parent order at base limit 60,000.00
    # Expected cushioned price: 60000 * (1 - 0.0002) = 59,988.00
    rec = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-btcusdt",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("4.00"),
        limit_price=Decimal("60000.00"),
    )
    assert rec.status == OrderLifecycleState.FILLED
    assert len(rec.child_order_ids) == 2
    for child_id in rec.child_order_ids:
        child_ord = dispatcher.orders[child_id]
        assert Decimal(child_ord.price) == Decimal("59988.00")

    # Transition to SEVERE_HAWKES_CONTROLS regime (5.0 bps cushion)
    engine._regimes["ETHUSDT"] = HawkesRegime.SEVERE_HAWKES_CONTROLS
    # Dispatch TWAP SELL parent order at base limit 3,000.00
    # Expected cushioned price: 3000 * (1 + 0.0005) = 3,001.50
    rec_sell = dispatcher.dispatch_twap_sliced_parent(
        candidate_id="cand-ethusdt",
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        target_notional=Decimal("2.50"),
        limit_price=Decimal("3000.00"),
    )
    assert rec_sell.status == OrderLifecycleState.FILLED
    for child_id in rec_sell.child_order_ids:
        child_ord = dispatcher.orders[child_id]
        assert Decimal(child_ord.price) == Decimal("3001.50")


def test_cross_asset_regime_synchronization_on_jump_burst_shock(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
):
    """Verifies that record_jump_burst_shock on one symbol synchronizes severe cascade
    controls across all staged symbols when systemic spectral radius exceeds critical threshold."""
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)

    # Induce large jump shock on BTCUSDT
    engine.record_jump_burst_shock("BTCUSDT", alpha_self=Decimal("0.90"))

    assert engine.get_spectral_radius() >= engine.critical_threshold
    # All staged symbols must reflect severe controls
    for sym in CANARY_STAGED_SYMBOLS:
        assert engine.get_regime(sym) == HawkesRegime.SEVERE_HAWKES_CONTROLS
        assert engine.get_pacing_interval_ms(sym) == 1000.0
        assert engine.get_limit_offset_cushion_bps(sym) == Decimal("5.0")
        assert engine.get_slice_chunk_cap(sym) == DYNAMIC_SLICING_DOWNSCALED_CHUNK_USDT


def test_zero_beta_guard_in_branching_ratio(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
):
    """Verifies that get_branching_ratio safely returns 0.0000 when beta is zero or negative."""
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    engine._beta[("BTCUSDT", "ETHUSDT")] = Decimal("0.0")
    ratio = engine.get_branching_ratio("BTCUSDT", "ETHUSDT")
    assert ratio == Decimal("0.0000")


def test_negative_and_zero_price_quantity_rejection(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that orders with non-positive price or quantity are rejected fail-closed."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )
    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Test in interlock
    with pytest.raises(CanaryHawkesCascadeError, match="strictly positive"):
        interlock.evaluate_order_pre_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("-0.00005"),
            price=Decimal("-60000.00"),
        )

    with pytest.raises(CanaryHawkesCascadeError, match="strictly positive"):
        interlock.evaluate_order_pre_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.0"),
            price=Decimal("60000.00"),
        )

    with pytest.raises(CanaryHawkesCascadeError, match="strictly positive"):
        interlock.evaluate_order_pre_dispatch(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.00005"),
            price=Decimal("0.0"),
        )

    # Test in dispatcher
    cid = generate_canary_client_order_id("BTCUSDT")
    with pytest.raises(CanaryHawkesCascadeError, match="strictly positive"):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("-0.00005"),
            price=Decimal("-60000.00"),
            client_order_id=cid,
        )


def test_closing_order_without_open_position_rejection(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that closing orders are rejected fail-closed if no open position exists."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )
    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    cid = generate_canary_client_order_id("ETHUSDT")
    with pytest.raises(CanaryHawkesCascadeError, match="No open position exists"):
        dispatcher.dispatch_micro_order(
            candidate_id="cand-ethusdt",
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.001"),
            price=Decimal("3000.00"),
            client_order_id=cid,
            is_closing=True,
        )


def test_order_cancellation_and_lifecycle_transition(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies order cancellation transitions order to CANCELLED, releases margin,
    records lifecycle transition in SQLite, and logs to JSONL sink."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )

    cid = generate_canary_client_order_id("BTCUSDT")
    from autonomous_futures.feed.hawkes_cascades import HawkesCascadeOrderRecord

    ord_rec = HawkesCascadeOrderRecord(
        client_order_id=cid,
        order_id="ord-mock-cancel-1",
        track_id="test_track",
        candidate_id="cand-btcusdt",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price="60000.00",
        quantity="0.00005",
        notional_usdt="3.00",
        status=OrderLifecycleState.NEW,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
    )
    with dispatcher._lock:
        dispatcher.orders[cid] = ord_rec
        dispatcher._order_committed_notionals[cid] = Decimal("3.00")
        interlock.reserve_committed_margin("BTCUSDT", Decimal("3.00"))

    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("3.00")
    assert gateway.cancel_order(cid) is True

    cancelled = dispatcher.cancel_order(cid, track_id="test_track")
    assert cancelled is True
    assert dispatcher.orders[cid].status == OrderLifecycleState.CANCELLED
    assert interlock.get_total_committed_margin("BTCUSDT") == Decimal("0.00")

    # Verify lifecycle transition recorded in SQLite
    row = temp_telemetry_store.conn.execute(
        "SELECT * FROM lifecycle_transitions WHERE client_order_id = ?;", (cid,)
    ).fetchone()
    assert row is not None
    assert row["from_state"] == OrderLifecycleState.NEW.value
    assert row["to_state"] == OrderLifecycleState.CANCELLED.value
    assert row["trigger_reason"] == "ORDER_CANCELLED"

    # Verify JSONL record written
    import json

    lines = [
        json.loads(line)
        for line in temp_jsonl_sink.file_path.read_text().splitlines()
        if line.strip()
    ]
    assert any(
        entry.get("client_order_id") == cid and entry.get("status") == "CANCELLED"
        for entry in lines
    )

    # Verify alias cancel_micro_order exists and returns False for non-existent
    assert dispatcher.cancel_micro_order("non_existent_cid") is False


def test_filled_order_logged_to_jsonl_sink(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that an immediately filled order logs its FILLED state to the JSONL sink."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
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
        candidate_id="cand-btcusdt",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("0.00005"),
        price=Decimal("60000.00"),
        client_order_id=cid,
        track_id="test_fill",
    )
    assert ord_rec.status == OrderLifecycleState.FILLED

    import json

    lines = [
        json.loads(line)
        for line in temp_jsonl_sink.file_path.read_text().splitlines()
        if line.strip()
    ]
    filled_entries = [
        entry
        for entry in lines
        if entry.get("client_order_id") == cid and entry.get("status") == "FILLED"
    ]
    assert len(filled_entries) == 1


def test_per_asset_margin_headroom_with_depressed_price(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
):
    """Verifies per-asset margin calculation uses max(per_asset_margin, abs(pos)*price)
    to prevent headroom under-reporting when limit price is depressed."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(
        starting_equity=Decimal("100.00"), telemetry_store=temp_telemetry_store
    )
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    # Simulate existing SOL position with per_asset_margin = 18.00 USDT (entry @ 150)
    reconciler.positions["SOLUSDT"] = Decimal("0.12")
    reconciler.per_asset_margin["SOLUSDT"] = Decimal("18.00")
    # Max per-asset margin is 20% of 100 = 20.00 USDT.
    # An incoming buy order with notional 3.00 USDT at depressed price 10.00 USDT:
    # If using abs(pos)*price = 0.12 * 10 = 1.20 USDT, cand_margin would appear
    # as 1.20 + 3.00 = 4.20 <= 20 (false pass).
    # With max(per_asset_margin, abs(pos)*price) = max(18.00, 1.20) = 18.00 USDT.
    # 18.00 + 3.00 = 21.00 > 20.00 -> correctly rejects!
    with pytest.raises(MarginAllocationExceededError):
        interlock.evaluate_order_pre_dispatch(
            symbol="SOLUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.30"),
            price=Decimal("10.00"),  # 3.00 USDT
        )


def test_parent_order_partial_fill_telemetry_recording(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies that if a child slice fails mid-TWAP, parent order record is written to SQLite
    with PARTIALLY_FILLED and accurate executed notional and quantity."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )
    hb = gateway.generate_heartbeat()
    heartbeat_mon.record_heartbeat(hb["serverTime"], hb["latencyMs"])

    real_dispatch = dispatcher.dispatch_micro_order
    call_count = 0

    def failing_dispatch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("Synthetic child slice failure")
        return real_dispatch(*args, **kwargs)

    dispatcher.dispatch_micro_order = failing_dispatch  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Synthetic child slice failure"):
        dispatcher.dispatch_twap_sliced_parent(
            candidate_id="cand-btcusdt",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            target_notional=Decimal("4.00"),  # 2 slices of 2.00 USDT
            limit_price=Decimal("60000.00"),
        )

    # Inspect SQLite parent_orders table
    row = temp_telemetry_store.conn.execute(
        "SELECT * FROM parent_orders WHERE symbol = 'BTCUSDT';"
    ).fetchone()
    assert row is not None
    assert row["status"] == OrderLifecycleState.PARTIALLY_FILLED.value
    assert Decimal(row["executed_notional_usdt"]) > Decimal("0.0")
    assert Decimal(row["executed_quantity"]) > Decimal("0.0")


def test_hawkes_intensity_temporal_decay_over_lookback(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
):
    """Verifies that Hawkes jump intensity lambda(t) continuously decays toward
    baseline mu as time passes."""
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    t0 = 1000.0
    engine.record_event_arrival("BTCUSDT", timestamp_sec=t0)
    int_t0 = engine.get_jump_intensity("BTCUSDT", timestamp_sec=t0)
    int_t5 = engine.get_jump_intensity("BTCUSDT", timestamp_sec=t0 + 5.0)
    int_t60 = engine.get_jump_intensity("BTCUSDT", timestamp_sec=t0 + 60.0)

    assert int_t0 > int_t5 > int_t60
    assert int_t60 >= engine._mu["BTCUSDT"]


def test_daemon_start_and_shutdown_balance_snapshots(
    temp_telemetry_store: SqliteCanaryHawkesTelemetryStore,
    temp_jsonl_sink: JsonlCanaryOrderSink,
):
    """Verifies daemon writes INITIALIZED and SHUTDOWN balance snapshots to SQLite."""
    gateway = MockBinanceHawkesCascadeGateway()
    reconciler = HawkesCascadeUserDataStreamReconciler(telemetry_store=temp_telemetry_store)
    heartbeat_mon = GatewayHeartbeatMonitor()
    engine = HawkesCascadeEngine(telemetry_store=temp_telemetry_store)
    interlock = HawkesCascadeOrderDispatchInterlock(
        reconciler=reconciler,
        heartbeat_monitor=heartbeat_mon,
        engine=engine,
        expansion_stage=CapitalExpansionStage.STAGE_12_HAWKES_CASCADE_EXPANSION,
        telemetry_store=temp_telemetry_store,
    )
    dispatcher = HawkesCascadeMicroOrderDispatcher(
        gateway=gateway,
        interlock=interlock,
        reconciler=reconciler,
        telemetry_store=temp_telemetry_store,
        jsonl_sink=temp_jsonl_sink,
    )
    daemon = HawkesCascadeAutonomousDaemon(
        dispatcher=dispatcher,
        reconciler=reconciler,
        interlock=interlock,
        heartbeat_monitor=heartbeat_mon,
        telemetry_store=temp_telemetry_store,
        track_id="test_daemon",
    )
    daemon.start()
    daemon.shutdown(graceful=True)

    rows = temp_telemetry_store.conn.execute(
        "SELECT * FROM balance_snapshots WHERE track_id = 'test_daemon' ORDER BY timestamp_utc ASC;"
    ).fetchall()
    assert len(rows) == 2
    triggers = [r["trigger_event"] for r in rows]
    assert "DAEMON_INITIALIZED" in triggers
    assert "DAEMON_SHUTDOWN" in triggers
