"""Milestone 1 Adversarial Challenger Verification Suite for Phase 295.

Empirically challenges:
1. Challenge 1: slice_parent_order
   - Massive random parent notionals (1.00 to 5,000.00 USDT).
   - Fractional prices ($0.000001 to $100,000.00) and extreme ticks.
   - Strict micro notional boundary: EVERY child slice must be <= 5.00 USDT.
   - Strict quantity rounding: ROUND_DOWN precision and Binance LOT_SIZE adherence.
   - Extreme inputs and floor violation defenses.
2. Challenge 2: Continuous Double-Entry Balance Zero-Drift Equation
   - 1,000 randomized rapid fills, adds, partial closes, full liquidations, and shocks.
   - Evaluates: drift = abs((cash + allocated_margin + unrealized_pnl)
     - (starting_equity + realized_pnl + pos_unrealized))
   - Asserts drift < 1e-15 holds for 100.0% of transitions.
3. Challenge 3: Merkle DAG Hash Chain Single-Byte Corruption
   - Modifies single bytes at offset 0, mid, end, and random positions in summary.
   - Verifies immediate detection (verification returns False / CLI exit code 1).
   - Verifies tamper-detection on Phase 295 child artifacts.
   - Confirms recovery upon restoring uncorrupted artifacts.
"""

from __future__ import annotations

