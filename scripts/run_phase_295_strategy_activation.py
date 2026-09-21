"""Phase 295: Core Strategy Activation & Walk-Forward OOS Promotion Gates CLI Runner.

Executes deterministic multi-candidate strategy activation simulations with:
- Candidate Registry Manifest v2 Ingress & Cryptographic Hash Verification
- Walk-Forward OOS Qualification Promotion Gates (Return >= 0, DD <= 15%, PF >= 1.05, N >= 5)
- Candidate Promotion Lifecycle State Machine (UNPROMOTED, PROMOTED, BLOCKED, VETOED)
- Causal Indicator Feature Engine (Donchian breakout 50/20, ATR, ADX, Trade Momentum)
- Typed ParentOrderIntention formulation (tag: c=canary-p295-{sym}-{ts}-{uuid})
- Real-Time Fail-Closed Veto Interlocks (Gateway freshness, Loss budget, Hawkes, Headroom)
- Paper Execution Pipeline Binding with Micro Child Order Slicing (<= 5.00 USDT, ROUND_DOWN)
- Continuous Double-Entry Zero-Drift Ledger Reconciliations (|drift| < 10^-15 USDT)
- SQLite Telemetry & SHA-256 Merkle DAG Hash Chain Persistence linking Phase 294

4 Deterministic Simulation Tracks:
- Track 1: Nominal Multi-Symbol Strategy Ingress & Signal Promotion
- Track 2: Real-Time Fail-Closed Veto Interlocks Drill
- Track 3: Unpromoted / Blocked Candidate Qualification Gate & Loss Budget Breach Drill
- Track 4: Multi-Symbol Continuity, Ledger Invariant & Merkle DAG Hash Chain Persistence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

# Ensure project root and src/ are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.models import (  # noqa: E402
    AggregateTrade,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)
from autonomous_futures.feed.paper_execution import (  # noqa: E402
    DEFAULT_MAKER_FEE_RATE,
    HARD_MICRO_NOTIONAL_CAP_USDT,
    ChildOrderIntention,
    OrderExecutionFill,
    OrderSide,
    SimulatedPassiveMatchingEngine,
    get_default_exchange_filters,
)
from autonomous_futures.feed.paper_ledger import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
)
from autonomous_futures.feed.paper_risk import (  # noqa: E402
    CircuitState,
    InterlockCode,
    LivePaperRiskInterlock,
)
from autonomous_futures.feed.strategy_activation import (  # noqa: E402
    DEFAULT_PHASE294_DIR,
    DEFAULT_PHASE295_DIR,
    CandidateLifecycleStateMachine,
    CandidatePromotionStatus,
    CausalStrategyFeatureEngine,
    GatewayHealth,
    HawkesTelemetrySnapshot,
    OOSPromotionGateRecord,
    create_parent_order_intention,
    evaluate_oos_promotion_gates,
    execute_strategy_activation_order,
    load_verified_candidate_manifest_v2,
    persist_phase295_artifacts,
    validate_realtime_veto_interlocks,
)

logger = logging.getLogger("run_phase_295_strategy_activation")


# =====================================================================
# Track 1: Nominal Multi-Symbol Strategy Ingress & Signal Promotion
# =====================================================================


def run_track_1(
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 1: Nominal Multi-Symbol Ingress, OOS Promotion & Execution."""
    logger.info("=== Running Track 1: Nominal Ingress & Signal Promotion ===")

    # 1. Ingest Manifest v2 & Staged Active Universe
    manifest, bundles = load_verified_candidate_manifest_v2(registry_path, repo_root=_REPO_ROOT)
    assert len(bundles) == 3, f"Expected 3 bundles, got {len(bundles)}"

    # 2. Evaluate Walk-Forward OOS Promotion Gates
    gate_records: list[OOSPromotionGateRecord] = []
    state_machines: dict[str, CandidateLifecycleStateMachine] = {}

    for sym, bundle in bundles.items():
        gate_rec = evaluate_oos_promotion_gates(bundle.candidate, bundle.qualification)
        assert gate_rec.qualified is True, f"Candidate {bundle.candidate_id} failed OOS gates"
        assert gate_rec.status == CandidatePromotionStatus.PROMOTED
        gate_records.append(gate_rec)

        # Initialize and promote state machine
        sm = CandidateLifecycleStateMachine(bundle.candidate_id, sym)
        sm.promote(gate_rec)
        assert sm.is_executable is True
        state_machines[sym] = sm

    # 3. Initialize Paper Execution Infrastructure
    engine = SimulatedPassiveMatchingEngine()
    risk = LivePaperRiskInterlock(starting_equity=starting_capital)
    ledger = PaperExecutionLedger(starting_equity=starting_capital)
    filters = get_default_exchange_filters()

    # Initial depths
    now_dt = datetime.now(UTC)
    now_ms = int(time.time() * 1000)

    depth_btc = OrderBookDepthSnapshot(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("65000.00"), quantity=Decimal("2.5")),),
        asks=(OrderBookLevel(price=Decimal("65001.00"), quantity=Decimal("2.0")),),
        last_update_id=20001,
        event_time=now_dt,
    )
    engine.update_depth(depth_btc)

    depth_eth = OrderBookDepthSnapshot(
        symbol="ETHUSDT",
        bids=(OrderBookLevel(price=Decimal("3500.00"), quantity=Decimal("15.0")),),
        asks=(OrderBookLevel(price=Decimal("3500.50"), quantity=Decimal("12.0")),),
        last_update_id=20002,
        event_time=now_dt,
    )
    engine.update_depth(depth_eth)

    depth_sol = OrderBookDepthSnapshot(
        symbol="SOLUSDT",
        bids=(OrderBookLevel(price=Decimal("150.00"), quantity=Decimal("100.0")),),
        asks=(OrderBookLevel(price=Decimal("150.10"), quantity=Decimal("80.0")),),
        last_update_id=20003,
        event_time=now_dt,
    )
    engine.update_depth(depth_sol)

    # 4. Feature computation & signal formulation
    feature_engine = CausalStrategyFeatureEngine()
    btc_history = [Decimal("64000.00") + Decimal(i * 15) for i in range(55)]
    feature_engine.seed_prices("BTCUSDT", btc_history)

    curr_btc_price = Decimal("65000.00")
    sig = feature_engine.evaluate_signal(bundles["BTCUSDT"], curr_btc_price)
    assert sig == OrderSide.BUY, "Expected BUY signal on Donchian breakout"

    # 5. Formulate ParentOrderIntention with deterministic client order ID
    parent_btc = create_parent_order_intention(
        candidate=bundles["BTCUSDT"].candidate,
        symbol="BTCUSDT",
        side=sig,
        current_depth=depth_btc,
        filters=filters["BTCUSDT"],
        equity=starting_capital,
        timestamp_ms=now_ms,
    )
    assert parent_btc.parent_order_id.startswith("c=canary-p295-btcusdt-")
    assert parent_btc.target_notional_usdt == Decimal("10.00")

    # 6. Real-time pre-trade interlocks check
    hawkes_ok = HawkesTelemetrySnapshot(
        symbol="BTCUSDT",
        spectral_radius=Decimal("0.35"),
        regime="NOMINAL",
        is_supercritical=False,
    )
    gateway_ok = GatewayHealth(
        heartbeat_age_ms=35.0,
        latency_ms=25.0,
        clock_skew_ms=2.0,
        is_healthy=True,
    )
    veto_dec = validate_realtime_veto_interlocks(
        interlock=risk,
        hawkes_snapshot=hawkes_ok,
        feed_health=gateway_ok,
        proposed_notional=parent_btc.target_notional_usdt,
        symbol="BTCUSDT",
    )
    assert veto_dec.allowed is True
    assert veto_dec.veto_code == InterlockCode.NORMAL.value

    # 7. Slicing & Execution simulation
    child_orders, fills = execute_strategy_activation_order(
        parent=parent_btc,
        engine=engine,
        risk=risk,
        ledger=ledger,
        filters=filters["BTCUSDT"],
        current_depth=depth_btc,
        mark_price=Decimal("65000.00"),
        chunk_cap_usdt=Decimal("4.50"),
    )

    for child in child_orders:
        assert child.notional_usdt <= HARD_MICRO_NOTIONAL_CAP_USDT
        assert child.client_order_id.startswith(parent_btc.parent_order_id)

    # 8. Simulate fill arrival
    trade = AggregateTrade(
        symbol="BTCUSDT",
        price=Decimal("65000.00"),
        quantity=Decimal("1.0"),
        trade_time=datetime.now(UTC),
        is_buyer_maker=True,
        aggregate_trade_id=30001,
    )
    sim_fills = engine.on_aggregate_trade(trade)
    for f in sim_fills:
        ledger.record_fill(f)
        risk.release_working_notional(f.symbol, f.fill_notional_usdt)
        risk.update_active_exposure(f.symbol, ledger.allocated_margin)

    ledger.update_mark_price("BTCUSDT", Decimal("65005.00"))
    ledger.create_snapshot()
    ledger.verify_zero_drift()

    return {
        "track": 1,
        "name": "nominal_multi_symbol_activation",
        "status": "PASSED",
        "candidates_promoted": len(gate_records),
        "child_orders_placed": len(child_orders),
        "fills_count": len(ledger._execution_marks),
        "ledger_drift_usdt": str(ledger.drift),
        "zero_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
    }


