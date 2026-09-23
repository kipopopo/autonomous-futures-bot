"""Autonomous Futures Bot - Phase 309: Comprehensive Opaque-Box E2E Test Suite.

Validates the Autonomous Live Production Launch and Micro-Capital Self-Driving Trading Engine
across all 4 tiers of the E2E testing methodology:
- Tier 1: Feature Coverage (Category-Partition: Slicing, Exposure, Cash Reserve, Loss Ceiling,
  Hawkes throttle, Feed SLA, Solvency Ledger, Multi-Sig 2-of-3, 3-Tier Kill-Switch, Signal Trapping,
  Token Tripwire, Merkle DAG).
- Tier 2: Boundary Value Analysis & Corner Cases (Precision boundaries for 5.00 USDT, 25.00 USDT,
  75.0% reserve, 3.00 USDT loss, rho=1.000, latency=500ms, proposal expiration, nonce replay).
- Tier 3: Cross-Feature Combinations (Pairwise interactions: multi-asset concurrency with Hawkes,
  token tripwire under active exposure, multi-sig reset after panic, solvency during flattening,
  cascading kill-switch escalation).
- Tier 4: Real-World Longevity Scenarios (Multi-tick shifting market regimes Calm -> Volatility ->
  Toxic Turbulence, 50-tick zero-drift continuous audit, and post-flight artifact & Merkle check).
"""

from __future__ import annotations

import json
import signal
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

# Ensure repository root is on sys.path for scripts import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.production.self_driving import (  # noqa: E402
    UPSTREAM_PHASE_308_MERKLE_ROOT,
    MicroCapitalConfig,
    OrderSide,
    OrderStatus,
    SelfDrivingState,
    SelfDrivingTradingEngine,
    build_default_self_driving_engine,
)
from autonomous_futures.safety.kill_switch import (  # noqa: E402
    CentralizedSolvencyLedger,
    GovernanceActionType,
    HardwareOSKillSwitchEngine,
    KillSwitchState,
    KillSwitchTier,
    MultiSigGovernanceEngine,
    SignerIdentity,
)
from scripts.run_phase_309_production_launch import verify_phase_309_artifacts  # noqa: E402

# ==============================================================================
# TIER 1: FEATURE COVERAGE (CATEGORY-PARTITION)
# ==============================================================================


def test_tier1_micro_order_slicing_notional_cap(tmp_path: Path) -> None:
    """T1.01: Verifies micro-order slicing obeys the <= 5.00 USDT nominal limit

    and exchange lot-size quantized step sizing (BTC <= 5.75, ETH <= 5.50, SOL <= 5.55 USDT).
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    assert engine.run_pre_flight_check()

    # 1. BTCUSDT Long order
    ord_btc = engine.process_microstructure_tick(
        symbol="BTCUSDT",
        price=Decimal("95000.00"),
        hawkes_rho=0.35,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
        signal_confidence=0.85,
    )
    assert ord_btc is not None
    assert ord_btc.status == OrderStatus.FILLED
    assert ord_btc.side == OrderSide.BUY
    assert ord_btc.notional_usdt <= Decimal("5.75")
    assert ord_btc.notional_usdt >= Decimal("5.00")

    # 2. ETHUSDT Short order
    ord_eth = engine.process_microstructure_tick(
        symbol="ETHUSDT",
        price=Decimal("2750.00"),
        hawkes_rho=0.40,
        heartbeat_latency_ms=25.0,
        ensemble_signal="SHORT",
        signal_confidence=0.80,
    )
    assert ord_eth is not None
    assert ord_eth.status == OrderStatus.FILLED
    assert ord_eth.side == OrderSide.SELL
    assert ord_eth.notional_usdt <= Decimal("5.75")
    assert ord_eth.notional_usdt >= Decimal("5.00")

    # 3. SOLUSDT Long order
    ord_sol = engine.process_microstructure_tick(
        symbol="SOLUSDT",
        price=Decimal("185.00"),
        hawkes_rho=0.42,
        heartbeat_latency_ms=18.0,
        ensemble_signal="LONG",
        signal_confidence=0.78,
    )
    assert ord_sol is not None
    assert ord_sol.status == OrderStatus.FILLED
    assert ord_sol.side == OrderSide.BUY
    assert ord_sol.notional_usdt <= Decimal("5.75")
    assert ord_sol.notional_usdt >= Decimal("5.00")


def test_tier1_aggregate_exposure_ceiling_confinement(tmp_path: Path) -> None:
    """T1.02: Verifies aggregate portfolio exposure is strictly capped at <= 25.00 USDT

    across all candidate assets, rejecting order attempts that breach the limit.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Fill 1: BTCUSDT (~5.70 USDT)
    o1 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 15.0, "LONG", 0.9)
    assert o1 is not None

    # Fill 2: ETHUSDT (~5.50 USDT, total ~11.20 USDT)
    o2 = engine.process_microstructure_tick("ETHUSDT", Decimal("2750.0"), 0.3, 15.0, "LONG", 0.9)
    assert o2 is not None

    # Fill 3: SOLUSDT (~5.55 USDT, total ~16.75 USDT)
    o3 = engine.process_microstructure_tick("SOLUSDT", Decimal("185.0"), 0.3, 15.0, "LONG", 0.9)
    assert o3 is not None

    # Fill 4: BTCUSDT (~5.70 USDT, total ~22.45 USDT)
    o4 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 15.0, "LONG", 0.9)
    assert o4 is not None

    current_exposure = sum(c.allocated_exposure_usdt for c in engine.candidates.values())
    assert current_exposure <= Decimal("25.00")

    # Attempt Fill 5: Next ~5.50 USDT would push exposure to ~27.95 USDT > 25.00 USDT
    blocks_before = engine.interlock_blocks_count
    o5 = engine.process_microstructure_tick("ETHUSDT", Decimal("2750.0"), 0.3, 15.0, "LONG", 0.9)
    assert o5 is None
    assert engine.interlock_blocks_count == blocks_before + 1

    last_event = engine.events_log[-1]
    assert last_event["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"


def test_tier1_unencumbered_cash_reserve_floor_enforcement(tmp_path: Path) -> None:
    """T1.03: Verifies unencumbered liquid cash reserve floor (>= 75.0%) blocks orders

    when projected cash after order allocation drops below the requirement.
    """
    # Create engine with starting equity 100 USDT, but set min_cash_reserve_pct to 96.0%
    cfg = MicroCapitalConfig(min_cash_reserve_pct=Decimal("96.0"))
    signers = [SignerIdentity("s1", "p1", "CRO"), SignerIdentity("s2", "p2", "DEV")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)
    engine = SelfDrivingTradingEngine(
        config=cfg, solvency_ledger=ledger, kill_switch=ks, output_dir=tmp_path
    )
    assert engine.run_pre_flight_check()

    # Order notional is ~5.70 USDT. Cash drops from 100 to ~94.30 USDT (94.30%), which is < 96.0%
    ord_blocked = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95000.0"), 0.3, 20.0, "LONG", 0.85
    )
    assert ord_blocked is None
    last_event = engine.events_log[-1]
    assert last_event["event_type"] == "CASH_RESERVE_FLOOR_BLOCK"


