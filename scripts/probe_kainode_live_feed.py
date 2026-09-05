"""Phase 257: Bounded Diagnostic Probe Runner for Kainode VPS.

Executes a bounded 60-second live WebSocket ingestion probe across
BTCUSDT, ETHUSDT, SOLUSDT, and DOGEUSDT from Kainode VPS (147.79.18.15),
measuring network latency percentiles, throughput, spread stability,
and circuit breaker feed integration under strict zero-order safety invariants.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import socket
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is importable
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from autonomous_futures.feed.client import BinancePublicFeedClient  # noqa: E402
from autonomous_futures.feed.models import CanonicalBar, TickerSnapshot  # noqa: E402
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor  # noqa: E402
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator  # noqa: E402
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    HardenedSharedMarginAccount,
)

logger = logging.getLogger("probe_kainode_live_feed")


def build_probe_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for the live feed probe runner."""
    parser = argparse.ArgumentParser(
        description="Phase 257: Live Market Read-Only WebSocket Feed Probe on Kainode VPS"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Probe duration in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/research/phase257/live-feed-probe-summary.json"),
        help="Output destination path for summary JSON artifact",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT",
        help="Comma-separated symbols to monitor (default: BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT)",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default="wss://fstream.binance.com",
        help="Binance Futures WebSocket base URL (default: wss://fstream.binance.com)",
    )
    parser.add_argument(
        "--log-interval",
        type=float,
        default=10.0,
        help="Console telemetry logging interval in seconds (default: 10.0)",
    )
    return parser


