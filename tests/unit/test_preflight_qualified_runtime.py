from __future__ import annotations

import json
import subprocess
from pathlib import Path

from autonomous_futures.execution.single_writer_guard import LegacyWriterHandoffGuard
from scripts.preflight_qualified_runtime import REPO, evaluate_preflight, main


def test_preflight_verifies_current_repo_calibration_policy_and_empty_admission() -> None:
    report = evaluate_preflight(repo=REPO)
    assert report["schema"] == "qualified-runtime-preflight-v1"
    assert report["execution_authority"] is False
    assert report["ready_to_activate"] is False
    assert report["blocking_reasons"] == ["no_admitted_qualification_reports"]
    assert report["checks"]["capital_and_universe_policy"]["passed"] is True
    assert report["checks"]["capital_and_universe_policy"]["equity_basis"] == "ACCOUNT"
    assert report["checks"]["capital_and_universe_policy"]["trade_risk_pct"] == "0.5"
    assert report["checks"]["capital_and_universe_policy"]["daily_loss_pct"] == "5"
    assert report["checks"]["capital_and_universe_policy"]["active_pairs_count"] == 12
    assert report["checks"]["hawkes_calibration"]["passed"] is True
    assert report["checks"]["hawkes_calibration"]["beta_per_second"] == "7.5"
    assert report["checks"]["hawkes_calibration"]["symbols_count"] == 12
    assert report["checks"]["qualification_admission"]["passed"] is False
    assert report["checks"]["qualification_admission"]["approved_count"] == 0
    assert report["checks"]["qualification_admission"]["approved_portfolio_count"] == 1
    verified_portfolios = report["checks"]["qualification_admission"]["verified_portfolio_reports"]
    assert len(verified_portfolios) == 1
    assert (
        verified_portfolios[0]["portfolio_id"]
        == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    )
    assert verified_portfolios[0]["family"] == "MACRO_SCALPER"
    assert verified_portfolios[0]["symbols"] == ["AVAXUSDT", "ETHUSDT", "SOLUSDT"]
    assert verified_portfolios[0]["member_count"] == 6
    assert (
        verified_portfolios[0]["report_hash"]
        == "72de22bde9a30101c791bcc981c89481c176b6a4fd63acfd4e2495e8e9122d89"
    )
    assert verified_portfolios[0]["execution_authority"] is False


def test_preflight_reports_legacy_writer_guard_and_storage_autopsy_ledger(
    tmp_path: Path,
) -> None:
    def active_runner(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd,
            0,
            "Id=autonomous-futures-trader.service\n"
            "LoadState=loaded\n"
            "UnitFileState=enabled\n"
            "Restart=always\n"
            "ActiveState=active\n"
            "SubState=running\n"
            "MainPID=87549\n",
            "",
        )

    guard = LegacyWriterHandoffGuard(
        command_runner=active_runner,
        systemctl_path="/bin/systemctl",
        platform_name="linux",
    )
    (tmp_path / "trade-autopsies.json").write_text(
        json.dumps(
            {
                "autopsies": [
                    {
                        "status": "FILLED_AND_CLOSED",
                        "symbol": "BTCUSDT",
                        "net_pnl_usdt": "-2.50",
                        "attribution_cause": "STOP_LOSS_REGIME_MISMATCH",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_preflight(
        repo=REPO,
        storage_dir=tmp_path,
        handoff_guard=guard,
    )
    assert report["ready_to_activate"] is False
    assert "legacy_writer_still_active_or_enabled" in report["blocking_reasons"]
    assert report["checks"]["legacy_writer_handoff"]["passed"] is False
    assert report["checks"]["storage_autopsy_ledger"]["passed"] is True
    assert report["checks"]["storage_autopsy_ledger"]["autopsy_count"] == 1
    assert report["checks"]["storage_autopsy_ledger"]["filled_trade_count"] == 1
    assert report["checks"]["storage_autopsy_ledger"]["needs_revision"] is True


def test_preflight_cli_exit_code_respects_allow_blocked() -> None:
    assert main([]) == 1
    assert main(["--allow-blocked"]) == 0