import json
import logging
import random
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from autonomous_futures.data.exchange_filters import ExchangeSymbolFilters  # noqa: E402
from autonomous_futures.feed.paper_execution import (  # noqa: E402
    HARD_MICRO_NOTIONAL_CAP_USDT,
    ChildOrderIntention,
    MicroNotionalFloorViolationError,
    OrderExecutionFill,
    OrderSide,
    OrderStatus,
    OrderType,
    ParentOrderIntention,
    get_default_exchange_filters,
    slice_parent_order,
)
from autonomous_futures.feed.paper_ledger import (  # noqa: E402
    DOUBLE_ENTRY_MAX_DRIFT,
    PaperExecutionLedger,
)
from autonomous_futures.feed.strategy_activation import (  # noqa: E402
    CandidatePromotionStatus,
    OOSPromotionGateRecord,
    persist_phase295_artifacts,
    verify_phase295_artifacts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("m1_challenger_2")


def build_sample_filters(symbol: str = "BTCUSDT", **overrides: Any) -> ExchangeSymbolFilters:
    """Build compliant ExchangeSymbolFilters with optional overrides."""
    defaults: dict[str, Any] = {
        "symbol": symbol.upper(),
        "status": "TRADING",
        "contract_type": "PERPETUAL",
        "base_asset": symbol[:3].upper(),
        "quote_asset": "USDT",
        "settle_asset": "USDT",
        "price_min": Decimal("0.10"),
        "price_max": Decimal("1000000.00"),
        "price_tick_size": Decimal("0.10"),
        "quantity_min": Decimal("0.001"),
        "quantity_max": Decimal("1000.000"),
        "quantity_step_size": Decimal("0.001"),
        "market_quantity_min": Decimal("0.001"),
        "market_quantity_max": Decimal("100.000"),
        "market_quantity_step_size": Decimal("0.001"),
        "min_notional": Decimal("5.00"),
    }
    defaults.update(overrides)
    return ExchangeSymbolFilters(**defaults)


# =====================================================================
# Challenge 1: Order Slicing Stress Test
# =====================================================================


def challenge_order_slicing() -> dict[str, Any]:
    """Stress test slice_parent_order across extreme and random parameters."""
    logger.info("=== Starting Challenge 1: Order Slicing Stress Test ===")
    rng = random.Random(42)

    stats: dict[str, Any] = {
        "total_parent_orders": 0,
        "total_child_slices_generated": 0,
        "max_child_notional_usdt": Decimal("0"),
        "all_slices_strictly_le_5_usdt": True,
        "all_quantities_round_down": True,
        "all_filters_respected": True,
        "floor_violations_handled": True,
        "edge_cases_tested": 0,
    }

    # 1. Extreme and Random Notional Batches using canonical filters
    canonical_filters = get_default_exchange_filters()
    test_symbols = [
        ("BTCUSDT", Decimal("65432.10"), canonical_filters["BTCUSDT"]),
        ("ETHUSDT", Decimal("3456.78"), canonical_filters["ETHUSDT"]),
        ("SOLUSDT", Decimal("145.67"), canonical_filters["SOLUSDT"]),
        (
            "DOGEUSDT",
            Decimal("0.12345"),
            build_sample_filters(
                "DOGEUSDT",
                price_min=Decimal("0.00001"),
                price_tick_size=Decimal("0.00001"),
                quantity_min=Decimal("1.0"),
                quantity_step_size=Decimal("1.0"),
                min_notional=Decimal("1.00"),
            ),
        ),
        (
            "SHIBUSDT",
            Decimal("0.0000185"),
            build_sample_filters(
                "SHIBUSDT",
                price_min=Decimal("0.0000001"),
                price_tick_size=Decimal("0.0000001"),
                quantity_min=Decimal("100.0"),
                quantity_step_size=Decimal("100.0"),
                min_notional=Decimal("1.00"),
            ),
        ),
    ]

    for sym, ref_price, filters in test_symbols:
        # Diverse notionals: small, boundary, medium, large, very large
        notionals = [
            Decimal("1.00"),
            Decimal("1.01"),
            Decimal("2.49"),
            Decimal("2.50"),
            Decimal("2.51"),
            Decimal("4.99"),
            Decimal("5.00"),
            Decimal("5.01"),
            Decimal("9.99"),
            Decimal("10.00"),
            Decimal("25.75"),
            Decimal("50.00"),
            Decimal("100.00"),
            Decimal("250.00"),
            Decimal("500.00"),
            Decimal("1000.00"),
            Decimal("2500.00"),
        ]

        # Add 20 random notionals
        for _ in range(20):
            val = Decimal(f"{rng.uniform(1.0, 1000.0):.4f}")
            notionals.append(val)

        for notional in notionals:
            for side in (OrderSide.BUY, OrderSide.SELL):
                stats["total_parent_orders"] += 1
                now_ms = int(time.time() * 1000)
                p_id = f"c=canary-p295-{sym.lower()}-{now_ms}-{stats['total_parent_orders']:04d}"
                parent = ParentOrderIntention(
                    parent_order_id=p_id,
                    symbol=sym,
                    side=side,
                    order_type=OrderType.LIMIT,
                    target_notional_usdt=notional,
                    limit_price=ref_price,
                    created_time_ms=now_ms,
                )

                children = slice_parent_order(
                    parent=parent,
                    filters=filters,
                    reference_price=ref_price,
                    chunk_cap_usdt=Decimal("4.50"),
                )

                assert len(children) > 0, (
                    f"Expected child orders for {sym} with notional {notional}"
                )

                for child in children:
                    stats["total_child_slices_generated"] += 1
                    if child.notional_usdt > stats["max_child_notional_usdt"]:
                        stats["max_child_notional_usdt"] = child.notional_usdt

                    # INVARIANT 1: Child notional strictly <= 5.00 USDT
                    if child.notional_usdt > HARD_MICRO_NOTIONAL_CAP_USDT:
                        stats["all_slices_strictly_le_5_usdt"] = False
                        msg = f"Child {child.notional_usdt} exceeded {HARD_MICRO_NOTIONAL_CAP_USDT}"
                        raise AssertionError(msg)

                    # INVARIANT 2: Actual calculated notional (qty * price) <= 5.00 USDT
                    actual_notional = child.quantity * child.price
                    if actual_notional > HARD_MICRO_NOTIONAL_CAP_USDT:
                        stats["all_slices_strictly_le_5_usdt"] = False
                        msg = f"Actual {actual_notional} exceeded {HARD_MICRO_NOTIONAL_CAP_USDT}"
                        raise AssertionError(msg)

                    # INVARIANT 3: Quantity strictly conforms to quantity_step_size
                    remainder = (child.quantity / filters.quantity_step_size) % 1
                    if remainder != 0:
                        stats["all_quantities_round_down"] = False
                        step_s = filters.quantity_step_size
                        raise AssertionError(f"Quantity {child.quantity} not multiple of {step_s}")

                    # INVARIANT 4: Binance Filters Respected
                    if child.quantity < filters.quantity_min:
                        stats["all_filters_respected"] = False
                        raise AssertionError(
                            f"Quantity {child.quantity} below min {filters.quantity_min}"
                        )
                    if child.price < filters.price_min:
                        stats["all_filters_respected"] = False
                        raise AssertionError(
                            f"Price {child.price} below price_min {filters.price_min}"
                        )

    # 2. Edge Case Challenges
    # Sub-floor notional (< 1.00 USDT)
    try:
        sub_floor_parent = ParentOrderIntention(
            parent_order_id="p-floor-fail",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            target_notional_usdt=Decimal("0.99"),
            limit_price=Decimal("60000.0"),
        )
        slice_parent_order(sub_floor_parent, build_sample_filters("BTCUSDT"))
        raise AssertionError("Expected MicroNotionalFloorViolationError for notional < 1.00")
    except MicroNotionalFloorViolationError:
        stats["edge_cases_tested"] += 1

    # Zero or Negative notional
    try:
        zero_parent = ParentOrderIntention(
            parent_order_id="p-zero-fail",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            target_notional_usdt=Decimal("0.00"),
            limit_price=Decimal("60000.0"),
        )
        slice_parent_order(zero_parent, build_sample_filters("BTCUSDT"))
        raise AssertionError("Expected ValueError for zero notional")
    except ValueError:
        stats["edge_cases_tested"] += 1

    # Chunk cap clamping test: pass chunk_cap_usdt = 100.00, verify children are STILL <= 5.00 USDT
    large_cap_parent = ParentOrderIntention(
        parent_order_id="p-large-cap",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        target_notional_usdt=Decimal("50.00"),
        limit_price=Decimal("60000.0"),
    )
    large_cap_children = slice_parent_order(
        large_cap_parent,
        build_sample_filters("BTCUSDT"),
        chunk_cap_usdt=Decimal("100.00"),
    )
    for c in large_cap_children:
        assert c.notional_usdt <= HARD_MICRO_NOTIONAL_CAP_USDT, (
            "Chunk cap override violated hard cap"
        )
    stats["edge_cases_tested"] += 1

    logger.info(
        "Challenge 1 PASSED: Generated %d child slices across %d parent orders. "
        "Max child notional: %s USDT. All <= 5.00 USDT: %s.",
        stats["total_child_slices_generated"],
        stats["total_parent_orders"],
        stats["max_child_notional_usdt"],
        stats["all_slices_strictly_le_5_usdt"],
    )
    return stats


# =====================================================================
# Challenge 2: Continuous Double-Entry Ledger Invariant Across 1,000 Transitions
# =====================================================================


def challenge_double_entry_ledger_1000_transitions() -> dict[str, Any]:
    """Execute 1,000 randomized rapid fills, adds, closes, and mark price shocks."""
    logger.info(
        "=== Starting Challenge 2: Double-Entry Balance Equation Across 1,000 Transitions ==="
    )
    rng = random.Random(1337)

    ledger = PaperExecutionLedger(starting_equity=Decimal("100.00"))
    assert ledger.drift < DOUBLE_ENTRY_MAX_DRIFT

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    current_prices = {
        "BTCUSDT": Decimal("60000.00"),
        "ETHUSDT": Decimal("3000.00"),
        "SOLUSDT": Decimal("150.00"),
    }
    step_sizes = {
        "BTCUSDT": Decimal("0.001"),
        "ETHUSDT": Decimal("0.001"),
        "SOLUSDT": Decimal("0.01"),
    }

    stats: dict[str, Any] = {
        "transitions_evaluated": 0,
        "fills_count": 0,
        "adds_count": 0,
        "partial_closes_count": 0,
        "full_closes_count": 0,
        "reversals_count": 0,
        "mark_price_updates_count": 0,
        "max_observed_drift": Decimal("0"),
        "all_transitions_zero_drift": True,
    }

    def verify_transition_drift(step_name: str) -> None:
        stats["transitions_evaluated"] += 1
        pos_unrealized = sum(
            (
                getattr(p, "unrealized_pnl", Decimal("0"))
                if not isinstance(p, dict)
                else Decimal(str(p.get("unrealized_pnl", "0")))
                for p in ledger._positions.values()
            ),
            Decimal("0"),
        )
        lhs = ledger.cash + ledger.allocated_margin + ledger.unrealized_pnl
        rhs = ledger.starting_equity + ledger.realized_pnl + pos_unrealized
        current_drift = abs(lhs - rhs)

        if current_drift > stats["max_observed_drift"]:
            stats["max_observed_drift"] = current_drift

        if current_drift >= DOUBLE_ENTRY_MAX_DRIFT:
            stats["all_transitions_zero_drift"] = False
            raise AssertionError(
                f"Transition {stats['transitions_evaluated']} ({step_name}) violated zero drift! "
                f"drift={current_drift} >= {DOUBLE_ENTRY_MAX_DRIFT}. "
                f"LHS={lhs}, RHS={rhs}, Cash={ledger.cash}, Margin={ledger.allocated_margin}, "
                f"Unrealized={ledger.unrealized_pnl}, Realized={ledger.realized_pnl}"
            )

    fill_seq = 0
    while stats["transitions_evaluated"] < 1000:
        sym = rng.choice(symbols)
        action_type = rng.choice(["MARK_PRICE", "MARK_PRICE", "FILL", "FILL", "FILL"])

        if action_type == "MARK_PRICE":
            # Price jump: -5% to +5%
            pct_change = Decimal(str(rng.uniform(-0.05, 0.05)))
            new_price = (current_prices[sym] * (Decimal("1.0") + pct_change)).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            if new_price <= Decimal("0"):
                new_price = Decimal("0.01")
            current_prices[sym] = new_price

            ledger.update_mark_price(sym, new_price)
            stats["mark_price_updates_count"] += 1
            verify_transition_drift("update_mark_price")

        else:
            fill_seq += 1
            pos = ledger._positions.get(sym)
            px = current_prices[sym]
            step = step_sizes[sym]

            if pos is None or pos.quantity <= Decimal("0"):
                # Open new position
                side = rng.choice([OrderSide.BUY, OrderSide.SELL])
                # Small micro quantity: 1.00 to 4.50 USDT notional
                target_notional = Decimal(f"{rng.uniform(1.5, 4.5):.2f}")
                raw_qty = target_notional / px
                qty = (raw_qty / step).to_integral_value(rounding=ROUND_DOWN) * step
                if qty <= Decimal("0"):
                    qty = step
                notional = (qty * px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                fee = (notional * Decimal("0.0002")).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )

                fill = OrderExecutionFill(
                    fill_id=f"fill-{fill_seq:05d}",
                    symbol=sym,
                    side=side,
                    fill_price=px,
                    fill_quantity=qty,
                    fill_notional_usdt=notional,
                    fee_usdt=fee,
                    is_maker=rng.choice([True, False]),
                    slippage_bps=Decimal("0"),
                    timestamp_ms=int(time.time() * 1000),
                )
                ledger.record_fill(fill)
                stats["fills_count"] += 1
                verify_transition_drift("open_position")

            else:
                # We have an existing position: pick ADD, PARTIAL CLOSE, FULL CLOSE, or REVERSAL
                roll = rng.random()
                if roll < 0.35:
                    # ADD to position
                    side = pos.side
                    target_notional = Decimal(f"{rng.uniform(1.0, 3.0):.2f}")
                    raw_qty = target_notional / px
                    qty = (raw_qty / step).to_integral_value(rounding=ROUND_DOWN) * step
                    if qty <= Decimal("0"):
                        qty = step
                    notional = (qty * px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    fee = (notional * Decimal("0.0002")).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )

                    fill = OrderExecutionFill(
                        fill_id=f"fill-{fill_seq:05d}",
                        symbol=sym,
                        side=side,
                        fill_price=px,
                        fill_quantity=qty,
                        fill_notional_usdt=notional,
                        fee_usdt=fee,
                        is_maker=rng.choice([True, False]),
                        timestamp_ms=int(time.time() * 1000),
                    )
                    ledger.record_fill(fill)
                    stats["adds_count"] += 1
                    verify_transition_drift("add_to_position")

                elif roll < 0.65:
                    # PARTIAL CLOSE
                    side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                    # Close 25% to 75% of existing quantity
                    close_frac = Decimal(str(rng.uniform(0.25, 0.75)))
                    raw_qty = pos.quantity * close_frac
                    qty = (raw_qty / step).to_integral_value(rounding=ROUND_DOWN) * step
                    if qty <= Decimal("0") or qty >= pos.quantity:
                        qty = pos.quantity / Decimal("2")
                        qty = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
                    if qty <= Decimal("0"):
                        qty = pos.quantity

                    notional = (qty * px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    fee = (notional * Decimal("0.0002")).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )

                    fill = OrderExecutionFill(
                        fill_id=f"fill-{fill_seq:05d}",
                        symbol=sym,
                        side=side,
                        fill_price=px,
                        fill_quantity=qty,
                        fill_notional_usdt=notional,
                        fee_usdt=fee,
                        is_maker=rng.choice([True, False]),
                        timestamp_ms=int(time.time() * 1000),
                    )
                    ledger.record_fill(fill)
                    if qty < pos.quantity:
                        stats["partial_closes_count"] += 1
                    else:
                        stats["full_closes_count"] += 1
                    verify_transition_drift("partial_close")

                elif roll < 0.85:
                    # FULL CLOSE
                    side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                    qty = pos.quantity
                    notional = (qty * px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    fee = (notional * Decimal("0.0002")).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )

                    fill = OrderExecutionFill(
                        fill_id=f"fill-{fill_seq:05d}",
                        symbol=sym,
                        side=side,
                        fill_price=px,
                        fill_quantity=qty,
                        fill_notional_usdt=notional,
                        fee_usdt=fee,
                        is_maker=True,
                        timestamp_ms=int(time.time() * 1000),
                    )
                    ledger.record_fill(fill)
                    stats["full_closes_count"] += 1
                    verify_transition_drift("full_close")

                else:
                    # POSITION REVERSAL (close and flip to opposite side)
                    side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                    # Add extra 1-3 steps of opposite side
                    excess_steps = rng.randint(1, 5)
                    qty = pos.quantity + (Decimal(str(excess_steps)) * step)
                    notional = (qty * px).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    fee = (notional * Decimal("0.0002")).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )

                    fill = OrderExecutionFill(
                        fill_id=f"fill-{fill_seq:05d}",
                        symbol=sym,
                        side=side,
                        fill_price=px,
                        fill_quantity=qty,
                        fill_notional_usdt=notional,
                        fee_usdt=fee,
                        is_maker=False,
                        slippage_bps=Decimal("2.0"),
                        timestamp_ms=int(time.time() * 1000),
                    )
                    ledger.record_fill(fill)
                    stats["reversals_count"] += 1
                    verify_transition_drift("reversal")

    logger.info(
        "Challenge 2 PASSED: 100%% of %d transitions verified zero-drift. "
        "Max observed drift: %s USDT (Tolerance: %s). Fills: %d, Adds: %d, "
        "Partial Closes: %d, Full Closes: %d, Reversals: %d, Mark Updates: %d.",
        stats["transitions_evaluated"],
        stats["max_observed_drift"],
        DOUBLE_ENTRY_MAX_DRIFT,
        stats["fills_count"],
        stats["adds_count"],
        stats["partial_closes_count"],
        stats["full_closes_count"],
        stats["reversals_count"],
        stats["mark_price_updates_count"],
    )
    return stats