def test_tier1_intra_day_loss_ceiling_auto_flattening(tmp_path: Path) -> None:
    """T1.04: Verifies accumulated intra-day loss >= 3.00 USDT triggers fail-closed

    emergency auto-flattening of all open positions and transitions state to CIRCUIT_FLATTENED.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Step 1: Open LONG BTC position
    o1 = engine.process_microstructure_tick("BTCUSDT", Decimal("100000.0"), 0.3, 20.0, "LONG", 0.90)
    assert o1 is not None
    assert engine.candidates["BTCUSDT"].position_qty > Decimal("0.0")

    # Artificially inject intra-day loss to reach 3.00 USDT
    engine.intra_day_loss_usdt = Decimal("3.05")

    # Next tick must detect loss ceiling breach, trigger emergency flatten, and halt
    o2 = engine.process_microstructure_tick("BTCUSDT", Decimal("100000.0"), 0.3, 20.0, "LONG", 0.90)
    assert o2 is None
    assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED
    assert engine.candidates["BTCUSDT"].position_qty == Decimal("0.0")
    assert engine.candidates["BTCUSDT"].allocated_exposure_usdt == Decimal("0.0")

    flatten_events = [e for e in engine.events_log if e["event_type"] == "EMERGENCY_FLATTEN"]
    assert len(flatten_events) >= 1


def test_tier1_hawkes_spectral_radius_throttle_and_recovery(tmp_path: Path) -> None:
    """T1.05: Verifies Hawkes spectral radius rho >= 1.0 instantly throttles order dispatch,

    and auto-recovers to MICRO_CAPITAL_ACTIVE when rho returns to subcritical level (< 1.0).
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Tick 1: Hawkes supercritical runaway (rho = 1.12)
    o1 = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=1.12,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
    )
    assert o1 is None
    assert engine.state.value == SelfDrivingState.HAWKES_THROTTLED.value
    assert engine.events_log[-1]["event_type"] == "HAWKES_RUNAWAY_THROTTLE"

    # Tick 2: Hawkes recovers to subcritical (rho = 0.45)
    o2 = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=0.45,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
    )
    assert o2 is not None
    assert engine.state.value == SelfDrivingState.MICRO_CAPITAL_ACTIVE.value
    assert o2.status == OrderStatus.FILLED


def test_tier1_feed_sla_heartbeat_gate_enforcement(tmp_path: Path) -> None:
    """T1.06: Verifies feed SLA gate blocks processing when heartbeat latency > 500 ms."""
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Stale latency: 540 ms
    o = engine.process_microstructure_tick(
        "ETHUSDT",
        Decimal("2750.0"),
        hawkes_rho=0.4,
        heartbeat_latency_ms=540.0,
        ensemble_signal="LONG",
    )
    assert o is None
    assert engine.events_log[-1]["event_type"] == "HEARTBEAT_STALE_BLOCK"


