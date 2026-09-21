"""Phase 296: Full Autonomous Lifecycle Orchestration & Multi-Session Longevity Runner.

Executes deterministic multi-session lifecycle simulations with:
- Unified Ingress, Hawkes Microstructure Streaming, Strategy Activation, and Passive Matching
- Multi-Session Longevity & Reconnection Engine (preserving positions & equity)
- Sequence Gap Detection & Packet Deduplication via PublicMarketStreamSequencer
- Bounded Memory Buffers (O(1) footprint across continuous event streams)
- Continuous Fail-Closed Risk Interlocks (Freshness, Clock drift, Hawkes rho, Loss budget)
- Continuous Mathematical Double-Entry Zero-Drift Balance Governance (|drift| < 10^-15 USDT)
- Isolated SQLite Telemetry (7 tables) & SHA-256 Merkle DAG Hash Chain Persistence linking Phase 295

4 Deterministic Simulation Tracks:
- Track 1: Nominal Multi-Session Lifecycle Replay
- Track 2: Multi-Session Recovery and Continuity Drill
- Track 3: Sequence Gap and Packet Deduplication Drill
- Track 4: Memory Boundedness and Merkle DAG Persistence
"""

from __future__ import annotations

import argparse
import json
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
    DEFAULT_PHASE295_DIR,
    DEFAULT_PHASE296_DIR,
    DOUBLE_ENTRY_MAX_DRIFT,
    AutonomousLifecycleDaemon,
    SessionStatus,
    persist_phase296_artifacts,
    verify_phase296_artifacts,
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

logger = logging.getLogger("run_phase_296_autonomous_lifecycle")


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
# Track 1: Nominal Multi-Session Lifecycle Replay
# =====================================================================


