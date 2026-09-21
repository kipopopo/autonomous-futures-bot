"""Phase 291: Production Canary Hawkes Jump Intensity & Cascades Runner CLI.

Validates production canary multi-candidate autonomous continuous live execution daemon runner,
cross-asset Hawkes process jump intensity modeling, rolling spectral radius rho(Gamma) cascade
governance, stepped exposure scaling up to 60.00 USDT, and continuous balance reconciliation
across staged canary symbols (BTCUSDT, ETHUSDT, SOLUSDT) under Candidate Registry Manifest
Version 2.
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
from autonomous_futures.feed.depth_imbalance import (  # noqa: E402
    DEFAULT_PHASE287_OUTPUT_DIR,
)
from autonomous_futures.feed.flow_toxicity import (  # noqa: E402
    DEFAULT_PHASE288_OUTPUT_DIR,
)
from autonomous_futures.feed.hawkes_cascades import (  # noqa: E402
    DEFAULT_PHASE291_OUTPUT_DIR,
    INTRA_PHASE_LOSS_CEILING_USDT,
    CanaryHawkesCascadeConfig,
    CanaryHawkesCascadeReport,
    CanaryHawkesCascadeRunner,
    verify_phase_291_hash_chain,
)
from autonomous_futures.feed.liquidity_regime import (  # noqa: E402
    DEFAULT_PHASE284_OUTPUT_DIR,
)
from autonomous_futures.feed.liquidity_shock import (  # noqa: E402
    DEFAULT_PHASE286_OUTPUT_DIR,
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
from autonomous_futures.feed.market_impact import (  # noqa: E402
    DEFAULT_PHASE289_OUTPUT_DIR,
)
from autonomous_futures.feed.ofi_cross_impact import (  # noqa: E402
    DEFAULT_PHASE290_OUTPUT_DIR,
)
from autonomous_futures.feed.testnet_deployment import (  # noqa: E402
    DEFAULT_PHASE278_OUTPUT_DIR,
)
from autonomous_futures.feed.volatility_spillover import (  # noqa: E402
    DEFAULT_PHASE285_OUTPUT_DIR,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_291_hawkes_cascades")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 291 Hawkes cascades runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Phase 291 Production Canary Multi-Candidate Cross-Asset Hawkes Process Jump "
            "Intensity & Cascades Autonomous Daemon Runner CLI."
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
        "--phase285-dir",
        type=Path,
        default=DEFAULT_PHASE285_OUTPUT_DIR,
        help="Path to upstream Phase 285 volatility spillover directory",
    )
    parser.add_argument(
        "--phase286-dir",
        type=Path,
        default=DEFAULT_PHASE286_OUTPUT_DIR,
        help="Path to upstream Phase 286 liquidity shock directory",
    )
    parser.add_argument(
        "--phase287-dir",
        type=Path,
        default=DEFAULT_PHASE287_OUTPUT_DIR,
        help="Path to upstream Phase 287 depth imbalance directory",
    )
    parser.add_argument(
        "--phase288-dir",
        type=Path,
        default=DEFAULT_PHASE288_OUTPUT_DIR,
        help="Path to upstream Phase 288 flow toxicity directory",
    )
    parser.add_argument(
        "--phase289-dir",
        type=Path,
        default=DEFAULT_PHASE289_OUTPUT_DIR,
        help="Path to upstream Phase 289 market impact directory",
    )
    parser.add_argument(
        "--phase290-dir",
        type=Path,
        default=DEFAULT_PHASE290_OUTPUT_DIR,
        help="Path to upstream Phase 290 OFI cross-impact directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PHASE291_OUTPUT_DIR,
        help="Path to output canary Hawkes cascade telemetry artifacts",
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
        help="Intra-phase cumulative loss ceiling in USDT (default: 7.00)",
    )
    parser.add_argument(
        "--simulate-loss-breach",
        action="store_true",
        help="Simulate intra-phase cumulative loss budget breach to test fail-closed lockout",
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


def format_summary_table(report: CanaryHawkesCascadeReport) -> str:
    """Format Phase 291 Hawkes cascades results into human-readable ASCII table."""
    lines: list[str] = [
        "=" * 96,
        "   PHASE 291: PRODUCTION CANARY HAWKES JUMP INTENSITY & CASCADES GOVERNANCE",
        "=" * 96,
        f" Daemon Status       : {report.daemon_status}",
        f" Timestamp (UTC)     : {report.timestamp_utc}",
        f" Staged Manifest Hash: {report.staged_manifest_hash[:16]}... "
        f"(Manifest v{report.manifest_version})",
        "-" * 96,
        " TRACK RESULTS:",
    ]
    for trk in report.tracks:
        if isinstance(trk, dict):
            t_id = trk.get("track_id", "")
            status = trk.get("status", "")
            cash = trk.get("final_cash_usdt", "")
            drift = trk.get("drift_usdt", "")
            zero_drift = trk.get("zero_balance_drift", False)
            succ = trk.get("success", False)
            placed = trk.get("orders_placed_count", 0)
            filled = trk.get("orders_filled_count", 0)
            stage = trk.get("final_expansion_stage", "")
        else:
            t_id = trk.track_id
            status = trk.status
            cash = trk.final_cash_usdt
            drift = trk.drift_usdt
            zero_drift = trk.zero_balance_drift
            succ = trk.success
            placed = trk.orders_placed_count
            filled = trk.orders_filled_count
            stage = trk.final_expansion_stage

        drift_tag = "[ZERO-DRIFT]" if zero_drift else f"[DRIFT: {drift}]"
        succ_tag = "[PASS]" if succ else "[FAIL]"
        lines.append(
            f"   {t_id:<8} | {succ_tag} {status:<55} | Cash: {cash:>11} USDT | "
            f"Orders: {placed} placed, {filled} filled | Stage: {stage} | {drift_tag}"
        )

    lines.append("-" * 96)
    lines.append(" GOVERNANCE METRICS & COMPLIANCE:")
    lines.append(
        f"   Aggregate Exposure Cap: "
        f"{report.daemon_stats.get('aggregate_exposure_cap_usdt', '60.00')} USDT | "
        f"Micro Cap: {report.daemon_stats.get('individual_micro_notional_cap_usdt', '5.00')} USDT"
    )
    lines.append(
        f"   TWAP Slice Cap: "
        f"{report.daemon_stats.get('dynamic_slicing_max_chunk_usdt', '2.50')} USDT | "
        f"Branching Ratio Critical (rho >= 0.85)"
    )
    lines.append(
        f"   Supercritical Runaway (rho >= 1.00) | "
        f"Loss Budget: {report.daemon_stats.get('intra_phase_loss_ceiling_usdt', '7.00')} USDT"
    )
    lines.append(
        f"   All Criteria Passed: {report.compliance.get('all_criteria_passed', False)} | "
        f"Zero Drift: {report.compliance.get('zero_balance_drift', False)} | "
        f"Zero Secrets: {report.compliance.get('zero_secret_leakage', False)}"
    )
    lines.append("=" * 96)
    return "\n".join(lines)


def execute_phase_291_runner(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    phase276_dir: Path | str = DEFAULT_PHASE276_OUTPUT_DIR,
    phase277_dir: Path | str = DEFAULT_PHASE277_OUTPUT_DIR,
    phase278_dir: Path | str = DEFAULT_PHASE278_OUTPUT_DIR,
    phase279_dir: Path | str = DEFAULT_PHASE279_OUTPUT_DIR,
    phase280_dir: Path | str = DEFAULT_PHASE280_OUTPUT_DIR,
    phase281_dir: Path | str = DEFAULT_PHASE281_OUTPUT_DIR,
    phase282_dir: Path | str = DEFAULT_PHASE282_OUTPUT_DIR,
    phase283_dir: Path | str = DEFAULT_PHASE283_OUTPUT_DIR,
    phase284_dir: Path | str = DEFAULT_PHASE284_OUTPUT_DIR,
    phase285_dir: Path | str = DEFAULT_PHASE285_OUTPUT_DIR,
    phase286_dir: Path | str = DEFAULT_PHASE286_OUTPUT_DIR,
    phase287_dir: Path | str = DEFAULT_PHASE287_OUTPUT_DIR,
    phase288_dir: Path | str = DEFAULT_PHASE288_OUTPUT_DIR,
    phase289_dir: Path | str = DEFAULT_PHASE289_OUTPUT_DIR,
    phase290_dir: Path | str = DEFAULT_PHASE290_OUTPUT_DIR,
    output_dir: Path | str = DEFAULT_PHASE291_OUTPUT_DIR,
    track: str = "all",
    intra_phase_loss_ceiling_usdt: float = float(INTRA_PHASE_LOSS_CEILING_USDT),
    simulate_adverse_drift: bool = False,
    simulate_loss_breach: bool = False,
    json_output: bool = False,
    verify_hash_chain: bool = False,
    verify_only: bool = False,
) -> int:
    """Orchestrate Phase 291 Hawkes cascades execution daemon runner."""
    normalized_track = track.strip().lower()
    if normalized_track.startswith("track_"):
        pass
    elif normalized_track in ("1", "2", "3", "4"):
        normalized_track = f"track_{normalized_track}"
    elif normalized_track != "all":
        raise ValueError(f"Unsupported track identifier: {track}")

    if verify_only:
        logger.info("Executing verify-only mode for Phase 291 cryptographic DAG hash chain.")
        hash_ok = verify_phase_291_hash_chain(
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
            phase285_dir=phase285_dir,
            phase286_dir=phase286_dir,
            phase287_dir=phase287_dir,
            phase288_dir=phase288_dir,
            phase289_dir=phase289_dir,
            phase290_dir=phase290_dir,
        )
        if hash_ok:
            sys.stdout.write(
                "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 291 artifacts.\n"
            )
            return 0
        else:
            logger.error(
                "Cryptographic SHA-256 DAG hash chain verification failed in verify-only mode."
            )
            return 1

    loss_ceiling = Decimal(str(intra_phase_loss_ceiling_usdt))

    cfg = CanaryHawkesCascadeConfig(
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
        phase285_input_dir=Path(phase285_dir),
        phase286_input_dir=Path(phase286_dir),
        phase287_input_dir=Path(phase287_dir),
        phase288_input_dir=Path(phase288_dir),
        phase289_input_dir=Path(phase289_dir),
        phase290_input_dir=Path(phase290_dir),
        output_dir=Path(output_dir),
        track=normalized_track,
        intra_phase_loss_ceiling_usdt=loss_ceiling,
        simulate_adverse_drift=simulate_adverse_drift,
        simulate_loss_breach=simulate_loss_breach,
    )

    runner = CanaryHawkesCascadeRunner(cfg)
    report = runner.execute_all_tracks()

    if verify_hash_chain:
        hash_ok = verify_phase_291_hash_chain(
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
            phase285_dir=phase285_dir,
            phase286_dir=phase286_dir,
            phase287_dir=phase287_dir,
            phase288_dir=phase288_dir,
            phase289_dir=phase289_dir,
            phase290_dir=phase290_dir,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across Phase 291 artifacts.\n"
        )

    if json_output:
        sys.stdout.write(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(report) + "\n")

    all_tracks_ok = all(
        getattr(t, "success", False) for t in report.tracks
    ) and report.compliance.get("zero_balance_drift", False)
    all_passed = report.compliance.get("all_criteria_passed", False)
    return 0 if (all_passed and all_tracks_ok) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 291 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_291_runner(
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
            phase285_dir=args.phase285_dir,
            phase286_dir=args.phase286_dir,
            phase287_dir=args.phase287_dir,
            phase288_dir=args.phase288_dir,
            phase289_dir=args.phase289_dir,
            phase290_dir=args.phase290_dir,
            output_dir=args.output_dir,
            track=args.track,
            intra_phase_loss_ceiling_usdt=args.intra_phase_loss_ceiling_usdt,
            simulate_adverse_drift=args.simulate_adverse_drift,
            simulate_loss_breach=args.simulate_loss_breach,
            json_output=args.json,
            verify_hash_chain=args.verify_hash_chain,
            verify_only=args.verify_only,
        )
    except KeyboardInterrupt:
        logger.info("Hawkes cascade runner cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Hawkes cascade runner failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