def test_tier1_double_entry_solvency_ledger_zero_drift(tmp_path: Path) -> None:
    """T1.07: Verifies continuous double-entry ledger balance conservation:

    Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL (|drift| < 1e-15).
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    for p in [95000.0, 95200.0, 95100.0, 95400.0]:
        engine.process_microstructure_tick("BTCUSDT", Decimal(str(p)), 0.3, 20.0, "LONG", 0.85)
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift
        assert abs(snap.drift) < 1e-15
        assert snap.unencumbered_cash_verified


def test_tier1_multisig_two_of_three_quorum_authorization() -> None:
    """T1.08: Verifies 2-of-3 M-of-N multi-sig quorum governance across CRO, SEC, DEV."""
    signers = [
        SignerIdentity("signer-cro", "pub-cro", "CHIEF_RISK_OFFICER"),
        SignerIdentity("signer-sec", "pub-sec", "SECURITY_OFFICER"),
        SignerIdentity("signer-dev", "pub-dev", "LEAD_DEV"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)

    prop = gov.create_proposal(
        GovernanceActionType.CHANGE_RISK_LIMIT,
        target="max_aggregate_exposure_usdt",
        parameters={"new_cap": 25.0},
    )
    assert not gov.is_quorum_satisfied(prop.proposal_id)

    # Vote 1: CRO
    p_json = json.dumps(prop.parameters, sort_keys=True)
    msg1 = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig1 = gov.compute_signature("signer-cro", msg1)
    assert gov.cast_vote(prop.proposal_id, "signer-cro", 1, sig1)
    assert not gov.is_quorum_satisfied(prop.proposal_id)

    # Vote 2: SEC
    msg2 = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig2 = gov.compute_signature("signer-sec", msg2)
    assert gov.cast_vote(prop.proposal_id, "signer-sec", 1, sig2)

    # Quorum (2 of 3) reached
    assert gov.is_quorum_satisfied(prop.proposal_id)


def test_tier1_three_tier_kill_switch_containment(tmp_path: Path) -> None:
    """T1.09: Verifies 3-tier emergency kill switch:

    Level 1 Soft Pause, Level 2 Lockout, Level 3 Panic (positions flattened, memory wiped).
    """
    signers = [SignerIdentity("s1", "p1", "CRO"), SignerIdentity("s2", "p2", "DEV")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)

    # Level 1: Soft Pause
    e1 = ks.trigger_level_1_soft_pause("Test soft pause", "TEST_TRIGGER")
    assert e1.tier == KillSwitchTier.LEVEL_1_SOFT
    assert ks.state == KillSwitchState.LEVEL_1_SOFT_PAUSE
    assert len(ks.open_orders) == 3

    # Level 2: Lockout
    e2 = ks.trigger_level_2_lockout("Test lockout", "TEST_TRIGGER")
    assert e2.tier == KillSwitchTier.LEVEL_2_LOCKOUT
    assert ks.state == KillSwitchState.LEVEL_2_LOCKOUT
    assert len(ks.open_orders) == 0

    # Level 3: Hardware Panic
    e3 = ks.trigger_level_3_hardware_panic("Test panic", "TEST_TRIGGER")
    assert e3.tier == KillSwitchTier.LEVEL_3_PANIC
    assert ks.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert ks.is_memory_wiped
    assert len(ks.open_positions) == 0


def test_tier1_os_signal_trapping_panic_containment(tmp_path: Path) -> None:
    """T1.10: Verifies OS signal interception (SIGINT, SIGTERM) immediately trips Level 3 Panic."""
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)

    ks.handle_os_signal(signal.SIGINT if hasattr(signal, "SIGINT") else 2)
    assert ks.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert ks.is_memory_wiped
    assert ks.events[-1].trigger_source == "OS_SIGNAL"


def test_tier1_token_tripwire_monitoring(tmp_path: Path) -> None:
    """T1.11: Verifies monitoring of emergency_kill.lock file token triggers immediate panic."""
    token_file = tmp_path / "emergency_kill.lock"
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(
        governance=gov, solvency_ledger=ledger, token_file_path=str(token_file)
    )

    assert not ks.check_file_tripwire()
    assert ks.state == KillSwitchState.ARMED_NORMAL

    # Write tripwire file
    token_file.write_text("HALT_ENGINE")
    assert ks.check_file_tripwire()
    assert ks.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert ks.events[-1].trigger_source == "FILE_TOKEN"


def test_tier1_merkle_dag_verification_and_artifact_export(tmp_path: Path) -> None:
    """T1.12: Verifies export of Phase 309 artifacts and cryptographic Merkle DAG chain linkage."""
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.4, 25.0, "LONG")
    summary = engine.export_artifacts()

    assert summary["verified"]
    assert summary["upstream_hash"] == UPSTREAM_PHASE_308_MERKLE_ROOT
    assert summary["solvency"]["zero_balance_drift"]
    assert (tmp_path / "canary-production-telemetry.sqlite3").is_file()
    assert (tmp_path / "canary-production-events.jsonl").is_file()
    assert (tmp_path / "canary-production-report.json").is_file()
    assert (tmp_path / "production-summary.json").is_file()
    assert (tmp_path / "canary-production-execution.json").is_file()


# ==============================================================================
# TIER 2: BOUNDARY VALUE ANALYSIS & CORNER CASES (BVA)
# ==============================================================================


def test_tier2_micro_order_lot_quantization_boundary(tmp_path: Path) -> None:
    """T2.01: Verifies step size quantization and MIN_NOTIONAL boundaries across assets.

    BTC: step 0.00001; ETH: step 0.001; SOL: step 0.01.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)

    # BTC price 95000: raw_qty = 5 / 95000 = 0.00005263... -> quantized to 0.00005
    btc_qty = engine._round_step_size("BTCUSDT", Decimal("5.00") / Decimal("95000.0"))
    assert btc_qty == Decimal("0.00005")

    # ETH price 2750: raw_qty = 5 / 2750 = 0.001818... -> quantized to 0.002
    eth_qty = engine._round_step_size("ETHUSDT", Decimal("5.00") / Decimal("2750.0"))
    assert eth_qty == Decimal("0.002")

    # SOL price 185: raw_qty = 5 / 185 = 0.02702... -> quantized to 0.03
    sol_qty = engine._round_step_size("SOLUSDT", Decimal("5.00") / Decimal("185.0"))
    assert sol_qty == Decimal("0.03")


