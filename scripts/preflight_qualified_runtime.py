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
            verified_portfolios.append(
                {
                    "portfolio_id": p_receipt.portfolio_id,
                    "family": p_receipt.family,
                    "symbols": list(p_receipt.symbols),
                    "member_count": len(p_receipt.members),
                    "path": p_rel_path,
                    "report_hash": p_receipt.report_hash,
                    "selection_hash": p_receipt.selection_hash or "",
                    "development_report_hash": p_receipt.development_report_hash or "",
                    "execution_authority": p_receipt.execution_authority,
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
        try:
            guard.assert_legacy_inactive()
            checks["legacy_writer_handoff"] = {
                "passed": True,
                "unit": guard.service_name,
            }
        except Exception as exc:
            blocking_reasons.append("legacy_writer_still_active_or_enabled")
            checks["legacy_writer_handoff"] = {
                "passed": False,
                "unit": guard.service_name,
                "error": str(exc),
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
