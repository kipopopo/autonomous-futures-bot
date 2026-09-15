"""Unit tests for Phase 263 multi-asset paper replay under Manifest Version 2."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autonomous_futures.domain.errors import DomainViolation  # noqa: E402
from scripts.run_phase_263_paper_simulation import (  # noqa: E402
    main,
    run_phase_263_simulation,
)


def test_run_phase_263_simulation_short_slice(tmp_path: Path) -> None:
    output_dir = tmp_path / "phase263_test"
    result = run_phase_263_simulation(
        output_dir=output_dir,
        days=1,
        starting_equity=Decimal("100.00"),
    )

    assert result.output_dir == output_dir
    assert result.total_bars == 96  # 1 day * 96 bars/day
    assert result.positions_reconciled is True
    assert result.accounting_reconciled is True
    assert result.starting_equity == Decimal("100.00")
    assert result.registry_version >= 2

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

    # Verify candidate summaries structure and calibrated ETH candidate
    assert set(result.candidate_summaries.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert result.candidate_summaries["ETHUSDT"]["candidate_id"] == "cand-ethusdt-dcb-003"
    assert result.candidate_summaries["BTCUSDT"]["candidate_id"] == "cand-btcusdt-dcb-002"
    assert result.candidate_summaries["SOLUSDT"]["candidate_id"] == "cand-solusdt-rgb-001"


def test_run_phase_263_simulation_rejects_manifest_v1(tmp_path: Path) -> None:
    # Point to the historical baseline registry (Version 1)
    baseline_reg = Path("artifacts/research/phase262/baseline_candidate_registry.json")
    if not baseline_reg.is_file():
        pytest.skip("baseline_candidate_registry.json not found")

    output_dir = tmp_path / "phase263_reject_test"
    with pytest.raises(DomainViolation, match="requires candidate registry version >= 2"):
        run_phase_263_simulation(
            output_dir=output_dir,
            registry_path=baseline_reg,
            days=1,
        )


def test_phase_263_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_dir = tmp_path / "cli_test"
    code = main(["--output-dir", str(output_dir), "--days", "1", "--json"])
    assert code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["phase"] == "phase_263"
    assert data["registry_version"] >= 2
    assert data["portfolio_summary"]["positions_reconciled"] is True
    assert data["portfolio_summary"]["accounting_reconciled"] is True
    assert data["portfolio_summary"]["zero_balance_drift"] is True
    assert data["candidates"]["ETHUSDT"]["candidate_id"] == "cand-ethusdt-dcb-003"