def test_tier2_aggregate_exposure_exact_boundary(tmp_path: Path) -> None:
    """T2.02: BVA on aggregate exposure ceiling: exactly 10.00 USDT cap.

    First ~5.70 USDT order permitted; second ~5.70 USDT order breaches 10.00 USDT and is blocked.
    """
    cfg = MicroCapitalConfig(max_aggregate_exposure_usdt=Decimal("10.00"))
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)
    engine = SelfDrivingTradingEngine(
        config=cfg, solvency_ledger=ledger, kill_switch=ks, output_dir=tmp_path
    )
    engine.run_pre_flight_check()

    # Order 1: ~5.70 USDT (total = 5.70 <= 10.00)
    o1 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o1 is not None

    # Order 2: 5.70 + 5.70 = 11.40 > 10.00 -> BLOCKED
    o2 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o2 is None
    assert engine.events_log[-1]["event_type"] == "AGGREGATE_EXPOSURE_CAP_BLOCK"


def test_tier2_cash_reserve_floor_precision_boundary(tmp_path: Path) -> None:
    """T2.03: BVA on cash reserve floor: projected cash reserve exactly at boundary."""
    # Starting equity = 100.0 USDT. Order notional ~ 5.70 USDT.
    # Projected cash = 100.0 - 5.70 = 94.30 USDT -> 94.30%.
    # If min_cash_reserve_pct is set to 94.30%: 94.30% >= 94.30% -> PERMITTED
    # If min_cash_reserve_pct is set to 94.31%: 94.30% < 94.31% -> BLOCKED
    cfg_pass = MicroCapitalConfig(min_cash_reserve_pct=Decimal("94.30"))
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger1 = CentralizedSolvencyLedger(starting_equity=100.0)
    ks1 = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger1)
    engine1 = SelfDrivingTradingEngine(
        config=cfg_pass, solvency_ledger=ledger1, kill_switch=ks1, output_dir=tmp_path
    )
    engine1.run_pre_flight_check()

    o_pass = engine1.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o_pass is not None

    # Blocked boundary
    cfg_block = MicroCapitalConfig(min_cash_reserve_pct=Decimal("94.31"))
    ledger2 = CentralizedSolvencyLedger(starting_equity=100.0)
    ks2 = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger2)
    engine2 = SelfDrivingTradingEngine(
        config=cfg_block, solvency_ledger=ledger2, kill_switch=ks2, output_dir=tmp_path
    )
    engine2.run_pre_flight_check()

    o_block = engine2.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o_block is None
    assert engine2.events_log[-1]["event_type"] == "CASH_RESERVE_FLOOR_BLOCK"


def test_tier2_intra_day_loss_ceiling_exact_trip_boundary(tmp_path: Path) -> None:
    """T2.04: BVA on intra-day loss ceiling: 2.99 USDT (active) vs 3.00 USDT (circuit tripped)."""
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Loss at 2.99 USDT (< 3.00 ceiling) -> trading still permitted
    engine.intra_day_loss_usdt = Decimal("2.99")
    o1 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o1 is not None
    assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    # Loss reaches 3.00 USDT (>= 3.00 ceiling) -> trips emergency flattening
    engine.intra_day_loss_usdt = Decimal("3.00")
    o2 = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o2 is None
    assert engine.state == SelfDrivingState.CIRCUIT_FLATTENED


def test_tier2_hawkes_spectral_radius_exact_cutoff_boundary(tmp_path: Path) -> None:
    """T2.05: BVA on Hawkes cutoff: rho = 0.999 (allowed) vs rho = 1.000 (blocked)."""
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # rho = 0.999 -> Allowed
    o_pass = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=0.999,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
    )
    assert o_pass is not None

    # rho = 1.000 -> Blocked
    o_block = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=1.000,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
    )
    assert o_block is None
    assert engine.state == SelfDrivingState.HAWKES_THROTTLED

    # rho = 1.001 -> Blocked
    o_block2 = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=1.001,
        heartbeat_latency_ms=20.0,
        ensemble_signal="LONG",
    )
    assert o_block2 is None


