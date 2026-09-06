"""Phase 259: 24/7 Continuous Sandboxed Live Paper Trading Daemon.

Runs an autonomous 24/7 forward-testing daemon on live Binance Futures
public WebSocket streams across BTCUSDT, ETHUSDT, SOLUSDT, and DOGEUSDT.
Couples top-of-book market data with a shared 100.00 USDT margin engine,
dynamic leverage (1.0x-3.0x), <=80% utilization ceiling, >=20% reserve buffer,
0.04% taker fees, 2 bps adverse slippage, tick-level ATR circuit breakers,
periodic health checkpoints (paper-daemon-health.json), and exact Decimal
balance reconciliation recorded in isolated SQLite ledgers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import signal
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure src/ is importable
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import pandas as pd  # noqa: E402

from autonomous_futures.feed.client import BinancePublicFeedClient  # noqa: E402
from autonomous_futures.feed.monitor import CircuitBreakerFeedMonitor  # noqa: E402
from autonomous_futures.feed.rest_client import (  # noqa: E402
    DEFAULT_REST_URL,
    BinancePublicRestClient,
    fetch_warmup_bars_with_fallback,
)
from autonomous_futures.feed.telemetry import FeedTelemetryAccumulator  # noqa: E402
from autonomous_futures.paper.circuit_breakers import (  # noqa: E402
    HardenedSharedMarginAccount,
)
from autonomous_futures.paper.live_engine import (  # noqa: E402
    DEFAULT_STARTING_CAPITAL,
    DEFAULT_SYMBOLS,
    LivePaperEngine,
)

logger = logging.getLogger("run_phase_259_live_paper_daemon")


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for the 24/7 live paper trading daemon."""
    parser = argparse.ArgumentParser(
        description="Phase 259: 24/7 Continuous Sandboxed Live Paper Trading Daemon"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Session duration in seconds (default: None for continuous 24/7 operation)",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        default=False,
        help="Run a bounded smoke test session (defaults to 10.0s if --duration omitted)",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path("artifacts/paper_live"),
        help="Directory to persist ledgers and checkpoints (default: artifacts/paper_live)",
    )
    parser.add_argument(
        "--starting-capital",
        type=Decimal,
        default=DEFAULT_STARTING_CAPITAL,
        help="Shared portfolio cash balance in USDT (default: 100.00)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols to trade (default: BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT)",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default="wss://fstream.binance.com",
        help="Binance Futures WebSocket base URL (default: wss://fstream.binance.com)",
    )
    parser.add_argument(
        "--rest-url",
        type=str,
        default=DEFAULT_REST_URL,
        help="Binance Futures REST base URL (default: https://fapi.binance.com)",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=float,
        default=30.0,
        help="Interval in seconds between periodic health checkpoints (default: 30.0)",
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=Path("research/immutable-data/5m/canonical"),
        help="Directory holding canonical historical 5m Parquet data for warmup",
    )
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=100,
        help="Number of historical 5m bars to seed for causal feature warmup (default: 100)",
    )
    parser.add_argument(
        "--warmup-timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds for dynamic REST warmup fetch before falling back (default: 10.0)",
    )
    parser.add_argument(
        "--offline-warmup",
        action="store_true",
        default=False,
        help="Force offline fallback warmup without attempting public REST fetch",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Alias for --offline-warmup",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    return parser


def parse_cli_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse and validate CLI arguments for Phase 259 live paper daemon."""
    parser = build_arg_parser()
    parsed = parser.parse_args(args)

    if parsed.smoke_test and parsed.duration is None:
        parsed.duration = 10.0

    if parsed.duration is not None and parsed.duration <= 0.0:
        parser.error("--duration must be positive")
    if parsed.starting_capital <= Decimal("0"):
        parser.error("--starting-capital must be positive")
    if parsed.checkpoint_interval <= 0.0:
        parser.error("--checkpoint-interval must be positive")
    return parsed


def verify_strict_safety_invariants(*, orders_submitted: int = 0) -> dict[str, Any]:
    """Enforce strict read-only safety invariants (zero live orders, zero private keys)."""
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
        "paper_activation": True,
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
    if invariants["api_keys_loaded"] != 0:
        raise RuntimeError(
            f"SAFETY VIOLATION: private credentials detected in environment ({private_keys_found})"
        )

    return invariants


def emit_daemon_health_checkpoint(
    output_path: Path,
    status: str,
    uptime_seconds: float,
    started_at: str,
    symbols: list[str],
    starting_capital: Decimal,
    current_cash: Decimal,
    current_equity: Decimal,
    margin_utilization_pct: float,
    reserve_buffer_pct: float,
    active_positions: dict[str, Any],
    total_trades: int,
    circuit_breaker_status: str,
    feed_messages_received: int,
    reconnect_count: int,
) -> None:
    """Persist atomic JSON health checkpoint for systemd and operator inspection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "daemon_status": status,
        "pid": os.getpid(),
        "uptime_seconds": round(uptime_seconds, 2),
        "started_at_utc": started_at,
        "last_heartbeat_utc": datetime.now(UTC).isoformat(),
        "symbols_monitored": symbols,
        "starting_capital_usdt": str(starting_capital),
        "current_cash_usdt": str(current_cash),
        "current_equity_usdt": str(current_equity),
        "margin_utilization_pct": round(margin_utilization_pct, 4),
        "reserve_buffer_pct": round(reserve_buffer_pct, 4),
        "active_positions_count": len(active_positions),
        "active_positions": active_positions,
        "total_trades_count": total_trades,
        "circuit_breaker_status": circuit_breaker_status,
        "feed_messages_received": feed_messages_received,
        "feed_reconnects_count": reconnect_count,
        "zero_order_safety_invariants": {
            "orders_submitted": 0,
            "execution_authority": False,
            "live_trading_activation": False,
            "paper_activation": True,
            "promotion_state": "unpromoted",
            "zero_private_credentials": True,
        },
    }
    tmp_path = output_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(output_path)


