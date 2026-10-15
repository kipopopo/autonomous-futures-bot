"""Read-only preflight verification for the qualified Testnet runtime deployment.

Verifies:
1. Qualification admission manifest (`deploy/qualification-admission.json`) and report receipts.
2. Hawkes microstructure calibration (`runtime-hawkes-calibration-20261013.json`) & 12-pair traces.
3. Capital and risk policy (`AFBOT_EQUITY_BASIS=ACCOUNT`, 0.5% trade risk, 5% UTC daily loss).
4. Optional read-only systemd handoff guard (`LegacyWriterHandoffGuard`) without mutating services.
5. Optional durable storage directory (`trade-autopsies.json` and `daily-risk.json` state).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.execution.portfolio_runtime import (  # noqa: E402
    build_verified_runtime_portfolio,
)
from autonomous_futures.execution.qualification_receipts import (  # noqa: E402
    verify_runtime_portfolio_report,
    verify_runtime_report,
)
from autonomous_futures.execution.single_writer_guard import (  # noqa: E402
    LegacyWriterHandoffGuard,
)
from autonomous_futures.execution.trade_autopsy_evidence import (  # noqa: E402
    summarize_autopsy_feedback,
)
from autonomous_futures.execution.trade_plan import DEFAULT_CAPITAL_POLICY  # noqa: E402
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS  # noqa: E402
from autonomous_futures.feed.runtime_hawkes_calibration import (  # noqa: E402
    load_runtime_hawkes_calibration,
)

DEFAULT_HAWKES_CALIBRATION = (
    REPO
    / "artifacts"
    / "qualification"
    / "runtime-microstructure"
    / "runtime-hawkes-calibration-20261013.json"
)


def evaluate_preflight(
    *,
    repo: Path = REPO,
    storage_dir: Path | None = None,
    account_path: Path | None = None,
    equity_basis: str = "ACCOUNT",
    hawkes_calibration_path: Path = DEFAULT_HAWKES_CALIBRATION,
    check_systemd: bool = False,
    handoff_guard: LegacyWriterHandoffGuard | None = None,
) -> dict[str, Any]:
    """Run read-only preflight checks and return a deterministic JSON-serializable report."""
    blocking_reasons: list[str] = []
    checks: dict[str, Any] = {}

    # 1. Capital & Risk Policy Check
    policy_ok = (
        equity_basis == "ACCOUNT"
        and DEFAULT_CAPITAL_POLICY.trade_risk_pct == Decimal("0.5")
        and DEFAULT_CAPITAL_POLICY.daily_loss_pct == Decimal("5")
        and len(ACTIVE_PAIRS) == 12
    )
    if not policy_ok:
        blocking_reasons.append("capital_or_universe_policy_mismatch")
    checks["capital_and_universe_policy"] = {
        "passed": policy_ok,
        "equity_basis": equity_basis,
        "trade_risk_pct": str(DEFAULT_CAPITAL_POLICY.trade_risk_pct),
        "daily_loss_pct": str(DEFAULT_CAPITAL_POLICY.daily_loss_pct),
        "active_pairs_count": len(ACTIVE_PAIRS),
        "active_pairs": list(ACTIVE_PAIRS),
    }

    # 2. Hawkes Calibration Check
    try:
        cal_path = (
            hawkes_calibration_path
            if hawkes_calibration_path.is_absolute()
            else (repo / hawkes_calibration_path)
        )
        calibration = load_runtime_hawkes_calibration(cal_path, repo)
        checks["hawkes_calibration"] = {
            "passed": True,
            "beta_per_second": str(calibration.beta_per_second),
            "artifact_sha256": calibration.artifact_sha256,
            "symbols_count": len(calibration.symbols),
        }
    except Exception as exc:
        blocking_reasons.append("hawkes_calibration_invalid")
        checks["hawkes_calibration"] = {
            "passed": False,
            "error": str(exc),
        }

    # 3. Admission Manifest Check
    manifest_path = repo / "deploy" / "qualification-admission.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("schema") != "runtime-qualification-admission-v1":
            raise ValueError("Invalid qualification-admission.json schema")
        approved_items = manifest.get("approved_reports", [])
        if not isinstance(approved_items, list):
            raise ValueError("approved_reports must be a list")
        verified_reports: list[dict[str, str]] = []
        seen_identities: set[tuple[str, str]] = set()
        for item in approved_items:
            rel_path = str(item["path"])
            report_path = (repo / rel_path).resolve()
            if not report_path.is_relative_to(repo.resolve()):
                raise ValueError("Admitted report must be inside repository")
            identity = (str(item["family"]), str(item["symbol"]))
            if identity in seen_identities:
                raise ValueError("Duplicate admitted strategy report")
            seen_identities.add(identity)
            receipt = verify_runtime_report(
                report_path, repo=repo, family=identity[0], symbol=identity[1]
            )
            if receipt.execution_domain is None:
                raise ValueError("Admitted report has no researched runtime execution domain")
            verified_reports.append(
                {
                    "family": identity[0],
                    "symbol": identity[1],
                    "path": rel_path,
                    "report_hash": receipt.report_hash,
                }
            )
        approved_portfolios = manifest.get("approved_portfolio_reports", [])
        if not isinstance(approved_portfolios, list):
            raise ValueError("approved_portfolio_reports must be a list")
        verified_portfolios: list[dict[str, Any]] = []
        seen_portfolio_ids: set[str] = set()
        for p_item in approved_portfolios:
            pid = str(p_item["portfolio_id"])
            if pid in seen_portfolio_ids:
                raise ValueError("Duplicate admitted portfolio qualification report")
            seen_portfolio_ids.add(pid)
            p_rel_path = str(p_item.get("holdout_report_path") or p_item["path"])
            p_path = (repo / p_rel_path).resolve()
            if not p_path.is_relative_to(repo.resolve()):
                raise ValueError("Admitted portfolio report must be inside repository")
            p_receipt = verify_runtime_portfolio_report(p_path, repo=repo, portfolio_id=pid)
            runtime_portfolio = build_verified_runtime_portfolio(p_receipt, report_path=p_path)
            if not set(runtime_portfolio.symbols).issubset(ACTIVE_PAIRS):
                raise ValueError("Admitted portfolio symbols are outside ACTIVE_PAIRS")
            verified_portfolios.append(
                {
                    "portfolio_id": runtime_portfolio.portfolio_id,
                    "family": runtime_portfolio.family,
                    "symbols": list(runtime_portfolio.symbols),
                    "member_count": len(runtime_portfolio.members),
                    "member_ids": [m.member_id for m in runtime_portfolio.members],
                    "members_by_symbol_counts": {
                        sym: len(members)
                        for sym, members in runtime_portfolio.members_by_symbol.items()
                    },
                    "path": p_rel_path,
                    "report_hash": runtime_portfolio.report_hash,
                    "selection_hash": runtime_portfolio.selection_hash,
                    "development_report_hash": runtime_portfolio.development_report_hash,
                    "execution_domain": runtime_portfolio.execution_domain,
                    "execution_authority": runtime_portfolio.execution_authority,
                }
            )
        if not verified_reports:
            blocking_reasons.append("no_admitted_qualification_reports")
        checks["qualification_admission"] = {
            "passed": len(verified_reports) > 0,
            "approved_count": len(verified_reports),
            "verified_reports": verified_reports,
            "approved_portfolio_count": len(verified_portfolios),
            "verified_portfolio_reports": verified_portfolios,
        }
    except Exception as exc:
        blocking_reasons.append("qualification_admission_invalid")
        checks["qualification_admission"] = {
            "passed": False,
            "error": str(exc),
        }

    # 4. Optional Read-Only Legacy Writer Handoff Guard Check
    if check_systemd or handoff_guard is not None:
        guard = handoff_guard or LegacyWriterHandoffGuard()
        status_info: dict[str, str] | None = None
        if hasattr(guard, "inspect_legacy_status"):
            try:
                status_info = guard.inspect_legacy_status()
            except Exception:
                status_info = None
        try:
            guard.assert_legacy_inactive()
            checks["legacy_writer_handoff"] = {
                "passed": True,
                "unit": guard.service_name,
                **({"status": status_info} if status_info is not None else {}),
            }
        except Exception as exc:
            blocking_reasons.append("legacy_writer_still_active_or_enabled")
            checks["legacy_writer_handoff"] = {
                "passed": False,
                "unit": guard.service_name,
                "error": str(exc),
                **({"status": status_info} if status_info is not None else {}),
            }
    else:
        checks["legacy_writer_handoff"] = {
            "passed": True,
            "skipped": True,
            "reason": "systemd_check_not_requested",
        }

    # 5. Optional Storage Directory & Trade Autopsy Ledger Check
    if storage_dir is not None:
        autopsies_path = storage_dir / "trade-autopsies.json"
        if autopsies_path.is_file():
            try:
                raw_autopsies = json.loads(autopsies_path.read_text(encoding="utf-8"))
                records = raw_autopsies.get("autopsies", [])
                if not isinstance(records, list):
                    raise ValueError("trade-autopsies.json autopsies field must be a list")
                summary = summarize_autopsy_feedback(records)
                checks["storage_autopsy_ledger"] = {
                    "passed": True,
                    "present": True,
                    "autopsy_count": len(records),
                    "filled_trade_count": summary["trade_count"],
                    "needs_revision": summary["needs_revision"],
                }
            except Exception as exc:
                blocking_reasons.append("storage_autopsy_ledger_corrupted")
                checks["storage_autopsy_ledger"] = {
                    "passed": False,
                    "present": True,
                    "error": str(exc),
                }
        else:
            checks["storage_autopsy_ledger"] = {
                "passed": True,
                "present": False,
                "autopsy_count": 0,
            }

    # 6. Optional Exchange Account & Portfolio Execution-Domain Audit
    resolved_account_path = account_path
    if (
        resolved_account_path is None
        and storage_dir is not None
        and (storage_dir / "exchange-account.json").is_file()
    ):
        resolved_account_path = storage_dir / "exchange-account.json"

    if resolved_account_path is not None:
        try:
            raw_acc = json.loads(resolved_account_path.read_text(encoding="utf-8"))
            acc_testnet = bool(raw_acc.get("testnet"))
            acc_ts_ms = int(raw_acc.get("timestamp_ms", 0))
            acc_balance = raw_acc.get("account", {})
            equity_usdt = Decimal(str(acc_balance["totalMarginBalance"]))
            available_usdt = Decimal(str(acc_balance["availableBalance"]))
            wallet_usdt = Decimal(str(acc_balance["totalWalletBalance"]))
            daily_risk = raw_acc.get("daily_risk", {})
            daily_verified = (
                isinstance(daily_risk, dict)
                and daily_risk.get("verified") is True
                and daily_risk.get("equity_basis") == equity_basis
            )
            if not daily_verified:
                blocking_reasons.append("account_daily_risk_unverified")

            occupied_syms: set[str] = {
                str(row["symbol"])
                for row in raw_acc.get("positions", [])
                if Decimal(str(row.get("positionAmt", "0"))) != 0
            }
            occupied_syms.update(
                str(row["symbol"])
                for row in raw_acc.get("open_orders", [])
                if row.get("reduceOnly") not in (True, "true")
            )
            sym_configs = {
                str(row["symbol"]): int(row["leverage"])
                for row in raw_acc.get("symbol_configuration", [])
                if "symbol" in row and "leverage" in row
            }

            portfolio_audits: list[dict[str, Any]] = []
            verified_portfolios_list = checks.get("qualification_admission", {}).get(
                "verified_portfolio_reports", []
            )
            all_portfolios_ok = True
            for vp in verified_portfolios_list:
                domain = vp.get("execution_domain") or {}
                min_eq = Decimal(str(domain.get("minimum_equity", "0")))
                max_eq = Decimal(str(domain.get("maximum_equity", "0")))
                equity_ok = acc_testnet is bool(domain.get("testnet", True)) and (
                    0 < min_eq <= equity_usdt <= max_eq
                )
                if not equity_ok:
                    blocking_reasons.append("account_equity_outside_portfolio_domain")
                    all_portfolios_ok = False
                allowed_leverages = set(domain.get("leverages", [1]))
                observed_leverages = {sym: sym_configs.get(sym) for sym in vp.get("symbols", [])}
                leverage_ok = all(lev in allowed_leverages for lev in observed_leverages.values())
                if not leverage_ok:
                    blocking_reasons.append("portfolio_symbol_leverage_mismatch")
                    all_portfolios_ok = False
                max_conc = int(domain.get("maximum_concurrent_symbols", 1))
                concurrency_ok = len(occupied_syms) < max_conc
                if not concurrency_ok:
                    blocking_reasons.append("portfolio_concurrency_limit_reached")
                    all_portfolios_ok = False
                portfolio_audits.append(
                    {
                        "portfolio_id": vp["portfolio_id"],
                        "equity_in_domain": equity_ok,
                        "minimum_equity_usdt": str(min_eq),
                        "maximum_equity_usdt": str(max_eq),
                        "required_leverages": sorted(allowed_leverages),
                        "observed_symbol_leverages": observed_leverages,
                        "leverage_matches_domain": leverage_ok,
                        "concurrency_ok": concurrency_ok,
                        "passed": equity_ok and leverage_ok and concurrency_ok and daily_verified,
                    }
                )

            checks["account_and_portfolio_domain"] = {
                "passed": daily_verified and all_portfolios_ok,
                "testnet": acc_testnet,
                "timestamp_ms": acc_ts_ms,
                "total_margin_balance_usdt": str(equity_usdt),
                "available_balance_usdt": str(available_usdt),
                "total_wallet_balance_usdt": str(wallet_usdt),
                "daily_risk_verified": daily_verified,
                "daily_risk_reason": daily_risk.get("reason")
                if isinstance(daily_risk, dict)
                else None,
                "occupied_symbols": sorted(occupied_syms),
                "portfolio_audits": portfolio_audits,
            }
        except Exception as exc:
            blocking_reasons.append("account_evidence_unreadable_or_invalid")
            checks["account_and_portfolio_domain"] = {
                "passed": False,
                "error": str(exc),
            }

    sorted_reasons = sorted(set(blocking_reasons))
    report: dict[str, Any] = {
        "schema": "qualified-runtime-preflight-v1",
        "ready_to_activate": len(sorted_reasons) == 0,
        "blocking_reasons": sorted_reasons,
        "checks": checks,
        "execution_authority": False,
    }
    report["preflight_hash"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--storage-dir", type=Path, default=None)
    parser.add_argument("--account-path", type=Path, default=None)
    parser.add_argument("--equity-basis", default="ACCOUNT")
    parser.add_argument(
        "--hawkes-calibration",
        type=Path,
        default=DEFAULT_HAWKES_CALIBRATION,
    )
    parser.add_argument("--check-systemd", action="store_true")
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Return exit code 0 even when activation is blocked by preflight gates.",
    )
    args = parser.parse_args(argv)
    report = evaluate_preflight(
        repo=args.repo,
        storage_dir=args.storage_dir,
        account_path=args.account_path,
        equity_basis=args.equity_basis,
        hawkes_calibration_path=args.hawkes_calibration,
        check_systemd=args.check_systemd,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["ready_to_activate"] or args.allow_blocked:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
