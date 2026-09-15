"""Unit tests for Phase 262 deterministic multi-asset paper replay harness."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_phase_262_paper_simulation import (  # noqa: E402
    SharedMarginAccount,
    calculate_dynamic_leverage,
    main,
    run_phase_262_simulation,
)


def test_calculate_dynamic_leverage() -> None:
    # Boundary and scaling test
    assert calculate_dynamic_leverage(Decimal("0.50")) == Decimal("1.0")
    assert calculate_dynamic_leverage(Decimal("0.75")) == Decimal("2.0")
    assert calculate_dynamic_leverage(Decimal("1.00")) == Decimal("3.0")

    # Clamping tests
    assert calculate_dynamic_leverage(Decimal("0.20")) == Decimal("1.0")
    assert calculate_dynamic_leverage(Decimal("1.50")) == Decimal("3.0")


def test_shared_margin_account_lifecycle() -> None:
    account = SharedMarginAccount(
        starting_capital=Decimal("100.00"),
        max_utilization=Decimal("0.80"),
        base_allocation_fraction=Decimal("0.30"),
    )

    assert account.cash == Decimal("100.00")
    assert account.total_locked_margin() == Decimal("0")
    assert account.available_margin(Decimal("100.00")) == Decimal("80.00")

    # Allocate trade 1: BTCUSDT with 0.75 confidence (2.0x leverage)
    alloc = account.allocate_order(
        symbol="BTCUSDT",
        confidence=Decimal("0.75"),
        mark_price=Decimal("60000.00"),
        current_equity=Decimal("100.00"),
    )
    assert alloc is not None
    margin, leverage, qty = alloc
    assert margin == Decimal("30.00")
    assert leverage == Decimal("2.0")
    assert qty == (Decimal("30.00") * Decimal("2.0")) / Decimal("60000.00")

    trade_id_1 = "trade-001"
    account.record_open(
        trade_id=trade_id_1,
        margin_allocated=margin,
        leverage=leverage,
        entry_fee=Decimal("0.024"),
        equity=Decimal("100.00"),
    )
    assert account.total_locked_margin() == Decimal("30.00")
    assert account.cash == Decimal("99.976")

    # Allocate trade 2: ETHUSDT with 0.50 confidence (1.0x leverage)
    alloc2 = account.allocate_order(
        symbol="ETHUSDT",
        confidence=Decimal("0.50"),
        mark_price=Decimal("3000.00"),
        current_equity=Decimal("100.00"),
    )
    assert alloc2 is not None
    margin2, leverage2, qty2 = alloc2
    assert margin2 == Decimal("30.00")
    assert leverage2 == Decimal("1.0")
    assert qty2 == Decimal("30.00") / Decimal("3000.00")

    trade_id_2 = "trade-002"
    account.record_open(
        trade_id=trade_id_2,
        margin_allocated=margin2,
        leverage=leverage2,
        entry_fee=Decimal("0.012"),
        equity=Decimal("100.00"),
    )
    assert account.total_locked_margin() == Decimal("60.00")

    # Attempt allocate trade 3: targeting 30 USDT but only 20 USDT available (ceiling 80%)
    alloc3 = account.allocate_order(
        symbol="SOLUSDT",
        confidence=Decimal("1.00"),
        mark_price=Decimal("150.00"),
        current_equity=Decimal("100.00"),
    )
    assert alloc3 is not None
    margin3, leverage3, _qty3 = alloc3
    assert margin3 == Decimal("20.00")
    assert leverage3 == Decimal("3.0")

    trade_id_3 = "trade-003"
    account.record_open(
        trade_id=trade_id_3,
        margin_allocated=margin3,
        leverage=leverage3,
        entry_fee=Decimal("0.024"),
        equity=Decimal("100.00"),
    )
    assert account.total_locked_margin() == Decimal("80.00")
    assert account.available_margin(Decimal("100.00")) == Decimal("0")

    # Further allocation should now be rejected due to 80% ceiling
    alloc4 = account.allocate_order(
        symbol="DOGEUSDT",
        confidence=Decimal("0.80"),
        mark_price=Decimal("0.10"),
        current_equity=Decimal("100.00"),
    )
    assert alloc4 is None

    # Close trade 1 with gross profit of +5.00 USDT and exit fee 0.024
    account.record_close(
        trade_id=trade_id_1,
        gross_pnl=Decimal("5.00"),
        exit_fee=Decimal("0.024"),
    )
    assert account.total_locked_margin() == Decimal("50.00")
    # cash = 100 - 0.024 - 0.012 - 0.024 + 5.00 - 0.024 = 104.916
    assert account.cash == Decimal("104.916")


def test_run_phase_262_simulation_short_slice(tmp_path: Path) -> None:
    output_dir = tmp_path / "phase262_test"
    result = run_phase_262_simulation(
        output_dir=output_dir,
        days=1,
        starting_equity=Decimal("100.00"),
    )

    assert result.output_dir == output_dir
    assert result.total_bars == 96  # 1 day * 96 bars/day
    assert result.positions_reconciled is True
    assert result.accounting_reconciled is True
    assert result.starting_equity == Decimal("100.00")

    # Verify zero balance drift within sub-epsilon tolerance
    drift = abs(result.final_cash - (result.starting_equity + result.realized_pnl))
    assert drift < Decimal("1e-15")

    # Verify SQLite ledgers created
    assert (output_dir / "paper-ledger.sqlite3").is_file()
    assert (output_dir / "paper-lifecycle.sqlite3").is_file()
    assert (output_dir / "paper-observations.sqlite3").is_file()

    # Verify health reports and readiness reports created
    assert (output_dir / "paper-health-report-BTCUSDT.json").is_file()
    assert (output_dir / "paper-health-report-ETHUSDT.json").is_file()
    assert (output_dir / "paper-health-report-SOLUSDT.json").is_file()
    assert (output_dir / "paper-cohort-readiness-report.json").is_file()
    assert (output_dir / "paper-summary.json").is_file()

    # Verify candidate summaries structure
    assert set(result.candidate_summaries.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert result.candidate_summaries["BTCUSDT"]["timeframe"] == "15m"
    assert result.candidate_summaries["SOLUSDT"]["timeframe"] == "1h"


def test_phase_262_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = tmp_path / "cli_test"
    code = main(["--output-dir", str(output_dir), "--days", "1", "--json"])
    assert code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["phase"] == "phase_262"
    assert data["portfolio_summary"]["positions_reconciled"] is True
    assert data["portfolio_summary"]["accounting_reconciled"] is True
    assert data["portfolio_summary"]["zero_balance_drift"] is True
    assert "candidates" in data
    assert len(data["candidates"]) == 3