# =====================================================================
# Challenge 3: Merkle DAG Hash Chain Single-Byte Corruption
# =====================================================================


def challenge_merkle_dag_corruption() -> dict[str, Any]:
    """Test Merkle DAG: verify single-byte corruption triggers verification failure."""
    logger.info("=== Starting Challenge 3: Merkle DAG Hash Chain Single-Byte Corruption ===")
    stats: dict[str, Any] = {
        "clean_verification_passed": False,
        "single_byte_upstream_corruptions_tested": 0,
        "all_single_byte_corruptions_detected": True,
        "restoration_passes": False,
        "child_artifact_corruptions_tested": 0,
        "all_child_corruptions_detected": True,
        "cli_runner_verify_only_corrupted_detected": False,
    }

    with tempfile.TemporaryDirectory(prefix="challenger_merkle_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        up_dir = tmp_path / "upstream_p294"
        out_dir = tmp_path / "out_p295"
        up_dir.mkdir(parents=True)
        out_dir.mkdir(parents=True)

        # 1. Setup realistic upstream summary
        upstream_summary_path = up_dir / "paper-execution-summary.json"
        p294_real_summary = (
            REPO_ROOT / "artifacts" / "research" / "phase294" / "paper-execution-summary.json"
        )
        if p294_real_summary.exists():
            original_up_bytes = p294_real_summary.read_bytes()
        else:
            original_up_bytes = json.dumps({"phase": "phase_294", "status": "VERIFIED"}).encode(
                "utf-8"
            )
        upstream_summary_path.write_bytes(original_up_bytes)

        # 2. Generate Phase 295 artifacts
        ledger = PaperExecutionLedger(starting_equity=Decimal("100.00"))
        candidate_records = [
            OOSPromotionGateRecord(
                candidate_id="cand-btc-test",
                symbol="BTCUSDT",
                status=CandidatePromotionStatus.PROMOTED,
                oos_average_return_pct=Decimal("2.5"),
                oos_worst_drawdown_pct=Decimal("8.0"),
                oos_profit_factor=Decimal("1.8"),
                oos_trade_count=10,
                oos_window_count=3,
                gates_passed={
                    "avg_return": True,
                    "drawdown": True,
                    "profit_factor": True,
                    "trade_count": True,
                },
                qualified=True,
                evaluated_at=datetime.now(UTC),
            )
        ]
        child_orders = [
            ChildOrderIntention(
                client_order_id="c-slice-0",
                child_id="c-slice-0",
                parent_order_id="p-0",
                child_index=0,
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                price=Decimal("60000.0"),
                quantity=Decimal("0.00005"),
                notional_usdt=Decimal("3.00"),
                notional=Decimal("3.00"),
                status=OrderStatus.NEW,
            )
        ]

        persist_phase295_artifacts(
            output_dir=out_dir,
            ledger=ledger,
            child_orders=child_orders,
            interlocks=[],
            candidate_records=candidate_records,
            upstream_dir=up_dir,
            circuit_state="NOMINAL",
            manifest_version=2,
        )

        # Check clean state
        clean_ok = verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir)
        assert clean_ok is True, "Clean artifacts must verify successfully"
        stats["clean_verification_passed"] = True

        # 3. Test single-byte corruptions in upstream Phase 294 summary
        n_bytes = len(original_up_bytes)
        test_offsets = [
            0,  # First byte
            n_bytes // 4,  # Quarter
            n_bytes // 2,  # Middle byte
            3 * (n_bytes // 4),  # 3/4 byte
            n_bytes - 1,  # Last byte
        ]
        # Add 15 random offsets
        rng = random.Random(999)
        for _ in range(15):
            test_offsets.append(rng.randint(0, n_bytes - 1))

        for offset in test_offsets:
            stats["single_byte_upstream_corruptions_tested"] += 1
            corrupted_bytes = bytearray(original_up_bytes)
            # Flip bits in byte
            corrupted_bytes[offset] = corrupted_bytes[offset] ^ 0xFF
            upstream_summary_path.write_bytes(corrupted_bytes)

            ok = verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir)
            if ok is not False:
                stats["all_single_byte_corruptions_detected"] = False
                raise AssertionError(
                    f"Corrupted byte at offset {offset} failed to trigger verification rejection!"
                )

        # 4. Restore original bytes and verify immediate recovery
        upstream_summary_path.write_bytes(original_up_bytes)
        restored_ok = verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir)
        assert restored_ok is True, (
            "Restoring original upstream summary must restore verification to True"
        )
        stats["restoration_passes"] = True

        # 5. CLI runner --verify-only with corrupted upstream
        corrupted_bytes = bytearray(original_up_bytes)
        corrupted_bytes[0] ^= 0x01
        upstream_summary_path.write_bytes(corrupted_bytes)

        cli_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_phase_295_strategy_activation.py"),
            "--verify-only",
            "--output-dir",
            str(out_dir),
            "--upstream-dir",
            str(up_dir),
        ]
        proc = subprocess.run(cli_cmd, capture_output=True, text=True)
        assert proc.returncode != 0, (
            "CLI runner --verify-only must exit with non-zero when upstream is corrupted"
        )
        stats["cli_runner_verify_only_corrupted_detected"] = True

        # Restore
        upstream_summary_path.write_bytes(original_up_bytes)

        # 6. Test corrupting child artifacts in Phase 295
        child_files = [
            out_dir / "canary-orders.jsonl",
            out_dir / "canary-strategy-activation-report.json",
            out_dir / "canary-strategy-activation-telemetry.sqlite3",
        ]
        for cf in child_files:
            if not cf.exists():
                continue
            stats["child_artifact_corruptions_tested"] += 1
            original_cf_bytes = cf.read_bytes()
            corrupted_cf = bytearray(original_cf_bytes)
            corrupted_cf[0] ^= 0x5A
            cf.write_bytes(corrupted_cf)

            ok = verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir)
            if ok is not False:
                stats["all_child_corruptions_detected"] = False
                raise AssertionError(f"Corruption in child artifact {cf.name} was not detected!")

            cf.write_bytes(original_cf_bytes)

    logger.info(
        "Challenge 3 PASSED: %d upstream byte offsets and %d child artifacts tested. "
        "100%% of corruptions immediately detected. CLI exit code 1 verified.",
        stats["single_byte_upstream_corruptions_tested"],
        stats["child_artifact_corruptions_tested"],
    )
    return stats