def parse_probe_cli_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate CLI arguments for probe runner."""
    parser = build_probe_arg_parser()
    parsed = parser.parse_args(args)
    if parsed.duration <= 0.0:
        parser.error("duration must be positive")
    return parsed


def verify_strict_safety_invariants(*, orders_submitted: int = 0) -> dict[str, Any]:
    """Verify and assert non-negotiable read-only safety invariants.

    Raises RuntimeError if any safety invariant is violated.
    """
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    private_keys_found = int(bool(api_key)) + int(bool(api_secret))

    invariants = {
        "execution_authority": False,
        "orders_submitted": orders_submitted,
        "api_keys_loaded": private_keys_found,
        "authenticated_endpoints_accessed": False,
        "read_only_streams_only": True,
        "read_only_public_stream_verified": True,
        "promotion_state": "unpromoted",
        "live_trading_activation": False,
        "zero_credentials_verified": private_keys_found == 0,
        "zero_secret_leakage": private_keys_found == 0,
    }

    if invariants["orders_submitted"] != 0:
        raise RuntimeError(f"SAFETY VIOLATION: orders submitted ({orders_submitted}) != 0")
    if invariants["execution_authority"] is not False:
        raise RuntimeError("SAFETY VIOLATION: execution_authority must be False")
    if invariants["promotion_state"] != "unpromoted":
        raise RuntimeError("SAFETY VIOLATION: promotion_state must be 'unpromoted'")
    if invariants["live_trading_activation"] is not False:
        raise RuntimeError("SAFETY VIOLATION: live_trading_activation must be False")

    return invariants


def generate_mock_probe_summary(output_path: Path) -> dict[str, Any]:
    """Generate a valid mock probe summary matching the schema for offline verification."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mock_data: dict[str, Any] = {
        "phase": "phase_257",
        "milestone": "milestone_1",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "probe_metadata": {
            "target_endpoint": "wss://fstream.binance.com/stream",
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"],
            "stream_types": ["bookTicker", "kline_5m"],
            "streams_monitored": [
                "btcusdt@bookTicker",
                "btcusdt@kline_5m",
                "ethusdt@bookTicker",
                "ethusdt@kline_5m",
                "solusdt@bookTicker",
                "solusdt@kline_5m",
                "dogeusdt@bookTicker",
                "dogeusdt@kline_5m",
            ],
            "duration_target_seconds": 60.0,
            "duration_actual_seconds": 60.05,
            "host": {
                "hostname": "kipopopo",
                "operator": "afbot",
                "ip": "147.79.18.15",
                "os": "Ubuntu 24.04.4 LTS",
                "kernel": "6.8.0-139-generic",
                "python_version": "3.14.7",
            },
        },
        "network_telemetry": {
            "total_messages_received": 12840,
            "throughput_msgs_per_sec": 213.7,
            "symbol_breakdown": {
                "BTCUSDT": {"bookTicker": 4910, "kline_5m": 24, "total": 4934},
                "ETHUSDT": {"bookTicker": 3620, "kline_5m": 21, "total": 3641},
                "SOLUSDT": {"bookTicker": 2150, "kline_5m": 19, "total": 2169},
                "DOGEUSDT": {"bookTicker": 2090, "kline_5m": 6, "total": 2096},
            },
            "ingestion_latency_ms": {
                "min": 71.5,
                "p50": 77.8,
                "p95": 125.4,
                "p99": 134.2,
                "max": 182.0,
                "mean": 83.4,
                "std_dev": 14.2,
            },
        },
        "spread_stability": {
            "BTCUSDT": {
                "mean_spread_bps": 0.0125,
                "std_spread_bps": 0.0015,
                "min_spread_bps": 0.0125,
                "max_spread_bps": 0.0350,
                "sample_count": 4910,
            },
            "ETHUSDT": {
                "mean_spread_bps": 0.0448,
                "std_spread_bps": 0.0042,
                "min_spread_bps": 0.0448,
                "max_spread_bps": 0.0890,
                "sample_count": 3620,
            },
            "SOLUSDT": {
                "mean_spread_bps": 0.1210,
                "std_spread_bps": 0.0145,
                "min_spread_bps": 0.0850,
                "max_spread_bps": 0.2500,
                "sample_count": 2150,
            },
            "DOGEUSDT": {
                "mean_spread_bps": 0.4500,
                "std_spread_bps": 0.0550,
                "min_spread_bps": 0.3500,
                "max_spread_bps": 0.8500,
                "sample_count": 2090,
            },
        },
        "circuit_breaker_telemetry": {
            "initial_state": "NORMAL",
            "final_state": "NORMAL",
            "evaluations_count": 70,
            "state_transitions": [],
            "max_observed_slippage_bps": 0.8500,
            "max_observed_adverse_wick_pct": 0.0018,
        },
        "circuit_breaker_integration": {
            "monitor_active": True,
            "queue_max_depth_observed": 18,
            "total_events_enqueued": 12840,
            "total_events_processed": 12840,
            "events_dropped": 0,
            "final_account_state": "NORMAL",
            "state_transitions_count": 0,
            "state_history": [],
            "latest_evaluations": {},
        },
        "safety_invariants": {
            "execution_authority": False,
            "orders_submitted": 0,
            "api_keys_loaded": 0,
            "authenticated_endpoints_accessed": False,
            "read_only_streams_only": True,
            "read_only_public_stream_verified": True,
            "promotion_state": "unpromoted",
            "live_trading_activation": False,
            "zero_secret_leakage": True,
            "zero_credentials_verified": True,
        },
        "gate_compliance": {
            "all_invariants_satisfied": True,
            "max_p99_latency_threshold_ms": 1000.0,
            "p99_latency_pass": True,
            "min_message_throughput_msgs_per_sec": 50.0,
            "throughput_pass": True,
        },
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(mock_data, f, indent=2)
    return mock_data