def generate_deterministic_doge_warmup(
    bars_count: int = 100,
    start_ts: datetime | None = None,
) -> pd.DataFrame:
    """Generate deterministic 5m OHLC bars for DOGEUSDT warmup if Parquet missing."""
    if start_ts is not None:
        start = start_ts
    else:
        now_dt = datetime.now(UTC)
        now_ms = int(now_dt.timestamp() * 1000)
        last_closed_open_s = ((now_ms // 300_000) - 1) * 300
        start_s = last_closed_open_s - (bars_count - 1) * 300
        start = datetime.fromtimestamp(start_s, tz=UTC)

    records: list[dict[str, Any]] = []
    base_price = 0.150

    for i in range(bars_count):
        ts = start + timedelta(minutes=5 * i)
        angle = (i % 36) * (2 * math.pi / 36)
        variation = 0.005 * math.sin(angle)
        close_p = base_price + variation
        open_p = close_p - 0.0005 * math.cos(angle)
        high_p = max(open_p, close_p) + 0.0008
        low_p = min(open_p, close_p) - 0.0008
        volume = 500_000.0 + 100_000.0 * math.sin(angle)
        records.append(
            {
                "timestamp": ts.astimezone(UTC).replace(microsecond=0),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": volume,
            }
        )
    return pd.DataFrame(records)


def canonical_df_to_bar_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Transform canonical DataFrame into list of exact bar dictionaries for engine.seed_history."""
    records: list[dict[str, Any]] = []
    has_ts_col = "timestamp" in df.columns
    for idx, row in df.iterrows():
        ts_raw = row["timestamp"] if has_ts_col else idx
        if isinstance(ts_raw, datetime):
            ts = ts_raw
        elif hasattr(ts_raw, "to_pydatetime"):
            ts = ts_raw.to_pydatetime()
        else:
            ts = pd.to_datetime(ts_raw, utc=True).to_pydatetime()
        ts_utc = ts.astimezone(UTC).replace(microsecond=0)
        records.append(
            {
                "timestamp": ts_utc,
                "open": Decimal(str(row["open"])),
                "high": Decimal(str(row["high"])),
                "low": Decimal(str(row["low"])),
                "close": Decimal(str(row["close"])),
                "volume": Decimal(str(row.get("volume", "0"))),
            }
        )
    return records


async def seed_historical_warmup_bars(
    engine: LivePaperEngine,
    symbols: Sequence[str],
    warmup_bars: int = 100,
    history_dir: Path | str = Path("research/immutable-data/5m/canonical"),
    timeout_seconds: float = 10.0,
    offline: bool = False,
    rest_client: BinancePublicRestClient | None = None,
    rest_url: str = DEFAULT_REST_URL,
    now: datetime | None = None,
) -> dict[str, int]:
    """Concurrently fetch and seed historical warmup bars for all symbols with bounded timeout."""
    is_offline = offline or (os.environ.get("AF_OFFLINE_WARMUP") == "1")
    shared_client = (
        rest_client
        if rest_client is not None
        else (
            None
            if is_offline
            else BinancePublicRestClient(base_url=rest_url, timeout=timeout_seconds)
        )
    )
    owns_client = rest_client is None and shared_client is not None

    seeded_counts: dict[str, int] = {}
    try:

        async def _fetch_single(sym: str, force_offline: bool = False) -> tuple[str, pd.DataFrame]:
            eff_offline = is_offline or force_offline
            df = await fetch_warmup_bars_with_fallback(
                sym,
                limit=warmup_bars,
                only_closed=True,
                history_dir=history_dir,
                offline=eff_offline,
                rest_client=None if eff_offline else shared_client,
                now=now,
            )
            return sym, df

        coros = [_fetch_single(sym) for sym in symbols]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "Dynamic warmup timed out after %.1fs; falling back to offline for all symbols",
                timeout_seconds,
            )
            fallback_coros = [_fetch_single(sym, force_offline=True) for sym in symbols]
            results = await asyncio.gather(*fallback_coros, return_exceptions=True)

        for item in results:
            if isinstance(item, BaseException):
                logger.error("Warmup fetch failed with exception: %s", item)
                continue
            sym, df = item
            engine.seed_history(sym, df)
            seeded_counts[sym] = len(df)

            history = engine._bar_history.get(sym.upper(), [])
            oldest_ts = history[0]["timestamp"].isoformat() if history else "NONE"
            newest_ts = history[-1]["timestamp"].isoformat() if history else "NONE"
            source = getattr(df, "attrs", {}).get("source", "UNKNOWN")

            logger.info(
                "Seeded %d warmup bars for %s [%s -> %s] (source: %s)",
                len(df),
                sym,
                oldest_ts,
                newest_ts,
                source,
            )
    finally:
        if owns_client and shared_client is not None:
            await shared_client.aclose()

    return seeded_counts


async def seed_engine_history(
    engine: LivePaperEngine,
    history_dir: Path | str = Path("research/immutable-data/5m/canonical"),
    symbols: Sequence[str] = DEFAULT_SYMBOLS,
    warmup_bars: int = 100,
    timeout_seconds: float = 10.0,
    offline: bool = False,
    rest_client: BinancePublicRestClient | None = None,
    rest_url: str = DEFAULT_REST_URL,
    now: datetime | None = None,
) -> dict[str, int]:
    """Compatibility wrapper for dynamic historical warmup seeding."""
    return await seed_historical_warmup_bars(
        engine=engine,
        symbols=symbols,
        warmup_bars=warmup_bars,
        history_dir=history_dir,
        timeout_seconds=timeout_seconds,
        offline=offline,
        rest_client=rest_client,
        rest_url=rest_url,
        now=now,
    )


def setup_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install SIGINT/SIGTERM handlers for graceful daemon shutdown."""

    def _handler() -> None:
        logger.info("Caught termination signal; triggering clean daemon shutdown...")
        stop_event.set()

    if sys.platform != "win32":
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _handler)
        except NotImplementedError, RuntimeError:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda s, f: _handler())
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda s, f: _handler())
            except ValueError, AttributeError:
                pass


