"""Phase 272: Continuous Canary Heartbeat Daemon & Real-Time Alert Dispatcher CLI.

Supervises public market data streams, monitors RFC 6455 round-trip ping/pong latency,
evaluates Binance Futures server time clock drift, tracks inter-arrival message jitter,
and manages a multi-tiered real-time alerting dispatcher with circuit-breaker fail-closed
containment under Candidate Registry Manifest Version 2 and Canary Staging Manifest, while
strictly enforcing zero-drift double-entry accounting.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

# Ensure src/ and repo root are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.heartbeat_daemon import (  # noqa: E402
    DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    DEFAULT_PHASE272_OUTPUT_DIR,
    DEFAULT_REST_URL,
    DEFAULT_WS_URL,
    CanaryHeartbeatDaemonConfig,
    CanaryHeartbeatDaemonRunner,
    CanaryHeartbeatSummary,
)
from autonomous_futures.paper.candidate_registry import (  # noqa: E402
    DEFAULT_CANDIDATE_REGISTRY_PATH,
)

logger = logging.getLogger("run_phase_272_heartbeat_daemon")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for Phase 272 runner."""
    parser = argparse.ArgumentParser(
        description="Phase 272 Continuous Canary Heartbeat Daemon & Real-Time Alert Dispatcher CLI."
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
        default=DEFAULT_PHASE272_OUTPUT_DIR,
        help="Path to output canary telemetry artifacts",
    )
    parser.add_argument(
        "--daemon-seconds",
        type=float,
        default=30.0,
        help="Bounded daemon execution duration in seconds (default: 30.0)",
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
        "--simulate-latency-spike",
        action="store_true",
        help="Inject synthetic latency spike (> 300ms) to trigger WARNING alert",
    )
    parser.add_argument(
        "--simulate-feed-drop",
        action="store_true",
        help="Inject synthetic feed drop / connection timeout (>= 10.0s) to trigger CRITICAL alert",
    )
    parser.add_argument(
        "--simulate-clock-drift-breach",
        action="store_true",
        help="Inject synthetic clock drift violation (> 1000ms) to trigger CRITICAL alert",
    )
    parser.add_argument(
        "--simulate-adverse-drift",
        action="store_true",
        help="Inject synthetic accounting drift (> 1e-15 USDT) to trigger EMERGENCY alert",
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


def format_summary_table(summary: CanaryHeartbeatSummary) -> str:
    """Format human-readable execution summary table."""
    sep = "=" * 80
    sub_sep = "-" * 80
    lines = [
        sep,
        "PHASE 272: CONTINUOUS CANARY HEARTBEAT DAEMON & MULTI-TIER HEALTH MONITOR",
        sep,
        f"Execution Mode:              {summary.execution_mode.upper()}",
        f"Timestamp UTC:               {summary.timestamp_utc}",
        f"Daemon Duration:             {summary.duration_seconds:.2f}s",
        f"Staged Manifest Hash:        {summary.staged_manifest_hash[:16]}...",
        f"Circuit Breaker State:       {summary.circuit_breaker_state}",
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

    lines.extend(
        [
            sub_sep,
            "Multi-Tiered Alerting Dispatcher Summary:",
            f"  Total Dispatched Alerts:   {summary.alerts_summary['total_alerts']}",
        ]
    )
    for sev, cnt in summary.alerts_summary["counts_by_severity"].items():
        lines.append(f"    {sev:<12}            {cnt}")

    if summary.circuit_breaker_transitions:
        lines.extend(
            [
                sub_sep,
                "Circuit Breaker State Transitions:",
            ]
        )
        for t in summary.circuit_breaker_transitions:
            lines.append(f"  {t['previous_state']} -> {t['new_state']} (reason: {t['reason']})")

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


def execute_phase_272_runner(
    manifest_path: Path | str = DEFAULT_CANARY_STAGING_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_CANDIDATE_REGISTRY_PATH,
    output_dir: Path | str = DEFAULT_PHASE272_OUTPUT_DIR,
    daemon_seconds: float = 30.0,
    max_heartbeats: int = 10,
    heartbeat_interval_seconds: float = 3.0,
    offline_replay: bool = False,
    simulate_latency_spike: bool = False,
    simulate_feed_drop: bool = False,
    simulate_clock_drift_breach: bool = False,
    simulate_adverse_drift: bool = False,
    ws_url: str = DEFAULT_WS_URL,
    rest_url: str = DEFAULT_REST_URL,
    json_output: bool = False,
) -> int:
    """Execute deterministic Phase 272 canary heartbeat daemon workflow."""
    cfg = CanaryHeartbeatDaemonConfig(
        manifest_path=Path(manifest_path),
        registry_path=Path(registry_path),
        output_dir=Path(output_dir),
        daemon_seconds=daemon_seconds,
        max_heartbeats=max_heartbeats,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        offline_replay=offline_replay,
        simulate_latency_spike=simulate_latency_spike,
        simulate_feed_drop=simulate_feed_drop,
        simulate_clock_drift_breach=simulate_clock_drift_breach,
        simulate_adverse_drift=simulate_adverse_drift,
        ws_url=ws_url,
        rest_url=rest_url,
    )

    runner = CanaryHeartbeatDaemonRunner(cfg)

    def _signal_handler(sig: int, frame: Any) -> None:
        logger.info("Termination signal %d received; requesting graceful stop...", sig)
        runner.request_stop()

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _signal_handler)
    except ValueError, OSError:
        pass

    summary, db_path, alerts_path, rep_path, hb_sum_path, paper_sum_path = runner.run()

    if json_output:
        sys.stdout.write(json.dumps(summary.model_dump(mode="json"), indent=2) + "\n")
    else:
        sys.stdout.write(format_summary_table(summary) + "\n")

    return 0 if summary.compliance.get("all_criteria_passed", True) else 1


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point for Phase 272 runner script."""
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        return execute_phase_272_runner(
            manifest_path=args.manifest_path,
            registry_path=args.registry_path,
            output_dir=args.output_dir,
            daemon_seconds=args.daemon_seconds,
            max_heartbeats=args.max_heartbeats,
            heartbeat_interval_seconds=args.heartbeat_interval,
            offline_replay=args.offline_replay,
            simulate_latency_spike=args.simulate_latency_spike,
            simulate_feed_drop=args.simulate_feed_drop,
            simulate_clock_drift_breach=args.simulate_clock_drift_breach,
            simulate_adverse_drift=args.simulate_adverse_drift,
            ws_url=args.ws_url,
            rest_url=args.rest_url,
            json_output=args.json,
        )
    except KeyboardInterrupt:
        logger.info("Canary heartbeat daemon cancelled by operator")
        return 1
    except Exception as exc:
        logger.error("Canary heartbeat daemon failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