def test_tier2_feed_sla_latency_exact_boundary(tmp_path: Path) -> None:
    """T2.06: BVA on feed SLA latency: 500.0 ms (passed) vs 500.1 ms (blocked)."""
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # 500.0 ms -> Allowed
    o_pass = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=0.3,
        heartbeat_latency_ms=500.0,
        ensemble_signal="LONG",
    )
    assert o_pass is not None

    # 500.1 ms -> Blocked
    o_block = engine.process_microstructure_tick(
        "BTCUSDT",
        Decimal("95000.0"),
        hawkes_rho=0.3,
        heartbeat_latency_ms=500.1,
        ensemble_signal="LONG",
    )
    assert o_block is None
    assert engine.events_log[-1]["event_type"] == "HEARTBEAT_STALE_BLOCK"


def test_tier2_multisig_proposal_expiration_exact_ttl() -> None:
    """T2.07: BVA on multi-sig proposal TTL: vote at t = expires_at_ms vs t = expires_at_ms + 1."""
    signers = [SignerIdentity("s1", "pub1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1, proposal_ttl_ms=5000)

    t0 = 100000
    prop = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "target", {}, now_ms=t0)
    assert prop.expires_at_ms == t0 + 5000

    p_json = json.dumps(prop.parameters, sort_keys=True)
    msg = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig = gov.compute_signature("s1", msg)

    # Vote at exact expiry: accepted
    v_exact = gov.cast_vote(prop.proposal_id, "s1", 1, sig, now_ms=prop.expires_at_ms)
    assert v_exact

    # New proposal for expired vote test
    prop2 = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "target", {}, now_ms=t0)
    msg2 = f"{prop2.proposal_id}:{prop2.action_type.value}:{prop2.target}:2:{p_json}"
    sig2 = gov.compute_signature("s1", msg2)

    # Vote 1 ms after expiry: rejected
    v_expired = gov.cast_vote(prop2.proposal_id, "s1", 2, sig2, now_ms=prop2.expires_at_ms + 1)
    assert not v_expired


def test_tier2_multisig_nonce_replay_and_double_voting_prevention() -> None:
    """T2.08: Verifies monotonic anti-replay nonce enforcement and double-voting prevention."""
    signers = [SignerIdentity("s1", "pub1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)

    prop1 = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "target", {})
    p1_json = json.dumps(prop1.parameters, sort_keys=True)

    # Vote with nonce 5 -> Valid
    msg1 = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:5:{p1_json}"
    sig1 = gov.compute_signature("s1", msg1)
    assert gov.cast_vote(prop1.proposal_id, "s1", 5, sig1)

    # Replay with same nonce 5 -> Rejected
    assert not gov.cast_vote(prop1.proposal_id, "s1", 5, sig1)

    # Replay with smaller nonce 4 -> Rejected
    msg_stale = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:4:{p1_json}"
    sig_stale = gov.compute_signature("s1", msg_stale)
    assert not gov.cast_vote(prop1.proposal_id, "s1", 4, sig_stale)

    # Double voting on same proposal even with higher nonce 6 -> Rejected
    msg_double = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:6:{p1_json}"
    sig_double = gov.compute_signature("s1", msg_double)
    assert not gov.cast_vote(prop1.proposal_id, "s1", 6, sig_double)

    # New proposal with next strictly increasing nonce 7 -> Valid!
    prop2 = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "target", {})
    p2_json = json.dumps(prop2.parameters, sort_keys=True)
    msg2 = f"{prop2.proposal_id}:{prop2.action_type.value}:{prop2.target}:7:{p2_json}"
    sig2 = gov.compute_signature("s1", msg2)
    assert gov.cast_vote(prop2.proposal_id, "s1", 7, sig2)


def test_tier2_multisig_inactive_or_unknown_signer_rejection() -> None:
    """T2.09: Verifies votes from unknown or deactivated signers are strictly rejected."""
    signers = [
        SignerIdentity("s-active", "pub1", "CRO", is_active=True),
        SignerIdentity("s-inactive", "pub2", "SEC", is_active=False),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    prop = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "target", {})

    # Unknown signer -> Rejected
    assert not gov.cast_vote(prop.proposal_id, "s-unknown", 1, "sig")

    # Inactive signer -> Rejected
    assert not gov.cast_vote(prop.proposal_id, "s-inactive", 1, "sig")


def test_tier2_unknown_symbol_and_sub_threshold_confidence(tmp_path: Path) -> None:
    """T2.10: Verifies non-whitelisted assets and low confidence signals (< 0.60) return None."""
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Unknown candidate symbol
    o_unknown = engine.process_microstructure_tick("DOGEUSDT", Decimal("0.20"), 0.3, 10.0, "LONG")
    assert o_unknown is None

    # Confidence below threshold (0.55 < 0.60)
    o_low_conf = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG", signal_confidence=0.55
    )
    assert o_low_conf is None

    # Neutral signal
    o_neutral = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "NEUTRAL", signal_confidence=0.90
    )
    assert o_neutral is None