def run_track_1(
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 1: Nominal Multi-Session Ingress, Strategy Evaluation & Order Execution."""
    logger.info("=== Running Track 1: Nominal Multi-Session Lifecycle Replay ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        registry_path=registry_path,
        repo_root=_REPO_ROOT,
    )

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    base_prices = {
        "BTCUSDT": Decimal("60000.00"),
        "ETHUSDT": Decimal("3000.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    # Execute Session 1
    daemon.start_session("track1_session_001")
    seq_u = 1000
    seq_a = 5000
    base_time = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

    # Ingest seed ticks across all symbols
    for i in range(25):
        t_now = base_time + timedelta(seconds=i)
        for sym in symbols:
            seq_u += 1
            seq_a += 1
            bp = base_prices[sym] + Decimal(i * 2)

            # Mark price
            daemon.on_mark_price(_make_synthetic_mark(sym, bp, ts=t_now))

            # Depth snapshot
            prev_u = seq_u - 1 if i > 0 else None
            depth = _make_synthetic_depth(sym, bp, update_id=seq_u, prev_update_id=prev_u, ts=t_now)
            daemon.on_depth(depth)

            # Trade tick
            trade = _make_synthetic_trade(sym, bp, Decimal("0.05"), trade_id=seq_a, ts=t_now)
            daemon.on_trade(trade)

    # Evaluate strategy on Session 1
    orders_1, _ = daemon.evaluate_strategy(symbol="BTCUSDT", force_side=OrderSide.BUY)
    if orders_1:
        trade_fill1 = _make_synthetic_trade(
            "BTCUSDT",
            base_prices["BTCUSDT"],
            Decimal("1.0"),
            trade_id=seq_a + 50,
            is_buyer_maker=False,
            ts=base_time + timedelta(seconds=26),
        )
        daemon.on_trade(trade_fill1)

    orders_2, _ = daemon.evaluate_strategy(symbol="ETHUSDT", force_side=OrderSide.BUY)
    if orders_2:
        trade_fill2 = _make_synthetic_trade(
            "ETHUSDT",
            base_prices["ETHUSDT"],
            Decimal("5.0"),
            trade_id=seq_a + 51,
            is_buyer_maker=False,
            ts=base_time + timedelta(seconds=27),
        )
        daemon.on_trade(trade_fill2)

    # Verify zero-drift after fills
    is_valid, drift = daemon.verify_zero_drift()
    assert is_valid, f"Double-entry drift {drift} exceeds tolerance in Session 1"

    daemon.end_session()

    # Execute Session 2 (Disjoint continuation)
    daemon.start_session("track1_session_002")

    # Ingest more ticks in Session 2
    for i in range(25, 50):
        t_now = base_time + timedelta(seconds=i)
        for sym in symbols:
            seq_u += 1
            seq_a += 1
            bp = base_prices[sym] + Decimal(i * 2)

            daemon.on_mark_price(_make_synthetic_mark(sym, bp, ts=t_now))
            depth = _make_synthetic_depth(
                sym, bp, update_id=seq_u, prev_update_id=seq_u - 1, ts=t_now
            )
            daemon.on_depth(depth)
            trade = _make_synthetic_trade(sym, bp, Decimal("0.05"), trade_id=seq_a, ts=t_now)
            daemon.on_trade(trade)

    orders_3, _ = daemon.evaluate_strategy(symbol="SOLUSDT", force_side=OrderSide.BUY)
    if orders_3:
        trade_fill3 = _make_synthetic_trade(
            "SOLUSDT",
            base_prices["SOLUSDT"],
            Decimal("20.0"),
            trade_id=seq_a + 52,
            is_buyer_maker=False,
            ts=base_time + timedelta(seconds=51),
        )
        daemon.on_trade(trade_fill3)
    daemon.end_session()

    snapshot = daemon.get_telemetry_snapshot()

    return {
        "track": 1,
        "name": "nominal_multi_session_lifecycle",
        "status": "PASSED",
        "total_sessions": snapshot.total_sessions,
        "total_orders_placed": len(daemon._child_orders),
        "total_fills_count": len(daemon._execution_marks),
        "ledger_cash_usdt": snapshot.accounting["cash_usdt"],
        "ledger_equity_usdt": snapshot.accounting["total_equity_usdt"],
        "drift_usdt": snapshot.accounting["drift_usdt"],
        "zero_balance_drift": snapshot.accounting["zero_balance_drift"],
    }


# =====================================================================
# Track 2: Multi-Session Recovery and Continuity Drill
# =====================================================================


def run_track_2(
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 2: Multi-Session Recovery, Disconnection Drills & Continuity."""
    logger.info("=== Running Track 2: Multi-Session Recovery & Continuity Drill ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        repo_root=_REPO_ROOT,
    )

    sym = "BTCUSDT"
    base_price = Decimal("60000.00")
    t0 = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)

    # 1. Start Session 1
    daemon.start_session("track2_session_001")
    depth = _make_synthetic_depth(sym, base_price, update_id=101, prev_update_id=None, ts=t0)
    daemon.on_depth(depth)
    daemon.on_mark_price(_make_synthetic_mark(sym, base_price, ts=t0))

    # Place an initial micro order and fill it
    orders_1, _ = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
    assert len(orders_1) > 0, "Expected sliced orders in Session 1"
    fill_price = orders_1[0].price
    trade_fill = _make_synthetic_trade(
        sym, fill_price, Decimal("5.0"), trade_id=2001, is_buyer_maker=True, ts=t0
    )
    daemon.on_trade(trade_fill)
    initial_cash = daemon.ledger.cash
    initial_margin = daemon.ledger.allocated_margin
    assert initial_margin > Decimal("0"), "Expected allocated margin from fill"

    # 2. Simulate Mid-Session Transport Disconnect
    daemon.simulate_disconnect(reason="simulated_ws_eof")
    assert daemon.get_status() == SessionStatus.DISCONNECTED
    assert daemon._disconnect_count == 1

    # 3. Simulate Clean Auto-Recovery
    daemon.recover_connection(reason="simulated_ws_reconnect")
    assert daemon.get_status() == SessionStatus.ACTIVE
    assert daemon._reconnect_count == 1

    # Ingest new ticks after reconnect
    depth2 = _make_synthetic_depth(
        sym,
        base_price + Decimal("50.00"),
        update_id=102,
        prev_update_id=101,
        ts=t0 + timedelta(seconds=1),
    )
    daemon.on_depth(depth2)
    daemon.on_mark_price(
        _make_synthetic_mark(sym, base_price + Decimal("50.00"), ts=t0 + timedelta(seconds=1))
    )

    # Verify positions and cash were preserved across disconnect
    assert daemon.ledger.allocated_margin == initial_margin, "Margin lost during disconnect"
    is_valid, drift = daemon.verify_zero_drift()
    assert is_valid, f"Drift {drift} detected after reconnect"

    daemon.end_session()

    # 4. Start Session 2 without state loss
    daemon.start_session("track2_session_002")
    assert daemon.ledger.allocated_margin == initial_margin, "Margin lost across session boundary"
    assert daemon.ledger.cash == initial_cash, "Cash reset across session boundary"

    # End Session 2 cleanly
    daemon.end_session()

    return {
        "track": 2,
        "name": "multi_session_recovery_and_continuity",
        "status": "PASSED",
        "disconnect_count": daemon._disconnect_count,
        "reconnect_count": daemon._reconnect_count,
        "preserved_margin_usdt": str(daemon.ledger.allocated_margin),
        "zero_balance_drift": drift < DOUBLE_ENTRY_MAX_DRIFT,
        "drift_usdt": str(drift),
    }


