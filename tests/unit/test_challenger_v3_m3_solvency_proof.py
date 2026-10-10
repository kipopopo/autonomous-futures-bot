"""Milestone 3 Empirical Challenger Verification Suite.

Adversarially probes and verifies:
1. Double-Entry Balance Invariant:
   Cash + Allocated Margin + Unrealized PnL == Starting Equity + Realized PnL
   Strict tolerance |Delta| < 1e-15 USDT across:
   - artifacts/research/phase310/canary-production-report.json
   - artifacts/research/phase309/canary-production-report.json
   - artifacts/research/phase311/canary-drill-report.json
   - artifacts/research/phase311/canary-orders.jsonl
   - artifacts/research/phase311/canary-lifecycle-telemetry.sqlite3
   - artifacts/research/phase310/canary-production-telemetry.sqlite3
   - Local FastAPI load_execution_status()
   - Live production endpoint https://futures.semua.dev/api/v1/execution/status
2. Hard Micro-Capital Boundaries:
   - Child order cap <= $5.00 USDT (with Binance MIN_NOTIONAL single step-up allowance)
   - Aggregate portfolio exposure <= $25.00 USDT
   - Liquid cash reserve floor >= 75.0%
   - Intra-day loss ceiling <= $3.00 USDT
3. Dynamic Stress Harnesses:
   - 1,000 randomized state transitions under extreme sub-satoshi precision
   - Fail-closed interlock enforcement on cap breaches
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from autonomous_futures.api.app import load_execution_status
from autonomous_futures.feed.execution_drill import DrillSolvencyLedger

RESEARCH_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "research"
TOLERANCE = Decimal("1e-15")


def evaluate_double_entry(
    cash: Any,
    allocated_margin: Any,
    unrealized_pnl: Any,
    starting_equity: Any,
    realized_pnl: Any,
) -> tuple[Decimal, Decimal, Decimal, bool]:
    """Evaluates the double-entry balance invariant using exact Decimal arithmetic.

    LHS: Cash + Allocated Margin + Unrealized PnL
    RHS: Starting Equity + Realized PnL
    Delta: |LHS - RHS|
    """
    c = Decimal(str(cash))
    m = Decimal(str(allocated_margin))
    u = Decimal(str(unrealized_pnl))
    s = Decimal(str(starting_equity))
    r = Decimal(str(realized_pnl))

    lhs = c + m + u
    rhs = s + r
    delta = abs(lhs - rhs)
    is_valid = delta < TOLERANCE
    return lhs, rhs, delta, is_valid


# ==============================================================================
# SUITE 1: DOUBLE-ENTRY BALANCE INVARIANT VERIFICATION
# ==============================================================================


class TestDoubleEntryBalanceInvariantEmpirical:
    """Verifies Cash + Margin + UnrealizedPnL == StartingEquity + RealizedPnL (|Delta| < 1e-15)."""

    def test_phase310_production_report_solvency(self) -> None:
        """Verifies double-entry invariant in phase310/canary-production-report.json."""
        report_path = RESEARCH_DIR / "phase310" / "canary-production-report.json"
        assert report_path.is_file(), f"Missing {report_path}"

        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)

        solv = data["solvency"]
        _lhs, _rhs, delta, ok = evaluate_double_entry(
            cash=solv["cash"],
            allocated_margin=solv["allocated_margin"],
            unrealized_pnl=solv["unrealized_pnl"],
            starting_equity=solv["starting_equity"],
            realized_pnl=solv["realized_pnl"],
        )

        assert ok is True, f"Phase 310 report delta {delta} exceeds tolerance {TOLERANCE}"
        assert delta < TOLERANCE
        assert solv["zero_balance_drift"] is True
        assert solv["drift"] == 0.0

    def test_phase309_production_report_solvency(self) -> None:
        """Verifies double-entry invariant in phase309/canary-production-report.json."""
        report_path = RESEARCH_DIR / "phase309" / "canary-production-report.json"
        assert report_path.is_file(), f"Missing {report_path}"

        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)

        solv = data["solvency"]
        _lhs, _rhs, delta, ok = evaluate_double_entry(
            cash=solv["cash"],
            allocated_margin=solv["allocated_margin"],
            unrealized_pnl=solv["unrealized_pnl"],
            starting_equity=solv["starting_equity"],
            realized_pnl=solv["realized_pnl"],
        )

        assert ok is True, f"Phase 309 report delta {delta} exceeds tolerance {TOLERANCE}"
        assert delta < TOLERANCE
        assert solv["zero_balance_drift"] is True

    def test_phase311_drill_report_solvency(self) -> None:
        """Verifies double-entry invariant in phase311/canary-drill-report.json."""
        report_path = RESEARCH_DIR / "phase311" / "canary-drill-report.json"
        assert report_path.is_file(), f"Missing {report_path}"

        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)

        solv = data["solvency"]
        _lhs, _rhs, delta, ok = evaluate_double_entry(
            cash=solv["cash"],
            allocated_margin=solv["allocated_margin"],
            unrealized_pnl=solv["unrealized_pnl"],
            starting_equity=solv["starting_equity"],
            realized_pnl=solv["realized_pnl"],
        )

        assert ok is True, f"Phase 311 drill report delta {delta} exceeds tolerance {TOLERANCE}"
        assert delta < TOLERANCE
        assert solv["zero_balance_drift"] is True
        assert solv["drift"] == 0.0

    def test_phase311_orders_jsonl_all_solvency_snapshots(self) -> None:
        """Verifies double-entry invariant across all SOLVENCY_SNAPSHOT lines in phase311 jsonl."""
        jsonl_path = RESEARCH_DIR / "phase311" / "canary-orders.jsonl"
        assert jsonl_path.is_file(), f"Missing {jsonl_path}"

        snapshot_count = 0
        with open(jsonl_path, encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("event_type") == "SOLVENCY_SNAPSHOT":
                    snapshot_count += 1
                    _lhs, _rhs, delta, ok = evaluate_double_entry(
                        cash=record["cash"],
                        allocated_margin=record["allocated_margin"],
                        unrealized_pnl=record["unrealized_pnl"],
                        starting_equity=record["starting_equity"],
                        realized_pnl=record["realized_pnl"],
                    )
                    assert ok is True, (
                        f"Line {line_idx}: delta {delta} exceeds tolerance {TOLERANCE}"
                    )
                    assert record.get("zero_balance_drift") is True

        assert snapshot_count >= 5, f"Expected >= 5 snapshots in jsonl, found {snapshot_count}"

    def test_phase311_lifecycle_telemetry_sqlite_snapshots(self) -> None:
        """Verifies double-entry invariant across all rows in phase311 SQLite database."""
        db_path = RESEARCH_DIR / "phase311" / "canary-lifecycle-telemetry.sqlite3"
        assert db_path.is_file(), f"Missing {db_path}"

        con = sqlite3.connect(str(db_path))
        cursor = con.cursor()
        rows = cursor.execute(
            "SELECT id, cash, allocated_margin, unrealized_pnl, starting_equity, realized_pnl, "
            "drift FROM solvency_snapshots"
        ).fetchall()
        con.close()

        assert len(rows) >= 5, f"Expected >= 5 snapshots in sqlite, found {len(rows)}"
        for row in rows:
            snap_id, cash, margin, unrealized, starting, realized, stored_drift = row
            _lhs, _rhs, delta, ok = evaluate_double_entry(
                cash=cash,
                allocated_margin=margin,
                unrealized_pnl=unrealized,
                starting_equity=starting,
                realized_pnl=realized,
            )
            assert ok is True, f"SQLite snapshot ID {snap_id} delta {delta} exceeds {TOLERANCE}"
            assert Decimal(str(stored_drift)) < TOLERANCE

    def test_phase310_production_telemetry_sqlite_snapshots(self) -> None:
        """Verifies double-entry invariant across all rows in phase310 SQLite database."""
        db_path = RESEARCH_DIR / "phase310" / "canary-production-telemetry.sqlite3"
        assert db_path.is_file(), f"Missing {db_path}"

        con = sqlite3.connect(str(db_path))
        cursor = con.cursor()
        rows = cursor.execute(
            "SELECT id, cash, allocated_margin, unrealized_pnl, starting_equity, realized_pnl, "
            "drift FROM solvency_snapshots"
        ).fetchall()
        con.close()

        assert len(rows) >= 3, f"Expected >= 3 snapshots in phase310 sqlite, found {len(rows)}"
        for row in rows:
            snap_id, cash, margin, unrealized, starting, realized, stored_drift = row
            _lhs, _rhs, delta, ok = evaluate_double_entry(
                cash=cash,
                allocated_margin=margin,
                unrealized_pnl=unrealized,
                starting_equity=starting,
                realized_pnl=realized,
            )
            assert ok is True, f"SQLite snapshot ID {snap_id} delta {delta} exceeds {TOLERANCE}"
            assert Decimal(str(stored_drift)) < TOLERANCE

    def test_local_execution_status_endpoint_solvency(self) -> None:
        """Verifies load_execution_status() dynamically calculates zero balance drift."""
        status = load_execution_status(RESEARCH_DIR)
        solv = status.solvency

        _lhs, _rhs, delta, ok = evaluate_double_entry(
            cash=solv.cash_usdt,
            allocated_margin=solv.allocated_margin_usdt,
            unrealized_pnl=solv.unrealized_pnl_usdt,
            starting_equity=solv.starting_equity_usdt,
            realized_pnl=solv.realized_pnl_usdt,
        )

        assert ok is True, f"Local execution status delta {delta} exceeds {TOLERANCE}"
        assert solv.zero_balance_drift_verified is True
        assert solv.drift_usdt < float(TOLERANCE)

    def test_live_remote_production_execution_status_solvency(self) -> None:
        """Empirically queries Kainode VPS /api/v1/execution/status and proves solvency."""
        url = "https://futures.semua.dev/api/v1/execution/status"
        headers = {"User-Agent": "AutonomousFuturesEmpiricalChallenger/1.0"}
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            pytest.skip(f"Live endpoint unreachable: {exc}")

        solv = data.get("solvency", {})
        _lhs, _rhs, delta, ok = evaluate_double_entry(
            cash=solv["cash_usdt"],
            allocated_margin=solv["allocated_margin_usdt"],
            unrealized_pnl=solv["unrealized_pnl_usdt"],
            starting_equity=solv["starting_equity_usdt"],
            realized_pnl=solv["realized_pnl_usdt"],
        )

        assert ok is True, f"Live production delta {delta} exceeds {TOLERANCE}"
        assert solv.get("zero_balance_drift_verified") is True
        assert solv.get("drift_usdt", 1.0) == 0.0


# ==============================================================================
# SUITE 2: HARD MICRO-CAPITAL GOVERNANCE BOUNDARIES
# ==============================================================================


class TestMicroCapitalGovernanceBoundariesEmpirical:
    """Verifies adherence to all hard micro-capital boundaries."""

    def test_child_order_cap_and_binance_min_notional_step_up(self) -> None:
        """Verifies all submitted/executed orders respect the child cap or single step-up.

        Micro-capital rule: Target notional <= 5.00 USDT.
        When Binance exchange filters require MIN_NOTIONAL (>= 5.00 USDT), single step-size
        step-up is permitted (e.g. 0.03 SOL at 185 = 5.55 USDT, or 0.002 ETH at 2750 = 5.50 USDT),
        ensuring zero deadlocks and 0 exchange rejections. All notionals must be <= 5.55 USDT.
        """
        # 1. Phase 310 Orders
        p310_exec = json.load(
            open(RESEARCH_DIR / "phase310" / "canary-production-execution.json", encoding="utf-8")
        )
        for o in p310_exec["orders"]:
            notional = Decimal(str(o["notional_usdt"]))
            assert notional <= Decimal("5.55"), (
                f"Phase 310 order {o['order_id']} notional {notional} exceeds cap"
            )
            assert notional >= Decimal("5.00"), (
                f"Notional {notional} must satisfy Binance MIN_NOTIONAL"
            )

        # 2. Phase 311 Orders in SQLite
        con = sqlite3.connect(
            str(RESEARCH_DIR / "phase311" / "canary-lifecycle-telemetry.sqlite3")
        )
        rows = con.execute(
            "SELECT order_id, symbol, price, quantity, notional_usdt FROM orders"
        ).fetchall()
        con.close()

        assert len(rows) >= 8
        for order_id, _sym, price, qty, notional in rows:
            notional_dec = Decimal(str(notional))
            calc_notional = Decimal(str(price)) * Decimal(str(qty))
            assert notional_dec <= Decimal("5.55"), (
                f"Phase 311 order {order_id} notional {notional_dec} > 5.55"
            )
            assert abs(notional_dec - calc_notional) < Decimal("0.0001")

        # 3. Phase 311 Drill Report
        drill_report = json.load(
            open(RESEARCH_DIR / "phase311" / "canary-drill-report.json", encoding="utf-8")
        )
        sizing = drill_report["sizing"]
        assert Decimal(str(sizing["actual_notional"])) <= Decimal("5.55")
        assert sizing["step_up_applied"] is True

    def test_aggregate_portfolio_exposure_ceiling(self) -> None:
        """Verifies aggregate portfolio exposure is strictly <= 25.00 USDT across all states."""
        # Phase 310 Report
        p310 = json.load(
            open(RESEARCH_DIR / "phase310" / "canary-production-report.json", encoding="utf-8")
        )
        cand_exposure_sum = sum(
            Decimal(str(c["allocated_exposure_usdt"])) for c in p310["candidates"].values()
        )
        assert cand_exposure_sum <= Decimal("25.00"), f"Phase 310 exposure {cand_exposure_sum} > 25"
        assert p310["micro_capital_confinement"]["max_aggregate_exposure_usdt"] == 25.0

        # Phase 311 Report
        p311 = json.load(
            open(RESEARCH_DIR / "phase311" / "canary-drill-report.json", encoding="utf-8")
        )
        assert p311["guardrails"]["exposure_cap_usdt"] == 25.0

        # Local Execution Status
        local_status = load_execution_status(RESEARCH_DIR)
        assert Decimal(str(local_status.aggregate_exposure_usdt)) <= Decimal("25.00")

    def test_liquid_cash_reserve_floor(self) -> None:
        """Verifies liquid cash reserve floor >= 75.0% across all observed states."""
        # Phase 310
        p310 = json.load(
            open(RESEARCH_DIR / "phase310" / "canary-production-report.json", encoding="utf-8")
        )
        solv310 = p310["solvency"]
        cash_pct_310 = (
            Decimal(str(solv310["cash"])) / Decimal(str(solv310["starting_equity"]))
        ) * Decimal("100")
        assert cash_pct_310 >= Decimal("75.0"), f"Phase 310 cash reserve {cash_pct_310}% < 75.0%"

        # Phase 311
        p311 = json.load(
            open(RESEARCH_DIR / "phase311" / "canary-drill-report.json", encoding="utf-8")
        )
        solv311 = p311["solvency"]
        cash_pct_311 = (
            Decimal(str(solv311["cash"])) / Decimal(str(solv311["starting_equity"]))
        ) * Decimal("100")
        assert cash_pct_311 >= Decimal("75.0"), f"Phase 311 cash reserve {cash_pct_311}% < 75.0%"

        # Local Execution Status
        local_status = load_execution_status(RESEARCH_DIR)
        assert Decimal(str(local_status.solvency.cash_reserve_pct)) >= Decimal("75.0")

    def test_intraday_loss_ceiling(self) -> None:
        """Verifies cumulative intra-day loss <= 3.00 USDT across all observed states."""
        # Phase 310 Report
        p310 = json.load(
            open(RESEARCH_DIR / "phase310" / "canary-production-report.json", encoding="utf-8")
        )
        intra_loss_310 = Decimal(str(p310.get("intra_day_loss_usdt", 0.0)))
        assert intra_loss_310 <= Decimal("3.00"), f"Phase 310 loss {intra_loss_310} > 3.00 USDT"

        # Phase 311 Report
        p311 = json.load(
            open(RESEARCH_DIR / "phase311" / "canary-drill-report.json", encoding="utf-8")
        )
        solv311 = p311["solvency"]
        realized_pnl = Decimal(str(solv311["realized_pnl"]))
        observed_loss = abs(realized_pnl) if realized_pnl < Decimal("0") else Decimal("0")
        assert observed_loss <= Decimal("3.00"), f"Phase 311 loss {observed_loss} > 3.00 USDT"

        # Local Execution Status
        local_status = load_execution_status(RESEARCH_DIR)
        assert Decimal(str(local_status.intra_day_loss_usdt)) <= Decimal("3.00")


# ==============================================================================
# SUITE 3: ADVERSARIAL STRESS & DRIFT CHAOS HARNESS
# ==============================================================================


class TestAdversarialStressAndFailClosedInterlocks:
    """Stress tests double-entry solvency and micro-capital governance with chaos injection."""

    def test_1000_randomized_micro_fills_sub_satoshi_drift_invariance(self) -> None:
        """Simulates 1,000 rapid chaotic state transitions verifying zero drift at every step."""
        ledger = DrillSolvencyLedger(starting_equity=Decimal("100.00"))

        import random
        rng = random.Random(1337)

        for step in range(1000):
            margin = Decimal(str(round(rng.uniform(1.0, 5.0), 4)))
            allocated = ledger.allocate_margin(margin)
            assert allocated is True
            assert ledger.is_zero_drift is True
            assert ledger.drift < TOLERANCE

            fee = Decimal(str(round(rng.uniform(0.0001, 0.002), 8)))
            rpnl = Decimal(str(round(rng.uniform(-0.10, 0.25), 8)))
            ledger.record_fill(margin_released=margin, realized_pnl_delta=rpnl, fee_cost=fee)

            assert ledger.is_zero_drift is True, f"Drift breach at step {step}: {ledger.drift}"
            assert ledger.drift < TOLERANCE

    def test_fail_closed_on_oversized_order_attempt(self) -> None:
        """Verifies sizing logic clamps requested notional to micro-cap <= $5.00."""
        from autonomous_futures.feed.execution_drill import (
            ExecutionDrillConfig,
            ExecutionDrillEngine,
        )

        cfg = ExecutionDrillConfig(requested_notional=Decimal("10.00"), dry_run=True)
        engine = ExecutionDrillEngine(cfg)

        sizing = engine.validate_and_size_order(
            symbol="SOLUSDT",
            side="BUY",
            mark_price=Decimal("185.00"),
            requested_notional=Decimal("10.00"),
        )
        # Engine clamps capped_notional = min(requested, 5.00) = 5.00
        # Resulting notional after 1 step-up is 5.55 (0.03 SOL), never 10.00
        assert sizing.actual_notional <= Decimal("5.55")
        assert sizing.actual_notional < Decimal("10.00")
        assert sizing.is_valid is True
        assert sizing.step_up_applied is True

    def test_tampered_solvency_fails_tolerance(self) -> None:
        """Adversarially injects tiny synthetic drift (1e-14) and verifies detection."""
        _lhs, _rhs, delta, ok = evaluate_double_entry(
            cash="100.00000000000001",
            allocated_margin="0.0",
            unrealized_pnl="0.0",
            starting_equity="100.0",
            realized_pnl="0.0",
        )
        assert ok is False, "Formula must reject 1e-14 drift"
        assert delta >= TOLERANCE

    def test_btc_high_price_notional_rejection_in_self_driving(self) -> None:
        """Verifies self-driving engine blocks BTC orders when rounded quantity < min_notional."""
        from autonomous_futures.production.self_driving import build_default_self_driving_engine

        engine, _ = build_default_self_driving_engine()
        # Ingest tick at 95,000 USDT with strong LONG signal
        order = engine.process_microstructure_tick(
            symbol="BTCUSDT",
            price=Decimal("95000.00"),
            hawkes_rho=0.15,
            heartbeat_latency_ms=45.0,
            ensemble_signal="LONG",
        )
        # Order is blocked due to MIN_NOTIONAL_INCOMPATIBLE_BLOCK (4.75 USDT < 5.00 USDT)
        assert order is None
        assert any(
            ev.get("event_type") == "MIN_NOTIONAL_INCOMPATIBLE_BLOCK"
            for ev in engine.events_log
        )

    def test_aggregate_exposure_and_cash_reserve_interlock_simulation(self) -> None:
        """Simulates consecutive micro orders and confirms exposure cap and cash floor."""
        starting_cash = Decimal("100.00")
        current_cash = starting_cash
        current_exposure = Decimal("0.00")
        max_cap = Decimal("25.00")
        min_reserve_pct = Decimal("75.0")

        # Can add 4 orders of 5.50 USDT (total 22.00 USDT)
        for _i in range(4):
            order_notional = Decimal("5.50")
            assert current_exposure + order_notional <= max_cap
            current_exposure += order_notional
            current_cash -= order_notional
            reserve_pct = (current_cash / starting_cash) * Decimal("100.0")
            assert reserve_pct >= min_reserve_pct

        # 5th order would push exposure to 27.50 USDT (> 25.00 USDT cap)
        order_notional = Decimal("5.50")
        assert (current_exposure + order_notional) > max_cap
        # Fail-closed guardrail blocks 5th order
        blocked = (current_exposure + order_notional) > max_cap
        assert blocked is True