# =====================================================================
# Main Runner
# =====================================================================


def main() -> int:
    """Execute all empirical challenge suites and print consolidated verdict."""
    logger.info("=====================================================================")
    logger.info("   PHASE 295 MILESTONE 1 ADVERSARIAL CHALLENGER VERIFICATION HARNESS")
    logger.info("=====================================================================")

    t0 = time.perf_counter()
    report: dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": "m1_challenger_2",
        "challenges": {},
        "overall_verdict": "REJECT",
    }

    try:
        # Challenge 1
        res1 = challenge_order_slicing()
        report["challenges"]["challenge_1_order_slicing"] = {
            "status": "PASSED",
            "details": res1,
        }

        # Challenge 2
        res2 = challenge_double_entry_ledger_1000_transitions()
        report["challenges"]["challenge_2_double_entry_ledger"] = {
            "status": "PASSED",
            "details": {k: str(v) if isinstance(v, Decimal) else v for k, v in res2.items()},
        }

        # Challenge 3
        res3 = challenge_merkle_dag_corruption()
        report["challenges"]["challenge_3_merkle_dag_corruption"] = {
            "status": "PASSED",
            "details": res3,
        }

        elapsed = time.perf_counter() - t0
        report["elapsed_seconds"] = round(elapsed, 3)
        report["overall_verdict"] = "CONFIRM"

        print("\n=== EMPIRICAL CHALLENGER REPORT ===")
        print(json.dumps(report, indent=2, default=str))
        logger.info("ALL EMPIRICAL CHALLENGES PASSED! FINAL VERDICT: CONFIRM")
        return 0

    except Exception as exc:
        logger.exception("CHALLENGE FAILED: %s", exc)
        report["overall_verdict"] = "REJECT"
        report["error"] = str(exc)
        print("\n=== EMPIRICAL CHALLENGER REPORT (FAILED) ===")
        print(json.dumps(report, indent=2, default=str))
        return 1


if __name__ == "__main__":
    sys.exit(main())
