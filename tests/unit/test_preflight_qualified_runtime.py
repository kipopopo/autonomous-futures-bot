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
    assert report["ready_to_activate"] is True
    assert report["blocking_reasons"] == []
    assert report["checks"]["capital_and_universe_policy"]["passed"] is True
    assert report["checks"]["capital_and_universe_policy"]["equity_basis"] == "ACCOUNT"
    assert report["checks"]["capital_and_universe_policy"]["trade_risk_pct"] == "0.5"
    assert report["checks"]["capital_and_universe_policy"]["daily_loss_pct"] == "5"
    assert report["checks"]["capital_and_universe_policy"]["active_pairs_count"] == 12
    assert report["checks"]["hawkes_calibration"]["passed"] is True
    assert report["checks"]["hawkes_calibration"]["beta_per_second"] == "7.5"
    assert report["checks"]["hawkes_calibration"]["symbols_count"] == 12
    assert report["checks"]["qualification_admission"]["passed"] is True
    assert report["checks"]["qualification_admission"]["admission_mode"] == "portfolio"
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
    assert verified_portfolios[0]["members_by_symbol_counts"] == {
        "AVAXUSDT": 1,
        "ETHUSDT": 3,
        "SOLUSDT": 2,
    }
    assert verified_portfolios[0]["execution_domain"]["schema"] == "researched-execution-domain-v1"
    assert verified_portfolios[0]["execution_domain"]["maximum_concurrent_symbols"] == 3
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
    assert report["blocking_reasons"] == ["legacy_writer_still_active_or_enabled"]
    assert report["checks"]["legacy_writer_handoff"]["passed"] is False
    assert report["checks"]["storage_autopsy_ledger"]["passed"] is True
    assert report["checks"]["storage_autopsy_ledger"]["autopsy_count"] == 1
    assert report["checks"]["storage_autopsy_ledger"]["filled_trade_count"] == 1
    assert report["checks"]["storage_autopsy_ledger"]["needs_revision"] is True


def test_preflight_cli_exit_code_respects_allow_blocked() -> None:
    assert main([]) == 0
    assert main(["--check-systemd"]) == 1
    assert main(["--check-systemd", "--allow-blocked"]) == 0


def test_preflight_audits_account_and_portfolio_domain_and_detects_leverage_mismatch(
    tmp_path: Path,
) -> None:
    account_file = tmp_path / "exchange-account.json"
    account_file.write_text(
        json.dumps(
            {
                "testnet": True,
                "timestamp_ms": 1775832651015,
                "account": {
                    "totalMarginBalance": "4224.09882354",
                    "availableBalance": "4224.09882354",
                    "totalWalletBalance": "4224.09882354",
                },
                "daily_risk": {
                    "verified": False,
                    "equity_basis": "ACCOUNT",
                    "reason": "daily_risk_state_missing",
                },
                "positions": [],
                "open_orders": [],
                "symbol_configuration": [
                    {"symbol": "AVAXUSDT", "leverage": 20},
                    {"symbol": "ETHUSDT", "leverage": 20},
                    {"symbol": "SOLUSDT", "leverage": 20},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_preflight(repo=REPO, account_path=account_file)
    assert "account_daily_risk_unverified" in report["blocking_reasons"]
    assert "portfolio_symbol_leverage_mismatch" in report["blocking_reasons"]
    domain_check = report["checks"]["account_and_portfolio_domain"]
    assert domain_check["passed"] is False
    assert domain_check["total_margin_balance_usdt"] == "4224.09882354"
    audit = domain_check["portfolio_audits"][0]
    assert audit["portfolio_id"] == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    assert audit["equity_in_domain"] is True
    assert audit["leverage_matches_domain"] is False
    assert audit["observed_symbol_leverages"] == {
        "AVAXUSDT": 20,
        "ETHUSDT": 20,
        "SOLUSDT": 20,
    }
    assert audit["concurrency_ok"] is True

    account_file.write_text(
        json.dumps(
            {
                "testnet": True,
                "timestamp_ms": 1775832651015,
                "account": {
                    "totalMarginBalance": "4224.09882354",
                    "availableBalance": "4224.09882354",
                    "totalWalletBalance": "4224.09882354",
                },
                "daily_risk": {
                    "verified": True,
                    "equity_basis": "ACCOUNT",
                    "reason": "verified",
                },
                "positions": [],
                "open_orders": [],
                "symbol_configuration": [
                    {"symbol": "AVAXUSDT", "leverage": 1},
                    {"symbol": "ETHUSDT", "leverage": 1},
                    {"symbol": "SOLUSDT", "leverage": 1},
                ],
            }
        ),
        encoding="utf-8",
    )

    passed_report = evaluate_preflight(repo=REPO, account_path=account_file)
    assert "account_daily_risk_unverified" not in passed_report["blocking_reasons"]
    assert "portfolio_symbol_leverage_mismatch" not in passed_report["blocking_reasons"]
    assert passed_report["checks"]["account_and_portfolio_domain"]["passed"] is True
    assert (
        passed_report["checks"]["account_and_portfolio_domain"]["portfolio_audits"][0]["passed"]
        is True
    )