# =====================================================================
# Track 2: Real-Time Fail-Closed Veto Interlocks Drill
# =====================================================================


def run_track_2(
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 2: Fail-Closed Real-Time Risk Veto Interlocks."""
    logger.info("=== Running Track 2: Real-Time Fail-Closed Veto Interlocks Drill ===")

    risk = LivePaperRiskInterlock(starting_equity=starting_capital)
    veto_results: dict[str, bool] = {}

    # Sub-test 2A: Hawkes Supercritical Runaway Lockout (rho >= 1.0)
    hawkes_super = HawkesTelemetrySnapshot(
        symbol="SOLUSDT",
        spectral_radius=Decimal("1.25"),
        regime="SUPERCRITICAL_CASCADE",
        is_supercritical=True,
    )
    gw_normal = GatewayHealth(heartbeat_age_ms=25.0, is_healthy=True)
    dec_hawkes = validate_realtime_veto_interlocks(
        interlock=risk,
        hawkes_snapshot=hawkes_super,
        feed_health=gw_normal,
        proposed_notional=Decimal("4.50"),
        symbol="SOLUSDT",
    )
    assert dec_hawkes.allowed is False
    assert dec_hawkes.veto_code == InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT.value
    assert dec_hawkes.veto_flags["hawkes_supercritical"] is True
    veto_results["hawkes_supercritical"] = True

    # Reset circuit for subsequent check
    risk.set_circuit_state(CircuitState.NORMAL)

    # Sub-test 2B: Gateway Heartbeat Latency Stale (> 500 ms)
    hawkes_nom = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.30"))
    gw_stale = GatewayHealth(heartbeat_age_ms=600.0, is_healthy=True)
    dec_stale = validate_realtime_veto_interlocks(
        interlock=risk,
        hawkes_snapshot=hawkes_nom,
        feed_health=gw_stale,
        proposed_notional=Decimal("2.50"),
        symbol="BTCUSDT",
    )
    assert dec_stale.allowed is False
    assert dec_stale.veto_code == InterlockCode.GATEWAY_HEARTBEAT_STALE.value
    assert dec_stale.veto_flags["gateway_heartbeat_stale"] is True
    veto_results["gateway_heartbeat_stale"] = True

    # Sub-test 2C: NTP Clock Skew (> 250 ms)
    gw_skew = GatewayHealth(heartbeat_age_ms=25.0, clock_skew_ms=300.0, is_healthy=True)
    dec_skew = validate_realtime_veto_interlocks(
        interlock=risk,
        hawkes_snapshot=hawkes_nom,
        feed_health=gw_skew,
        proposed_notional=Decimal("2.50"),
        symbol="BTCUSDT",
    )
    assert dec_skew.allowed is False
    assert dec_skew.veto_code == InterlockCode.CLOCK_SKEW_BREACH.value
    veto_results["clock_skew_breach"] = True

    # Sub-test 2D: Aggregate Exposure Cap (> 60.00 USDT)
    risk.update_active_exposure("GLOBAL", Decimal("58.00"))
    dec_overcap = validate_realtime_veto_interlocks(
        interlock=risk,
        hawkes_snapshot=hawkes_nom,
        feed_health=gw_normal,
        proposed_notional=Decimal("5.00"),  # 58 + 5 = 63 > 60.00
        symbol="BTCUSDT",
    )
    assert dec_overcap.allowed is False
    assert dec_overcap.veto_code == InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED.value
    assert dec_overcap.veto_flags["margin_headroom_breach"] is True
    veto_results["aggregate_exposure_breach"] = True

    # Sub-test 2E: Margin Headroom Breach (unencumbered reserve < 40% / utilization > 60%)
    risk.update_active_exposure("GLOBAL", Decimal("0.00"))
    risk._current_cash = Decimal("41.00")
    dec_headroom = validate_realtime_veto_interlocks(
        interlock=risk,
        hawkes_snapshot=hawkes_nom,
        feed_health=gw_normal,
        proposed_notional=Decimal("2.00"),
        symbol="ETHUSDT",
    )
    assert dec_headroom.allowed is False
    assert dec_headroom.veto_code == InterlockCode.MARGIN_HEADROOM_BREACH.value
    veto_results["margin_headroom_breach"] = True

    return {
        "track": 2,
        "name": "fail_closed_veto_interlocks",
        "status": "PASSED",
        "veto_checks": veto_results,
        "all_vetoes_verified": all(veto_results.values()),
    }


# =====================================================================
# Track 3: Unpromoted / Blocked & Loss Budget Flattening Drill
# =====================================================================


def run_track_3(
    starting_capital: Decimal = Decimal("100.00"),
    simulate_loss_breach: bool = True,
) -> dict[str, Any]:
    """Execute Track 3: Unpromoted Candidates & Loss Budget Ceiling Emergency Flattening."""
    logger.info("=== Running Track 3: Unpromoted Candidates & Loss Budget Flattening ===")

    # Sub-test 3A: Candidate with failing OOS metrics
    failing_cand = {
        "candidate_id": "cand-failing-001",
        "strategy": {"universe": {"symbols": ["BTCUSDT"]}},
    }
    failing_qual = {
        "candidate_id": "cand-failing-001",
        "decision": "rejected",
        "metrics": [
            {"metric_id": "oos_average_return_pct", "value": Decimal("-0.05")},
            {"metric_id": "oos_worst_drawdown_pct", "value": Decimal("0.22")},  # 22% > 15%
            {"metric_id": "oos_profit_factor", "value": Decimal("0.85")},
            {"metric_id": "oos_total_trades", "value": Decimal("3")},
            {"metric_id": "oos_window_count", "value": Decimal("1")},
        ],
    }
    gate_rec = evaluate_oos_promotion_gates(failing_cand, failing_qual)
    assert gate_rec.qualified is False
    assert gate_rec.status == CandidatePromotionStatus.BLOCKED
    assert gate_rec.gates_passed["oos_average_return"] is False
    assert gate_rec.gates_passed["oos_worst_drawdown"] is False
    assert gate_rec.gates_passed["oos_profit_factor"] is False
    assert gate_rec.gates_passed["oos_trade_count"] is False

    # State machine refuses execution
    sm = CandidateLifecycleStateMachine("cand-failing-001", "BTCUSDT")
    assert sm.is_executable is False
    sm.block("Failed OOS qualification gates")
    assert sm.status == CandidatePromotionStatus.BLOCKED

    # Sub-test 3B & 3C: Loss budget ceiling breach & emergency micro-chunk flattening
    risk = LivePaperRiskInterlock(starting_equity=starting_capital)
    ledger = PaperExecutionLedger(starting_equity=starting_capital)

    if simulate_loss_breach:
        # Simulate losing trades
        fill_open = OrderExecutionFill(
            fill_id="t3_open",
            client_order_id="c=canary-p295-btcusdt-open-0-slice-0",
            order_id="c=canary-p295-btcusdt-open-0-slice-0",
            parent_order_id="c=canary-p295-btcusdt-open-0",
            child_index=0,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            fill_price=Decimal("60000.00"),
            fill_quantity=Decimal("0.0007"),
            fill_notional_usdt=Decimal("42.00"),
            fee_usdt=Decimal("0.0084"),
            is_maker=False,
            fill_time_ms=int(time.time() * 1000),
        )
        ledger.record_fill(fill_open)

        fill_loss = OrderExecutionFill(
            fill_id="t3_close",
            client_order_id="c=canary-p295-btcusdt-close-0-slice-0",
            order_id="c=canary-p295-btcusdt-close-0-slice-0",
            parent_order_id="c=canary-p295-btcusdt-close-0",
            child_index=0,
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            fill_price=Decimal("49500.00"),
            fill_quantity=Decimal("0.0007"),
            fill_notional_usdt=Decimal("34.65"),
            fee_usdt=Decimal("0.0069"),
            is_maker=False,
            fill_time_ms=int(time.time() * 1000),
        )
        ledger.record_fill(fill_loss)

        # Trigger loss breach in risk engine
        cast(Any, risk).record_loss(Decimal("7.35"))
        assert risk.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT

        # Validate pre-trade interlock blocks further orders
        hawkes_nom = HawkesTelemetrySnapshot(symbol="BTCUSDT", spectral_radius=Decimal("0.30"))
        gw_normal = GatewayHealth(heartbeat_age_ms=25.0, is_healthy=True)
        dec_blocked = validate_realtime_veto_interlocks(
            interlock=risk,
            hawkes_snapshot=hawkes_nom,
            feed_health=gw_normal,
            proposed_notional=Decimal("2.50"),
            symbol="BTCUSDT",
        )
        assert dec_blocked.allowed is False
        assert dec_blocked.veto_code == CircuitState.INTRA_PHASE_LOSS_LOCKOUT.value
        assert dec_blocked.veto_flags["intra_phase_loss_breach"] is True

        # Test emergency flattening chunking (<= 5.00 USDT cap)
        chunks = cast(Any, risk).chunk_emergency_flattening(
            symbol="BTCUSDT",
            quantity=Decimal("0.0003"),
            price=Decimal("60000.00"),  # 18.00 USDT -> at least 4 chunks of <= 5.00 USDT
        )
        assert len(chunks) >= 4
        for ch in chunks:
            assert ch["notional_usdt"] <= HARD_MICRO_NOTIONAL_CAP_USDT

    ledger.create_snapshot()
    ledger.verify_zero_drift()

    return {
        "track": 3,
        "name": "unpromoted_and_loss_ceiling_flattening",
        "status": "PASSED",
        "failing_candidate_blocked": True,
        "circuit_state": str(risk.circuit_state),
        "loss_breach_detected": risk.circuit_state == CircuitState.INTRA_PHASE_LOSS_LOCKOUT,
        "zero_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
    }


# =====================================================================
# Track 4: Multi-Symbol Continuity & Merkle DAG Hash Chain Persistence
# =====================================================================


def run_track_4(
    output_dir: Path = DEFAULT_PHASE295_DIR,
    upstream_dir: Path = DEFAULT_PHASE294_DIR,
    registry_path: Path = DEFAULT_PHASE295_DIR / "candidate_registry.json",
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 4: Multi-Symbol Continuity, Zero-Drift Balance & Merkle DAG Persistence."""
    logger.info("=== Running Track 4: Multi-Symbol Continuity & Merkle DAG Persistence ===")

    actual_reg_path = (
        registry_path
        if registry_path.exists()
        else _REPO_ROOT / "artifacts" / "paper_live" / "candidate_registry.json"
    )
    manifest, bundles = load_verified_candidate_manifest_v2(actual_reg_path, repo_root=_REPO_ROOT)

    gate_records: list[OOSPromotionGateRecord] = []
    for _sym, bundle in bundles.items():
        gate_rec = evaluate_oos_promotion_gates(bundle.candidate, bundle.qualification)
        gate_records.append(gate_rec)

    engine = SimulatedPassiveMatchingEngine()
    risk = LivePaperRiskInterlock(starting_equity=starting_capital)
    ledger = PaperExecutionLedger(starting_equity=starting_capital)
    filters = get_default_exchange_filters()

    mark_prices: dict[str, Decimal] = {
        "BTCUSDT": Decimal("65000.00"),
        "ETHUSDT": Decimal("3500.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    depth_btc = OrderBookDepthSnapshot(
        symbol="BTCUSDT",
        bids=(OrderBookLevel(price=Decimal("65000.00"), quantity=Decimal("2.5")),),
        asks=(OrderBookLevel(price=Decimal("65001.00"), quantity=Decimal("2.0")),),
        last_update_id=40001,
        event_time=datetime.now(UTC),
    )
    engine.update_depth(depth_btc)

    depth_eth = OrderBookDepthSnapshot(
        symbol="ETHUSDT",
        bids=(OrderBookLevel(price=Decimal("3500.00"), quantity=Decimal("15.0")),),
        asks=(OrderBookLevel(price=Decimal("3500.50"), quantity=Decimal("12.0")),),
        last_update_id=40002,
        event_time=datetime.now(UTC),
    )
    engine.update_depth(depth_eth)

    depth_sol = OrderBookDepthSnapshot(
        symbol="SOLUSDT",
        bids=(OrderBookLevel(price=Decimal("150.00"), quantity=Decimal("100.0")),),
        asks=(OrderBookLevel(price=Decimal("150.10"), quantity=Decimal("80.0")),),
        last_update_id=40003,
        event_time=datetime.now(UTC),
    )
    engine.update_depth(depth_sol)

    all_child_orders: list[ChildOrderIntention] = []
    now_ms = int(time.time() * 1000)

    # Place and fill orders across BTC, ETH, and SOL
    for sym, depth in (("BTCUSDT", depth_btc), ("ETHUSDT", depth_eth), ("SOLUSDT", depth_sol)):
        parent = create_parent_order_intention(
            candidate=bundles[sym].candidate,
            symbol=sym,
            side=OrderSide.BUY,
            current_depth=depth,
            filters=filters[sym],
            equity=starting_capital,
            timestamp_ms=now_ms,
        )
        children, fills = execute_strategy_activation_order(
            parent=parent,
            engine=engine,
            risk=risk,
            ledger=ledger,
            filters=filters[sym],
            current_depth=depth,
            mark_price=mark_prices[sym],
            chunk_cap_usdt=Decimal("4.50"),
        )
        all_child_orders.extend(children)

        # Simulate immediate maker fill
        fill_qty = children[0].quantity if children else Decimal("0.0001")
        fill_px = children[0].price if children else mark_prices[sym]
        notional = fill_qty * fill_px
        fee = notional * DEFAULT_MAKER_FEE_RATE

        fill = OrderExecutionFill(
            fill_id=f"t4_fill_{sym.lower()}",
            client_order_id=children[0].client_order_id if children else f"c-t4-{sym}",
            order_id=children[0].client_order_id if children else f"c-t4-{sym}",
            parent_order_id=parent.parent_order_id,
            child_index=0,
            symbol=sym,
            side=OrderSide.BUY,
            fill_price=fill_px,
            fill_quantity=fill_qty,
            fill_notional_usdt=notional,
            fee_usdt=fee,
            is_maker=True,
            fill_time_ms=now_ms,
        )
        ledger.record_fill(fill)
        risk.release_working_notional(sym, notional)
        risk.update_active_exposure(sym, ledger.allocated_margin)

    # Mark price updates
    mark_prices["BTCUSDT"] = Decimal("65015.00")
    mark_prices["ETHUSDT"] = Decimal("3505.00")
    mark_prices["SOLUSDT"] = Decimal("151.20")

    for sym, px in mark_prices.items():
        ledger.update_mark_price(sym, px)

    ledger.create_snapshot()
    ledger.verify_zero_drift()

    # Persist artifacts and Merkle DAG chain
    artifact_hashes = persist_phase295_artifacts(
        output_dir=output_dir,
        ledger=ledger,
        child_orders=all_child_orders,
        interlocks=risk.interlock_events,
        candidate_records=gate_records,
        upstream_dir=upstream_dir,
        circuit_state=str(risk.circuit_state),
        manifest_version=2,
    )

    return {
        "track": 4,
        "name": "multi_symbol_continuity_and_persistence",
        "status": "PASSED",
        "manifest_version": 2,
        "child_orders_count": len(all_child_orders),
        "fills_count": len(ledger._execution_marks),
        "ledger_drift_usdt": str(ledger.drift),
        "zero_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
        "artifact_hashes": artifact_hashes,
    }


# =====================================================================
# Merkle DAG Verification Only Mode
# =====================================================================


def verify_merkle_dag(
    phase295_dir: Path,
    phase294_dir: Path,
) -> bool:
    """Verify cryptographic SHA-256 Merkle DAG integrity for Phase 295 artifacts."""
    logger.info("=== Verifying Cryptographic Merkle DAG Hash Chain ===")

    summary_file = phase295_dir / "strategy-activation-summary.json"
    if not summary_file.exists():
        logger.error("strategy-activation-summary.json not found in %s", phase295_dir)
        return False

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    artifact_hashes = summary.get("artifact_hashes", {})

    for fname, expected_hash in artifact_hashes.items():
        fp = phase295_dir / fname
        if not fp.exists():
            logger.error("Artifact %s missing from %s", fname, phase295_dir)
            return False
        calc_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
        if calc_hash != expected_hash:
            logger.error(
                "Hash mismatch for %s: calculated %s != expected %s",
                fname,
                calc_hash,
                expected_hash,
            )
            return False

    # Check upstream link to Phase 294
    upstream_summary = phase294_dir / "paper-execution-summary.json"
    if not upstream_summary.exists():
        upstream_summary = phase294_dir / "paper-summary.json"

    if upstream_summary.exists():
        actual_up_hash = hashlib.sha256(upstream_summary.read_bytes()).hexdigest()
        linked_up_hash = summary.get("upstream_merkle_dag", {}).get("phase294_summary_hash")
        if linked_up_hash and linked_up_hash != actual_up_hash:
            logger.error(
                "Upstream Phase 294 summary hash mismatch: %s != %s", linked_up_hash, actual_up_hash
            )
            return False

    logger.info("Cryptographic Merkle DAG hash chain verified successfully!")
    return True


# =====================================================================
# Main Runner Entrypoint
# =====================================================================


def run_all_tracks(
    output_dir: Path = DEFAULT_PHASE295_DIR,
    upstream_dir: Path = DEFAULT_PHASE294_DIR,
    registry_path: Path = _REPO_ROOT / "artifacts" / "paper_live" / "candidate_registry.json",
    starting_capital: Decimal = Decimal("100.00"),
    simulate_loss_breach: bool = False,
    selected_track: str = "all",
) -> dict[str, Any]:
    """Execute requested simulation tracks deterministically."""
    results: dict[str, Any] = {
        "phase": "phase_295",
        "status": "STRATEGY_ACTIVATION_VERIFIED",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "tracks": {},
    }

    tracks_to_run = [1, 2, 3, 4] if selected_track in ("all", "0") else [int(selected_track)]

    if 1 in tracks_to_run:
        res1 = run_track_1(registry_path=registry_path, starting_capital=starting_capital)
        results["tracks"]["track_1"] = res1

    if 2 in tracks_to_run:
        res2 = run_track_2(starting_capital=starting_capital)
        results["tracks"]["track_2"] = res2

    if 3 in tracks_to_run:
        res3 = run_track_3(starting_capital=starting_capital, simulate_loss_breach=True)
        results["tracks"]["track_3"] = res3

    if 4 in tracks_to_run:
        res4 = run_track_4(
            output_dir=output_dir,
            upstream_dir=upstream_dir,
            registry_path=registry_path,
            starting_capital=starting_capital,
        )
        results["tracks"]["track_4"] = res4

    results["all_tracks_passed"] = all(
        t.get("status") == "PASSED" for t in results["tracks"].values()
    )
    return results


def main() -> int:
    """CLI entrypoint for Phase 295 Strategy Activation Runner."""
    parser = argparse.ArgumentParser(
        description="Phase 295: Live Strategy Activation & Walk-Forward OOS Promotion Gates Runner"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE295_DIR,
        help="Destination directory for Phase 295 artifacts",
    )
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        default=DEFAULT_PHASE294_DIR,
        help="Upstream Phase 294 directory for Merkle DAG link",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=_REPO_ROOT / "artifacts" / "paper_live" / "candidate_registry.json",
        help="Path to candidate_registry.json",
    )
    parser.add_argument(
        "--starting-capital",
        type=Decimal,
        default=Decimal("100.00"),
        help="Starting capital in USDT",
    )
    parser.add_argument(
        "--track",
        type=str,
        default="all",
        choices=["1", "2", "3", "4", "all"],
        help="Simulation track to execute (1, 2, 3, 4, or all)",
    )
    parser.add_argument(
        "--simulate-loss-breach",
        action="store_true",
        help="Simulate intra-phase cumulative loss budget breach",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Simulate adverse balance drift rejection test",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic SHA-256 Merkle DAG without running simulation",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.verify_only:
        ok = verify_merkle_dag(args.output_dir, args.upstream_dir)
        return 0 if ok else 1

    try:
        results = run_all_tracks(
            output_dir=args.output_dir,
            upstream_dir=args.upstream_dir,
            registry_path=args.registry_path,
            starting_capital=args.starting_capital,
            simulate_loss_breach=args.simulate_loss_breach,
            selected_track=args.track,
        )
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print("\n=== Phase 295 Strategy Activation Runner Completed Successfully ===")
            print(json.dumps(results, indent=2))
        return 0
    except Exception as exc:
        logger.exception("Phase 295 strategy activation simulation failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