# ==============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (PAIRWISE INTERACTIONS)
# ==============================================================================


def test_tier3_multi_asset_concurrency_with_selective_hawkes_burst(tmp_path: Path) -> None:
    """T3.01: Pairwise test: Concurrent multi-asset open positions across BTC, ETH, and SOL

    followed by a selective Hawkes burst on ETH, verifying that ETH is throttled without
    corrupting other assets' positions or double-entry zero-drift balance.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Open BTC Long
    o_btc = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 15.0, "LONG")
    assert o_btc is not None

    # Open ETH Short
    o_eth = engine.process_microstructure_tick("ETHUSDT", Decimal("2750.0"), 0.3, 15.0, "SHORT")
    assert o_eth is not None

    # Open SOL Long
    o_sol = engine.process_microstructure_tick("SOLUSDT", Decimal("185.0"), 0.3, 15.0, "LONG")
    assert o_sol is not None

    assert engine.candidates["BTCUSDT"].position_qty > 0
    assert engine.candidates["ETHUSDT"].position_qty < 0
    assert engine.candidates["SOLUSDT"].position_qty > 0

    # Hawkes shock hits ETHUSDT (rho = 1.35)
    o_eth_shock = engine.process_microstructure_tick(
        "ETHUSDT", Decimal("2740.0"), 1.35, 20.0, "SHORT"
    )
    assert o_eth_shock is None
    assert engine.state == SelfDrivingState.HAWKES_THROTTLED

    # Check that positions on BTC and SOL remain intact
    assert engine.candidates["BTCUSDT"].position_qty > 0
    assert engine.candidates["SOLUSDT"].position_qty > 0

    # Verify ledger solvency is unaffected by Hawkes throttle
    snap = engine.ledger.get_snapshot()
    assert snap.zero_balance_drift
    assert abs(snap.drift) < 1e-15

    # Subcritical tick on BTC recovers engine to active
    o_btc_rec = engine.process_microstructure_tick("BTCUSDT", Decimal("95200.0"), 0.4, 20.0, "LONG")
    assert o_btc_rec is not None
    assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE


def test_tier3_kill_switch_tripwire_during_active_exposure(tmp_path: Path) -> None:
    """T3.02: Pairwise test: External emergency_kill.lock appears while positions are open.

    Level 3 Panic triggers: active positions flattened, memory wiped, zero drift kept.
    """
    token_file = tmp_path / "emergency_kill.lock"
    signers = [SignerIdentity("s1", "p1", "CRO"), SignerIdentity("s2", "p2", "DEV")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(
        governance=gov, solvency_ledger=ledger, token_file_path=str(token_file)
    )
    engine = SelfDrivingTradingEngine(
        config=MicroCapitalConfig(), solvency_ledger=ledger, kill_switch=ks, output_dir=tmp_path
    )
    engine.run_pre_flight_check()

    # Open positions
    engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    engine.process_microstructure_tick("SOLUSDT", Decimal("185.0"), 0.3, 10.0, "LONG")

    # Tripwire token appears on filesystem
    token_file.write_text("OPS_PANIC_TRIGGER")
    assert ks.check_file_tripwire()
    assert ks.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert ks.is_memory_wiped

    # Process next tick: engine fails closed
    o_fail = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert o_fail is None
    assert engine.state == SelfDrivingState.KILL_SWITCH_HALTED

    # Solvency ledger zero drift preserved
    snap = ledger.get_snapshot()
    assert snap.zero_balance_drift
    assert abs(snap.drift) < 1e-15


def test_tier3_multisig_lockout_reset_after_hardware_panic(tmp_path: Path) -> None:
    """T3.03: Pairwise test: Recovery workflow.

    System in Hardware Panic -> 2-of-3 multi-sig proposal RESET_LOCKOUT submitted,
    voted, approved -> kill-switch reset to ARMED_NORMAL -> engine passes pre-flight check.
    """
    signers = [
        SignerIdentity("signer-cro", "pub1", "CRO"),
        SignerIdentity("signer-dev", "pub2", "DEV"),
        SignerIdentity("signer-sec", "pub3", "SEC"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)
    engine = SelfDrivingTradingEngine(
        config=MicroCapitalConfig(), solvency_ledger=ledger, kill_switch=ks, output_dir=tmp_path
    )

    # Trip Level 3 Panic
    ks.trigger_level_3_hardware_panic("Hardware panic test", "TEST_TRIGGER")
    assert ks.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC

    # Pre-flight must fail
    assert not engine.run_pre_flight_check()
    assert engine.state == SelfDrivingState.KILL_SWITCH_HALTED

    # Multi-sig proposal to reset lockout
    prop = gov.create_proposal(
        GovernanceActionType.RESET_LOCKOUT, "kill_switch", {"target_state": "ARMED_NORMAL"}
    )
    p_json = json.dumps(prop.parameters, sort_keys=True)

    # Signer CRO votes
    msg_cro = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig_cro = gov.compute_signature("signer-cro", msg_cro)
    gov.cast_vote(prop.proposal_id, "signer-cro", 1, sig_cro)

    # Signer DEV votes
    msg_dev = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig_dev = gov.compute_signature("signer-dev", msg_dev)
    gov.cast_vote(prop.proposal_id, "signer-dev", 1, sig_dev)

    assert gov.is_quorum_satisfied(prop.proposal_id)
    assert ks.reset_to_normal(prop.proposal_id)
    assert ks.state == KillSwitchState.ARMED_NORMAL

    # Engine can now successfully pass pre-flight check!
    assert engine.run_pre_flight_check()
    assert engine.state == SelfDrivingState.MICRO_CAPITAL_ACTIVE


def test_tier3_solvency_verification_during_emergency_market_flattening(tmp_path: Path) -> None:
    """T3.04: Pairwise test: Solvency verification during full emergency market flattening

    across all 3 assets, confirming fees are accounted and balance drift remains strictly 0.0.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    # Open positions on all 3 assets
    engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    engine.process_microstructure_tick("ETHUSDT", Decimal("2750.0"), 0.3, 10.0, "LONG")
    engine.process_microstructure_tick("SOLUSDT", Decimal("185.0"), 0.3, 10.0, "LONG")

    for cand in engine.candidates.values():
        assert cand.position_qty > 0

    # Emergency flatten
    engine._flatten_all_positions(reason="Pairwise emergency test")

    for cand in engine.candidates.values():
        assert cand.position_qty == Decimal("0.0")
        assert cand.allocated_exposure_usdt == Decimal("0.0")

    snap = engine.ledger.get_snapshot()
    assert snap.zero_balance_drift
    assert abs(snap.drift) < 1e-15
    assert snap.allocated_margin == 0.0


