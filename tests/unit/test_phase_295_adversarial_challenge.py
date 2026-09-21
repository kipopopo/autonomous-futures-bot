"""Milestone 1 Adversarial Challenger Unit & Stress Tests for Phase 295.

Authored by m1_challenger_2 to empirically verify:
1. Micro child order slicing (strictly <= 5.00 USDT cap, ROUND_DOWN precision).
2. Continuous double-entry accounting balance zero-drift equation over 1,000 transitions.
3. Cryptographic Merkle DAG hash chain tamper detection in upstream summary.
"""

from __future__ import annotations

import random
import sys
import tempfile
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from autonomous_futures.feed.paper_execution import (  # noqa: E402
    HARD_MICRO_NOTIONAL_CAP_USDT,
    ChildOrderIntention,
    MicroNotionalFloorViolationError,
    OrderExecutionFill,
    OrderSide,
    OrderStatus,
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


class TestOrderSlicingAdversarialStress:
    """Stress testing slice_parent_order against notionals, prices, and ticks."""

    def test_massive_random_parent_notionals_and_filters(self) -> None:
        """Verify that every child slice across parent orders is <= 5.00 USDT."""
        rng = random.Random(42)
        canonical_filters = get_default_exchange_filters()

        symbols_and_prices = [
            ("BTCUSDT", Decimal("65432.10"), canonical_filters["BTCUSDT"]),
            ("ETHUSDT", Decimal("3456.78"), canonical_filters["ETHUSDT"]),
            ("SOLUSDT", Decimal("145.67"), canonical_filters["SOLUSDT"]),
        ]

        total_slices = 0
        for sym, ref_price, filters in symbols_and_prices:
            notionals = [
                Decimal("1.00"),
                Decimal("2.49"),
                Decimal("2.50"),
                Decimal("4.99"),
                Decimal("5.00"),
                Decimal("5.01"),
                Decimal("10.00"),
                Decimal("50.00"),
                Decimal("100.00"),
                Decimal("500.00"),
                Decimal("1000.00"),
                Decimal("2500.00"),
            ]
            for _ in range(15):
                notionals.append(Decimal(f"{rng.uniform(1.0, 500.0):.2f}"))

            for notional in notionals:
                for side in (OrderSide.BUY, OrderSide.SELL):
                    parent = ParentOrderIntention(
                        parent_order_id=f"p-{sym}-{notional}-{side}",
                        symbol=sym,
                        side=side,
                        target_notional_usdt=notional,
                        limit_price=ref_price,
                    )
                    children = slice_parent_order(
                        parent=parent,
                        filters=filters,
                        reference_price=ref_price,
                        chunk_cap_usdt=Decimal("4.50"),
                    )
                    assert len(children) > 0

                    for child in children:
                        total_slices += 1
                        # Micro notional cap
                        assert child.notional_usdt <= HARD_MICRO_NOTIONAL_CAP_USDT
                        assert (child.quantity * child.price) <= HARD_MICRO_NOTIONAL_CAP_USDT

                        # Quantity step size multiple
                        rem = (child.quantity / filters.quantity_step_size) % 1
                        assert rem == Decimal("0")

                        # Filter bounds
                        assert child.quantity >= filters.quantity_min
                        assert child.price >= filters.price_min

        assert total_slices > 5000

    def test_sub_floor_and_zero_notional_rejection(self) -> None:
        """Verify fail-closed error handling on invalid parent notionals."""
        filters = get_default_exchange_filters()["BTCUSDT"]

        # Below 1.00 USDT floor
        sub_parent = ParentOrderIntention(
            parent_order_id="p-sub",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            target_notional_usdt=Decimal("0.99"),
            limit_price=Decimal("60000.0"),
        )
        with pytest.raises(MicroNotionalFloorViolationError):
            slice_parent_order(sub_parent, filters)

        # Zero notional
        zero_parent = ParentOrderIntention(
            parent_order_id="p-zero",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            target_notional_usdt=Decimal("0.00"),
            limit_price=Decimal("60000.0"),
        )
        with pytest.raises(ValueError):
            slice_parent_order(zero_parent, filters)

    def test_chunk_cap_clamping(self) -> None:
        """Verify that chunk_cap_usdt exceeding 5.00 USDT is strictly clamped to <= 5.00 USDT."""
        filters = get_default_exchange_filters()["BTCUSDT"]
        parent = ParentOrderIntention(
            parent_order_id="p-overcap",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            target_notional_usdt=Decimal("20.00"),
            limit_price=Decimal("60000.0"),
        )
        children = slice_parent_order(parent, filters, chunk_cap_usdt=Decimal("50.00"))
        for c in children:
            assert c.notional_usdt <= HARD_MICRO_NOTIONAL_CAP_USDT


class TestDoubleEntryBalanceZeroDriftStress:
    """Stress testing double-entry balance equation across 1,000 rapid transitions."""

    def test_1000_randomized_transitions_preserve_zero_drift(self) -> None:
        """Execute 1,000 fills, adds, closes, and mark updates with drift < 1e-15."""
        rng = random.Random(1337)
        ledger = PaperExecutionLedger(starting_equity=Decimal("100.00"))

        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        prices = {
            "BTCUSDT": Decimal("60000.00"),
            "ETHUSDT": Decimal("3000.00"),
            "SOLUSDT": Decimal("150.00"),
        }
        steps = {
            "BTCUSDT": Decimal("0.00001"),
            "ETHUSDT": Decimal("0.001"),
            "SOLUSDT": Decimal("0.01"),
        }

        fill_seq = 0
        for step_i in range(1000):
            sym = rng.choice(symbols)
            action_type = rng.choice(["MARK", "MARK", "FILL", "FILL", "FILL"])

            if action_type == "MARK":
                pct_change = Decimal(str(rng.uniform(-0.05, 0.05)))
                new_px = (prices[sym] * (Decimal("1.0") + pct_change)).quantize(
                    Decimal("0.01"), rounding=ROUND_DOWN
                )
                if new_px <= Decimal("0"):
                    new_px = Decimal("0.01")
                prices[sym] = new_px
                ledger.update_mark_price(sym, new_px)
            else:
                fill_seq += 1
                pos = ledger._positions.get(sym)
                px = prices[sym]
                step = steps[sym]

                if pos is None or pos.quantity <= Decimal("0"):
                    side = rng.choice([OrderSide.BUY, OrderSide.SELL])
                    notional = Decimal(f"{rng.uniform(1.5, 4.5):.2f}")
                    qty = (notional / px / step).to_integral_value(rounding=ROUND_DOWN) * step
                    if qty <= Decimal("0"):
                        qty = step
                    actual_notional = (qty * px).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )
                    fee = (actual_notional * Decimal("0.0002")).quantize(
                        Decimal("0.00000001"), rounding=ROUND_DOWN
                    )

                    fill = OrderExecutionFill(
                        fill_id=f"f-{fill_seq}",
                        symbol=sym,
                        side=side,
                        fill_price=px,
                        fill_quantity=qty,
                        fill_notional_usdt=actual_notional,
                        fee_usdt=fee,
                        is_maker=rng.choice([True, False]),
                    )
                    ledger.record_fill(fill)
                else:
                    roll = rng.random()
                    if roll < 0.40:
                        # Add
                        notional = Decimal(f"{rng.uniform(1.0, 3.0):.2f}")
                        qty = (notional / px / step).to_integral_value(rounding=ROUND_DOWN) * step
                        if qty <= Decimal("0"):
                            qty = step
                        actual_notional = (qty * px).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        fee = (actual_notional * Decimal("0.0002")).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        fill = OrderExecutionFill(
                            fill_id=f"f-{fill_seq}",
                            symbol=sym,
                            side=pos.side,
                            fill_price=px,
                            fill_quantity=qty,
                            fill_notional_usdt=actual_notional,
                            fee_usdt=fee,
                            is_maker=True,
                        )
                        ledger.record_fill(fill)
                    elif roll < 0.70:
                        # Partial close
                        opp_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                        frac = Decimal(str(rng.uniform(0.2, 0.8)))
                        qty = (pos.quantity * frac / step).to_integral_value(
                            rounding=ROUND_DOWN
                        ) * step
                        if qty <= Decimal("0") or qty >= pos.quantity:
                            qty = pos.quantity
                        actual_notional = (qty * px).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        fee = (actual_notional * Decimal("0.0002")).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        fill = OrderExecutionFill(
                            fill_id=f"f-{fill_seq}",
                            symbol=sym,
                            side=opp_side,
                            fill_price=px,
                            fill_quantity=qty,
                            fill_notional_usdt=actual_notional,
                            fee_usdt=fee,
                            is_maker=False,
                        )
                        ledger.record_fill(fill)
                    else:
                        # Reversal
                        opp_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                        excess = rng.randint(1, 5) * step
                        qty = pos.quantity + excess
                        actual_notional = (qty * px).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        fee = (actual_notional * Decimal("0.0002")).quantize(
                            Decimal("0.00000001"), rounding=ROUND_DOWN
                        )
                        fill = OrderExecutionFill(
                            fill_id=f"f-{fill_seq}",
                            symbol=sym,
                            side=opp_side,
                            fill_price=px,
                            fill_quantity=qty,
                            fill_notional_usdt=actual_notional,
                            fee_usdt=fee,
                            is_maker=False,
                            slippage_bps=Decimal("2.0"),
                        )
                        ledger.record_fill(fill)

            # Invariant check at every single transition
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
            drift = abs(lhs - rhs)
            assert drift < DOUBLE_ENTRY_MAX_DRIFT, (
                f"Drift {drift} >= {DOUBLE_ENTRY_MAX_DRIFT} at step {step_i}"
            )