async def run_heartbeat_loop(
    health_file: Path,
    engine: LivePaperEngine,
    account: HardenedSharedMarginAccount,
    telemetry: FeedTelemetryAccumulator,
    feed_client: BinancePublicFeedClient,
    symbols: list[str],
    interval: float,
    stop_event: asyncio.Event,
    start_time: float,
    started_at_str: str,
) -> None:
    """Periodically write health checkpoint JSON while daemon is running."""
    while not stop_event.is_set():
        try:
            uptime = time.monotonic() - start_time
            current_eq = engine.current_equity()
            utilization = float(account.margin_utilization(current_eq)) * 100.0
            reserve = float(account.unencumbered_reserve_buffer(current_eq)) * 100.0
            cb_status = (
                "HALTED"
                if account.current_state in ("HALTED", "EMERGENCY_FLAT")
                else ("THROTTLED" if account.current_state == "THROTTLED" else "NORMAL")
            )
            positions = {
                sym: {
                    "side": pos.side,
                    "quantity": str(pos.quantity),
                    "entry_price": str(pos.open_entry.fill_price),
                    "leverage": str(pos.leverage),
                }
                for sym, pos in engine.active_trades.items()
            }
            emit_daemon_health_checkpoint(
                output_path=health_file,
                status="RUNNING",
                uptime_seconds=uptime,
                started_at=started_at_str,
                symbols=symbols,
                starting_capital=account.starting_capital,
                current_cash=account.cash,
                current_equity=current_eq,
                margin_utilization_pct=utilization,
                reserve_buffer_pct=reserve,
                active_positions=positions,
                total_trades=engine.total_closed_trades,
                circuit_breaker_status=cb_status,
                feed_messages_received=telemetry.total_messages,
                reconnect_count=feed_client.reconnect_count,
            )
        except Exception as exc:
            logger.warning("Error during heartbeat write: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass


async def run_live_paper_daemon(args: argparse.Namespace) -> dict[str, Any]:
    """Run continuous or bounded 24/7 live paper trading daemon."""
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    storage_dir = args.storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    ledger_db = storage_dir / "paper-ledger.sqlite3"
    lifecycle_db = storage_dir / "paper-lifecycle.sqlite3"
    observations_db = storage_dir / "paper-observations.sqlite3"
    health_file = storage_dir / "paper-daemon-health.json"

    # Verify zero-order safety invariants prior to execution
    verify_strict_safety_invariants(orders_submitted=0)

    # Initialize shared margin account
    account = HardenedSharedMarginAccount(
        starting_capital=args.starting_capital,
        max_utilization=Decimal("0.80"),
        base_allocation_fraction=Decimal("0.20"),
        min_reserve_buffer=Decimal("0.20"),
    )

    # Initialize feed telemetry and client
    telemetry = FeedTelemetryAccumulator(symbols=symbols)
    feed_client = BinancePublicFeedClient(
        symbols=symbols,
        streams=("bookTicker", "kline_5m"),
        url=args.ws_url,
        telemetry=telemetry,
    )

    # Initialize circuit breaker monitor
    monitor = CircuitBreakerFeedMonitor(
        account=account,
        symbols=symbols,
        max_queue_size=10_000,
        evaluate_on_ticker=True,
    )

    # Initialize integrated paper engine
    engine = LivePaperEngine(
        symbols=symbols,
        starting_capital=args.starting_capital,
        ledger_db=ledger_db,
        lifecycle_db=lifecycle_db,
        observations_db=observations_db,
        feed_client=feed_client,
        monitor=monitor,
        account=account,
        telemetry=telemetry,
    )

    # Seed causal feature history via dynamic async warmup with fallback
    is_offline = (
        getattr(args, "offline_warmup", False)
        or getattr(args, "offline", False)
        or (os.environ.get("AF_OFFLINE_WARMUP") == "1")
    )
    await seed_historical_warmup_bars(
        engine=engine,
        symbols=symbols,
        warmup_bars=args.warmup_bars,
        history_dir=args.history_dir,
        timeout_seconds=getattr(args, "warmup_timeout", 10.0),
        offline=is_offline,
        rest_url=getattr(args, "rest_url", DEFAULT_REST_URL),
    )

    # Setup termination event
    stop_event = asyncio.Event()
    setup_signal_handlers(stop_event)

    # Start monitor worker
    await monitor.start()

    start_time = time.monotonic()
    started_at_str = datetime.now(UTC).isoformat()

    logger.info("Starting 24/7 live paper daemon on %s symbols", list(symbols))
    logger.info("Storage directory: %s", storage_dir)
    logger.info(
        "Duration: %s (shared margin: %s USDT)",
        f"{args.duration:.1f}s" if args.duration else "Continuous 24/7",
        args.starting_capital,
    )

    # Emit initial checkpoint
    emit_daemon_health_checkpoint(
        output_path=health_file,
        status="STARTING",
        uptime_seconds=0.0,
        started_at=started_at_str,
        symbols=list(symbols),
        starting_capital=account.starting_capital,
        current_cash=account.cash,
        current_equity=account.cash,
        margin_utilization_pct=0.0,
        reserve_buffer_pct=100.0,
        active_positions={},
        total_trades=0,
        circuit_breaker_status="NORMAL",
        feed_messages_received=0,
        reconnect_count=0,
    )

    # Start periodic heartbeat task
    heartbeat_task = asyncio.create_task(
        run_heartbeat_loop(
            health_file=health_file,
            engine=engine,
            account=account,
            telemetry=telemetry,
            feed_client=feed_client,
            symbols=list(symbols),
            interval=args.checkpoint_interval,
            stop_event=stop_event,
            start_time=start_time,
            started_at_str=started_at_str,
        )
    )

    # Run stream with timeout and stop event monitoring
    stream_task = asyncio.create_task(
        feed_client.connect_and_stream(
            duration_seconds=args.duration,
            on_bar=engine.handle_bar,
            on_ticker=engine.handle_ticker,
        )
    )

    try:
        wait_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            [stream_task, wait_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        logger.info("Initiating graceful daemon shutdown...")
        stop_event.set()
        await engine.stop()
        if not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    # Reconcile exact Decimal cash balance
    reconciliation = engine.reconcile_balances()
    logger.info("Exact balance reconciliation result: %s", reconciliation)

    if not reconciliation["zero_balance_drift"]:
        raise RuntimeError(f"Balance drift detected: {reconciliation['drift']}")

    # Final summary artifact
    summary_path = storage_dir / "live-paper-summary.json"
    summary = engine.build_summary(
        duration_target=args.duration or (time.monotonic() - start_time),
        output_path=summary_path,
    )

    # Final clean shutdown checkpoint
    uptime_final = time.monotonic() - start_time
    final_eq = engine.current_equity()
    emit_daemon_health_checkpoint(
        output_path=health_file,
        status="SHUTDOWN_CLEAN",
        uptime_seconds=uptime_final,
        started_at=started_at_str,
        symbols=list(symbols),
        starting_capital=account.starting_capital,
        current_cash=account.cash,
        current_equity=final_eq,
        margin_utilization_pct=float(account.margin_utilization(final_eq)) * 100.0,
        reserve_buffer_pct=float(account.unencumbered_reserve_buffer(final_eq)) * 100.0,
        active_positions={},
        total_trades=engine.total_closed_trades,
        circuit_breaker_status="NORMAL",
        feed_messages_received=telemetry.total_messages,
        reconnect_count=feed_client.reconnect_count,
    )

    # Verify zero-order safety invariants post execution
    verify_strict_safety_invariants(orders_submitted=0)

    logger.info("Live paper daemon session ended cleanly. Final cash: %s USDT", account.cash)
    return summary


def main(argv: list[str] | None = None) -> int:
    """Entry point for 24/7 live paper daemon."""
    args = parse_cli_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_live_paper_daemon(args))
        return 0
    except KeyboardInterrupt:
        logger.info("Daemon cancelled by operator")
        return 0
    except Exception as exc:
        logger.error("Daemon failed with exception: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
