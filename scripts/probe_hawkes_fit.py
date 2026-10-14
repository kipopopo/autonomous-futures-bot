"""Measure a Testnet Hawkes fit from genuine exchange event timestamps, without orders.

This diagnostic intentionally does not validate local receive-time freshness and can
never grant execution authority. Use probe_persistent_market_feed.py for that gate.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import websockets

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


async def receive_frame(stream: Any, timeout_seconds: float) -> Any | None:
    if timeout_seconds <= 0:
        return None
    try:
        return await asyncio.wait_for(stream.recv(), timeout=timeout_seconds)
    except TimeoutError:
        return None


async def probe(
    directory: Path,
    duration: int,
    calibration: RuntimeHawkesCalibration,
    calibration_window_ms: int,
) -> Path:
    if not 90 <= duration <= 3600 or duration * 1000 < calibration_window_ms:
        raise ValueError("Probe duration must cover the configured calibration window")
    directory.mkdir(parents=True, exist_ok=True)
    identifier = str(time.time_ns())
    trace_path = directory / f"hawkes-fit-diagnostic-{identifier}.jsonl"
    gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
    monitor = RuntimeMicrostructure(
        tuple(ACTIVE_PAIRS),
        calibration=calibration,
        calibration_window_ms=calibration_window_ms,
    )
    endpoint = LiveMarketFeed(gateway, monitor).endpoint
    frame_counts: Counter[tuple[str, str]] = Counter()
    ingress_errors: Counter[str] = Counter()
    started = time.monotonic()
    frame_count = 0
    connected = False
    with trace_path.open("x", encoding="utf-8") as trace:
        async with websockets.connect(
            endpoint,
            open_timeout=15,
            close_timeout=5,
            max_size=2**20,
            max_queue=32,
        ) as stream:
            connected = True
            while True:
                remaining = duration - (time.monotonic() - started)
                if remaining <= 0:
                    break
                wire = await receive_frame(stream, remaining)
                if wire is None:
                    break
                observed_local_ms = time.time_ns() // 1_000_000
                payload = json.loads(wire)
                data = payload.get("data", payload)
                symbol = str(data.get("s", "unknown"))
                event_type = str(data.get("e", "unknown"))
                event_ms = int(data["E"])
                frame_counts[(symbol, event_type)] += 1
                line = json.dumps(
                    {
                        "observed_local_ms": observed_local_ms,
                        "exchange_event_ms": event_ms,
                        "payload": payload,
                    },
                    separators=(",", ":"),
                )
                trace.write(line + "\n")
                frame_count += 1
                if frame_count % 500 == 0:
                    trace.flush()
                try:
                    # Event timestamps drive fitting; this diagnostic does not claim
                    # that the local wall clock or ingress age passed live admission.
                    monitor.ingest(payload, event_ms)
                except ValueError as exc:
                    ingress_errors[type(exc).__name__] += 1
        await monitor.calibrate()
    fit = monitor.fit
    result: dict[str, Any] = {
        "schema": "hawkes-fit-diagnostic-v1",
        "source": endpoint,
        "testnet": True,
        "execution_authority": False,
        "clock_validation": "NOT_PERFORMED_DIAGNOSTIC_ONLY",
        "receive_time_freshness": "NOT_PERFORMED_DIAGNOSTIC_ONLY",
        "fit_window_time_basis": "exchange_event_timestamp",
        "duration_seconds": duration,
        "calibration_window_ms": monitor.calibration_window_ms,
        "beta_per_second": calibration.beta_per_second,
        "calibration_sha256": calibration.artifact_sha256,
        "connected": connected,
        "frame_counts": {
            f"{symbol}:{event_type}": count
            for (symbol, event_type), count in sorted(frame_counts.items())
        },
        "ingress_error_counts": dict(ingress_errors),
        "sequence_gaps": monitor.gaps,
        "duplicate_frames": monitor.duplicates,
        "arrival_count": len(monitor.arrivals),
        "fit_error": monitor.last_fit_error,
        "fit": None if fit is None else dataclasses.asdict(fit),
        "fit_accepted_for_diagnostic": bool(
            fit is not None and not fit.baseline_boundary_symbols and 0 <= fit.spectral_radius < 1
        ),
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "trace_path": str(trace_path),
        "implementation": {
            str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                REPO / "src/autonomous_futures/execution/binance_gateway.py",
                REPO / "src/autonomous_futures/feed/kline_sequencer.py",
                REPO / "src/autonomous_futures/feed/live_market_feed.py",
                REPO / "src/autonomous_futures/feed/measured_hawkes.py",
                REPO / "src/autonomous_futures/feed/runtime_microstructure.py",
                REPO / "src/autonomous_futures/feed/runtime_hawkes_calibration.py",
            )
        },
    }
    output = directory / f"hawkes-fit-diagnostic-{identifier}.json"
    output.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
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