class TestMerkleDAGAdversarialCorruption:
    """Stress testing Merkle DAG hash chain against single-byte tampering."""

    def test_single_byte_upstream_corruption_fails_verification(self) -> None:
        """Verify that single-byte corruption in upstream summary fails verification."""
        with tempfile.TemporaryDirectory(prefix="merkle_test_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            up_dir = tmp_path / "upstream"
            out_dir = tmp_path / "out"
            up_dir.mkdir()
            out_dir.mkdir()

            up_file = up_dir / "paper-execution-summary.json"
            p294_dir = _REPO_ROOT / "artifacts" / "research" / "phase294"
            real_up = p294_dir / "paper-execution-summary.json"
            orig_bytes = real_up.read_bytes() if real_up.exists() else b'{"phase":"294"}'
            up_file.write_bytes(orig_bytes)

            ledger = PaperExecutionLedger(starting_equity=Decimal("100.00"))
            candidate_records = [
                OOSPromotionGateRecord(
                    candidate_id="cand-btc",
                    symbol="BTCUSDT",
                    status=CandidatePromotionStatus.PROMOTED,
                    oos_average_return_pct=Decimal("3.0"),
                    oos_worst_drawdown_pct=Decimal("9.0"),
                    oos_profit_factor=Decimal("1.7"),
                    oos_trade_count=10,
                    oos_window_count=3,
                    gates_passed={"avg_return": True},
                    qualified=True,
                    evaluated_at=datetime.now(UTC),
                )
            ]
            child_orders = [
                ChildOrderIntention(
                    client_order_id="c-0",
                    child_id="c-0",
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
                manifest_version=2,
            )

            # Clean verification passes
            assert verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir) is True

            # Corrupt single byte at multiple positions
            offsets = [0, len(orig_bytes) // 2, len(orig_bytes) - 1]
            for off in offsets:
                corrupted = bytearray(orig_bytes)
                corrupted[off] ^= 0xFF
                up_file.write_bytes(corrupted)
                assert verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir) is False

            # Restore and verify recovery
            up_file.write_bytes(orig_bytes)
            assert verify_phase295_artifacts(output_dir=out_dir, upstream_dir=up_dir) is True