# =====================================================================
# Track 3: Sequence Gap and Packet Deduplication Drill
# =====================================================================


def run_track_3(
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 3: Sequence Gap, Deduplication & Fail-Closed Interlocks Drill."""
    logger.info("=== Running Track 3: Sequence Gap & Deduplication Drill ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        repo_root=_REPO_ROOT,
    )

    daemon.start_session("track3_session_001")
    sym = "BTCUSDT"
    base_price = Decimal("60000.00")
    t0 = datetime(2026, 9, 21, 16, 0, tzinfo=UTC)

    # 1. Nominal depth packet
    d1 = _make_synthetic_depth(sym, base_price, update_id=200, prev_update_id=None, ts=t0)
    accepted_1 = daemon.on_depth(d1)
    assert accepted_1 is True

    # 2. Inject duplicate depth packet (u <= last_u)
    d_dup = _make_synthetic_depth(sym, base_price, update_id=200, prev_update_id=199, ts=t0)
    accepted_dup = daemon.on_depth(d_dup)
    assert accepted_dup is False, "Duplicate depth packet should be discarded"
    assert daemon.sequencer.duplicate_count >= 1, "Expected duplicate count increment"

    # 3. Inject sequence gap (pu != last_u)
    d_gap = _make_synthetic_depth(sym, base_price, update_id=250, prev_update_id=210, ts=t0)
    accepted_gap = daemon.on_depth(d_gap)
    assert accepted_gap is True
    assert daemon.sequencer.sequence_gap_count >= 1, "Expected sequence gap count increment"

    # 4. Inject duplicate trade packet (a <= last_a)
    t1 = _make_synthetic_trade(sym, base_price, Decimal("0.01"), trade_id=5000, ts=t0)
    daemon.on_trade(t1)
    t_dup = _make_synthetic_trade(sym, base_price, Decimal("0.01"), trade_id=5000, ts=t0)
    fills_dup = daemon.on_trade(t_dup)
    assert len(fills_dup) == 0, "Duplicate trade should produce zero fills"

    # 5. Fail-Closed Interlock Verification: Stale Gateway Heartbeat
    daemon._last_heartbeat_age_ms = 750.0  # > 500 ms limit
    orders_veto, fills_veto = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
    assert len(orders_veto) == 0, "Stale heartbeat should block order dispatch"
    daemon._last_heartbeat_age_ms = 0.0

    # 6. Fail-Closed Interlock Verification: Supercritical Hawkes Lockout
    daemon.simulate_supercritical_hawkes = True
    orders_super, fills_super = daemon.evaluate_strategy(symbol=sym, force_side=OrderSide.BUY)
    assert len(orders_super) == 0, "Supercritical Hawkes rho >= 1.0 must trigger lockout"
    daemon.simulate_supercritical_hawkes = False

    daemon.end_session()
    is_valid, drift = daemon.verify_zero_drift()

    return {
        "track": 3,
        "name": "sequence_gap_and_deduplication_drill",
        "status": "PASSED",
        "duplicate_packets_detected": daemon.sequencer.duplicate_count,
        "sequence_gaps_detected": daemon.sequencer.sequence_gap_count,
        "veto_events_logged": len(daemon._interlock_events),
        "zero_balance_drift": is_valid,
        "drift_usdt": str(drift),
    }


# =====================================================================
# Track 4: Memory Boundedness and Merkle DAG Persistence
# =====================================================================


def run_track_4(
    output_dir: Path,
    upstream_dir: Path,
    registry_path: Path,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, Any]:
    """Execute Track 4: High-Throughput Endurance, Bounded Memory & Merkle DAG Packaging."""
    logger.info("=== Running Track 4: Memory Boundedness & Merkle DAG Persistence ===")

    daemon = AutonomousLifecycleDaemon(
        starting_capital=starting_capital,
        registry_path=registry_path,
        repo_root=_REPO_ROOT,
    )

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    base_prices = {
        "BTCUSDT": Decimal("60000.00"),
        "ETHUSDT": Decimal("3000.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    # Run endurance loop of 1,200 events across 3 sessions
    t_start = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)
    seq_u = 10000
    seq_a = 50000

    for s_idx in range(1, 4):
        daemon.start_session(f"track4_session_{s_idx:03d}")

        for tick in range(100):
            t_now = t_start + timedelta(seconds=(s_idx * 100 + tick))
            for sym in symbols:
                seq_u += 1
                seq_a += 1
                bp = base_prices[sym] + Decimal((tick % 20) * 2)

                daemon.on_mark_price(_make_synthetic_mark(sym, bp, ts=t_now))
                depth = _make_synthetic_depth(
                    sym, bp, update_id=seq_u, prev_update_id=seq_u - 1, ts=t_now
                )
                daemon.on_depth(depth)
                trade = _make_synthetic_trade(sym, bp, Decimal("0.02"), trade_id=seq_a, ts=t_now)
                daemon.on_trade(trade)

                # Inject periodic duplicate packet to verify dedup_events persistence
                if s_idx == 2 and tick == 50 and sym == "BTCUSDT":
                    daemon.on_depth(depth)
                    daemon.on_trade(trade)

        # Place periodic micro orders
        if s_idx in (1, 2):
            target_sym = symbols[s_idx - 1]
            daemon.evaluate_strategy(symbol=target_sym, force_side=OrderSide.BUY)

        daemon.end_session()

    # Verify Bounded Memory Queues
    for sym in symbols:
        assert len(daemon._trade_history[sym]) <= 500, "Trade history queue unbounded"
        assert len(daemon._depth_history[sym]) <= 100, "Depth history queue unbounded"
        assert len(daemon._mark_history[sym]) <= 100, "Mark history queue unbounded"
    assert len(daemon._child_orders) <= 1000, "Child orders queue unbounded"
    assert len(daemon._interlock_events) <= 500, "Interlock events queue unbounded"
    assert len(daemon._recovery_events) <= 500, "Recovery events queue unbounded"

    # Persist all 5 research artifacts into artifacts/research/phase296/
    artifact_hashes = persist_phase296_artifacts(
        output_dir=output_dir,
        daemon=daemon,
        upstream_dir=upstream_dir,
        manifest_version=2,
    )

    is_valid, drift = daemon.verify_zero_drift()
    assert is_valid, f"Ledger drift {drift} exceeds tolerance"

    return {
        "track": 4,
        "name": "memory_boundedness_and_merkle_dag_persistence",
        "status": "PASSED",
        "total_sessions": len(daemon._sessions_history),
        "total_child_orders": len(daemon._child_orders),
        "total_fills": len(daemon._execution_marks),
        "memory_bounded": True,
        "artifact_hashes": artifact_hashes,
        "zero_balance_drift": is_valid,
        "drift_usdt": str(drift),
    }


# =====================================================================
# Main Runner Entrypoint
# =====================================================================


def run_all_tracks(
    output_dir: Path = DEFAULT_PHASE296_DIR,
    upstream_dir: Path = DEFAULT_PHASE295_DIR,
    registry_path: Path = _REPO_ROOT / "artifacts" / "paper_live" / "candidate_registry.json",
    starting_capital: Decimal = Decimal("100.00"),
    selected_track: str = "all",
) -> dict[str, Any]:
    """Execute requested simulation tracks deterministically."""
    results: dict[str, Any] = {
        "phase": "phase_296",
        "status": "AUTONOMOUS_LIFECYCLE_VERIFIED",
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
        res3 = run_track_3(starting_capital=starting_capital)
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
    """CLI entrypoint for Phase 296 Autonomous Lifecycle Runner."""
    parser = argparse.ArgumentParser(
        description="Phase 296: Autonomous Lifecycle Orchestration & Longevity Runner"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE296_DIR,
        help="Destination directory for Phase 296 research artifacts",
    )
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        default=DEFAULT_PHASE295_DIR,
        help="Upstream Phase 295 directory for Merkle DAG link",
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
        ok = verify_phase296_artifacts(args.output_dir, args.upstream_dir)
        return 0 if ok else 1

    try:
        results = run_all_tracks(
            output_dir=args.output_dir,
            upstream_dir=args.upstream_dir,
            registry_path=args.registry_path,
            starting_capital=args.starting_capital,
            selected_track=args.track,
        )
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print("\n=== Phase 296 Autonomous Lifecycle Runner Completed Successfully ===")
            print(json.dumps(results, indent=2))
        return 0
    except Exception as exc:
        logger.exception("Phase 296 autonomous lifecycle simulation failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
