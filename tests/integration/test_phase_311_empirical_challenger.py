"""Phase 311 Empirical Challenger Stress Test Suite.

Adversarially probes:
1. Double-entry zero-drift balance invariant of CentralizedSolvencyLedger across >= 1,000 fills.
2. Double-entry zero-drift balance invariant of DrillSolvencyLedger across >= 1,000 fills.
3. Mark price fluctuations and open position unrealized PnL drift dynamics.
4. Emergency position flattening behavior and margin release integrity.
5. 1.66:1 Risk:Reward bracket ratio across 1,000 randomized entry prices and ATR regimes.
6. Edge case boundary probing (sub-tick ATR quantization, zero ATR, extreme prices).
"""

from __future__ import annotations

import random
from decimal import Decimal

from autonomous_futures.feed.execution_drill import (
    DOUBLE_ENTRY_TOLERANCE,
    DrillSolvencyLedger,
    ExecutionDrillConfig,
    ExecutionDrillEngine,
)
from autonomous_futures.safety.kill_switch import CentralizedSolvencyLedger


class TestEmpiricalCentralizedSolvencyLedgerStress:
    """Empirical challenge on CentralizedSolvencyLedger double-entry invariant."""

    def test_1000_randomized_micro_fills_sub_satoshi(self) -> None:
        """Executes >= 1,000 randomized micro-fills with sub-satoshi quantities."""
        rng = random.Random(42)
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        max_drift = Decimal("0")
        total_fills = 1200  # >= 1000

        symbols = ["SOLUSDT", "ETHUSDT", "BTCUSDT"]

        for i in range(total_fills):
            sym = rng.choice(symbols)
            side = rng.choice(["BUY", "SELL"])
            # Sub-satoshi quantities down to 10^-8
            qty = round(rng.uniform(1e-8, 0.05), 8)
            price = round(rng.uniform(10.0, 70000.0), 2)
            # Arbitrary fee deductions down to 10^-8
            fee = round(rng.uniform(1e-8, 0.005), 8)
            # Realized PnL variations
            rpnl = round(rng.uniform(-0.50, 0.50), 8)

            success = ledger.record_fill(
                symbol=sym,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                realized_pnl=rpnl,
            )
            assert success is True

            snap = ledger.get_snapshot()
            drift_dec = abs(Decimal(str(snap.drift)))
            if drift_dec > max_drift:
                max_drift = drift_dec

            assert drift_dec < DOUBLE_ENTRY_TOLERANCE, (
                f"Transition {i}: drift {drift_dec} exceeds tolerance {DOUBLE_ENTRY_TOLERANCE}"
            )
            assert snap.zero_balance_drift is True

        assert total_fills >= 1000
        assert max_drift < DOUBLE_ENTRY_TOLERANCE

    def test_sub_satoshi_extreme_precision_micro_fills(self) -> None:
        """Executes fills with sub-satoshi fractional precision down to 10^-12."""
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)

        # Micro-fills with high precision
        sub_satoshi_fees = [
            0.00000001,  # 10^-8
            0.000000001,  # 10^-9
            0.0000000001,  # 10^-10
            0.00000000001,  # 10^-11
            0.000000000001,  # 10^-12
        ]

        for fee in sub_satoshi_fees:
            ledger.record_fill(
                symbol="SOLUSDT",
                side="BUY",
                qty=0.00000001,
                price=110.0,
                fee=fee,
                realized_pnl=0.00000002,
            )
            snap = ledger.get_snapshot()
            assert abs(Decimal(str(snap.drift))) < DOUBLE_ENTRY_TOLERANCE
            assert snap.zero_balance_drift is True

    def test_flatten_position_anomaly_when_margin_is_staged(self) -> None:
        """Empirically probes CentralizedSolvencyLedger.flatten_position with staged margin.

        Critical Finding: In CentralizedSolvencyLedger.flatten_position(symbol, notional, fee):
        The released notional margin is decremented from allocated_margin but never credited
        back to cash!
        Consequently, total_equity drops by notional, creating a severe drift of |notional|!
        """
        ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        # Stage margin (e.g. 5.50 USDT allocated)
        staged_margin = Decimal("5.50")
        ledger.cash -= staged_margin
        ledger.allocated_margin += staged_margin

        # Prior to flatten: drift is strictly 0.00
        snap_before = ledger.get_snapshot()
        assert abs(Decimal(str(snap_before.drift))) < DOUBLE_ENTRY_TOLERANCE
        assert snap_before.zero_balance_drift is True

        # Flatten position using built-in flatten_position
        ledger.flatten_position(symbol="SOLUSDT", notional=float(staged_margin), fee=0.0011)
        snap_after = ledger.get_snapshot()

        # EMPIRICAL DISCOVERY:
        # snap_after.drift is -5.50 USDT (NOT < 1e-15!)
        # zero_balance_drift is FALSE!
        drift_magnitude = abs(Decimal(str(snap_after.drift)))
        msg = f"Expected drift equal to margin {staged_margin}, got {drift_magnitude}"
        assert drift_magnitude == staged_margin, msg
        assert snap_after.zero_balance_drift is False, (
            "Empirical verification: flatten_position violates zero-drift invariant when margin > 0"
        )


