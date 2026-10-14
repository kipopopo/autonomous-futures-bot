"""Finite public Testnet probe of the persistent measured feed; no order methods are called."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway  # noqa: E402
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS  # noqa: E402
from autonomous_futures.feed.live_market_feed import LiveMarketFeed  # noqa: E402
from autonomous_futures.feed.runtime_hawkes_calibration import (  # noqa: E402
    RuntimeHawkesCalibration,
    load_runtime_hawkes_calibration,
)
from autonomous_futures.feed.runtime_microstructure import (  # noqa: E402
    DEFAULT_CALIBRATION_WINDOW_MS,
    RuntimeMicrostructure,
)


def _source_routes(feed: LiveMarketFeed) -> dict[str, str]:
    """Return every independent WebSocket route used by a probe run."""
    return {
        "market": feed.market_endpoint,
        "public_depth": feed.public_endpoint,
    }


async def probe(
    directory: Path,
    duration: int,
    calibration: RuntimeHawkesCalibration,
    calibration_window_ms: int = DEFAULT_CALIBRATION_WINDOW_MS,
) -> Path:
    if not 90 <= duration <= 3600:
        raise ValueError("Probe duration must be between 90 and 3600 seconds")
    directory.mkdir(parents=True, exist_ok=True)
    identifier = str(time.time_ns())
    trace_path = directory / f"persistent-feed-{identifier}.jsonl"
    monitor = RuntimeMicrostructure(
        tuple(ACTIVE_PAIRS),
        calibration=calibration,
        calibration_window_ms=calibration_window_ms,
    )
    frame_count = 0
    with trace_path.open("x", encoding="utf-8") as trace:

        def record(payload: dict[str, Any], observed_ms: int) -> None:
            nonlocal frame_count
            frame_count += 1
            trace.write(
                json.dumps(
                    {
                        "received_ms": observed_ms,
                        "generation_before_ingest": monitor.generation,
                        "payload": payload,
                        "clock": None if feed.clock is None else dataclasses.asdict(feed.clock),
                    }
                )
                + "\n"
            )
            if frame_count % 500 == 0:
                trace.flush()

        feed = LiveMarketFeed(
            BinanceFuturesGateway(testnet=True, offline_mode=False), monitor, on_frame=record
        )
        task = asyncio.create_task(feed.run())
        try:
            await asyncio.sleep(duration)
            if task.done():
                await task
                raise ValueError("Persistent feed unexpectedly terminated")
            local_ms = time.time_ns() // 1_000_000
            clock = feed.clock
            evidence = {}
            for symbol in monitor.symbols:
                try:
                    if clock is None:
                        raise ValueError("No observed exchange clock")
                    observed = monitor.evidence(
                        symbol, clock.aligned_ms(local_ms), uncertainty_ms=clock.uncertainty_ms
                    )
                    evidence[symbol] = {"accepted": True, **dataclasses.asdict(observed)}
                except ValueError as exc:
                    evidence[symbol] = {"accepted": False, "reason": str(exc)}
            result = {
                # Keep the old field for readers of earlier probe artifacts. The
                # complete route inventory is recorded separately below.
                "source": feed.endpoint,
                "sources": _source_routes(feed),
                "testnet": True,
                "execution_authority": False,
                "observed_ms": local_ms,
                "duration_seconds": duration,
                "calibration_window_ms": monitor.calibration_window_ms,
                "beta_per_second": calibration.beta_per_second,
                "calibration_sha256": calibration.artifact_sha256,
                "connected": feed.connected,
                "clock": None if clock is None else dataclasses.asdict(clock),
                "fit": None if monitor.fit is None else dataclasses.asdict(monitor.fit),
                "generation": monitor.generation,
                "gaps": monitor.gaps,
                "duplicates": monitor.duplicates,
                "stale_frames": monitor.stale,
                "arrivals": len(monitor.arrivals),
                "fit_error": monitor.last_fit_error,
                "feed_error_type": feed.last_error_type,
                "symbol_evidence": evidence,
            }
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    result["trace_sha256"] = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    result["trace_path"] = str(trace_path)
    result["implementation"] = {
        str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__),
            REPO / "src/autonomous_futures/feed/live_market_feed.py",
            REPO / "src/autonomous_futures/feed/runtime_microstructure.py",
            REPO / "src/autonomous_futures/feed/exchange_clock.py",
            REPO / "src/autonomous_futures/feed/measured_hawkes.py",
            REPO / "src/autonomous_futures/feed/runtime_hawkes_calibration.py",
        )
    }
    output = directory / f"persistent-feed-{identifier}.json"
    with output.open("x", encoding="utf-8") as destination:
        destination.write(json.dumps(result, indent=2, default=str))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hawkes-calibration", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--calibration-window-ms", type=int, default=DEFAULT_CALIBRATION_WINDOW_MS)
    args = parser.parse_args()
    calibration = load_runtime_hawkes_calibration(args.hawkes_calibration, REPO)
    print(
        asyncio.run(probe(args.output, args.duration, calibration, args.calibration_window_ms)),
        flush=True,
    )


if __name__ == "__main__":
    main()
