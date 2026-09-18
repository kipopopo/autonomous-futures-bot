"""Phase 273: Automated Canary Circuit Breaker Recovery State Machine & Incident Response Drill CLI.

Executes deterministic multi-track incident response drills under Candidate Registry Manifest
Version 2 to validate automated recovery, dynamic soft-freeze de-escalation, tamper-evident
post-mortem generation, and zero-drift balance integrity under adverse stream conditions.
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

from autonomous_futures.feed.circuit_breaker_drill import (  # noqa: E402
    DEFAULT_PHASE273_OUTPUT_DIR,
    DEFAULT_RECOVERY_HYSTERESIS_TICKS,
    CanaryCircuitBreakerDrillConfig,
    CanaryCircuitBreakerDrillRunner,
    Phase273DrillSummary,
)
from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_273_circuit_breaker_drill")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 273 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 273 Canary Circuit Breaker Recovery & Incident Response Drill CLI."
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
        default=DEFAULT_PHASE273_OUTPUT_DIR,
        help="Path to output canary incident telemetry artifacts",
    )
    parser.add_argument(
        "--track",
        type=str,
        default="all",
        choices=["1", "2", "3", "4", "track_1", "track_2", "track_3", "track_4", "all"],
        help="Specific incident track to execute (default: all)",
    )
    parser.add_argument(
        "--recovery-hysteresis-ticks",
        type=int,
        default=DEFAULT_RECOVERY_HYSTERESIS_TICKS,
        help="Consecutive healthy stream ticks required for automated recovery (default: 5)",
    )
    parser.add_argument(
        "--force-freeze",
        action="store_true",
        help="Manual operator override: trigger Tier 1 Soft-Freeze",
    )
    parser.add_argument(
        "--force-abort",
        action="store_true",
        help="Manual operator override: trigger Tier 2 Hard-Abort",
    )
    parser.add_argument(
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
        default="Phase 273 manual operator intervention verification drill",
        help="Audit rationale for manual operator override",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Inject synthetic accounting drift (> 1e-15 USDT) to trigger catastrophic failure",
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


def format_summary_table(summary: Phase273DrillSummary) -> str:
    """Format human-readable execution summary table."""
    sep = "=" * 80
    sub_sep = "-" * 80
    cb_stats = summary.circuit_breaker_stats
    hard_aborts = cb_stats.get("hard_aborts_count", 0)
    manual_overrides = cb_stats.get("manual_overrides_count", 0)
    lines = [
        sep,
        "PHASE 273: CANARY CIRCUIT BREAKER RECOVERY & INCIDENT RESPONSE DRILL",
        sep,
        f"Timestamp UTC:               {summary.timestamp_utc}",
        f"Staged Manifest Hash:        {summary.staged_manifest_hash[:16]}...",
        f"Manifest Version:            {summary.manifest_version}",
        f"Tracks Executed:             {', '.join(summary.tracks_executed)}",
        sub_sep,
        "Circuit Breaker State Machine & Transition Statistics:",
        f"  Total State Transitions:   {cb_stats.get('total_transitions', 0)}",
        f"  Automated Recoveries:      {cb_stats.get('auto_recoveries_count', 0)}",
        f"  Outage Escalations:        {cb_stats.get('escalations_count', 0)}",
        f"  Hard Aborts (Fail-Closed): {hard_aborts}",
        f"  Manual Operator Overrides: {manual_overrides}",
        sub_sep,
        "Multi-Scenario Incident Simulation Tracks:",
    ]

    for tid, tinfo in summary.tracks_summary.items():
        name = tinfo.get("name", tid)
        status = tinfo.get("status", "UNKNOWN")
        transitions = tinfo.get("transitions_count", 0)
        rec_ms = tinfo.get("recovery_duration_ms", 0.0)
        esc_ms = tinfo.get("escalation_latency_ms", 0.0)
        lines.append(
            f"  [{tid:<7}] {name:<45} -> {status:<24} "
            f"(trans={transitions}, rec={rec_ms:.1f}ms, esc={esc_ms:.1f}ms)"
        )

    acct = summary.portfolio_accounting
    sec_inv = summary.safety_invariants
    max_util = acct.get("max_observed_margin_utilization", "0")
    zero_drift = acct.get("zero_balance_drift", True)
    margin_ok = acct.get("margin_guardrails_compliant", True)
    auth = sec_inv.get("execution_authority", False)
    exch = sec_inv.get("exchange_access", False)
    leakage = sec_inv.get("zero_secret_leakage", True)

    lines.extend(
        [
            sub_sep,
            "Exact Double-Entry Accounting & Margin Guardrails:",
            f"  Starting Equity:           {acct.get('starting_equity_usdt', '100.00')} USDT",
            f"  Final Cash Balance:        {acct.get('final_cash_usdt', '100.00')} USDT",
            f"  Realized PnL:              {acct.get('realized_pnl_usdt', '0.00')} USDT",
            f"  Double-Entry Drift:        {acct.get('drift_usdt', '0')} USDT "
            f"(zero_drift={zero_drift})",
            f"  Margin Utilization:        {max_util}% (0% ceiling)",
            "  Reserve Buffer:            100.00% (100% floor)",
            f"  Margin Compliant:          {margin_ok}",
            sub_sep,
            "Strict Read-Only Fail-Closed Safety Invariants:",
            f"  Execution Authority:       {auth}",
            f"  Exchange Access:           {exch}",
            f"  Orders Placed:             {sec_inv.get('orders', 0)}",
            f"  API Keys Loaded:           {sec_inv.get('api_keys_loaded', 0)}",
            f"  Zero Secret Leakage:       {leakage}",
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


def execute_phase_273_runner(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE273_OUTPUT_DIR,
    track: str = "all",
    recovery_hysteresis_ticks: int = DEFAULT_RECOVERY_HYSTERESIS_TICKS,
    force_freeze: bool = False,
    force_abort: bool = False,
    force_recover: bool = False,
    operator_id: str = "operator-lead-001",
    rationale: str = "Phase 273 manual operator intervention verification drill",
    simulate_adverse_drift: bool = False,
    json_output: bool = False,
) -> int:
    """Execute deterministic Phase 273 circuit breaker drill workflow."""
    # Normalize track string (e.g. "1" -> "track_1")
    normalized_track = track
    if track in ("1", "2", "3", "4"):
        normalized_track = f"track_{track}"

    cfg = CanaryCircuitBreakerDrillConfig(
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

    runner = CanaryCircuitBreakerDrillRunner(cfg)

    summary, db_path, incidents_path, rep_path, cb_sum_path, paper_sum_path = runner.execute_drill()

    if json_output:
        sys.stdout.write(json.dumps(summary.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(summary) + "\n")

    return 0 if summary.compliance.get("all_criteria_passed", True) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 273 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_273_runner(
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
        )
    except KeyboardInterrupt:
        logger.info("Circuit breaker incident drill cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Circuit breaker incident drill failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