class TestEmpiricalDrillSolvencyLedgerStress:
    """Empirical challenge on DrillSolvencyLedger double-entry invariant."""

    def test_1000_randomized_micro_fills_and_position_churn(self) -> None:
        """Executes >= 1,000 randomized micro-allocations and fills on DrillSolvencyLedger."""
        rng = random.Random(1337)
        ledger = DrillSolvencyLedger(starting_equity=Decimal("100.00"))
        max_drift = Decimal("0")
        total_transitions = 1500  # >= 1000

        for _i in range(total_transitions):
            # Step A: Allocate randomized micro-margin
            margin_amt = Decimal(str(round(rng.uniform(1e-8, 4.5), 8)))
            if margin_amt <= ledger.cash:
                allocated = ledger.allocate_margin(margin_amt)
                assert allocated is True
                assert ledger.is_zero_drift is True
                drift_step1 = ledger.drift
                if drift_step1 > max_drift:
                    max_drift = drift_step1
                assert drift_step1 < DOUBLE_ENTRY_TOLERANCE

                # Step B: Record fill (release margin, credit/debit PnL and fee)
                pnl = Decimal(str(round(rng.uniform(-0.5, 0.5), 8)))
                fee = Decimal(str(round(rng.uniform(1e-8, 0.005), 8)))
                ledger.record_fill(
                    margin_released=margin_amt,
                    realized_pnl_delta=pnl,
                    fee_cost=fee,
                )
                assert ledger.is_zero_drift is True
                drift_step2 = ledger.drift
                if drift_step2 > max_drift:
                    max_drift = drift_step2
                assert drift_step2 < DOUBLE_ENTRY_TOLERANCE

        assert total_transitions >= 1000
        assert max_drift < DOUBLE_ENTRY_TOLERANCE

    def test_multi_asset_concurrent_position_churn(self) -> None:
        """Simulates interleaved multi-asset positions (SOL, ETH, BTC) across 1,000 steps."""
        rng = random.Random(999)
        ledger = DrillSolvencyLedger(starting_equity=Decimal("200.00"))

        active_positions: dict[str, Decimal] = {
            "SOLUSDT": Decimal("0"),
            "ETHUSDT": Decimal("0"),
            "BTCUSDT": Decimal("0"),
        }

        for _i in range(1000):
            sym = rng.choice(list(active_positions.keys()))
            action = rng.choice(["ALLOCATE", "FILL", "PARTIAL_RELEASE"])

            if action == "ALLOCATE":
                add_margin = Decimal(str(round(rng.uniform(0.1, 1.0), 4)))
                if add_margin <= ledger.cash:
                    ledger.allocate_margin(add_margin)
                    active_positions[sym] += add_margin
            elif action == "FILL" and active_positions[sym] > Decimal("0"):
                rel_margin = active_positions[sym]
                pnl = Decimal(str(round(rng.uniform(-0.2, 0.2), 4)))
                fee = Decimal("0.001")
                ledger.record_fill(rel_margin, pnl, fee)
                active_positions[sym] = Decimal("0")
            elif action == "PARTIAL_RELEASE" and active_positions[sym] > Decimal("0.5"):
                part_margin = Decimal("0.25")
                pnl = Decimal("0.01")
                fee = Decimal("0.0005")
                ledger.record_fill(part_margin, pnl, fee)
                active_positions[sym] -= part_margin

            # Zero-drift check at EVERY transition
            assert ledger.is_zero_drift is True
            assert ledger.drift < DOUBLE_ENTRY_TOLERANCE

    def test_mark_price_fluctuation_unrealized_pnl_dynamics(self) -> None:
        """Empirically tests mark price fluctuations on DrillSolvencyLedger.

        Empirical Finding:
        In DrillSolvencyLedger:
        total_equity = cash + allocated_margin + unrealized_pnl
        target_equity = starting_equity + realized_pnl
        drift = abs(total_equity - target_equity)

        When an open position mark price moves, unrealized_pnl != 0.
        Because target_equity does not add unrealized_pnl, ledger.drift equals |unrealized_pnl|!
        Under the strict equation Cash + Margin + Unrealized PnL == Starting Equity + Realized PnL,
        the invariant holds if and only if unrealized_pnl is 0 (i.e. flat transitions),
        or if target_equity incorporates unrealized_pnl:
        target_equity = starting_equity + realized_pnl + unrealized_pnl.
        """
        ledger = DrillSolvencyLedger(starting_equity=Decimal("100.00"))
        # Allocate 5.50 USDT margin for SOL
        ledger.allocate_margin(Decimal("5.50"))
        assert ledger.is_zero_drift is True

        # Simulate mark price moving from 110.00 to 112.50 (+2.27%)
        # For 0.05 SOL, unrealized PnL = 0.05 * 2.50 = +0.125 USDT
        mark_pnl = Decimal("0.1250")
        ledger.update_unrealized_pnl(mark_pnl)

        # Built-in ledger.drift is 0.1250 USDT
        assert ledger.drift == mark_pnl
        assert ledger.is_zero_drift is False

        # In true double-entry accounting with marked-to-market positions:
        # total_equity = cash + allocated_margin + unrealized_pnl
        # target_equity_mtm = starting_equity + realized_pnl + unrealized_pnl
        target_equity_mtm = ledger.starting_equity + ledger.realized_pnl + ledger.unrealized_pnl
        mtm_drift = abs(ledger.total_equity - target_equity_mtm)
        assert mtm_drift < DOUBLE_ENTRY_TOLERANCE, (
            "Marked-to-market invariant holds: |total - target_mtm| < 1e-15"
        )

        # Upon closing / flattening the position:
        # Unrealized PnL converts to Realized PnL, and unrealized_pnl resets to 0.00:
        ledger.record_fill(
            margin_released=Decimal("5.50"),
            realized_pnl_delta=mark_pnl,
            fee_cost=Decimal("0.0011"),
        )
        ledger.update_unrealized_pnl(Decimal("0.00"))

        assert ledger.is_zero_drift is True
        assert ledger.drift < DOUBLE_ENTRY_TOLERANCE


