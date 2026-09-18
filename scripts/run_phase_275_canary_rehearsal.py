"""Phase 275: Unified End-to-End Canary Rehearsal & Live-Readiness Certification CLI.

Executes deterministic multi-track micro live execution rehearsals under
Candidate Registry Manifest Version 2 to validate real-time ingress, coupled stream
supervision, automated 3-state circuit breaker recovery with K=5 hysteresis,
post-only quoting, bracket execution, dynamic mark price revaluation,
and zero-drift double-entry balance integrity.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure src/ and repo root are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.canary_rehearsal import (  # noqa: E402
    DEFAULT_PHASE275_OUTPUT_DIR,
    DEFAULT_RECOVERY_HYSTERESIS_TICKS,
    CanaryLiveReadinessReport,
    CanaryRehearsalConfig,
    CanaryRehearsalDaemon,
    verify_phase_275_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_275_canary_rehearsal")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 275 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 275 Canary Live-Readiness Rehearsal & Promotion Certification CLI."
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
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE275_OUTPUT_DIR,
        help="Path to output canary rehearsal telemetry artifacts",
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
            "cli_override",
            "all",
        ],
        help="Specific rehearsal track to execute (default: all)",
    )
    parser.add_argument(
        "--rehearsal-seconds",
        type=float,
        default=30.0,
        help="Bounded rehearsal duration in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=50,
        help="Bounded maximum ingress ticks (default: 50)",
    )
    parser.add_argument(
        "--offline-replay",
        action="store_true",
        help="Execute deterministic offline replay mode without live network calls",
    )
    parser.add_argument(
        "--stream-ingress",
        action="store_true",
        help="Execute real-time or offline replay stream ingress daemon",
    )
    parser.add_argument(
        "--recovery-hysteresis-ticks",
        type=int,
        default=DEFAULT_RECOVERY_HYSTERESIS_TICKS,
        help="Consecutive healthy stream ticks required for automated recovery (default: 5)",
    )
    override_group = parser.add_mutually_exclusive_group()
    override_group.add_argument(
        "--force-freeze",
        action="store_true",
        help="Manual operator override: trigger Tier 1 Soft-Freeze",
    )
    override_group.add_argument(
        "--force-abort",
        action="store_true",
        help="Manual operator override: trigger Tier 2 Hard-Abort",
    )
    override_group.add_argument(
        "--force-recover",
        action="store_true",
        help="Manual operator override: trigger manual recovery to NORMAL",
    )
    parser.add_argument(
        "--operator-id",
        type=str,
        default="operator-lead-001",
        help="Operator ID for manual overrides (default: operator-lead-001)",
    )
    parser.add_argument(
        "--rationale",
        type=str,
        default="Phase 275 manual operator intervention rehearsal",
        help="Audit rationale for manual operator override",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Inject synthetic accounting drift (> 1e-15 USDT) to test fail-closed detection",
    )
    parser.add_argument(
        "--verify-hash-chain",
        action="store_true",
        help="Verify cryptographic SHA-256 DAG hash chain across artifacts and staging manifest",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic SHA-256 DAG hash chain without re-executing the rehearsal",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON summary to stdout",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return parser


def format_summary_table(report: CanaryLiveReadinessReport) -> str:
    """Format human-readable execution summary table."""
    sep = "=" * 80
    sub_sep = "-" * 80
    cb_stats = report.circuit_breaker_stats
    order_stats = report.order_stats
    stream_stats = report.stream_stats
    assessment = report.promotion_assessment

    lines = [
        sep,
        "PHASE 275: CANARY REHEARSAL & LIVE-READINESS PROMOTION CERTIFICATION",
        sep,
        f"Timestamp UTC:               {report.timestamp_utc}",
        f"Staged Manifest Hash:        {report.staged_manifest_hash[:16]}...",
        f"Manifest Version:            {report.manifest_version}",
        f"Registry Version:            {report.registry_version}",
        f"Promotion State:             {assessment.promotion_state}",
        f"Promotion Authorized:        {assessment.promotion_authorized}",
        f"Decision Rationale:          {assessment.decision_rationale}",
        sub_sep,
        "Real-Time Stream Ingress & Heartbeat Telemetry:",
        f"  Marks Ingested Count:      {stream_stats.get('marks_ingested_count', 0)}",
        f"  Canary Staged Symbols:     {', '.join(stream_stats.get('staged_assets', []))}",
        f"  Ingress Stream Types:      {', '.join(stream_stats.get('stream_types', []))}",
        sub_sep,
        "Micro Canary Order Lifecycle & Execution Statistics:",
        f"  Total Orders Placed:       {order_stats.get('total_orders_placed', 0)}",
        f"  Total Orders Filled:       {order_stats.get('total_orders_filled', 0)}",
        f"  Total Orders Cancelled:    {order_stats.get('total_orders_cancelled', 0)}",
        f"  Total Orders Rejected:     {order_stats.get('total_orders_rejected', 0)}",
        f"  Emergency Liquidations:    {order_stats.get('total_liquidations', 0)}",
        f"  Total Fees Incurred:       {order_stats.get('total_fees_usdt', '0.000000')} USDT",
        f"  Total Slippage Cost:       {order_stats.get('total_slippage_usdt', '0.000000')} USDT",
        sub_sep,
        "Circuit Breaker Telemetry & Automated State Recovery:",
        f"  Total State Transitions:   {cb_stats.get('total_transitions', 0)}",
        f"  Soft Freezes Triggered:    {cb_stats.get('total_soft_freezes', 0)}",
        f"  Hard Aborts Triggered:     {cb_stats.get('total_hard_aborts', 0)}",
        f"  Auto Recoveries (K=5):     {cb_stats.get('total_auto_recoveries', 0)}",
        f"  Terminal Breaker State:    {cb_stats.get('final_state', 'NORMAL')}",
        sub_sep,
        "Multi-Scenario Integrated Rehearsal Tracks:",
    ]

    for tr in report.tracks:
        lines.append(
            f"  [{tr.track_id:<7}] {tr.track_name:<50} -> {tr.status:<24} "
            f"(ord={tr.orders_placed_count}, fill={tr.orders_filled_count}, "
            f"cxl={tr.orders_cancelled_count}, rej={tr.orders_rejected_count}, "
            f"liq={tr.liquidations_count}, marks={tr.marks_ingested_count})"
        )

    lines.extend(
        [
            sub_sep,
            "Compliance Verification Matrix:",
        ]
    )
    for k, v in report.compliance.items():
        lines.append(f"  {k:<35} {v}")

    lines.extend(
        [
            sub_sep,
            "Deterministic Artifact SHA-256 Digests (Merkle DAG):",
        ]
    )
    for art, h in report.artifact_hashes.items():
        lines.append(f"  {art:<35} {h}")
    lines.append(sep)
    return "\n".join(lines)


def execute_phase_275_runner(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE275_OUTPUT_DIR,
    track: str = "all",
    rehearsal_seconds: float = 30.0,
    max_ticks: int = 50,
    recovery_hysteresis_ticks: int = DEFAULT_RECOVERY_HYSTERESIS_TICKS,
    offline_replay: bool = False,
    force_freeze: bool = False,
    force_abort: bool = False,
    force_recover: bool = False,
    operator_id: str = "operator-lead-001",
    rationale: str = "Phase 275 manual operator intervention rehearsal",
    simulate_adverse_drift: bool = False,
    stream_ingress: bool = False,
    json_output: bool = False,
    verify_hash_chain: bool = False,
    verify_only: bool = False,
) -> int:
    """Execute deterministic Phase 275 canary rehearsal runner workflow."""
    if verify_only:
        hash_ok = verify_phase_275_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across all Phase 275 artifacts.\n"
        )
        return 0

    normalized_track = track
    if force_freeze or force_abort or force_recover:
        normalized_track = "cli_override"
    elif track in ("1", "2", "3", "4"):
        normalized_track = f"track_{track}"

    cfg = CanaryRehearsalConfig(
        manifest_path=Path(manifest_path),
        registry_path=Path(registry_path),
        output_dir=Path(output_dir),
        track=normalized_track,
        rehearsal_seconds=rehearsal_seconds,
        max_ticks=max_ticks,
        recovery_hysteresis_ticks=recovery_hysteresis_ticks,
        offline_replay=offline_replay,
        force_freeze=force_freeze,
        force_abort=force_abort,
        force_recover=force_recover,
        operator_id=operator_id,
        rationale=rationale,
        simulate_adverse_drift=simulate_adverse_drift,
    )

    daemon = CanaryRehearsalDaemon(cfg)
    if stream_ingress:
        import asyncio

        ticks = asyncio.run(
            daemon.run_live_ingress_stream(
                duration_seconds=rehearsal_seconds,
                max_ticks=max_ticks,
            )
        )
        logger.info("Stream ingress drill completed: %d ticks ingested", ticks)
        sys.stdout.write(f"[PASS] Stream ingress drill completed: {ticks} ticks ingested.\n")
        return 0

    report = daemon.run()

    if verify_hash_chain:
        hash_ok = verify_phase_275_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across all Phase 275 artifacts.\n"
        )

    if json_output:
        sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(report) + "\n")

    all_tracks_ok = all(t.success for t in report.tracks) and report.compliance.get(
        "zero_balance_drift", False
    )
    return 0 if (report.promotion_assessment.promotion_authorized or all_tracks_ok) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 275 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_275_runner(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            output_dir=args.output_dir,
            track=args.track,
            rehearsal_seconds=args.rehearsal_seconds,
            max_ticks=args.max_ticks,
            recovery_hysteresis_ticks=args.recovery_hysteresis_ticks,
            offline_replay=args.offline_replay,
            force_freeze=args.force_freeze,
            force_abort=args.force_abort,
            force_recover=args.force_recover,
            operator_id=args.operator_id,
            rationale=args.rationale,
            simulate_adverse_drift=args.simulate_adverse_drift,
            stream_ingress=args.stream_ingress,
            json_output=args.json,
            verify_hash_chain=args.verify_hash_chain,
            verify_only=args.verify_only,
        )
    except KeyboardInterrupt:
        logger.info("Canary rehearsal runner cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Canary rehearsal runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
