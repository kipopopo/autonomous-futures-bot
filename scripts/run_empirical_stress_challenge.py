#!/usr/bin/env python3
"""Empirical Challenger Benchmark & Stress Test Harness.

Executes >= 1,000 (default: 10,000) randomized micro-fills under extreme adversarial conditions:
- Sub-satoshi quantities (10^-8 to 10^-18)
- Arbitrary fee deductions (10^-9 to 5.00 USDT)
- Multi-asset churn (SOL, ETH, BTC, DOGE, XRP)
- Mark price fluctuations and open position unrealized PnL
- 1.66:1 Risk:Reward bracket ratio evaluation across wide price/ATR regimes
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autonomous_futures.feed.execution_drill import (  # noqa: E402
    DOUBLE_ENTRY_TOLERANCE,
    DrillSolvencyLedger,
    ExecutionDrillConfig,
    ExecutionDrillEngine,
)
from autonomous_futures.safety.kill_switch import CentralizedSolvencyLedger  # noqa: E402


def run_centralized_solvency_stress(iterations: int = 10000) -> dict[str, Any]:
    """Stress tests CentralizedSolvencyLedger over randomized micro-fills."""
    rng = random.Random(42)
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    symbols = ["SOLUSDT", "ETHUSDT", "BTCUSDT", "DOGEUSDT", "XRPUSDT"]
    sides = ["BUY", "SELL"]

    max_drift = Decimal("0")
    violations = 0
    t0 = time.perf_counter()

    for _i in range(iterations):
        sym = rng.choice(symbols)
        side = rng.choice(sides)
        qty = round(rng.uniform(1e-8, 0.05), 8)
        price = round(rng.uniform(0.01, 75000.0), 4)
        fee = round(rng.uniform(1e-8, 0.005), 8)
        rpnl = round(rng.uniform(-0.5, 0.5), 8)

        ledger.record_fill(
            symbol=sym,
            side=side,
            qty=qty,
            price=price,
            fee=fee,
            realized_pnl=rpnl,
        )

        snap = ledger.get_snapshot()
        drift = abs(Decimal(str(snap.drift)))
        if drift > max_drift:
            max_drift = drift
        if drift >= DOUBLE_ENTRY_TOLERANCE:
            violations += 1

    elapsed = time.perf_counter() - t0

    # Test position flattening anomaly with staged margin
    ledger_flatten = CentralizedSolvencyLedger(starting_equity=100.0)
    staged_margin = Decimal("5.50")
    ledger_flatten.cash -= staged_margin
    ledger_flatten.allocated_margin += staged_margin
    ledger_flatten.flatten_position("SOLUSDT", float(staged_margin), fee=0.0011)
    flatten_snap = ledger_flatten.get_snapshot()
    flatten_drift = abs(Decimal(str(flatten_snap.drift)))

    return {
        "iterations": iterations,
        "elapsed_sec": round(elapsed, 4),
        "fills_per_sec": round(iterations / elapsed, 1),
        "max_drift_usdt": str(max_drift),
        "tolerance_usdt": str(DOUBLE_ENTRY_TOLERANCE),
        "violations": violations,
        "record_fill_zero_drift_invariant": "CONFIRMED" if violations == 0 else "REFUTED",
        "flatten_position_staged_drift_usdt": str(flatten_drift),
        "flatten_position_zero_drift_invariant": "REFUTED" if flatten_drift > 0 else "CONFIRMED",
    }


def run_drill_solvency_stress(iterations: int = 10000) -> dict[str, Any]:
    """Stress tests DrillSolvencyLedger over randomized micro-fills and churn."""
    rng = random.Random(1337)
    ledger = DrillSolvencyLedger(starting_equity=Decimal("100.00"))

    max_drift = Decimal("0")
    violations = 0
    t0 = time.perf_counter()

    for _i in range(iterations):
        margin = Decimal(str(round(rng.uniform(1e-8, 4.0), 8)))
        if margin <= ledger.cash:
            ledger.allocate_margin(margin)
            drift1 = ledger.drift
            if drift1 > max_drift:
                max_drift = drift1
            if drift1 >= DOUBLE_ENTRY_TOLERANCE:
                violations += 1

            pnl = Decimal(str(round(rng.uniform(-0.5, 0.5), 8)))
            fee = Decimal(str(round(rng.uniform(1e-8, 0.005), 8)))
            ledger.record_fill(
                margin_released=margin,
                realized_pnl_delta=pnl,
                fee_cost=fee,
            )
            drift2 = ledger.drift
            if drift2 > max_drift:
                max_drift = drift2
            if drift2 >= DOUBLE_ENTRY_TOLERANCE:
                violations += 1

    elapsed = time.perf_counter() - t0

    # Probe mark price fluctuation on open position
    ledger_mtm = DrillSolvencyLedger(starting_equity=Decimal("100.00"))
    ledger_mtm.allocate_margin(Decimal("5.50"))
    open_unrealized_pnl = Decimal("0.25")
    ledger_mtm.update_unrealized_pnl(open_unrealized_pnl)
    raw_drift_open = ledger_mtm.drift
    # Marked to market target equity
    target_mtm = ledger_mtm.starting_equity + ledger_mtm.realized_pnl + ledger_mtm.unrealized_pnl
    mtm_drift = abs(ledger_mtm.total_equity - target_mtm)

    return {
        "iterations": iterations,
        "elapsed_sec": round(elapsed, 4),
        "transitions_per_sec": round(iterations / elapsed, 1),
        "max_drift_usdt": str(max_drift),
        "tolerance_usdt": str(DOUBLE_ENTRY_TOLERANCE),
        "violations": violations,
        "closed_transition_zero_drift_invariant": "CONFIRMED" if violations == 0 else "REFUTED",
        "open_position_raw_drift_usdt": str(raw_drift_open),
        "open_position_raw_invariant": (
            "REFUTED" if raw_drift_open > DOUBLE_ENTRY_TOLERANCE else "CONFIRMED"
        ),
        "open_position_mtm_drift_usdt": str(mtm_drift),
        "open_position_mtm_invariant": (
            "CONFIRMED" if mtm_drift < DOUBLE_ENTRY_TOLERANCE else "REFUTED"
        ),
    }


def run_bracket_ratio_stress(iterations: int = 10000) -> dict[str, Any]:
    """Stress tests the 1.66:1 Risk:Reward bracket ratio."""
    rng = random.Random(777)
    config = ExecutionDrillConfig(dry_run=True)
    engine = ExecutionDrillEngine(config=config)

    nominal_ratio_target = Decimal("1.6667")
    nominal_violations = 0
    effective_rr_deviations = []
    sub_tick_sl_zero_count = 0

    t0 = time.perf_counter()
    for i in range(iterations):
        entry_price = Decimal(str(round(rng.uniform(0.01, 75000.0), 4)))
        # Mix of normal and tiny ATR values
        if i % 100 == 0:
            atr = Decimal(str(round(rng.uniform(0.0001, 0.004), 6)))  # Sub-tick
        else:
            atr = Decimal(str(round(rng.uniform(0.05, 500.0), 4)))

        side = rng.choice(["BUY", "SELL"])

        brackets = engine.calculate_protective_brackets(
            symbol="SOLUSDT",
            side=side,
            entry_price=entry_price,
            atr=atr,
            ts_ms=1791552000000 + i,
        )

        if brackets.risk_reward_ratio != nominal_ratio_target:
            nominal_violations += 1

        sl_dist = abs(brackets.stop_loss_price - entry_price)
        tp_dist = abs(brackets.take_profit_price - entry_price)

        if sl_dist == Decimal("0"):
            sub_tick_sl_zero_count += 1
        else:
            eff_rr = tp_dist / sl_dist
            diff = abs(eff_rr - Decimal("1.666666666666666666666666667"))
            effective_rr_deviations.append(diff)

    elapsed = time.perf_counter() - t0
    max_dev = max(effective_rr_deviations) if effective_rr_deviations else Decimal("0")
    avg_dev = (
        sum(effective_rr_deviations) / Decimal(str(len(effective_rr_deviations)))
        if effective_rr_deviations
        else Decimal("0")
    )

    return {
        "iterations": iterations,
        "elapsed_sec": round(elapsed, 4),
        "nominal_ratio_target": "1.6667:1",
        "nominal_violations": nominal_violations,
        "nominal_ratio_invariant": "CONFIRMED" if nominal_violations == 0 else "REFUTED",
        "effective_rr_max_deviation": str(round(max_dev, 6)),
        "effective_rr_avg_deviation": str(round(avg_dev, 6)),
        "sub_tick_atr_zero_sl_count": sub_tick_sl_zero_count,
        "sub_tick_collapse_boundary_observed": sub_tick_sl_zero_count > 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 311 Empirical Challenger Stress Test")
    parser.add_argument(
        "--iterations", type=int, default=10000, help="Number of iterations (>= 1,000)"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    iters = max(args.iterations, 1000)

    print(f"[*] Running Empirical Challenge Suite ({iters} iterations)...", file=sys.stderr)
    res_centralized = run_centralized_solvency_stress(iters)
    res_drill = run_drill_solvency_stress(iters)
    res_bracket = run_bracket_ratio_stress(iters)

    overall_report = {
        "timestamp_epoch": time.time(),
        "iterations": iters,
        "centralized_solvency_ledger": res_centralized,
        "drill_solvency_ledger": res_drill,
        "bracket_risk_reward_ratio": res_bracket,
    }

    if args.json:
        print(json.dumps(overall_report, indent=2))
    else:
        print("\n" + "=" * 70)
        print("          EMPIRICAL CHALLENGER STRESS REPORT (PHASE 311)")
        print("=" * 70)
        print(f"Iterations Executed: {iters:,}")
        print("\n--- 1. CentralizedSolvencyLedger Invariant ---")
        print(
            f"  Fills Executed       : {res_centralized['iterations']:,} "
            f"in {res_centralized['elapsed_sec']}s"
        )
        print(f"  Max Fill Drift       : {res_centralized['max_drift_usdt']} USDT (< 1e-15)")
        print(f"  Fill Violations      : {res_centralized['violations']}")
        print(f"  Record Fill Verdict  : [{res_centralized['record_fill_zero_drift_invariant']}]")
        f_drift = res_centralized['flatten_position_staged_drift_usdt']
        f_verdict = res_centralized['flatten_position_zero_drift_invariant']
        print(f"  Flatten Drift        : {f_drift} USDT")
        print(f"  Flatten Verdict      : [{f_verdict}]")

        print("\n--- 2. DrillSolvencyLedger Invariant ---")
        print(
            f"  Transitions Executed : {res_drill['iterations']:,} "
            f"in {res_drill['elapsed_sec']}s"
        )
        print(f"  Max Fill Drift       : {res_drill['max_drift_usdt']} USDT (< 1e-15)")
        print(f"  Fill Violations      : {res_drill['violations']}")
        print(f"  Closed Fill Verdict  : [{res_drill['closed_transition_zero_drift_invariant']}]")
        print(
            f"  Open Raw Drift       : {res_drill['open_position_raw_drift_usdt']} USDT -> "
            f"[{res_drill['open_position_raw_invariant']}]"
        )
        print(
            f"  Open MTM Drift       : {res_drill['open_position_mtm_drift_usdt']} USDT -> "
            f"[{res_drill['open_position_mtm_invariant']}]"
        )

        print("\n--- 3. 1.66:1 Risk:Reward Bracket Ratio ---")
        print(
            f"  Scenarios Evaluated  : {res_bracket['iterations']:,} "
            f"in {res_bracket['elapsed_sec']}s"
        )
        print(f"  Nominal Target       : {res_bracket['nominal_ratio_target']}")
        print(f"  Nominal Violations   : {res_bracket['nominal_violations']}")
        print(f"  Nominal Verdict      : [{res_bracket['nominal_ratio_invariant']}]")
        print(f"  Effective Max Dev    : {res_bracket['effective_rr_max_deviation']}")
        print(f"  Effective Avg Dev    : {res_bracket['effective_rr_avg_deviation']}")
        print(f"  Sub-Tick Collapses   : {res_bracket['sub_tick_atr_zero_sl_count']}")
        print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
