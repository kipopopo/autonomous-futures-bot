"""Phase 271: Canary Public Network Telemetry Probe & Handshake Runner CLI.

Evaluates public market data stream latency, connection handshake duration, round-trip
ping/pong heartbeat latency, and Binance Futures server time synchronization drift across
staged canary assets (BTCUSDT, ETHUSDT, SOLUSDT) under Candidate Registry Manifest Version 2
and Canary Staging Manifest, while strictly enforcing read-only fail-closed safety and
exact zero-drift accounting.
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

from autonomous_futures.feed.canary_probe import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_PHASE271_OUTPUT_DIR,
    DEFAULT_REST_URL,
    DEFAULT_WS_URL,
    CanaryProbeSummary,
    run_canary_network_probe,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_271_network_probe")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 271 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 271 Canary Public Network Telemetry Probe & Handshake Runner CLI."
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
        default=DEFAULT_PHASE271_OUTPUT_DIR,
        help="Path to output canary telemetry artifacts",
    )
    parser.add_argument(
        "--probe-seconds",
        type=float,
        default=30.0,
        help="Bounded probe execution duration in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--max-heartbeats",
        type=int,
        default=10,
        help="Maximum RFC 6455 Ping/Pong heartbeats to profile (default: 10)",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=3.0,
        help="Interval between heartbeats in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--offline-replay",
        action="store_true",
        help="Force deterministic offline replay without connecting to external exchange network",
    )
    parser.add_argument(
        "--simulate-clock-drift",
        action="store_true",
        help="Inject synthetic server time drift (> 1000ms) to test fail-safe threshold trip",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Inject synthetic accounting drift (> 1e-15 USDT) to test fail-safe shutdown",
    )
    parser.add_argument(
        "--simulate-network-timeout",
        action="store_true",
        help="Inject simulated network timeout to test graceful offline fallback",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default=DEFAULT_WS_URL,
        help="Binance Futures WebSocket base URL",
    )
    parser.add_argument(
        "--rest-url",
        type=str,
        default=DEFAULT_REST_URL,
        help="Binance Futures REST API base URL",
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


def format_summary_table(summary: CanaryProbeSummary) -> str:
    """Format human-readable execution summary table."""
    sep = "=" * 80
    sub_sep = "-" * 80
    lines = [
        sep,
        "PHASE 271: CANARY PUBLIC NETWORK TELEMETRY PROBE & HANDSHAKE PROFILER",
        sep,
        f"Execution Mode:              {summary.execution_mode.upper()}",
        f"Timestamp UTC:               {summary.timestamp_utc}",
        f"Probe Duration:              {summary.duration_seconds:.2f}s",
        f"Staged Manifest Hash:        {summary.staged_manifest_hash[:16]}...",
        sub_sep,
        "WebSocket Connection Profile:",
        f"  Endpoint:                  {summary.connection_profile['endpoint']}",
        f"  Handshake Time:            {summary.connection_profile['handshake_time_ms']:.2f} ms",
        f"  Connection Status:         {summary.connection_profile['status']}",
        f"  Lifecycle Events Logged:   {summary.connection_profile['events_count']}",
        sub_sep,
        "Server Time Synchronization (|drift| <= 1000ms):",
        f"  Mean Drift:                {summary.clock_sync_profile['mean_drift_ms']:.2f} ms",
        f"  Max Drift:                 {summary.clock_sync_profile['max_drift_ms']:.2f} ms",
        f"  Threshold:                 {summary.clock_sync_profile['threshold_ms']:.1f} ms",
        f"  Drift Compliant:           {summary.clock_sync_profile['within_threshold']}",
        sub_sep,
        "Heartbeat Latency Profile (RFC 6455 Ping/Pong):",
        f"  Heartbeats Completed:      {summary.heartbeat_profile['count']}",
        f"  Min RTT:                   {summary.heartbeat_profile['min_rtt_ms']:.2f} ms",
        f"  Mean RTT:                  {summary.heartbeat_profile['mean_rtt_ms']:.2f} ms",
        f"  p50 RTT:                   {summary.heartbeat_profile['p50_rtt_ms']:.2f} ms",
        f"  p95 RTT:                   {summary.heartbeat_profile['p95_rtt_ms']:.2f} ms",
        f"  p99 RTT:                   {summary.heartbeat_profile['p99_rtt_ms']:.2f} ms",
        f"  Max RTT:                   {summary.heartbeat_profile['max_rtt_ms']:.2f} ms",
        sub_sep,
        "Public Stream Telemetry (Multiplexed Ingress):",
        f"  Total Messages Received:   {summary.stream_telemetry['total_messages_received']}",
        f"  Throughput:                {summary.stream_telemetry['messages_per_second']:.1f} msg/s",
    ]

    for sym, st in summary.stream_telemetry.get("symbol_stats", {}).items():
        lines.append(
            f"  {sym:<7} msgs={st['messages']:<5} "
            f"p50={st['p50_latency_ms']:.1f}ms p95={st['p95_latency_ms']:.1f}ms "
            f"int={st['mean_interval_ms']:.1f}ms jit={st['mean_jitter_ms']:.1f}ms"
        )

    acct = summary.portfolio_accounting
    res_buf_pct = float(acct["min_observed_reserve_buffer"]) * 100
    lines.extend(
        [
            sub_sep,
            "Exact Double-Entry Accounting & Margin Guardrails:",
            f"  Starting Equity:           {acct['starting_equity_usdt']} USDT",
            f"  Final Cash Balance:        {acct['final_cash_usdt']} USDT",
            f"  Final Portfolio Equity:    {acct['final_equity_usdt']} USDT",
            f"  Realized PnL:              {acct['realized_pnl_usdt']} USDT",
            f"  Double-Entry Drift:        {acct['drift_usdt']} USDT "
            f"(zero_drift={acct['zero_balance_drift']})",
            f"  Margin Utilization:        {acct['max_observed_margin_utilization']}% (0% ceiling)",
            f"  Reserve Buffer:            {res_buf_pct:.2f}% (100% floor)",
            f"  Margin Guardrails Passed:  {acct['margin_guardrails_compliant']}",
            f"  Single-Position Invariant: {acct['single_position_invariant']}",
            sub_sep,
            "Strict Read-Only Fail-Closed Safety Invariants:",
            f"  Execution Authority:       {summary.safety_invariants['execution_authority']}",
            f"  Exchange Access:           {summary.safety_invariants['exchange_access']}",
            f"  Orders Placed:             {summary.safety_invariants['orders']}",
            f"  API Keys Loaded:           {summary.safety_invariants['api_keys_loaded']}",
            f"  Zero Secret Leakage:       {summary.safety_invariants['zero_secret_leakage']}",
            sub_sep,
            "Active Staged Canary Candidates:",
        ]
    )

    for sym, cand in summary.candidates.items():
        lines.append(
            f"  {sym:<8} id={cand['candidate_id']:<24} family={cand['family']:<24} "
            f"tf={cand['timeframe']:<4} state={cand['staging_promotion_state']}"
        )

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


def run_phase_271_network_probe(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE271_OUTPUT_DIR,
    probe_seconds: float = 30.0,
    max_heartbeats: int = 10,
    heartbeat_interval_seconds: float = 3.0,
    offline_replay: bool = False,
    simulate_clock_drift: bool = False,
    simulate_adverse_drift: bool = False,
    simulate_network_timeout: bool = False,
    ws_url: str = DEFAULT_WS_URL,
    rest_url: str = DEFAULT_REST_URL,
    json_output: bool = False,
) -> int:
    """Execute deterministic Phase 271 canary network probe workflow."""
    summary, db_path, report_path, net_sum_path, paper_sum_path = run_canary_network_probe(
        manifest_path=manifest_path,
        registry_path=registry_path,
        output_dir=output_dir,
        probe_seconds=probe_seconds,
        max_heartbeats=max_heartbeats,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        offline_replay=offline_replay,
        simulate_clock_drift=simulate_clock_drift,
        simulate_adverse_drift=simulate_adverse_drift,
        simulate_network_timeout=simulate_network_timeout,
        ws_url=ws_url,
        rest_url=rest_url,
    )

    if json_output:
        sys.stdout.write(json.dumps(summary.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(summary) + "\n")

    return 0 if summary.compliance.get("all_criteria_passed", True) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 271 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return run_phase_271_network_probe(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            output_dir=args.output_dir,
            probe_seconds=args.probe_seconds,
            max_heartbeats=args.max_heartbeats,
            heartbeat_interval_seconds=args.heartbeat_interval,
            offline_replay=args.offline_replay,
            simulate_clock_drift=args.simulate_clock_drift,
            simulate_adverse_drift=args.simulate_adverse_drift,
            simulate_network_timeout=args.simulate_network_timeout,
            ws_url=args.ws_url,
            rest_url=args.rest_url,
            json_output=args.json,
        )
    except KeyboardInterrupt:
        logger.info("Canary network probe cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Canary network probe failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
