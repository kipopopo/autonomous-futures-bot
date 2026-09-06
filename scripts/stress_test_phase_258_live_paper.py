"""Phase 258 Milestone M1: Empirical Stress Harness Script.

Executes standalone empirical stress testing across extreme market conditions:
- Sudden price gaps (+/- 20% on Long and Short, and 4-asset simultaneous crash)
- Crossed bid/ask books rejection at domain model and wire parsing levels
- Massive spread blowouts (>= 50 bps) and circuit breaker halt transitions
- Dynamic leverage boundary conditions (conviction < 0.50, = 0.50, = 0.75, = 1.00, > 1.00)
- Rapid tick burst processing (10,000 ticks) with zero unhandled exceptions
- Non-negative equity floor verification (Equity > 0)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is importable
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from pydantic import ValidationError  # noqa: E402

from autonomous_futures.feed.models import (  # noqa: E402
    TickerSnapshot,
    parse_binance_book_ticker,
)
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.live_engine import (  # noqa: E402
    LivePaperEngine,
)
from autonomous_futures.research.creator_artifacts import (  # noqa: E402
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)

logger = logging.getLogger("stress_test_phase_258")


def load_candidate_artifacts() -> dict[str, CreatorCandidateArtifact]:
    """Load pinned candidate artifacts for BTC, ETH, SOL, DOGE."""
    cand_dir = Path("artifacts/research/phase252/candidates")
    if not cand_dir.is_dir():
        raise RuntimeError(f"Candidate directory missing: {cand_dir}")
    cands: dict[str, CreatorCandidateArtifact] = {}
    for p in cand_dir.glob("cand-*.json"):
        c = read_creator_candidate_artifact(p)
        cands[c.strategy.universe.symbols[0]] = c
    return cands


async def run_empirical_stress_harness() -> dict[str, Any]:
    """Run all stress test suites and return structured evidence dictionary."""
    candidates = load_candidate_artifacts()
    results: dict[str, Any] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "suites": {},
    }

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_str:
        tmp_dir = Path(tmp_str)

        # ---------------------------------------------------------------------
        # 1. Sudden Price Gaps & Non-Negative Equity Floor
        # ---------------------------------------------------------------------
        print("[1/5] Stress Testing Sudden Price Gaps (+/-20%) & Equity Floor...")
        gap_results: dict[str, Any] = {}

        # 1A. Sudden -20% gap on Long position
        engine_long_drop = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_dir / "l_long_drop.sqlite3",
            lifecycle_db=tmp_dir / "lc_long_drop.sqlite3",
            observations_db=tmp_dir / "o_long_drop.sqlite3",
            candidates=candidates,
        )
        t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
        engine_long_drop.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t0,
            event_time=t0,
        )
        engine_long_drop.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=t0
        )
        assert len(engine_long_drop.active_trades) == 1

        # Crash -20% to 48,000
        t1 = t0 + timedelta(seconds=1)
        crash_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("48000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("48002.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        await engine_long_drop.handle_ticker(crash_ticker)
        assert len(engine_long_drop.active_trades) == 0
        eq_after_drop = engine_long_drop.current_equity()
        assert eq_after_drop > Decimal("0")
        assert engine_long_drop.reconcile_balances()["zero_balance_drift"] is True
        gap_results["long_down_20_pct"] = {
            "status": "PASSED",
            "equity_remaining": str(eq_after_drop),
            "cash_remaining": str(engine_long_drop.account.cash),
            "trades_closed": engine_long_drop.total_closed_trades,
            "zero_balance_drift": True,
        }

        # 1B. Sudden +20% gap on Short position
        engine_short_surge = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_dir / "l_short_surge.sqlite3",
            lifecycle_db=tmp_dir / "lc_short_surge.sqlite3",
            observations_db=tmp_dir / "o_short_surge.sqlite3",
            candidates=candidates,
        )
        engine_short_surge.latest_tickers["BTCUSDT"] = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t0,
            event_time=t0,
        )
        engine_short_surge.execute_open(
            "BTCUSDT", signal=-1, conviction=Decimal("1.00"), event_time=t0
        )
        assert len(engine_short_surge.active_trades) == 1

        # Surge +20% to 72,000
        surge_ticker = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("71998.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("72000.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        await engine_short_surge.handle_ticker(surge_ticker)
        assert len(engine_short_surge.active_trades) == 0
        eq_after_surge = engine_short_surge.current_equity()
        assert eq_after_surge > Decimal("0")
        assert engine_short_surge.reconcile_balances()["zero_balance_drift"] is True
        gap_results["short_up_20_pct"] = {
            "status": "PASSED",
            "equity_remaining": str(eq_after_surge),
            "cash_remaining": str(engine_short_surge.account.cash),
            "trades_closed": engine_short_surge.total_closed_trades,
            "zero_balance_drift": True,
        }

        # 1C. Simultaneous -20% crash across all 4 portfolio positions
        symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
        engine_quad = LivePaperEngine(
            symbols=symbols,
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_dir / "l_quad.sqlite3",
            lifecycle_db=tmp_dir / "lc_quad.sqlite3",
            observations_db=tmp_dir / "o_quad.sqlite3",
            candidates=candidates,
        )
        nominal_prices = {
            "BTCUSDT": Decimal("60000.00"),
            "ETHUSDT": Decimal("3000.00"),
            "SOLUSDT": Decimal("150.00"),
            "DOGEUSDT": Decimal("0.1500"),
        }
        for sym in symbols:
            p = nominal_prices[sym]
            engine_quad.latest_tickers[sym] = TickerSnapshot(
                symbol=sym,
                best_bid_price=p,
                best_bid_qty=Decimal("10.0"),
                best_ask_price=p * Decimal("1.0001"),
                best_ask_qty=Decimal("10.0"),
                transaction_time=t0,
                event_time=t0,
            )
            engine_quad.execute_open(sym, signal=1, conviction=Decimal("1.00"), event_time=t0)
        assert len(engine_quad.active_trades) == 4
        assert engine_quad.account.total_locked_margin() == Decimal("80.00")

        for sym in symbols:
            crashed_p = nominal_prices[sym] * Decimal("0.80")
            c_tick = TickerSnapshot(
                symbol=sym,
                best_bid_price=crashed_p,
                best_bid_qty=Decimal("10.0"),
                best_ask_price=crashed_p * Decimal("1.0001"),
                best_ask_qty=Decimal("10.0"),
                transaction_time=t1,
                event_time=t1,
            )
            await engine_quad.handle_ticker(c_tick)
        assert len(engine_quad.active_trades) == 0
        assert engine_quad.total_closed_trades == 4
        quad_eq = engine_quad.current_equity()
        assert quad_eq > Decimal("50.00"), f"Expected equity > 50 USDT, got {quad_eq}"
        assert engine_quad.account.cash > Decimal("50.00")
        assert engine_quad.reconcile_balances()["zero_balance_drift"] is True
        gap_results["quad_portfolio_simultaneous_crash"] = {
            "status": "PASSED",
            "starting_capital": "100.00",
            "ending_equity": str(quad_eq),
            "ending_cash": str(engine_quad.account.cash),
            "total_trades_closed": 4,
            "zero_balance_drift": True,
            "equity_floor_preserved": True,
        }
        results["suites"]["sudden_price_gaps"] = gap_results

        # ---------------------------------------------------------------------
        # 2. Crossed Bid/Ask Books Handling
        # ---------------------------------------------------------------------
        print("[2/5] Stress Testing Crossed Bid/Ask Books Validation...")
        crossed_results: dict[str, Any] = {}
        try:
            TickerSnapshot(
                symbol="BTCUSDT",
                best_bid_price=Decimal("60010.00"),
                best_bid_qty=Decimal("1.0"),
                best_ask_price=Decimal("60000.00"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=t0,
                event_time=t0,
            )
            crossed_snapshot_rejected = False
        except ValidationError:
            crossed_snapshot_rejected = True

        try:
            parse_binance_book_ticker(
                {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "s": "BTCUSDT",
                        "b": "60010.00",
                        "B": "1.0",
                        "a": "60000.00",
                        "A": "1.0",
                        "T": 1788622800000,
                        "E": 1788622800000,
                    },
                }
            )
            crossed_wire_rejected = False
        except ValidationError:
            crossed_wire_rejected = True

        assert crossed_snapshot_rejected and crossed_wire_rejected
        crossed_results["domain_model_validation"] = {
            "status": "PASSED",
            "ticker_snapshot_rejected": crossed_snapshot_rejected,
            "wire_parser_rejected": crossed_wire_rejected,
            "validation_error_confirmed": True,
        }
        results["suites"]["crossed_books"] = crossed_results

        # ---------------------------------------------------------------------
        # 3. Massive Spread Blowouts (>= 50 bps) & Circuit Breaker Halts
        # ---------------------------------------------------------------------
        print("[3/5] Stress Testing Massive Spread Blowouts (>= 50 bps) & Halts...")
        spread_results: dict[str, Any] = {}
        engine_spread = LivePaperEngine(
            symbols=("BTCUSDT",),
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_dir / "l_spread.sqlite3",
            lifecycle_db=tmp_dir / "lc_spread.sqlite3",
            observations_db=tmp_dir / "o_spread.sqlite3",
            candidates=candidates,
        )
        blowout_tick = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60360.00"),  # ~60 bps spread
            best_ask_qty=Decimal("1.0"),
            transaction_time=t0,
            event_time=t0,
        )
        assert blowout_tick.spread_bps >= Decimal("50.0")

        # Instantaneous guard: order rejected
        engine_spread.latest_tickers["BTCUSDT"] = blowout_tick
        res_blowout = engine_spread.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=t0
        )
        assert res_blowout is None

        # Feed into monitor
        await engine_spread.handle_ticker(blowout_tick)
        await engine_spread.monitor.process_single_queue_item()

        # Assert account state transitioned to HALTED
        assert str(engine_spread.account.current_state) == "HALTED"
        assert engine_spread.account.calculate_hardened_leverage(Decimal("1.00")) == Decimal("0.0")

        # Verify entry remains inhibited even when spread returns to 1 bps
        normal_tick = TickerSnapshot(
            symbol="BTCUSDT",
            best_bid_price=Decimal("60000.00"),
            best_bid_qty=Decimal("1.0"),
            best_ask_price=Decimal("60001.00"),
            best_ask_qty=Decimal("1.0"),
            transaction_time=t1,
            event_time=t1,
        )
        engine_spread.latest_tickers["BTCUSDT"] = normal_tick
        res_post_halt = engine_spread.execute_open(
            "BTCUSDT", signal=1, conviction=Decimal("1.00"), event_time=t1
        )
        assert res_post_halt is None, "HALTED state must strictly prevent entries"

        spread_results["spread_blowout_halt"] = {
            "status": "PASSED",
            "spread_tested_bps": str(blowout_tick.spread_bps),
            "order_rejected_by_guard": True,
            "circuit_breaker_state": engine_spread.account.current_state,
            "permanent_halt_enforced": True,
        }
        results["suites"]["spread_blowouts"] = spread_results

        # ---------------------------------------------------------------------
        # 4. Dynamic Leverage Boundary Conditions
        # ---------------------------------------------------------------------
        print("[4/5] Stress Testing Dynamic Leverage Boundary Conditions...")
        leverage_results: dict[str, Any] = {}
        margin_acct = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))

        test_boundaries = [
            (Decimal("0.00"), Decimal("1.0")),
            (Decimal("0.25"), Decimal("1.0")),
            (Decimal("0.4999"), Decimal("1.0")),
            (Decimal("0.50"), Decimal("1.0")),
            (Decimal("0.625"), Decimal("1.5")),
            (Decimal("0.75"), Decimal("2.0")),
            (Decimal("0.875"), Decimal("2.5")),
            (Decimal("1.00"), Decimal("3.0")),
            (Decimal("1.0001"), Decimal("3.0")),
            (Decimal("1.50"), Decimal("3.0")),
            (Decimal("2.00"), Decimal("3.0")),
        ]

        boundary_checks: list[dict[str, Any]] = []
        for conf, expected_lev in test_boundaries:
            actual_lev = margin_acct.calculate_hardened_leverage(conf)
            assert actual_lev == expected_lev, (
                f"For conf {conf}, expected {expected_lev}, got {actual_lev}"
            )
            boundary_checks.append(
                {
                    "conviction": str(conf),
                    "expected_leverage": str(expected_lev),
                    "actual_leverage": str(actual_lev),
                    "match": True,
                }
            )

        # Stress de-escalation
        lev_vol_stress = margin_acct.calculate_hardened_leverage(
            Decimal("1.00"), volatility_ratio=Decimal("2.5")
        )
        lev_slip_stress = margin_acct.calculate_hardened_leverage(
            Decimal("1.00"), slippage_ratio=Decimal("5.5")
        )
        assert lev_vol_stress == Decimal("1.0")
        assert lev_slip_stress == Decimal("1.0")

        leverage_results["boundary_evaluations"] = boundary_checks
        leverage_results["stress_de_escalations"] = {
            "volatility_surge_leverage": str(lev_vol_stress),
            "slippage_surge_leverage": str(lev_slip_stress),
            "de_escalation_enforced": True,
        }
        results["suites"]["dynamic_leverage"] = leverage_results

        # ---------------------------------------------------------------------
        # 5. Rapid Tick Bursts (10,000 updates)
        # ---------------------------------------------------------------------
        print("[5/5] Stress Testing 10,000 Rapid Tick Updates...")
        engine_burst = LivePaperEngine(
            symbols=symbols,
            starting_capital=Decimal("100.00"),
            ledger_db=tmp_dir / "l_burst.sqlite3",
            lifecycle_db=tmp_dir / "lc_burst.sqlite3",
            observations_db=tmp_dir / "o_burst.sqlite3",
            candidates=candidates,
        )

        burst_count = 10000
        start_burst = datetime.now(UTC)
        for i in range(burst_count):
            sym = symbols[i % 4]
            # Proportional jitter (+/- 0.5%) ensuring strictly positive prices
            jitter = nominal_prices[sym] * Decimal(str((i % 20) - 10)) * Decimal("0.0005")
            p = nominal_prices[sym] + jitter
            t_event = t0 + timedelta(milliseconds=i)
            ticker = TickerSnapshot(
                symbol=sym,
                best_bid_price=p,
                best_bid_qty=Decimal("1.0"),
                best_ask_price=p + Decimal("0.01"),
                best_ask_qty=Decimal("1.0"),
                transaction_time=t_event,
                event_time=t_event,
            )
            await engine_burst.handle_ticker(ticker)
        duration_burst = (datetime.now(UTC) - start_burst).total_seconds()
        rate_tps = burst_count / max(0.001, duration_burst)

        assert engine_burst.monitor.enqueued_count == burst_count
        assert engine_burst.monitor.dropped_count == 0
        assert engine_burst.reconcile_balances()["zero_balance_drift"] is True
        results["suites"]["rapid_ticks"] = {
            "status": "PASSED",
            "total_ticks_processed": burst_count,
            "duration_seconds": round(duration_burst, 3),
            "throughput_ticks_per_sec": round(rate_tps, 1),
            "dropped_ticks": engine_burst.monitor.dropped_count,
            "zero_balance_drift": True,
            "unhandled_exceptions": 0,
        }

    results["overall_verdict"] = "APPROVE"
    results["verdict_reason"] = (
        "All empirical stress test suites (sudden price gaps, crossed book rejection, "
        "spread blowouts >=50 bps, dynamic leverage boundaries, equity floor > 0, "
        "and 10,000 rapid tick burst processing) passed with 0 unhandled exceptions."
    )
    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("================================================================================")
    print("PHASE 258 MILESTONE M1: EMPIRICAL CHALLENGER STRESS HARNESS")
    print("================================================================================")
    evidence = asyncio.run(run_empirical_stress_harness())
    print("\n--------------------------------------------------------------------------------")
    print(json.dumps(evidence, indent=2))
    print("--------------------------------------------------------------------------------")
    print(f"FINAL VERDICT: {evidence['overall_verdict']}")
    print("================================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