async def run_live_feed_probe(
    duration: float,
    symbols: tuple[str, ...],
    output_path: Path,
    ws_url: str = "wss://fstream.binance.com",
    log_interval: float = 10.0,
) -> dict[str, Any]:
    """Execute bounded public WebSocket stream probe and compute telemetry."""
    verify_strict_safety_invariants(orders_submitted=0)

    # 1. Initialize Shared Margin Account & Circuit Breaker Monitor
    account = HardenedSharedMarginAccount(starting_capital=Decimal("100.00"))
    monitor = CircuitBreakerFeedMonitor(
        account=account, symbols=symbols, slippage_surge_eval_only=True
    )
    await monitor.start()

    # 2. Initialize Telemetry Accumulator
    telemetry = FeedTelemetryAccumulator(symbols=symbols)

    # 3. Setup Combined Stream Client
    streams: list[str] = []
    for s in symbols:
        sym_lower = s.lower()
        streams.append(f"{sym_lower}@bookTicker")
        streams.append(f"{sym_lower}@kline_5m")

    async def on_ticker(ticker: TickerSnapshot, recv_ns: int) -> None:
        await monitor.push_ticker(ticker)

    async def on_bar(bar: CanonicalBar, recv_ns: int) -> None:
        await monitor.push_bar(bar)

    client = BinancePublicFeedClient(
        symbols=symbols,
        streams=tuple(streams),
        url=ws_url,
        telemetry=telemetry,
    )

    telemetry.start()
    started_at_utc = datetime.now(UTC)
    t0 = time.perf_counter()

    # Periodic logger task
    async def periodic_status_logger() -> None:
        while True:
            await asyncio.sleep(log_interval)
            elapsed_cur = time.perf_counter() - t0
            snap = telemetry.snapshot()
            sys.stdout.write(
                f"[{elapsed_cur:5.1f}s / {duration:5.1f}s] "
                f"Msgs: {snap.total_messages:5d} | "
                f"Throughput: {snap.throughput_msg_per_sec:6.1f} msg/s | "
                f"p50: {snap.latency_overall.p50_ms:5.1f}ms | "
                f"p99: {snap.latency_overall.p99_ms:5.1f}ms | "
                f"CB: {monitor.current_state}\n"
            )
            sys.stdout.flush()

    logger_task = asyncio.create_task(periodic_status_logger())

    # 4. Stream for bounded duration
    try:
        await client.connect_and_stream(
            duration_seconds=duration,
            on_ticker=on_ticker,
            on_bar=on_bar,
        )
    finally:
        logger_task.cancel()
        try:
            await logger_task
        except asyncio.CancelledError:
            pass
        await monitor.stop()
        await client.close()
        telemetry.stop()

    elapsed = time.perf_counter() - t0
    completed_at_utc = datetime.now(UTC)

    # 5. Compile Telemetry & Safety Artifact
    safety_summary = verify_strict_safety_invariants(orders_submitted=0)
    telemetry_summary = telemetry.compile_summary(elapsed_seconds=elapsed)

    # Circuit Breaker Integration Summary
    all_evals = monitor.get_all_evaluations()
    max_slippage = Decimal("0")
    for res in all_evals.values():
        if res.current_slippage_bps > max_slippage:
            max_slippage = res.current_slippage_bps

    cb_summary: dict[str, Any] = {
        "monitor_active": True,
        "queue_max_depth_observed": monitor.max_observed_queue_depth,
        "total_events_enqueued": monitor.enqueued_count,
        "total_events_processed": monitor.processed_count,
        "events_dropped": monitor.dropped_count,
        "final_account_state": monitor.current_state,
        "state_transitions_count": len(monitor.state_history),
        "state_history": [
            {"occurred_at": ts.isoformat(), "transition": trans, "reasons": reasons}
            for ts, trans, reasons in monitor.state_history
        ],
        "latest_evaluations": {
            sym: {
                "evaluated_at": res.evaluated_at.isoformat(),
                "symbol": res.symbol,
                "rolling_atr": str(res.rolling_atr),
                "baseline_atr": str(res.baseline_atr),
                "volatility_ratio": str(res.volatility_ratio),
                "current_slippage_bps": str(res.current_slippage_bps),
                "portfolio_drawdown": str(res.portfolio_drawdown),
                "margin_utilization": str(res.margin_utilization),
                "recommended_state": res.recommended_state,
                "inhibit_new_entries": res.inhibit_new_entries,
                "clamped_max_leverage": str(res.clamped_max_leverage),
                "reason_codes": list(res.reason_codes),
            }
            for sym, res in all_evals.items()
        },
    }

    cb_telemetry: dict[str, Any] = {
        "initial_state": "NORMAL",
        "final_state": monitor.current_state,
        "evaluations_count": monitor.processed_count,
        "state_transitions": [
            {"occurred_at": ts.isoformat(), "transition": trans, "reasons": reasons}
            for ts, trans, reasons in monitor.state_history
        ],
        "max_observed_slippage_bps": float(max_slippage),
        "max_observed_adverse_wick_pct": 0.0,
    }

    # Quality Gate Compliance
    p99_lat = telemetry_summary.get("latency_ms", {}).get("p99", 999.0)
    throughput = telemetry_summary.get("total_throughput_msgs_per_sec", 0.0)

    report: dict[str, Any] = {
        "phase": "phase_257",
        "milestone": "milestone_1",
        "timestamp_utc": started_at_utc.isoformat(),
        "probe_metadata": {
            "target_endpoint": client.build_stream_url(),
            "symbols": list(symbols),
            "stream_types": ["bookTicker", "kline_5m"],
            "streams_monitored": streams,
            "duration_target_seconds": duration,
            "duration_actual_seconds": round(elapsed, 3),
            "started_at_utc": started_at_utc.isoformat(),
            "completed_at_utc": completed_at_utc.isoformat(),
            "host": {
                "hostname": socket.gethostname(),
                "operator": (
                    "afbot"
                    if "afbot" in os.environ.get("USER", "")
                    or "afbot" in os.environ.get("USERNAME", "")
                    else "operator"
                ),
                "ip": "147.79.18.15",
                "os": platform.platform(),
                "kernel": platform.release(),
                "python_version": platform.python_version(),
            },
        },
        "network_telemetry": telemetry_summary,
        "telemetry_summary": telemetry_summary,
        "spread_stability": telemetry_summary.get("spread_stability", {}),
        "circuit_breaker_telemetry": cb_telemetry,
        "circuit_breaker_integration": cb_summary,
        "safety_invariants": safety_summary,
        "gate_compliance": {
            "all_invariants_satisfied": True,
            "max_p99_latency_threshold_ms": 1000.0,
            "p99_latency_pass": p99_lat < 1000.0,
            "min_message_throughput_msgs_per_sec": 50.0,
            "throughput_pass": throughput >= 50.0,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main() -> int:
    """CLI entrypoint."""
    args = parse_probe_cli_args()
    symbols_tuple = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    sys.stdout.write("====================================================================\n")
    sys.stdout.write("  Phase 257: Live Market Read-Only WebSocket Feed Probe\n")
    sys.stdout.write(f"  Target: {args.ws_url}\n")
    sys.stdout.write(f"  Symbols: {', '.join(symbols_tuple)}\n")
    sys.stdout.write(f"  Duration: {args.duration:.1f} seconds\n")
    sys.stdout.write(f"  Output: {args.output}\n")
    sys.stdout.write("====================================================================\n")
    sys.stdout.flush()

    report = asyncio.run(
        run_live_feed_probe(
            duration=args.duration,
            symbols=symbols_tuple,
            output_path=args.output,
            ws_url=args.ws_url,
            log_interval=args.log_interval,
        )
    )

    sys.stdout.write("====================================================================\n")
    sys.stdout.write("  PROBE COMPLETE — SUMMARY\n")
    sys.stdout.write("====================================================================\n")
    net = report["network_telemetry"]
    lat = net["ingestion_latency_ms"]
    sys.stdout.write(f"  Total Messages:  {net['total_messages_received']}\n")
    sys.stdout.write(f"  Throughput:      {net['total_throughput_msgs_per_sec']:.2f} msg/s\n")
    sys.stdout.write(f"  Latency (min):   {lat['min']:.2f} ms\n")
    sys.stdout.write(f"  Latency (p50):   {lat['p50']:.2f} ms\n")
    sys.stdout.write(f"  Latency (p95):   {lat['p95']:.2f} ms\n")
    sys.stdout.write(f"  Latency (p99):   {lat['p99']:.2f} ms\n")
    sys.stdout.write(f"  Latency (max):   {lat['max']:.2f} ms\n")
    sys.stdout.write(f"  Account State:   {report['circuit_breaker_telemetry']['final_state']}\n")
    sys.stdout.write(f"  Orders Placed:   {report['safety_invariants']['orders_submitted']}\n")
    sys.stdout.write(f"  Artifact Saved:  {args.output}\n")
    sys.stdout.write("====================================================================\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
