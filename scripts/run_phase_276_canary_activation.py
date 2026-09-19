"""Phase 276: Operator Production Canary Authorization & Activation Governance CLI.

Ingests upstream Phase 275 live-readiness certification, verifies prerequisite qualification,
validates operator authorization, executes deterministic order dispatch interlock simulations
(Tracks 1-4), records isolated SQLite telemetry, and produces cryptographically signed
activation certificates and audit reports under Candidate Registry Manifest Version 2.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

# Ensure src/ and repo root are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.canary_activation import (  # noqa: E402
    DEFAULT_MAX_DURATION_HOURS,
    DEFAULT_PHASE275_INPUT_DIR,
    DEFAULT_PHASE276_OUTPUT_DIR,
    CanaryActivationConfig,
    CanaryActivationReport,
    CanaryActivationRunner,
    verify_phase_276_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_276_canary_activation")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 276 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 276 Operator Production Canary Authorization & Order Interlock CLI."
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=DEFAULT_CANARY_STAGING_MANIFEST_PATH,
        help="Path to verified Canary Staging Manifest",
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=DEFAULT_CANDIDATE_REGISTRY_PATH,
        help="Path to Candidate Registry Manifest",
    )
    parser.add_argument(
        "--phase275-dir",
        type=Path,
        default=DEFAULT_PHASE275_INPUT_DIR,
        help="Path to upstream Phase 275 certification directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE276_OUTPUT_DIR,
        help="Path to output canary activation telemetry artifacts",
    )
    parser.add_argument(
        "--track",
        type=str,
        default="all",
        choices=[
            "1",
            "2",
            "3",
            "4",
            "track_1",
            "track_2",
            "track_3",
            "track_4",
            "all",
        ],
        help="Specific simulation track to execute (default: all)",
    )
    parser.add_argument(
        "--authorize-canary",
        action="store_true",
        help="Batch operator sign-off flag authorizing production canary activation",
    )
    parser.add_argument(
        "--operator-id",
        type=str,
        default="operator-lead-001",
        help="Operator ID for canary authorization sign-off (default: operator-lead-001)",
    )
    parser.add_argument(
        "--operator-rationale",
        type=str,
        default="Phase 276 production canary authorization after complete Phase 275 certification",
        help="Audit rationale for canary activation sign-off",
    )
    parser.add_argument(
        "--max-duration-hours",
        type=float,
        default=DEFAULT_MAX_DURATION_HOURS,
        help="Maximum certificate authorized duration in hours (default: 24.0)",
    )
    parser.add_argument(
        "--daily-loss-budget-usdt",
        type=float,
        default=2.00,
        help="Daily cumulative loss budget ceiling in USDT (default: 2.00)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt operator interactively for authorization if --authorize-canary omitted",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Inject synthetic accounting drift (> 1e-15 USDT) to test fail-closed detection",
    )
    parser.add_argument(
        "--verify-hash-chain",
        action="store_true",
        help="Verify cryptographic SHA-256 DAG hash chain across artifacts after execution",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic SHA-256 DAG hash chain without executing tracks",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full telemetry report as JSON to stdout",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level (default: INFO)",
    )
    return parser


def format_summary_table(report: CanaryActivationReport) -> str:
    """Format Phase 276 activation results into human-readable ASCII table."""
    lines: list[str] = [
        "=" * 84,
        "   PHASE 276: OPERATOR PRODUCTION CANARY AUTHORIZATION & ORDER INTERLOCK HARNESS",
        "=" * 84,
        f"Timestamp UTC    : {report.timestamp_utc}",
        f"Manifest Version : {report.manifest_version}",
        f"Staged Manifest  : {report.staged_manifest_hash[:16]}...",
        f"Certificate ID   : {report.certificate_info.get('certificate_id')}",
        f"Operator Sign-Off: {report.certificate_info.get('operator_id')}",
        f"Expires At UTC   : {report.certificate_info.get('expires_at_utc')}",
        f"Loss Budget USDT : {report.certificate_info.get('daily_loss_budget_usdt')}",
        f"Micro Order Cap  : {report.certificate_info.get('max_micro_order_notional_usdt')} USDT",
        "-" * 84,
        f"{'Track ID':<10} {'Status':<38} {'Drift (USDT)':<15} {'Success':<8}",
        "-" * 84,
    ]
    for tr in report.tracks:
        lines.append(f"{tr.track_id:<10} {tr.status:<38} {tr.drift_usdt:<15} {str(tr.success):<8}")
    lines.extend(
        [
            "-" * 84,
            f"Total Orders Placed : {report.order_stats.get('total_orders_placed')}",
            f"Total Orders Filled : {report.order_stats.get('total_orders_filled')}",
            f"Total Orders Reject : {report.order_stats.get('total_orders_rejected')}",
            f"Interlock Blocks    : {report.interlock_stats.get('total_interlock_blocks')}",
            f"Daily Loss Lockouts : {report.interlock_stats.get('daily_loss_lockouts')}",
            f"Key Rejections      : {report.interlock_stats.get('key_permission_rejections')}",
            f"Zero Balance Drift  : {report.compliance.get('zero_balance_drift')}",
            f"Zero Secret Leakage : {report.compliance.get('zero_secret_leakage')}",
            f"All Criteria Passed : {report.compliance.get('all_criteria_passed')}",
            "=" * 84,
        ]
    )
    return "\n".join(lines)


def execute_phase_276_runner(
    manifest_path: Path = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    phase275_dir: Path = DEFAULT_PHASE275_INPUT_DIR,
    output_dir: Path = DEFAULT_PHASE276_OUTPUT_DIR,
    track: str = "all",
    authorize_canary: bool = False,
    operator_id: str = "operator-lead-001",
    operator_rationale: str = "Phase 276 canary authorization sign-off",
    max_duration_hours: float = DEFAULT_MAX_DURATION_HOURS,
    daily_loss_budget_usdt: float = 2.00,
    interactive: bool = False,
    simulate_adverse_drift: bool = False,
    json_output: bool = False,
    verify_hash_chain: bool = False,
    verify_only: bool = False,
) -> int:
    """Execute deterministic Phase 276 canary activation runner workflow."""
    if verify_only or (verify_hash_chain and not authorize_canary and not interactive):
        hash_ok = verify_phase_276_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            phase275_dir=phase275_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 276 artifacts.\n"
        )
        return 0

    is_authorized = authorize_canary
    if not is_authorized and interactive:
        sys.stdout.write(
            f"Operator Production Canary Activation Authorization Required\n"
            f"Operator ID       : {operator_id}\n"
            f"Daily Loss Budget : {daily_loss_budget_usdt:.2f} USDT\n"
            f"Authorized Hours  : {max_duration_hours:.1f}h\n"
            f"Do you authorize production canary activation? [y/N]: "
        )
        sys.stdout.flush()
        resp = sys.stdin.readline().strip().lower()
        if resp in ("y", "yes"):
            is_authorized = True

    if not is_authorized:
        sys.stderr.write(
            "ERROR: Operator canary authorization missing. "
            "Pass --authorize-canary or authorize interactively.\n"
        )
        return 1

    normalized_track = track
    if track in ("1", "2", "3", "4"):
        normalized_track = f"track_{track}"

    cfg = CanaryActivationConfig(
        manifest_path=Path(manifest_path),
        registry_path=Path(registry_path),
        phase275_input_dir=Path(phase275_dir),
        output_dir=Path(output_dir),
        track=normalized_track,
        operator_id=operator_id,
        operator_rationale=operator_rationale,
        authorize_canary=is_authorized,
        max_duration_hours=max_duration_hours,
        daily_loss_budget_usdt=Decimal(str(daily_loss_budget_usdt)),
        simulate_adverse_drift=simulate_adverse_drift,
    )

    runner = CanaryActivationRunner(cfg)
    report = runner.execute_all_tracks()

    if verify_hash_chain:
        hash_ok = verify_phase_276_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            phase275_dir=phase275_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 276 artifacts.\n"
        )

    if json_output:
        sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(report) + "\n")

    all_tracks_ok = all(t.success for t in report.tracks) and report.compliance.get(
        "zero_balance_drift", False
    )
    return 0 if (report.compliance.get("all_criteria_passed") and all_tracks_ok) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 276 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_276_runner(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            phase275_dir=args.phase275_dir,
            output_dir=args.output_dir,
            track=args.track,
            authorize_canary=args.authorize_canary,
            operator_id=args.operator_id,
            operator_rationale=args.operator_rationale,
            max_duration_hours=args.max_duration_hours,
            daily_loss_budget_usdt=args.daily_loss_budget_usdt,
            interactive=args.interactive,
            simulate_adverse_drift=args.simulate_adverse_drift,
            json_output=args.json,
            verify_hash_chain=args.verify_hash_chain,
            verify_only=args.verify_only,
        )
    except KeyboardInterrupt:
        logger.info("Canary activation runner cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Canary activation runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
