"""Phase 294: Live Paper-Safe Execution Engine & Zero-Drift Matching Simulator Runner.

Executes deterministic multi-candidate paper matching simulation with:
- Micro child order slicing (strictly <= 5.00 USDT, ROUND_DOWN)
- Binance exchange filter compliance (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL)
- Passive maker / aggressive taker matching simulation against depth and agg trades
- Hawkes supercritical runaway lockout (rho >= 1.0)
- Predatory downscaling and limit cushions
- Aggregate exposure ceiling (<= 60.00 USDT)
- Intra-phase loss ceiling (<= 7.00 USDT) with emergency micro-chunk flattening
- Real-time gateway heartbeat and clock skew monitoring
- Continuous zero-drift double-entry balance reconciliation (|drift| < 1e-15 USDT)
- SQLite telemetry persistence and SHA-256 Merkle DAG hash chain linking Phase 293
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# Ensure src/ and repo root are importable
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
    ChildOrderIntention,
    OrderSide,
    OrderStatus,
    OrderType,
    ParentOrderIntention,
    SimulatedPassiveMatchingEngine,
    get_default_exchange_filters,
    slice_parent_order,
)
from autonomous_futures.feed.paper_ledger import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
    persist_telemetry_artifacts,
)
from autonomous_futures.feed.paper_risk import (  # noqa: E402
    CircuitState,
    InterlockCode,
    LivePaperRiskInterlock,
)

logger = logging.getLogger("run_phase_294_paper_execution")

DEFAULT_PHASE294_OUTPUT_DIR = _REPO_ROOT / "artifacts" / "research" / "phase294"
DEFAULT_UPSTREAM_DIR = _REPO_ROOT / "artifacts" / "research" / "phase293"
DEFAULT_CANDIDATES = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def run_phase_294_simulation(
    output_dir: Path = DEFAULT_PHASE294_OUTPUT_DIR,
    upstream_dir: Path = DEFAULT_UPSTREAM_DIR,
    starting_capital: Decimal = Decimal("100.00"),
) -> dict[str, object]:
    """Execute deterministic Phase 294 paper simulation and generate artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize engines
    engine = SimulatedPassiveMatchingEngine()
    risk = LivePaperRiskInterlock(
        starting_equity=starting_capital,
    )
    ledger = PaperExecutionLedger(
        starting_equity=starting_capital,
    )

    filters = get_default_exchange_filters()

    # Initial mark prices
    mark_prices: dict[str, Decimal] = {
        "BTCUSDT": Decimal("65000.00"),
        "ETHUSDT": Decimal("3500.00"),
        "SOLUSDT": Decimal("150.00"),
    }

    now_dt = datetime.now(UTC)
    now_ms = int(time.time() * 1000)

    # Step 1: Initial balance reconciliation
    for sym, p in mark_prices.items():
        ledger.update_mark_price(sym, p)
    ledger.create_snapshot()
    assert ledger.drift < DOUBLE_ENTRY_MAX_DRIFT, f"Initial drift non-zero: {ledger.drift}"

    # Step 2: Establish initial order books
    depth_btc = OrderBookDepthSnapshot(
        symbol="BTCUSDT",
        bids=(
            OrderBookLevel(price=Decimal("64999.00"), quantity=Decimal("2.5")),
            OrderBookLevel(price=Decimal("64998.00"), quantity=Decimal("5.0")),
        ),
        asks=(
            OrderBookLevel(price=Decimal("65001.00"), quantity=Decimal("2.0")),
            OrderBookLevel(price=Decimal("65002.00"), quantity=Decimal("4.0")),
        ),
        last_update_id=10001,
        event_time=now_dt,
    )
    engine.update_depth(depth_btc)

    depth_eth = OrderBookDepthSnapshot(
        symbol="ETHUSDT",
        bids=(
            OrderBookLevel(price=Decimal("3499.50"), quantity=Decimal("15.0")),
            OrderBookLevel(price=Decimal("3499.00"), quantity=Decimal("30.0")),
        ),
        asks=(
            OrderBookLevel(price=Decimal("3500.50"), quantity=Decimal("12.0")),
            OrderBookLevel(price=Decimal("3501.00"), quantity=Decimal("25.0")),
        ),
        last_update_id=10002,
        event_time=now_dt,
    )
    engine.update_depth(depth_eth)

    depth_sol = OrderBookDepthSnapshot(
        symbol="SOLUSDT",
        bids=(
            OrderBookLevel(price=Decimal("149.90"), quantity=Decimal("100.0")),
            OrderBookLevel(price=Decimal("149.80"), quantity=Decimal("200.0")),
        ),
        asks=(
            OrderBookLevel(price=Decimal("150.10"), quantity=Decimal("80.0")),
            OrderBookLevel(price=Decimal("150.20"), quantity=Decimal("150.0")),
        ),
        last_update_id=10003,
        event_time=now_dt,
    )
    engine.update_depth(depth_sol)

    all_child_orders: list[ChildOrderIntention] = []

    # Step 3: Nominal micro child order placements (BTCUSDT Buy)
    # Parent order: 12.00 USDT at 64999.00
    # Expected child slices: strictly <= 5.00 USDT with ROUND_DOWN
    parent_btc = ParentOrderIntention(
        parent_order_id="p-btc-001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        target_notional_usdt=Decimal("12.00"),
        limit_price=Decimal("64999.00"),
        created_time_ms=now_ms,
    )
    children_btc = slice_parent_order(
        parent=parent_btc,
        filters=filters["BTCUSDT"],
        reference_price=Decimal("65000.00"),
        chunk_cap_usdt=Decimal("4.50"),
    )
    assert len(children_btc) >= 2, "Parent order should be sliced into micro children"
    for child in children_btc:
        assert child.notional_usdt <= Decimal("5.00"), f"Child exceeds cap: {child.notional_usdt}"
        # Pre-trade risk interlock check
        decision = risk.validate_pre_trade_interlocks(
            symbol=child.symbol,
            proposed_notional=child.notional_usdt,
            spectral_radius=Decimal("0.35"),
            heartbeat_age_ms=25.0,
            clock_skew_ms=1.5,
        )
        assert decision.allowed, f"Dispatch rejected unexpectedly: {decision.reason}"
        risk.reserve_working_notional(child.symbol, child.notional_usdt)
        all_child_orders.append(child)
        ledger.register_child_order(child)
        resting, fills = engine.place_order(child)
        for fill in fills:
            risk.release_working_notional(fill.symbol, fill.fill_notional_usdt)
            ledger.record_fill(fill)
            risk.update_active_exposure(fill.symbol, ledger.allocated_margin)
            risk.update_portfolio_state(
                cash=ledger.cash,
                realized_pnl=ledger.realized_pnl,
                cumulative_loss=ledger.cumulative_loss,
            )

    ledger.verify_zero_drift()

    # Step 4: Simulate aggregate trades matching BTCUSDT maker order
    trade_btc = AggregateTrade(
        symbol="BTCUSDT",
        aggregate_trade_id=50001,
        price=Decimal("64999.00"),
        quantity=Decimal("3.0"),
        trade_time=now_dt,
        is_buyer_maker=True,  # seller hit resting buyer order
    )
    fills_btc = engine.on_aggregate_trade(trade_btc)
    assert fills_btc, "Expected maker fill on BTCUSDT resting order"
    for fill in fills_btc:
        risk.release_working_notional(fill.symbol, fill.fill_notional_usdt)
        ledger.record_fill(fill)
        risk.update_active_exposure(fill.symbol, ledger.allocated_margin)
        risk.update_portfolio_state(
            cash=ledger.cash,
            realized_pnl=ledger.realized_pnl,
            cumulative_loss=ledger.cumulative_loss,
        )

    ledger.verify_zero_drift()

    # Step 5: Test aggressive taker order with fee and slippage (ETHUSDT)
    child_eth = ChildOrderIntention(
        client_order_id=f"c-eth-market-{now_ms}",
        parent_order_id="p-eth-001",
        child_index=0,
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        price=Decimal("3500.50"),
        quantity=Decimal("0.001"),
        notional_usdt=Decimal("3.50"),
        status=OrderStatus.OPEN,
        created_time_ms=now_ms + 200,
    )
    decision = risk.validate_pre_trade_interlocks(
        symbol="ETHUSDT",
        proposed_notional=child_eth.notional_usdt,
        spectral_radius=Decimal("0.30"),
        heartbeat_age_ms=30.0,
        clock_skew_ms=2.0,
    )
    assert decision.allowed
    all_child_orders.append(child_eth)
    ledger.register_child_order(child_eth)
    resting_eth, fills_eth = engine.place_order(child_eth)
    assert fills_eth, "Expected immediate fill on market order"
    for fill in fills_eth:
        ledger.record_fill(fill)
        risk.update_active_exposure(fill.symbol, ledger.allocated_margin)
        risk.update_portfolio_state(
            cash=ledger.cash,
            realized_pnl=ledger.realized_pnl,
            cumulative_loss=ledger.cumulative_loss,
        )

    ledger.verify_zero_drift()

    # Step 6: Test Hawkes Supercritical Lockout (rho >= 1.0)
    decision_hawkes = risk.validate_pre_trade_interlocks(
        symbol="SOLUSDT",
        proposed_notional=Decimal("4.50"),
        spectral_radius=Decimal("1.25"),
        heartbeat_age_ms=35.0,
        clock_skew_ms=2.0,
    )
    assert not decision_hawkes.allowed, "Dispatch should be blocked during Hawkes supercritical"
    assert decision_hawkes.code == InterlockCode.SUPERCRITICAL_CASCADE_LOCKOUT

    # Reset circuit state to NORMAL for subsequent tests
    risk.set_circuit_state(CircuitState.NORMAL)

    # Step 7: Test Aggregate Exposure Cap (<= 60.00 USDT)
    decision_overcap = risk.validate_pre_trade_interlocks(
        symbol="SOLUSDT",
        proposed_notional=Decimal("70.00"),
        spectral_radius=Decimal("0.35"),
        heartbeat_age_ms=35.0,
        clock_skew_ms=2.0,
    )
    assert not decision_overcap.allowed, "Dispatch exceeding 60.00 USDT must be blocked"
    assert decision_overcap.code == InterlockCode.AGGREGATE_EXPOSURE_CAP_EXCEEDED

    # Step 8: Test Gateway Heartbeat & Skew Interlocks
    decision_stale = risk.validate_pre_trade_interlocks(
        symbol="BTCUSDT",
        proposed_notional=Decimal("2.00"),
        heartbeat_age_ms=600.0,
    )
    assert not decision_stale.allowed
    assert decision_stale.code == InterlockCode.GATEWAY_HEARTBEAT_STALE

    decision_skew = risk.validate_pre_trade_interlocks(
        symbol="BTCUSDT",
        proposed_notional=Decimal("2.00"),
        clock_skew_ms=300.0,
    )
    assert not decision_skew.allowed
    assert decision_skew.code == InterlockCode.CLOCK_SKEW_BREACH

    # Step 9: Update mark prices and verify zero-drift ledger
    ledger.update_mark_price("BTCUSDT", Decimal("65010.00"))
    ledger.update_mark_price("ETHUSDT", Decimal("3505.00"))
    ledger.create_snapshot()
    assert ledger.drift < DOUBLE_ENTRY_MAX_DRIFT, f"Balance drift: {ledger.drift}"

    # Step 10: Persist artifacts & Merkle DAG hash chain
    state_str = str(getattr(risk.circuit_state, "value", risk.circuit_state))
    hashes = persist_telemetry_artifacts(
        output_dir=output_dir,
        ledger=ledger,
        child_orders=all_child_orders,
        interlocks=risk.interlock_events,
        upstream_dir=upstream_dir,
        circuit_state=state_str,
    )

    summary = {
        "phase": "phase_294",
        "status": "COMPLETED",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "zero_balance_drift": ledger.drift < DOUBLE_ENTRY_MAX_DRIFT,
        "drift_usdt": str(ledger.drift),
        "starting_equity_usdt": str(ledger.starting_equity),
        "final_cash_usdt": str(ledger.cash),
        "final_equity_usdt": str(ledger.total_equity),
        "total_fees_usdt": str(ledger.total_fees_usdt),
        "circuit_state": state_str,
        "child_orders_placed": len(all_child_orders),
        "child_orders_filled": len(ledger._execution_marks),
        "interlock_blocks": sum(1 for it in risk.interlock_events if not it.allowed),
        "artifact_hashes": hashes,
    }

    return summary


def main() -> int:
    """CLI entrypoint for Phase 294 Paper Execution Runner."""
    parser = argparse.ArgumentParser(
        description="Phase 294: Live Paper-Safe Execution Engine & Zero-Drift Matching Simulator"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE294_OUTPUT_DIR,
        help="Path to write phase 294 artifacts",
    )
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        default=DEFAULT_UPSTREAM_DIR,
        help="Path to upstream Phase 293 directory for Merkle DAG link",
    )
    parser.add_argument(
        "--starting-capital",
        type=Decimal,
        default=Decimal("100.00"),
        help="Starting capital in USDT",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        summary = run_phase_294_simulation(
            output_dir=args.output_dir,
            upstream_dir=args.upstream_dir,
            starting_capital=args.starting_capital,
        )
        print("\n=== Phase 294 Paper Execution Runner Completed Successfully ===")
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as exc:
        logger.exception("Phase 294 simulation failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
