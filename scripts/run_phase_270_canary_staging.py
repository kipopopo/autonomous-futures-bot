"""Phase 270: Canary Deployment Dry-Run Runner & Micro-Sized Shadow Order Engine CLI.

Executes pre-live canary order generation with micro notional sizing (<= 5.00 USDT),
multi-tier emergency kill-switch verification, isolated SQLite shadow order and ledger
persistence, exact zero-drift double-entry accounting reconciliation (< 1e-15 USDT),
and strict fail-closed boundaries under Candidate Registry Manifest Version 2.
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

from autonomous_futures.paper.canary_staging import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_CANONICAL_HISTORY_DIR,
    DEFAULT_PHASE270_OUTPUT_DIR,
    CanaryExecutionSummary,
    run_canary_staging_simulation,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_270_canary_staging")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 270 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 270 Canary Deployment Dry-Run Runner & Micro Shadow Execution Harness."
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
        default=DEFAULT_PHASE270_OUTPUT_DIR,
        help="Path to output canary execution artifacts",
    )
    parser.add_argument(
        "--canonical-history-dir",
        type=Path,
        default=DEFAULT_CANONICAL_HISTORY_DIR,
        help="Path to canonical parquet history directory",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=500,
        help="Maximum synchronized bar ticks to replay (default: 500)",
    )
    parser.add_argument(
        "--trigger-kill-switch",
        action="store_true",
        help="Explicitly trigger Tier 2 emergency kill-switch and liquidate positions",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Inject synthetic accounting drift (> 1e-15 USDT) to test fail-safe Tier 2 shutdown",
    )
    parser.add_argument(
        "--simulate-spread-expansion",
        action="store_true",
        help="Inject synthetic spread expansion (> 20 bps) to test Tier 1 freeze response",
    )
    parser.add_argument(
        "--simulate-volatility-surge",
        action="store_true",
        help="Inject synthetic volatility spike (> 2.5x) to test Tier 1 freeze response",
    )
    parser.add_argument(
        "--simulate-feed-timeout",
        action="store_true",
        help="Inject synthetic feed heartbeat timeout (> 10s) to test Tier 1 freeze response",
    )
    parser.add_argument(
        "--simulate-drawdown-breach",
        action="store_true",
        help="Inject synthetic adverse price movement to trigger Tier 2 drawdown breach (>= 2%%)",
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


def format_summary_table(summary: CanaryExecutionSummary) -> str:
    """Format human-readable execution summary table."""
    sep = "=" * 80
    sub_sep = "-" * 80
    lines = [
        sep,
        "PHASE 270: CANARY DEPLOYMENT DRY-RUN & MICRO SHADOW ORDER EXECUTION",
        sep,
        f"Circuit Breaker State:       {summary.circuit_state}",
        f"Starting Equity:             {summary.starting_capital_usdt:.4f} USDT",
        f"Final Cash Balance:          {summary.final_cash_usdt:.4f} USDT",
        f"Final Portfolio Equity:      {summary.final_equity_usdt:.4f} USDT",
        f"Realized PnL:                {summary.realized_pnl_usdt:+.4f} USDT",
        f"Total Simulated Fees:        {summary.total_fees_usdt:.4f} USDT",
        f"Total Simulated Slippage:    {summary.total_slippage_usdt:.4f} USDT",
        f"Double-Entry Drift:          {summary.drift_usdt} USDT "
        f"(zero_drift={summary.zero_balance_drift})",
        f"Max Margin Utilization:      {summary.max_observed_margin_utilization * 100:.2f}% "
        "(<= 60.00% ceiling)",
        f"Min Reserve Buffer:          {summary.min_observed_reserve_buffer * 100:.2f}% "
        "(>= 40.00% floor)",
        f"Margin Guardrails Passed:    {summary.margin_guardrails_compliant}",
        f"Single-Position Invariant:   {summary.single_position_invariant}",
        f"Shadow Orders Generated:     {summary.orders_count}",
        f"Shadow Fills Executed:       {summary.fills_count}",
        f"Orders Cancelled:            {summary.cancelled_orders_count}",
        f"Positions Liquidated:        {summary.liquidations_count}",
        f"Emergency Events Recorded:   {len(summary.kill_switch_events)}",
        sub_sep,
        "Active Canary Candidates:",
    ]
    for sym, cand in summary.candidates.items():
        lines.append(
            f"  {sym:<8} id={cand['candidate_id']:<24} family={cand['family']:<24}\n"
            f"           alloc_cap={cand['allocated_margin_usdt']} USDT "
            f"max_micro={cand['max_micro_notional_usdt']} USDT "
            f"status={cand['position_status']}"
        )

    if summary.kill_switch_events:
        lines.append(sub_sep)
        lines.append("Kill-Switch & De-escalation Activations:")
        for ev in summary.kill_switch_events:
            lines.append(
                f"  Tier {ev['tier']}: {ev['trigger_type']} - {ev['trigger_reason']} "
                f"(cancelled={ev['orders_cancelled']}, liquidated={ev['positions_liquidated']})"
            )

    lines.append(sep)
    return "\n".join(lines)


def run_phase_270_canary_staging(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE270_OUTPUT_DIR,
    canonical_history_dir: Path | str = DEFAULT_CANONICAL_HISTORY_DIR,
    max_ticks: int = 500,
    trigger_kill_switch: bool = False,
    simulate_adverse_drift: bool = False,
    simulate_spread_expansion: bool = False,
    simulate_volatility_surge: bool = False,
    simulate_feed_timeout: bool = False,
    simulate_drawdown_breach: bool = False,
    json_output: bool = False,
) -> int:
    """Execute deterministic Phase 270 canary staging workflow."""
    summary, ledger_db, orders_db = run_canary_staging_simulation(
        manifest_path=manifest_path,
        registry_path=registry_path,
        output_dir=output_dir,
        canonical_history_dir=canonical_history_dir,
        max_ticks=max_ticks,
        trigger_kill_switch=trigger_kill_switch,
        simulate_adverse_drift=simulate_adverse_drift,
        simulate_spread_expansion=simulate_spread_expansion,
        simulate_volatility_surge=simulate_volatility_surge,
        simulate_feed_timeout=simulate_feed_timeout,
        simulate_drawdown_breach=simulate_drawdown_breach,
    )

    if json_output:
        sys.stdout.write(json.dumps(summary.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(summary) + "\n")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for Phase 270 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return run_phase_270_canary_staging(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            output_dir=args.output_dir,
            canonical_history_dir=args.canonical_history_dir,
            max_ticks=args.max_ticks,
            trigger_kill_switch=args.trigger_kill_switch,
            simulate_adverse_drift=args.simulate_adverse_drift,
            simulate_spread_expansion=args.simulate_spread_expansion,
            simulate_volatility_surge=args.simulate_volatility_surge,
            simulate_feed_timeout=args.simulate_feed_timeout,
            simulate_drawdown_breach=args.simulate_drawdown_breach,
            json_output=args.json,
        )
    except KeyboardInterrupt:
        logger.info("Canary staging execution cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Canary staging execution failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