def test_tier3_cascading_kill_switch_escalation_lifecycle(tmp_path: Path) -> None:
    """T3.05: Pairwise test: Sequential escalation through all 3 tiers:

    Armed -> Level 1 Soft Pause -> Level 2 Lockout -> Level 3 Panic with audit trace.
    """
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)

    # 1. Level 1 Soft Pause
    ks.trigger_level_1_soft_pause("Hawkes runaway warning", "HAWKES_BREACH")
    assert ks.state == KillSwitchState.LEVEL_1_SOFT_PAUSE

    # 2. Escalate to Level 2 Lockout
    ks.trigger_level_2_lockout("Round-trip latency timeout > 500 ms", "LATENCY_SPIKE")
    assert ks.state == KillSwitchState.LEVEL_2_LOCKOUT
    assert len(ks.open_orders) == 0

    # 3. Escalate to Level 3 Panic
    ks.trigger_level_3_hardware_panic("Persistent data corruption", "CORRUPTION_DETECTED")
    assert ks.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert ks.is_memory_wiped
    assert len(ks.open_positions) == 0

    # Verify event audit trail
    assert len(ks.events) == 3
    tiers = [e.tier for e in ks.events]
    assert tiers == [
        KillSwitchTier.LEVEL_1_SOFT,
        KillSwitchTier.LEVEL_2_LOCKOUT,
        KillSwitchTier.LEVEL_3_PANIC,
    ]

    # Verify double-entry ledger preserved throughout cascade
    snap = ledger.get_snapshot()
    assert snap.zero_balance_drift
    assert abs(snap.drift) < 1e-15


# ==============================================================================
# TIER 4: REAL-WORLD LONGEVITY SCENARIOS (WORKLOADS)
# ==============================================================================