class TestEmpiricalRiskRewardBracketRatioStress:
    """Empirical challenge on the 1.66:1 Risk:Reward bracket ratio."""

    def test_nominal_rr_ratio_166_across_1000_random_scenarios(self) -> None:
        """Evaluates calculate_protective_brackets across 1,000 random entry prices and ATRs."""
        rng = random.Random(777)
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        total_scenarios = 1000
        for i in range(total_scenarios):
            entry_price = Decimal(str(round(rng.uniform(0.1, 100000.0), 4)))
            atr = Decimal(str(round(rng.uniform(0.05, 500.0), 4)))
            side = rng.choice(["BUY", "SELL"])

            brackets = engine.calculate_protective_brackets(
                symbol="SOLUSDT",
                side=side,
                entry_price=entry_price,
                atr=atr,
                ts_ms=1791552000000 + i,
            )

            # 1. Configured nominal ratio is strictly 1.6667 (1.66:1)
            assert brackets.risk_reward_ratio == Decimal("1.6667")

            # 2. Geometry: TP and SL are on appropriate sides of entry price
            if side == "BUY":
                assert brackets.take_profit_price > entry_price
                assert brackets.stop_loss_price < entry_price
            else:
                assert brackets.take_profit_price < entry_price
                assert brackets.stop_loss_price > entry_price

    def test_quantized_effective_rr_ratio_distribution(self) -> None:
        """Measures effective realized R:R ratio deviation caused by tick size quantization.

        Effective R:R = |tp_price - entry_price| / |sl_price - entry_price|
        Nominal target = 2.0 / 1.2 = 1.66666...
        """
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        # Test canonical SOLUSDT (entry ~ 110.00, ATR ~ 1.50, tick = 0.01)
        brackets = engine.calculate_protective_brackets(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("110.00"),
            atr=Decimal("1.50"),
            ts_ms=1791552000000,
        )
        # tp_dist = 2.0 * 1.50 = 3.00 -> tp_price = 113.00
        # sl_dist = 1.2 * 1.50 = 1.80 -> sl_price = 108.20
        eff_rr = abs(brackets.take_profit_price - brackets.entry_price) / abs(
            brackets.stop_loss_price - brackets.entry_price
        )
        assert eff_rr.quantize(Decimal("0.0001")) == Decimal("1.6667")

    def test_adversarial_sub_tick_atr_boundary(self) -> None:
        """Probes boundary condition where ATR is smaller than tick size.

        When ATR is extremely tiny (e.g., 0.003 USDT with tick size 0.01 USDT):
        sl_distance = 1.2 * 0.003 = 0.0036.
        quantize_tick_size(100.00 - 0.0036, 0.01) rounds to 100.00!
        sl_price becomes equal to entry_price, collapsing the Stop-Loss bracket!
        """
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        entry_price = Decimal("100.00")
        micro_atr = Decimal("0.003")  # Less than half tick size (0.01 / 2 = 0.005)

        brackets = engine.calculate_protective_brackets(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=entry_price,
            atr=micro_atr,
            ts_ms=1791552000000,
        )

        # Empirical finding: sl_price rounds to entry_price!
        sl_distance = abs(brackets.stop_loss_price - entry_price)
        assert sl_distance == Decimal("0.00"), (
            "Empirical boundary finding: Sub-tick ATR causes stop_loss_price to equal entry_price!"
        )
        assert brackets.sl_distance_pct == Decimal("0.0")

    def test_zero_atr_boundary(self) -> None:
        """Probes ATR = 0 condition: brackets collapse to entry price."""
        config = ExecutionDrillConfig(dry_run=True)
        engine = ExecutionDrillEngine(config=config)

        entry_price = Decimal("100.00")
        zero_atr = Decimal("0.00")

        brackets = engine.calculate_protective_brackets(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=entry_price,
            atr=zero_atr,
            ts_ms=1791552000000,
        )

        assert brackets.take_profit_price == entry_price
        assert brackets.stop_loss_price == entry_price
        assert brackets.tp_distance_pct == Decimal("0.0")
        assert brackets.sl_distance_pct == Decimal("0.0")
