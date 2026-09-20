"""Phase 285: Production Canary Volatility Spillover & Correlation Breakdown Runner CLI.

Validates production canary multi-candidate autonomous continuous live execution daemon runner,
cross-asset volatility spillover tracking, adaptive correlation breakdown throttling, stepped
exposure scaling up to 30.00 USDT, and continuous balance reconciliation across staged canary
symbols (BTCUSDT, ETHUSDT, SOLUSDT) under Candidate Registry Manifest Version 2.
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

from autonomous_futures.feed.adaptive_execution import (  # noqa: E402
    DEFAULT_PHASE283_OUTPUT_DIR,
)
from autonomous_futures.feed.canary_activation import (  # noqa: E402
    DEFAULT_PHASE276_OUTPUT_DIR,
)
from autonomous_futures.feed.canary_live_gateway import (  # noqa: E402
    DEFAULT_PHASE277_OUTPUT_DIR,
)
from autonomous_futures.feed.continuous_daemon import (  # noqa: E402
    DEFAULT_PHASE282_OUTPUT_DIR,
)
from autonomous_futures.feed.liquidity_regime import (  # noqa: E402
    DEFAULT_PHASE284_OUTPUT_DIR,
)
from autonomous_futures.feed.mainnet_authorization import (  # noqa: E402
    DEFAULT_PHASE279_OUTPUT_DIR,
)
from autonomous_futures.feed.mainnet_deployment import (  # noqa: E402
    DEFAULT_PHASE280_OUTPUT_DIR,
)
from autonomous_futures.feed.mainnet_expansion import (  # noqa: E402
    DEFAULT_PHASE281_OUTPUT_DIR,
)
from autonomous_futures.feed.testnet_deployment import (  # noqa: E402
    DEFAULT_PHASE278_OUTPUT_DIR,
)
from autonomous_futures.feed.volatility_spillover import (  # noqa: E402
    DEFAULT_PHASE285_OUTPUT_DIR,
    INTRA_PHASE_LOSS_CEILING_USDT,
    CanaryVolatilitySpilloverConfig,
    CanaryVolatilitySpilloverReport,
    CanaryVolatilitySpilloverRunner,
    verify_phase_285_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_285_volatility_spillover")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 285 volatility spillover runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Phase 285 Production Canary Multi-Candidate Cross-Asset Synthetic "
            "Volatility Spillover Autonomous Daemon Runner CLI."
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
        "--phase277-dir",
        type=Path,
        default=DEFAULT_PHASE277_OUTPUT_DIR,
        help="Path to upstream Phase 277 gateway report directory",
    )
    parser.add_argument(
        "--phase278-dir",
        type=Path,
        default=DEFAULT_PHASE278_OUTPUT_DIR,
        help="Path to upstream Phase 278 testnet deployment directory",
    )
    parser.add_argument(
        "--phase279-dir",
        type=Path,
        default=DEFAULT_PHASE279_OUTPUT_DIR,
        help="Path to upstream Phase 279 mainnet authorization directory",
    )
    parser.add_argument(
        "--phase280-dir",
        type=Path,
        default=DEFAULT_PHASE280_OUTPUT_DIR,
        help="Path to upstream Phase 280 mainnet deployment directory",
    )
    parser.add_argument(
        "--phase281-dir",
        type=Path,
        default=DEFAULT_PHASE281_OUTPUT_DIR,
        help="Path to upstream Phase 281 mainnet expansion directory",
    )
    parser.add_argument(
        "--phase282-dir",
        type=Path,
        default=DEFAULT_PHASE282_OUTPUT_DIR,
        help="Path to upstream Phase 282 continuous daemon directory",
    )
    parser.add_argument(
        "--phase283-dir",
        type=Path,
        default=DEFAULT_PHASE283_OUTPUT_DIR,
        help="Path to upstream Phase 283 adaptive execution directory",
    )
    parser.add_argument(
        "--phase284-dir",
        type=Path,
        default=DEFAULT_PHASE284_OUTPUT_DIR,
        help="Path to upstream Phase 284 liquidity regime directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE285_OUTPUT_DIR,
        help="Path to output canary volatility spillover telemetry artifacts",
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
        "--intra-phase-loss-ceiling-usdt",
        type=float,
        default=float(INTRA_PHASE_LOSS_CEILING_USDT),
        help="Intra-phase cumulative loss ceiling in USDT (default: 4.00)",
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


def format_summary_table(report: CanaryVolatilitySpilloverReport) -> str:
    """Format Phase 285 volatility spillover results into human-readable ASCII table."""
    lines: list[str] = [
        "=" * 96,
        "   PHASE 285: PRODUCTION CANARY VOLATILITY SPILLOVER & CORRELATION BREAKDOWN",
        "=" * 96,
        f"Timestamp UTC    : {report.timestamp_utc}",
        f"Daemon Status    : {report.daemon_status}",
        f"Manifest Version : {report.manifest_version}",
        f"Staged Manifest  : {report.staged_manifest_hash[:16]}...",
        f"Upstream Cert    : {report.upstream_phase276_certificate_hash[:16]}...",
        f"Upstream P277 Rep: {report.upstream_phase277_report_hash[:16]}...",
        f"Upstream P278 Rep: {report.upstream_phase278_report_hash[:16]}...",
        f"Upstream P279 Rep: {report.upstream_phase279_report_hash[:16]}...",
        f"Upstream P280 Rep: {report.upstream_phase280_report_hash[:16]}...",
        f"Upstream P281 Rep: {report.upstream_phase281_report_hash[:16]}...",
        f"Upstream P282 Rep: {report.upstream_phase282_report_hash[:16]}...",
        f"Upstream P283 Rep: {report.upstream_phase283_report_hash[:16]}...",
        f"Upstream P284 Rep: {report.upstream_phase284_report_hash[:16]}...",
        "-" * 96,
        f"{'Track ID':<10} {'Status':<48} {'Drift (USDT)':<15} {'Success':<8}",
        "-" * 96,
    ]
    for tr in report.tracks:
        lines.append(f"{tr.track_id:<10} {tr.status:<48} {tr.drift_usdt:<15} {str(tr.success):<8}")
    lines.extend(
        [
            "-" * 96,
            f"Total Orders Placed : {report.order_stats.get('total_orders_placed')}",
            f"Total Orders Filled : {report.order_stats.get('total_orders_filled')}",
            f"Interlock Blocks    : {report.order_stats.get('interlock_blocks_count')}",
            f"Heartbeats Recorded : {report.heartbeat_stats.get('total_heartbeats_recorded')}",
            f"Stale Heartbeats    : {report.heartbeat_stats.get('stale_heartbeat_breaches')}",
            f"Stream Events       : {report.stream_stats.get('total_stream_events')}",
            f"Deduplicated Events : {report.stream_stats.get('total_deduplicated_events')}",
            f"Zero Balance Drift  : {report.compliance.get('zero_balance_drift')}",
            f"Zero Secret Leakage : {report.compliance.get('zero_secret_leakage')}",
            f"All Criteria Passed : {report.compliance.get('all_criteria_passed')}",
            "=" * 96,
        ]
    )
    return "\n".join(lines)


def execute_phase_285_runner(
    manifest_path: Path = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path = DEFAULT_CANDIDATE_REGISTRY_PATH,
    phase276_dir: Path = DEFAULT_PHASE276_OUTPUT_DIR,
    phase277_dir: Path = DEFAULT_PHASE277_OUTPUT_DIR,
    phase278_dir: Path = DEFAULT_PHASE278_OUTPUT_DIR,
    phase279_dir: Path = DEFAULT_PHASE279_OUTPUT_DIR,
    phase280_dir: Path = DEFAULT_PHASE280_OUTPUT_DIR,
    phase281_dir: Path = DEFAULT_PHASE281_OUTPUT_DIR,
    phase282_dir: Path = DEFAULT_PHASE282_OUTPUT_DIR,
    phase283_dir: Path = DEFAULT_PHASE283_OUTPUT_DIR,
    phase284_dir: Path = DEFAULT_PHASE284_OUTPUT_DIR,
    output_dir: Path = DEFAULT_PHASE285_OUTPUT_DIR,
    track: str = "all",
    intra_phase_loss_ceiling_usdt: float = float(INTRA_PHASE_LOSS_CEILING_USDT),
    simulate_adverse_drift: bool = False,
    json_output: bool = False,
    verify_hash_chain: bool = False,
    verify_only: bool = False,
) -> int:
    """Execute deterministic Phase 285 volatility spillover runner workflow."""
    if verify_only:
        hash_ok = verify_phase_285_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            phase276_dir=phase276_dir,
            phase277_dir=phase277_dir,
            phase278_dir=phase278_dir,
            phase279_dir=phase279_dir,
            phase280_dir=phase280_dir,
            phase281_dir=phase281_dir,
            phase282_dir=phase282_dir,
            phase283_dir=phase283_dir,
            phase284_dir=phase284_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 285 artifacts.\n"
        )
        return 0

    normalized_track = track
    if track in ("1", "2", "3", "4"):
        normalized_track = f"track_{track}"

    cfg = CanaryVolatilitySpilloverConfig(
        manifest_path=Path(manifest_path),
        registry_path=Path(registry_path),
        phase276_input_dir=Path(phase276_dir),
        phase277_input_dir=Path(phase277_dir),
        phase278_input_dir=Path(phase278_dir),
        phase279_input_dir=Path(phase279_dir),
        phase280_input_dir=Path(phase280_dir),
        phase281_input_dir=Path(phase281_dir),
        phase282_input_dir=Path(phase282_dir),
        phase283_input_dir=Path(phase283_dir),
        phase284_input_dir=Path(phase284_dir),
        output_dir=Path(output_dir),
        track=normalized_track,
        intra_phase_loss_ceiling_usdt=Decimal(str(intra_phase_loss_ceiling_usdt)),
        simulate_adverse_drift=simulate_adverse_drift,
    )

    runner = CanaryVolatilitySpilloverRunner(cfg)
    report = runner.execute_all_tracks()

    if verify_hash_chain:
        hash_ok = verify_phase_285_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            phase276_dir=phase276_dir,
            phase277_dir=phase277_dir,
            phase278_dir=phase278_dir,
            phase279_dir=phase279_dir,
            phase280_dir=phase280_dir,
            phase281_dir=phase281_dir,
            phase282_dir=phase282_dir,
            phase283_dir=phase283_dir,
            phase284_dir=phase284_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 285 artifacts.\n"
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
    """Main CLI entry point for Phase 285 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_285_runner(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            phase276_dir=args.phase276_dir,
            phase277_dir=args.phase277_dir,
            phase278_dir=args.phase278_dir,
            phase279_dir=args.phase279_dir,
            phase280_dir=args.phase280_dir,
            phase281_dir=args.phase281_dir,
            phase282_dir=args.phase282_dir,
            phase283_dir=args.phase283_dir,
            phase284_dir=args.phase284_dir,
            output_dir=args.output_dir,
            track=args.track,
            intra_phase_loss_ceiling_usdt=args.intra_phase_loss_ceiling_usdt,
            simulate_adverse_drift=args.simulate_adverse_drift,
            json_output=args.json,
            verify_hash_chain=args.verify_hash_chain,
            verify_only=args.verify_only,
        )
    except KeyboardInterrupt:
        logger.info("Volatility spillover runner cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Volatility spillover runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