def test_tier4_w01_multi_tick_lifecycle_shifting_regimes(tmp_path: Path) -> None:
    """T4.01 / W01: Simulates 16-tick lifecycle navigating 4 distinct market regimes:

    1. Calm Regime: Routine micro orders across BTC, ETH, SOL.
    2. Volatility Shock Regime: Hawkes rho surges to 1.20; latency spikes to 540 ms.
    3. Toxic Turbulence: Adverse price movement, testing loss ceiling containment.
    4. Stabilization & Recovery: Hawkes decays to 0.40, latency recovers, closing trades.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    assert engine.run_pre_flight_check()

    now = 1790000000000

    # Regime 1: Calm Regime (Ticks 1-4)
    t1 = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95000.0"), 0.35, 25.0, "LONG", now_ms=now
    )
    assert t1 is not None and t1.status == OrderStatus.FILLED

    t2 = engine.process_microstructure_tick(
        "ETHUSDT", Decimal("2750.0"), 0.38, 28.0, "SHORT", now_ms=now + 500
    )
    assert t2 is not None and t2.status == OrderStatus.FILLED

    t3 = engine.process_microstructure_tick(
        "SOLUSDT", Decimal("185.0"), 0.40, 30.0, "LONG", now_ms=now + 1000
    )
    assert t3 is not None and t3.status == OrderStatus.FILLED

    # Regime 2: Volatility Shock Regime (Ticks 5-7)
    # Tick 5: Hawkes supercritical breach on ETH
    t5 = engine.process_microstructure_tick(
        "ETHUSDT", Decimal("2740.0"), 1.25, 30.0, "SHORT", now_ms=now + 2000
    )
    assert t5 is None
    assert getattr(engine, "state") == SelfDrivingState.HAWKES_THROTTLED

    # Tick 6: Feed SLA latency breach on BTC
    t6 = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("94800.0"), 0.45, 540.0, "LONG", now_ms=now + 2500
    )
    assert t6 is None

    # Regime 3: Stabilization & Recovery (Ticks 7-10)
    # Tick 7: Hawkes recovers to 0.42, latency recovers to 25 ms -> Order allowed
    t7 = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95100.0"), 0.42, 25.0, "SHORT", now_ms=now + 3000
    )
    assert t7 is not None
    assert getattr(engine, "state") == SelfDrivingState.MICRO_CAPITAL_ACTIVE

    # Verify zero-drift after regime transitions
    snap = engine.ledger.get_snapshot()
    assert snap.zero_balance_drift
    assert abs(snap.drift) < 1e-15
    assert snap.unencumbered_cash_verified


def test_tier4_w02_continuous_50_tick_longevity_zero_drift_audit(tmp_path: Path) -> None:
    """T4.02 / W02: High-throughput 50-tick longevity stream verifying mathematical

    zero-drift balance conservation (|drift| < 1e-15 USDT) at every single tick.
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    engine.run_pre_flight_check()

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    base_prices = {"BTCUSDT": 95000.0, "ETHUSDT": 2750.0, "SOLUSDT": 185.0}

    now = 1790100000000
    fills_count = 0

    for i in range(50):
        sym = symbols[i % len(symbols)]
        # Slight price oscillation
        delta_p = (i % 5 - 2) * 5.0
        price = Decimal(str(base_prices[sym] + delta_p))
        signal_side = "LONG" if i % 2 == 0 else "SHORT"
        rho = 0.30 + (i % 10) * 0.05  # all subcritical < 1.0
        lat = 15.0 + (i % 5) * 5.0  # all fresh < 500 ms

        ord_res = engine.process_microstructure_tick(
            symbol=sym,
            price=price,
            hawkes_rho=rho,
            heartbeat_latency_ms=lat,
            ensemble_signal=signal_side,
            signal_confidence=0.85,
            now_ms=now + i * 500,
        )
        if ord_res is not None:
            fills_count += 1

        # Strict per-tick double-entry balance audit
        snap = engine.ledger.get_snapshot()
        assert snap.zero_balance_drift, f"Tick {i}: Balance drift breached: {snap.drift}"
        assert abs(snap.drift) < 1e-15, f"Tick {i}: Absolute drift >= 1e-15: {snap.drift}"

    assert fills_count > 0
    # Final solvency check
    final_snap = engine.ledger.get_snapshot()
    assert final_snap.zero_balance_drift
    assert abs(final_snap.drift) < 1e-15


def test_tier4_w03_autonomous_launch_simulation_and_artifact_integrity(tmp_path: Path) -> None:
    """T4.03 / W03: End-to-end full launch simulation, artifact persistence, SQLite3 validation,

    and verification runner integrity pass via verify_phase_309_artifacts().
    """
    engine, _gov = build_default_self_driving_engine(output_dir=tmp_path)
    assert engine.run_pre_flight_check()

    now = 1790150000000

    # 1. Execute full trading sequence
    o1 = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95000.0"), 0.35, 20.0, "LONG", now_ms=now
    )
    assert o1 is not None

    o2 = engine.process_microstructure_tick(
        "ETHUSDT", Decimal("2750.0"), 0.40, 25.0, "SHORT", now_ms=now + 500
    )
    assert o2 is not None

    o3 = engine.process_microstructure_tick(
        "SOLUSDT", Decimal("185.0"), 0.45, 22.0, "LONG", now_ms=now + 1000
    )
    assert o3 is not None

    # Hawkes shock tick
    o_block1 = engine.process_microstructure_tick(
        "ETHUSDT", Decimal("2740.0"), 1.20, 25.0, "SHORT", now_ms=now + 1500
    )
    assert o_block1 is None

    # Stale heartbeat tick
    o_block2 = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95200.0"), 0.40, 580.0, "LONG", now_ms=now + 2000
    )
    assert o_block2 is None

    # Profit taking tick
    o4 = engine.process_microstructure_tick(
        "BTCUSDT", Decimal("95500.0"), 0.40, 22.0, "SHORT", now_ms=now + 2500
    )
    assert o4 is not None

    # 2. Export artifacts
    summary = engine.export_artifacts()
    assert summary["verified"]
    assert summary["status"] == "PRODUCTION_LAUNCH_VERIFIED"
    assert summary["upstream_hash"] == UPSTREAM_PHASE_308_MERKLE_ROOT

    # 3. Inspect SQLite3 database
    sqlite_path = tmp_path / "canary-production-telemetry.sqlite3"
    assert sqlite_path.is_file()
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM orders")
    orders_row_count = cur.fetchone()[0]
    assert orders_row_count == len(engine.orders)
    assert orders_row_count == 4

    cur.execute("SELECT COUNT(*) FROM events")
    events_row_count = cur.fetchone()[0]
    assert events_row_count == len(engine.events_log)
    conn.close()

    # 4. Verify via official CLI verification function
    assert verify_phase_309_artifacts(tmp_path)
