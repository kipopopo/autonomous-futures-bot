"""Phase 297: Extreme Market Stress, Flash Crash Simulation & Fault Injection Resilience Runner.

Executes 4 deterministic simulation tracks:
- Track 1: Nominal & Sequence Recovery Baseline Drill
- Track 2: Flash Crash Shock & Sub-ms Auto-Flattening Drill (< 1 ms, loss <= 7.00 USDT)
- Track 3: Liquidity Evaporation, Wide Spread & Toxic OFI Drill (Spread 10%, SPREAD_SHOCK_VETO)
- Track 4: Multi-Vector Crisis & Merkle DAG Packaging (linking Phase 296 parent hash)

Strictly enforces:
- EXECUTION AUTHORITY: OFF
- Continuous mathematical double-entry zero-drift balance governance (|drift| < 10^-15 USDT)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure project root and src/ are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.autonomous_lifecycle import (  # noqa: E402
    AutonomousLifecycleDaemon,
    SessionStatus,
)
from autonomous_futures.feed.models import (  # noqa: E402
    AggregateTrade,
    MarkPriceSnapshot,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)
from autonomous_futures.feed.paper_execution import (  # noqa: E402
    OrderSide,
)
from autonomous_futures.feed.paper_risk import (  # noqa: E402
    CircuitState,
    InterlockCode,
)
from autonomous_futures.feed.stress_fault_injection import (  # noqa: E402
    DEFAULT_PHASE296_DIR,
    DEFAULT_PHASE297_DIR,
    PHASE296_PARENT_HASH_EXPECTED,
    SUB_MS_LATENCY_CEILING_US,
    MarketFaultInjector,
    OnlineStressEvaluationEngine,
    ShockConfiguration,
    ShockVectorType,
    StressCircuitState,
    persist_phase297_artifacts,
    verify_phase297_artifacts,
)

logger = logging.getLogger("run_phase_297_stress_fault_injection")


# =====================================================================
# Synthetic Market Data Helper Functions
# =====================================================================


def _make_synthetic_depth(
    symbol: str,
    base_price: Decimal,
    update_id: int,
    prev_update_id: int | None = None,
    spread: Decimal = Decimal("1.00"),
    ts: datetime | None = None,
) -> OrderBookDepthSnapshot:
    """Construct deterministic top-5 depth snapshot."""
    event_time = ts or datetime.now(UTC)
    half_spread = spread / Decimal("2")
    best_bid = base_price - half_spread
    best_ask = base_price + half_spread
    step = spread / Decimal("5")

    bids = tuple(
        OrderBookLevel(price=best_bid - (step * Decimal(i)), quantity=Decimal("1.50") + Decimal(i))
        for i in range(5)
    )
    asks = tuple(
        OrderBookLevel(price=best_ask + (step * Decimal(i)), quantity=Decimal("1.50") + Decimal(i))
        for i in range(5)
    )

    return OrderBookDepthSnapshot(
        symbol=symbol.upper(),
        bids=bids,
        asks=asks,
        last_update_id=update_id,
        prev_last_update_id=prev_update_id,
        event_time=event_time,
    )


def _make_synthetic_trade(
    symbol: str,
    price: Decimal,
    quantity: Decimal,
    trade_id: int,
    is_buyer_maker: bool = False,
    ts: datetime | None = None,
) -> AggregateTrade:
    """Construct deterministic AggregateTrade."""
    return AggregateTrade(
        symbol=symbol.upper(),
        aggregate_trade_id=trade_id,
        price=price,
        quantity=quantity,
        first_trade_id=trade_id * 10,
        last_trade_id=trade_id * 10 + 1,
        trade_time=ts or datetime.now(UTC),
        is_buyer_maker=is_buyer_maker,
    )


def _make_synthetic_mark(
    symbol: str,
    mark_price: Decimal,
    ts: datetime | None = None,
) -> MarkPriceSnapshot:
    """Construct deterministic MarkPriceSnapshot."""
    return MarkPriceSnapshot(
        symbol=symbol.upper(),
        mark_price=mark_price,
        index_price=mark_price,
        estimated_settle_price=mark_price,
        funding_rate=Decimal("0.0001"),
        next_funding_time=(ts or datetime.now(UTC)) + timedelta(hours=8),
        event_time=ts or datetime.now(UTC),
    )


# =====================================================================
# Track 1: Nominal & Sequence Recovery Baseline Drill
# =====================================================================


def run_track_1(
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 1: Nominal Ingress, Strategy Evaluation & Clean Disconnect Recovery."""
    logger.info("=== Running Track 1: Nominal & Sequence Recovery Baseline Drill ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        registry_path=registry_path,
        repo_root=_REPO_ROOT,
    )
    injector = MarketFaultInjector(symbols=tuple(daemon.symbols))
    engine = OnlineStressEvaluationEngine(daemon=daemon, injector=injector)

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    base_prices = {
        "BTCUSDT": Decimal("60000.00"),
        "ETHUSDT": Decimal("3000.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    # Session 1: Nominal Ingress & Micro Order Execution
    daemon.start_session("track1_session_001")
    seq_u = 1000
    seq_a = 5000
    base_time = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

    for i in range(20):
        t_now = base_time + timedelta(seconds=i)
        for sym in symbols:
            seq_u += 1
            seq_a += 1
            bp = base_prices[sym] + Decimal(i * 2)

            mark = _make_synthetic_mark(sym, bp, ts=t_now)
            daemon.on_mark_price(mark)

            depth = _make_synthetic_depth(
                sym, bp, update_id=seq_u, prev_update_id=seq_u - 1, ts=t_now
            )
            daemon.on_depth(depth)

            trade = _make_synthetic_trade(sym, bp, Decimal("0.05"), trade_id=seq_a, ts=t_now)
            daemon.on_trade(trade)

            # Evaluate microstructure tick (assert nominal, sub-millisecond)
            tripped, _, lat_us = engine.evaluate_microstructure_tick(
                symbol=sym, depth=depth, trade=trade, mark=mark, hawkes_rho=Decimal("0.45")
            )
            assert not tripped, f"Spurious trip during nominal conditions: {sym}"
            assert lat_us < SUB_MS_LATENCY_CEILING_US, f"Sub-ms latency breached: {lat_us} us"

    # Place and fill small order in BTCUSDT
    orders, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
    if orders:
        fill_trade = _make_synthetic_trade(
            "BTCUSDT",
            base_prices["BTCUSDT"],
            Decimal("1.0"),
            trade_id=seq_a + 10,
            is_buyer_maker=False,
            ts=base_time + timedelta(seconds=21),
        )
        daemon.on_trade(fill_trade)

    is_valid, drift = engine.assert_double_entry_zero_drift()
    assert is_valid, f"Zero drift breached: {drift}"

    # Simulate disconnect and clean recovery
    daemon.simulate_disconnect(reason="simulated_wire_drop")
    assert daemon.get_status() == SessionStatus.DISCONNECTED
    daemon.recover_connection(reason="simulated_wire_restore")
    assert daemon.get_status() == SessionStatus.ACTIVE

    daemon.end_session()

    return {
        "track": 1,
        "name": "nominal_and_recovery_baseline",
        "status": "PASSED",
        "total_sessions": len(daemon._sessions_history),
        "total_orders_placed": len(daemon._child_orders),
        "total_fills_count": len(daemon._execution_marks),
        "zero_balance_drift": is_valid,
        "drift_usdt": str(drift),
        "circuit_state": str(engine.circuit_state),
    }


# =====================================================================
# Track 2: Flash Crash Shock & Sub-ms Emergency Auto-Flattening
# =====================================================================


def run_track_2(
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 2: Instantaneous -20% Flash Crash.

    Sub-ms Breaker Trip & Micro-Chunked Liquidation.
    """
    logger.info("=== Running Track 2: Flash Crash Shock & Auto-Flattening Drill ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        registry_path=registry_path,
        repo_root=_REPO_ROOT,
    )
    injector = MarketFaultInjector(symbols=tuple(daemon.symbols))
    engine = OnlineStressEvaluationEngine(
        daemon=daemon,
        injector=injector,
        loss_budget_usdt=Decimal("7.00"),
    )

    sym = "BTCUSDT"
    base_price = Decimal("60000.00")
    t0 = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)

    # 1. Start session & establish open long position
    daemon.start_session("track2_flash_crash_001")
    depth = _make_synthetic_depth(sym, base_price, update_id=500, prev_update_id=None, ts=t0)
    daemon.on_depth(depth)
    daemon.on_mark_price(_make_synthetic_mark(sym, base_price, ts=t0))

    orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
    assert len(orders) > 0, "Expected generated child orders"
    fill_price = orders[0].price
    trade_fill = _make_synthetic_trade(
        sym, fill_price, Decimal("5.0"), trade_id=6000, is_buyer_maker=True, ts=t0
    )
    daemon.on_trade(trade_fill)
    assert daemon.ledger.allocated_margin > Decimal("0"), "Expected active allocated margin"

    # 2. Arm and inject Flash Crash Shock (-20.0% sudden drop)
    shock_cfg = ShockConfiguration(
        shock_type=ShockVectorType.FLASH_CRASH,
        target_symbols=(sym,),
        price_drop_pct=Decimal("0.20"),
    )
    injector.arm_shock(shock_cfg)

    # Transform market feeds via injector
    crashed_depth, _ = injector.transform_depth(depth)
    crashed_trade, _ = injector.transform_trade(trade_fill)
    crashed_mark, _ = injector.transform_mark_price(_make_synthetic_mark(sym, base_price, ts=t0))

    # Ingest crashed tick
    daemon.on_depth(crashed_depth)
    daemon.on_mark_price(crashed_mark)
    daemon.on_trade(crashed_trade)

    # 3. Evaluate Microstructure Anomaly & Measure Sub-Millisecond Latency
    tripped, reason, latency_us = engine.evaluate_microstructure_tick(
        symbol=sym,
        depth=crashed_depth,
        trade=crashed_trade,
        mark=crashed_mark,
    )

    assert tripped is True, "Flash crash price drop must trip circuit breaker"
    assert latency_us < SUB_MS_LATENCY_CEILING_US, (
        f"Latency {latency_us:.2f} us exceeded 1.0 ms ceiling"
    )

    # 4. Verify Emergency Auto-Flattening Liquidation
    # Position must be closed (allocated margin == 0)
    assert daemon.ledger.allocated_margin == Decimal("0"), (
        "Expected 0 allocated margin after auto-flattening"
    )
    assert daemon.risk.circuit_state == CircuitState.HALTED, "Risk circuit must be HALTED"
    assert daemon.get_status() == SessionStatus.HALTED, "Daemon status must be HALTED"

    # Verify orders are purged
    active_resting = [o for o in daemon.matching_engine._resting_orders.values() if o.is_active]
    assert len(active_resting) == 0, "All resting orders must be purged"

    # Verify loss capped within intra-phase loss budget (<= 7.00 USDT)
    pnl = daemon.ledger.realized_pnl
    cumulative_loss = abs(pnl) if pnl < Decimal("0") else Decimal("0")
    assert cumulative_loss <= Decimal("7.00"), (
        f"Loss {cumulative_loss} exceeded 7.00 USDT budget ceiling"
    )
    assert daemon.ledger.total_equity > Decimal("0"), "Capital preservation failed (bankruptcy)"

    # Verify double-entry zero-drift balance
    is_valid, drift = engine.assert_double_entry_zero_drift()
    assert is_valid, f"Zero-drift verification failed: {drift}"

    # Subsequent strategy evaluation must reject fail-closed
    blocked_orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
    assert len(blocked_orders) == 0, "Orders must be blocked when circuit is HALTED"

    daemon.end_session()

    flattening_fills = sum(1 for f in daemon._execution_marks if "flatten" in f.client_order_id)

    return {
        "track": 2,
        "name": "flash_crash_sub_ms_auto_flattening",
        "status": "PASSED",
        "breaker_tripped": tripped,
        "reaction_latency_us": round(latency_us, 2),
        "reaction_latency_ms": round(latency_us / 1000.0, 4),
        "sub_millisecond_compliant": latency_us < SUB_MS_LATENCY_CEILING_US,
        "circuit_state": str(engine.circuit_state),
        "daemon_status": str(daemon.get_status()),
        "flattening_fills_count": flattening_fills,
        "final_cash_usdt": str(daemon.ledger.cash),
        "final_equity_usdt": str(daemon.ledger.total_equity),
        "realized_loss_usdt": str(cumulative_loss),
        "loss_budget_respected": cumulative_loss <= Decimal("7.00"),
        "zero_balance_drift": is_valid,
        "drift_usdt": str(drift),
    }


# =====================================================================
# Track 3: Liquidity Evaporation & Wide Spread Shock Drill
# =====================================================================


def run_track_3(
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 3: Liquidity Evaporation (10% spread, 95% depletion) & SPREAD_SHOCK_VETO."""
    logger.info("=== Running Track 3: Liquidity Evaporation & Spread Shock Drill ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        registry_path=registry_path,
        repo_root=_REPO_ROOT,
    )
    injector = MarketFaultInjector(symbols=tuple(daemon.symbols))
    engine = OnlineStressEvaluationEngine(daemon=daemon, injector=injector)

    sym = "BTCUSDT"
    base_price = Decimal("60000.00")
    t0 = datetime(2026, 9, 21, 16, 0, tzinfo=UTC)

    daemon.start_session("track3_liquidity_shock_001")
    normal_depth = _make_synthetic_depth(sym, base_price, update_id=100, ts=t0)
    daemon.on_depth(normal_depth)
    daemon.on_mark_price(_make_synthetic_mark(sym, base_price, ts=t0))

    # 1. Arm Liquidity Evaporation Shock (spread 10.0%, 95% depletion)
    liq_cfg = ShockConfiguration(
        shock_type=ShockVectorType.LIQUIDITY_EVAPORATION,
        target_symbols=(sym,),
        spread_pct=Decimal("0.10"),  # 10.0% spread (1,000 bps)
        depth_depletion_pct=Decimal("0.95"),
    )
    injector.arm_shock(liq_cfg)

    # Generate and ingest wide-spread depth with sequential update_id
    shock_depth_raw = _make_synthetic_depth(
        sym, base_price, update_id=101, prev_update_id=100, ts=t0
    )
    wide_depth, _ = injector.transform_depth(shock_depth_raw)
    daemon.on_depth(wide_depth)

    # 2. Microstructure anomaly evaluation
    tripped, reason, lat_us = engine.evaluate_microstructure_tick(symbol=sym, depth=wide_depth)
    assert tripped is True, "Wide spread shock must trip circuit breaker"
    assert "Relative spread" in reason, f"Unexpected trip reason: {reason}"
    assert lat_us < SUB_MS_LATENCY_CEILING_US, f"Sub-ms latency breached: {lat_us} us"

    # 3. Verify Pre-Trade Interlock: SPREAD_SHOCK_VETO actively blocks order dispatch
    spread_pct = Decimal("10.00")
    decision = daemon.risk.validate_pre_trade_interlocks(
        symbol=sym,
        proposed_notional=Decimal("4.50"),
        bid_ask_spread_pct=spread_pct,
    )
    assert decision.allowed is False, "Order must be blocked under spread shock"
    assert decision.code == InterlockCode.SPREAD_SHOCK_VETO, (
        f"Expected SPREAD_SHOCK_VETO, got {decision.code}"
    )

    # Evaluate strategy with daemon - orders must not be placed into the evaporated book
    orders, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
    # The spread shock prevents order execution
    active_resting = [o for o in daemon.matching_engine._resting_orders.values() if o.is_active]
    assert len(active_resting) == 0, "No orders should rest in the vacuum"

    # 4. Disarm spread shock and verify recovery
    injector.disarm_shock(ShockVectorType.LIQUIDITY_EVAPORATION)
    recovered_depth = _make_synthetic_depth(
        sym,
        base_price,
        update_id=102,
        prev_update_id=101,
        spread=Decimal("1.00"),
        ts=t0 + timedelta(seconds=1),
    )
    daemon.on_depth(recovered_depth)

    is_valid, drift = engine.assert_double_entry_zero_drift()
    assert is_valid, f"Drift {drift} detected in Track 3"

    daemon.end_session()

    return {
        "track": 3,
        "name": "liquidity_evaporation_spread_shock",
        "status": "PASSED",
        "spread_shock_tripped": tripped,
        "spread_veto_code": decision.code.value,
        "reaction_latency_us": round(lat_us, 2),
        "reaction_latency_ms": round(lat_us / 1000.0, 4),
        "zero_orders_rested": len(active_resting) == 0,
        "zero_balance_drift": is_valid,
        "drift_usdt": str(drift),
    }


# =====================================================================
# Track 4: Multi-Vector Crisis & Cryptographic Merkle DAG Persistence
# =====================================================================


def run_track_4(
    output_dir: Path,
    upstream_dir: Path,
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 4: Multi-Vector Crisis.

    Continuous Zero-Drift Balance & Merkle DAG Packaging.
    """
    logger.info("=== Running Track 4: Multi-Vector Crisis & Merkle DAG Persistence ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        registry_path=registry_path,
        repo_root=_REPO_ROOT,
    )
    injector = MarketFaultInjector(symbols=tuple(daemon.symbols))
    engine = OnlineStressEvaluationEngine(
        daemon=daemon,
        injector=injector,
        loss_budget_usdt=Decimal("7.00"),
    )

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    base_prices = {
        "BTCUSDT": Decimal("60000.00"),
        "ETHUSDT": Decimal("3000.00"),
        "SOLUSDT": Decimal("150.00"),
    }
    t0 = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)

    # 1. Start Session & Seed Normal Ticks
    daemon.start_session("track4_multi_crisis_001")
    for i in range(10):
        t_now = t0 + timedelta(seconds=i)
        for sym in symbols:
            bp = base_prices[sym]
            daemon.on_mark_price(_make_synthetic_mark(sym, bp, ts=t_now))
            daemon.on_depth(_make_synthetic_depth(sym, bp, update_id=1000 + i, ts=t_now))
            trade = _make_synthetic_trade(sym, bp, Decimal("0.05"), trade_id=2000 + i, ts=t_now)
            daemon.on_trade(trade)

    # Place and fill small order in ETHUSDT to have an active position
    orders, _ = daemon.evaluate_strategy(symbol="ETHUSDT", force_side=OrderSide.BUY)
    if orders:
        daemon.on_trade(
            _make_synthetic_trade(
                "ETHUSDT",
                base_prices["ETHUSDT"],
                Decimal("5.0"),
                trade_id=2050,
                is_buyer_maker=True,
                ts=t0,
            )
        )

    # 2. Inject Composite Multi-Vector Crisis:
    # - Vector 4: Telemetry Degradation (Clock Skew 650 ms, gap jump > 1000)
    # - Vector 3: Phantom Depth / Spoofing (|OFI| > 0.95)
    # - Vector 1: Flash Crash (-20%)
    injector.arm_shock(
        ShockConfiguration(
            shock_type=ShockVectorType.TELEMETRY_DEGRADATION,
            clock_skew_ms=650.0,
            silence_duration_ms=800,
        )
    )
    injector.arm_shock(
        ShockConfiguration(
            shock_type=ShockVectorType.PHANTOM_DEPTH_SPOOFING,
            asymmetry_ratio=Decimal("0.98"),
        )
    )
    injector.arm_shock(
        ShockConfiguration(
            shock_type=ShockVectorType.FLASH_CRASH,
            price_drop_pct=Decimal("0.20"),
        )
    )

    # Transform telemetry & depth
    telemetry_age, clock_skew, _ = injector.transform_telemetry(0.0, 0.0)
    depth_eth = _make_synthetic_depth("ETHUSDT", base_prices["ETHUSDT"], update_id=1020, ts=t0)
    crashed_eth_depth, _ = injector.transform_depth(depth_eth)
    mark_eth = _make_synthetic_mark("ETHUSDT", base_prices["ETHUSDT"], ts=t0)
    crashed_eth_mark, _ = injector.transform_mark_price(mark_eth)

    # Evaluate multi-vector shock tick
    tripped, reason, lat_us = engine.evaluate_microstructure_tick(
        symbol="ETHUSDT",
        depth=crashed_eth_depth,
        mark=crashed_eth_mark,
        heartbeat_age_ms=telemetry_age,
        clock_skew_ms=clock_skew,
        hawkes_rho=Decimal("1.25"),  # Supercritical runaway
    )

    assert tripped is True, "Multi-vector shock must trip circuit breaker"
    assert lat_us < SUB_MS_LATENCY_CEILING_US, f"Sub-ms latency breached: {lat_us} us"

    # Trigger emergency auto-flattening to preserve capital
    engine.trigger_emergency_auto_flattening(reason="multi_vector_crisis")
    assert daemon.ledger.allocated_margin == Decimal("0"), (
        "Allocated margin must be 0 after emergency flattening"
    )
    assert engine.circuit_state == StressCircuitState.HALTED, "Circuit state must be HALTED"

    # Assert continuous mathematical double-entry zero-drift balance governance
    is_valid, drift = engine.assert_double_entry_zero_drift()
    assert is_valid, f"Zero-drift balance check failed: {drift}"

    daemon.end_session()

    # 3. Persist All Research Artifacts to artifacts/research/phase297/
    logger.info("Persisting Phase 297 research artifacts to %s", output_dir)
    artifact_hashes = persist_phase297_artifacts(
        engine=engine,
        output_dir=output_dir,
        upstream_dir=upstream_dir,
        manifest_version=2,
    )

    # 4. Verify Cryptographic SHA-256 Merkle DAG Hash Chain
    logger.info("Verifying Phase 297 Merkle DAG integrity...")
    dag_verified = verify_phase297_artifacts(
        phase297_dir=output_dir,
        phase296_dir=upstream_dir,
    )
    assert dag_verified is True, "Phase 297 Merkle DAG verification failed!"

    lat_summary = engine.get_reaction_latencies_summary()

    return {
        "track": 4,
        "name": "multi_vector_crisis_and_merkle_dag_persistence",
        "status": "PASSED",
        "composite_shock_tripped": tripped,
        "reaction_latency_us": round(lat_us, 2),
        "reaction_latencies_summary": lat_summary,
        "circuit_state": str(engine.circuit_state),
        "zero_balance_drift": is_valid,
        "drift_usdt": str(drift),
        "artifact_hashes": artifact_hashes,
        "merkle_dag_verified": dag_verified,
        "upstream_phase296_parent_hash": PHASE296_PARENT_HASH_EXPECTED,
    }


# =====================================================================
# Main Runner Entrypoint
# =====================================================================


def main() -> int:
    """CLI entrypoint for Phase 297 Stress Fault Injection Runner."""
    parser = argparse.ArgumentParser(
        description="Phase 297: Extreme Market Stress & Fault Injection Runner"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE297_DIR,
        help="Directory to persist Phase 297 research artifacts",
    )
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        default=DEFAULT_PHASE296_DIR,
        help="Directory containing upstream Phase 296 summary artifacts",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=_REPO_ROOT / "artifacts" / "paper_live" / "candidate_registry.json",
        help="Path to CandidateRegistryManifest v2",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing Merkle DAG artifacts without re-running simulations",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose log messages",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.verify_only:
        logger.info("Executing Phase 297 verification-only check...")
        success = verify_phase297_artifacts(
            phase297_dir=args.output_dir,
            phase296_dir=args.upstream_dir,
        )
        if success:
            print("PHASE 297 MERKLE DAG INTEGRITY: VERIFIED")
            return 0
        else:
            print("PHASE 297 MERKLE DAG INTEGRITY: FAILED")
            return 1

    print("=" * 70)
    print("PHASE 297: EXTREME MARKET STRESS & FAULT INJECTION RESILIENCE RUNNER")
    print("=" * 70)

    try:
        t1 = run_track_1(registry_path=args.registry_path)
        print(f"Track 1 (Nominal & Recovery): PASSED | Drift: {t1['drift_usdt']} USDT")

        t2 = run_track_2(registry_path=args.registry_path)
        print(
            f"Track 2 (Flash Crash Auto-Flat): PASSED | "
            f"Latency: {t2['reaction_latency_us']} us (< 1 ms) | "
            f"Loss: {t2['realized_loss_usdt']} USDT (Budget: 7.00 USDT) | "
            f"Drift: {t2['drift_usdt']} USDT"
        )

        t3 = run_track_3(registry_path=args.registry_path)
        print(
            f"Track 3 (Spread Shock Veto): PASSED | "
            f"Veto: {t3['spread_veto_code']} | "
            f"Latency: {t3['reaction_latency_us']} us | "
            f"Drift: {t3['drift_usdt']} USDT"
        )

        t4 = run_track_4(
            output_dir=args.output_dir,
            upstream_dir=args.upstream_dir,
            registry_path=args.registry_path,
        )
        print(
            f"Track 4 (Multi-Vector Crisis & Merkle DAG): PASSED | "
            f"Drift: {t4['drift_usdt']} USDT | "
            f"DAG: {t4['merkle_dag_verified']}"
        )

        print("\nALL 4 DETERMINISTIC STRESS TRACKS PASSED CLEANLY.")
        print(f"Artifacts persisted to: {args.output_dir}")
        print("Merkle DAG chained to Phase 296 parent hash successfully.")
        return 0

    except Exception as exc:
        logger.exception("Phase 297 execution error: %s", exc)
        print(f"\nPHASE 297 EXECUTION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
