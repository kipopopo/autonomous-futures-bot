"""Phase 274: Unified Canary Micro-Execution Rehearsal Runner & Incident Response Drill CLI.

Executes deterministic multi-track micro live execution rehearsals under Candidate Registry Manifest
Version 2 to validate end-to-end order placement, post-only validation, margin cap adherence,
coupled circuit breaker state transitions, and zero-drift balance integrity.
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

from autonomous_futures.feed.micro_execution_drill import (  # noqa: E402
    DEFAULT_PHASE274_OUTPUT_DIR,
    DEFAULT_RECOVERY_HYSTERESIS_TICKS,
    CanaryMicroExecutionDrillConfig,
    CanaryMicroExecutionDrillRunner,
    Phase274DrillSummary,
    verify_phase_274_hash_chain,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_274_micro_execution_drill")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 274 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 274 Canary Micro-Execution Rehearsal Drill CLI."
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
        default=DEFAULT_PHASE274_OUTPUT_DIR,
        help="Path to output canary execution telemetry artifacts",
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
        help="Specific execution track to execute (default: all)",
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
        default="Phase 274 manual operator intervention rehearsal",
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
        help=(
            "Verify cryptographic SHA-256 DAG hash chain across generated "
            "artifacts and staging manifest"
        ),
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify cryptographic SHA-256 DAG hash chain without re-executing the drill",
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


def format_summary_table(summary: Phase274DrillSummary) -> str:
    """Format human-readable execution summary table."""
    sep = "=" * 80
    sub_sep = "-" * 80
    cb_stats = summary.circuit_breaker_stats
    order_stats = summary.order_stats
    acct = summary.portfolio_accounting
    risk = summary.risk_guardrails
    sec_inv = summary.safety_invariants

    lines = [
        sep,
        "PHASE 274: CANARY MICRO-EXECUTION REHEARSAL & RISK GUARDRAILS DRILL",
        sep,
        f"Timestamp UTC:               {summary.timestamp_utc}",
        f"Staged Manifest Hash:        {summary.staged_manifest_hash[:16]}...",
        f"Manifest Version:            {summary.manifest_version}",
        f"Tracks Executed:             {', '.join(summary.tracks_executed)}",
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
        "Circuit Breaker Telemetry & State Transitions:",
        f"  Total Ticks Processed:     {cb_stats.get('total_ticks_processed', 0)}",
        (
            f"  Soft Freezes Triggered:    "
            f"{cb_stats.get('total_soft_freezes', cb_stats.get('soft_freezes_triggered', 0))}"
        ),
        (
            f"  Hard Aborts Triggered:     "
            f"{cb_stats.get('total_hard_aborts', cb_stats.get('hard_aborts_triggered', 0))}"
        ),
        (
            f"  Auto Recoveries:           "
            f"{cb_stats.get('total_auto_recoveries', cb_stats.get('auto_recoveries', 0))}"
        ),
        (
            f"  Terminal Breaker State:    "
            f"{cb_stats.get('terminal_state', cb_stats.get('final_state', 'NORMAL'))}"
        ),
        sub_sep,
        "Multi-Scenario Micro-Execution Tracks:",
    ]

    for tid, tinfo in summary.tracks_summary.items():
        name = tinfo.get("name", tid)
        status = tinfo.get("status", "UNKNOWN")
        placed = tinfo.get("orders_placed", 0)
        filled = tinfo.get("orders_filled", 0)
        cancelled = tinfo.get("orders_cancelled", 0)
        rejected = tinfo.get("orders_rejected", 0)
        liqs = tinfo.get("liquidations", 0)
        lines.append(
            f"  [{tid:<7}] {name:<45} -> {status:<24} "
            f"(ord={placed}, fill={filled}, cxl={cancelled}, rej={rejected}, liq={liqs})"
        )

    lines.extend(
        [
            sub_sep,
            "Exact Double-Entry Accounting & Portfolio Solvency:",
            f"  Starting Equity:           {acct.get('starting_equity_usdt', '100.00')} USDT",
            f"  Final Cash Balance:        {acct.get('final_cash_usdt', '100.00')} USDT",
            f"  Double-Entry Drift:        {acct.get('drift_usdt', '0')} USDT "
            f"(zero_drift={acct.get('zero_balance_drift', True)})",
            f"  Peak Margin Utilization:   {risk.get('max_observed_margin_utilization', '0.00%')} "
            f"(<= {float(risk.get('max_aggregate_margin_pct', '0.60')) * 100:.2f}% ceiling)",
            f"  Min Reserve Buffer:        {risk.get('min_observed_reserve_buffer', '100.00%')} "
            f"(>= {float(risk.get('min_reserve_buffer_pct', '0.40')) * 100:.2f}% floor)",
            sub_sep,
            "Strict Read-Only Fail-Closed Safety Invariants:",
            f"  Execution Authority:       {sec_inv.get('execution_authority', False)}",
            f"  Exchange Access:           {sec_inv.get('exchange_access', False)}",
            f"  Real External Orders:      {sec_inv.get('orders', 0)}",
            f"  API Keys Loaded:           {sec_inv.get('api_keys_loaded', 0)}",
            f"  Zero Secret Leakage:       {sec_inv.get('zero_secret_leakage', True)}",
            sub_sep,
            "Compliance Verification Matrix:",
        ]
    )

    for k, v in summary.compliance.items():
        lines.append(f"  {k:<35} {v}")

    lines.extend(
        [
            sub_sep,
            "Deterministic Artifact SHA-256 Digests:",
        ]
    )
    for art, h in summary.artifact_hashes.items():
        lines.append(f"  {art:<35} {h}")
    lines.append(sep)
    return "\n".join(lines)


def execute_phase_274_runner(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE274_OUTPUT_DIR,
    track: str = "all",
    recovery_hysteresis_ticks: int = DEFAULT_RECOVERY_HYSTERESIS_TICKS,
    force_freeze: bool = False,
    force_abort: bool = False,
    force_recover: bool = False,
    operator_id: str = "operator-lead-001",
    rationale: str = "Phase 274 manual operator intervention rehearsal",
    simulate_adverse_drift: bool = False,
    json_output: bool = False,
    verify_hash_chain: bool = False,
    verify_only: bool = False,
) -> int:
    """Execute deterministic Phase 274 canary micro-execution drill workflow."""
    if verify_only:
        hash_ok = verify_phase_274_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            registry_path=registry_path,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across all Phase 274 artifacts.\n"
        )
        return 0

    normalized_track = track
    if track in ("1", "2", "3", "4"):
        normalized_track = f"track_{track}"

    cfg = CanaryMicroExecutionDrillConfig(
        manifest_path=Path(manifest_path),
        registry_path=Path(registry_path),
        output_dir=Path(output_dir),
        target_track=normalized_track,
        recovery_hysteresis_ticks=recovery_hysteresis_ticks,
        force_freeze=force_freeze,
        force_abort=force_abort,
        force_recover=force_recover,
        operator_id=operator_id,
        override_rationale=rationale,
        simulate_adverse_drift=simulate_adverse_drift,
    )

    runner = CanaryMicroExecutionDrillRunner(cfg)

    summary, db_path, orders_path, rep_path, exec_sum_path, paper_sum_path = runner.execute_drill()

    if verify_hash_chain:
        hash_ok = verify_phase_274_hash_chain(
            output_dir=output_dir,
            manifest_path=manifest_path,
            registry_path=registry_path,
        )
        if not hash_ok:
            logger.error("Cryptographic SHA-256 DAG hash chain verification failed.")
            return 1
        logger.info("Cryptographic SHA-256 DAG hash chain verified successfully.")
        sys.stdout.write(
            "[PASS] Cryptographic SHA-256 DAG hash chain verified across all Phase 274 artifacts.\n"
        )

    if json_output:
        sys.stdout.write(json.dumps(summary.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(summary) + "\n")

    return 0 if summary.compliance.get("all_criteria_passed", True) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 274 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_274_runner(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            output_dir=args.output_dir,
            track=args.track,
            recovery_hysteresis_ticks=args.recovery_hysteresis_ticks,
            force_freeze=args.force_freeze,
            force_abort=args.force_abort,
            force_recover=args.force_recover,
            operator_id=args.operator_id,
            rationale=args.rationale,
            simulate_adverse_drift=args.simulate_adverse_drift,
            json_output=args.json,
            verify_hash_chain=args.verify_hash_chain,
            verify_only=args.verify_only,
        )
    except KeyboardInterrupt:
        logger.info("Canary micro-execution drill cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Canary micro-execution drill failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
