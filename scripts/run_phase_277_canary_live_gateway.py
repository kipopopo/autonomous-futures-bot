"""Phase 277: Live Exchange Gateway Synchronization Runner CLI.

Validates end-to-end exchange communication, account ledger integrity, authenticated
endpoint synchronization, and error recovery under Candidate Registry Manifest Version 2.
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
    DEFAULT_PHASE276_OUTPUT_DIR,
)
from autonomous_futures.feed.canary_live_gateway import (  # noqa: E402
    DEFAULT_PHASE277_OUTPUT_DIR,
    CanaryGatewayConfig,
    CanaryGatewayReport,
    CanaryLiveGatewayRunner,
    verify_phase_277_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_277_canary_live_gateway")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 277 runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Phase 277 Live Exchange Gateway Synchronization Runner & Shadow Order Dispatch CLI."
        )
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
        "--phase276-dir",
        type=Path,
        default=DEFAULT_PHASE276_OUTPUT_DIR,
        help="Path to upstream Phase 276 activation certificate directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE277_OUTPUT_DIR,
        help="Path to output canary live gateway telemetry artifacts",
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
        "--daily-loss-budget-usdt",
        type=float,
        default=2.00,
        help="Daily cumulative loss budget ceiling in USDT (default: 2.00)",
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


def format_summary_table(report: CanaryGatewayReport) -> str:
    """Format Phase 277 gateway results into human-readable ASCII table."""
    lines: list[str] = [
        "=" * 88,
        "   PHASE 277: LIVE EXCHANGE GATEWAY SYNCHRONIZATION & SHADOW ORDER DISPATCH HARNESS",
        "=" * 88,
        f"Timestamp UTC    : {report.timestamp_utc}",
        f"Manifest Version : {report.manifest_version}",
        f"Staged Manifest  : {report.staged_manifest_hash[:16]}...",
        f"Upstream Cert    : {report.upstream_phase276_certificate_hash[:16]}...",
        "-" * 88,
        f"{'Track ID':<10} {'Status':<42} {'Drift (USDT)':<15} {'Success':<8}",
        "-" * 88,
    ]
    for tr in report.tracks:
        lines.append(f"{tr.track_id:<10} {tr.status:<42} {tr.drift_usdt:<15} {str(tr.success):<8}")
    lines.extend(
        [
            "-" * 88,
            f"Total Orders Placed : {report.order_stats.get('total_orders_placed')}",
            f"Total Orders Filled : {report.order_stats.get('total_orders_filled')}",
            f"Total Orders Reject : {report.order_stats.get('total_orders_rejected')}",
            f"Drift Recoveries    : {report.error_stats.get('timestamp_drift_recoveries')}",
            f"Rate Limit Backoffs : {report.error_stats.get('rate_limit_backoffs')}",
            f"Desync Lockouts     : {report.error_stats.get('desync_lockouts')}",
            f"Network Fallbacks   : {report.error_stats.get('network_partition_fallbacks')}",
            f"Zero Balance Drift  : {report.compliance.get('zero_balance_drift')}",
            f"Zero Secret Leakage : {report.compliance.get('zero_secret_leakage')}",
            f"All Criteria Passed : {report.compliance.get('all_criteria_passed')}",
            "=" * 88,
        ]
    )
    return "\n".join(lines)


def execute_phase_277_runner(
    manifest_path: Path = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    phase276_dir: Path = DEFAULT_PHASE276_OUTPUT_DIR,
    output_dir: Path = DEFAULT_PHASE277_OUTPUT_DIR,
    track: str = "all",
    daily_loss_budget_usdt: float = 2.00,
    simulate_adverse_drift: bool = False,
    json_output: bool = False,
    verify_hash_chain: bool = False,
    verify_only: bool = False,
) -> int:
    """Execute deterministic Phase 277 live gateway runner workflow."""
    if verify_only:
        hash_ok = verify_phase_277_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            phase276_dir=phase276_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 277 artifacts.\n"
        )
        return 0

    normalized_track = track
    if track in ("1", "2", "3", "4"):
        normalized_track = f"track_{track}"

    cfg = CanaryGatewayConfig(
        manifest_path=Path(manifest_path),
        registry_path=Path(registry_path),
        phase276_input_dir=Path(phase276_dir),
        output_dir=Path(output_dir),
        track=normalized_track,
        daily_loss_budget_usdt=Decimal(str(daily_loss_budget_usdt)),
        simulate_adverse_drift=simulate_adverse_drift,
    )

    runner = CanaryLiveGatewayRunner(cfg)
    report = runner.execute_all_tracks()

    if verify_hash_chain:
        hash_ok = verify_phase_277_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            phase276_dir=phase276_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 277 artifacts.\n"
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
    """Main CLI entry point for Phase 277 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_277_runner(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            phase276_dir=args.phase276_dir,
            output_dir=args.output_dir,
            track=args.track,
            daily_loss_budget_usdt=args.daily_loss_budget_usdt,
            simulate_adverse_drift=args.simulate_adverse_drift,
            json_output=args.json,
            verify_hash_chain=args.verify_hash_chain,
            verify_only=args.verify_only,
        )
    except KeyboardInterrupt:
        logger.info("Live gateway runner cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Live gateway runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
