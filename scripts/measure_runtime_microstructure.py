"""Record real Testnet market events and fit microstructure without placing any orders."""

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

import httpx
import websockets

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from autonomous_futures.feed.exchange_clock import ExchangeClock  # noqa: E402
from autonomous_futures.feed.kline_sequencer import ACTIVE_PAIRS  # noqa: E402
from autonomous_futures.feed.measured_hawkes import Arrival, fit_arrivals  # noqa: E402
from autonomous_futures.feed.runtime_hawkes_calibration import (  # noqa: E402
    RuntimeHawkesCalibration,
    load_runtime_hawkes_calibration,
)

SYMBOLS = tuple(ACTIVE_PAIRS)
BASE = "wss://stream.binancefuture.com"


async def capture(duration: float, directory: Path, calibration: RuntimeHawkesCalibration) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    run_id = str(time.time_ns())
    trace_path = directory / f"testnet-market-{run_id}.jsonl"
    endpoint = (
        BASE
        + "/stream?streams="
        + "/".join(
            f"{symbol.lower()}@{stream}"
            for symbol in SYMBOLS
            for stream in ("aggTrade", "depth5@100ms")
        )
    )
    arrivals: list[Arrival] = []
    last_ids: dict[str, int] = {}
    depths: dict[str, dict[str, Any]] = {}
    gaps = duplicates = stale = 0
    clocks = []
    async with httpx.AsyncClient(timeout=10) as client:
        for _ in range(3):
            sent_ms = time.time_ns() // 1000000
            response = await client.get("https://testnet.binancefuture.com/fapi/v1/time")
            received_ms = time.time_ns() // 1000000
            response.raise_for_status()
            try:
                clocks.append(
                    ExchangeClock(sent_ms, received_ms, int(response.json()["serverTime"]))
                )
            except ValueError:
                continue
    if not clocks:
        raise ValueError("No trustworthy public exchange clock observation")
    clock = min(clocks, key=lambda sample: sample.uncertainty_ms)
    started = time.monotonic()
    with trace_path.open("x", encoding="utf-8", newline="\n") as trace:
        async with websockets.connect(
            endpoint, open_timeout=15, close_timeout=5, max_size=2**20
        ) as stream:
            print(
                json.dumps({"event": "MARKET_CONNECTED", "source": BASE, "trace": str(trace_path)}),
                flush=True,
            )
            while time.monotonic() - started < duration:
                try:
                    wire = await asyncio.wait_for(
                        stream.recv(),
                        timeout=min(3, max(0.001, duration - (time.monotonic() - started))),
                    )
                except TimeoutError:
                    continue
                local_ms = time.time_ns() // 1000000
                now_ms = clock.aligned_ms(local_ms)
                payload = json.loads(wire)
                data = payload.get("data", payload)
                trace.write(
                    json.dumps({"received_ms": now_ms, "payload": payload}, sort_keys=True) + "\n"
                )
                symbol = data.get("s")
                if symbol not in SYMBOLS:
                    continue
                event_ms = int(data["E"])
                if not clock.event_fresh(event_ms, local_ms):
                    stale += 1
                    if event_ms > now_ms + clock.uncertainty_ms:
                        continue
                # Delayed past frames are real calibration history, not fresh entry evidence.
                if data.get("e") == "aggTrade":
                    identity = int(data["a"])
                    previous = last_ids.get(symbol)
                    if previous is not None and identity <= previous:
                        duplicates += 1
                        continue
                    if previous is not None and identity != previous + 1:
                        gaps += 1
                        arrivals.clear()
                    last_ids[symbol] = identity
                    arrivals.append(Arrival(symbol, int(data["T"]), identity))
                    if len(arrivals) > 200000:
                        raise ValueError("Capture exceeds its bounded event capacity")
                elif data.get("e") == "depthUpdate":
                    depths[symbol] = data
    result: dict[str, Any] = {
        "source": BASE,
        "clock": dataclasses.asdict(clock),
        "clock_offset_ms": clock.offset_ms,
        "clock_uncertainty_ms": clock.uncertainty_ms,
        "testnet": True,
        "execution_authority": False,
        "qualification": False,
        "beta_per_second": calibration.beta_per_second,
        "calibration_sha256": calibration.artifact_sha256,
        "trace_path": str(trace_path),
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "arrivals": len(arrivals),
        "gaps": gaps,
        "duplicates": duplicates,
        "stale_frames": stale,
        "depth_symbols": sorted(depths),
        "implementation": {
            str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                REPO / "src/autonomous_futures/feed/kline_sequencer.py",
                REPO / "src/autonomous_futures/feed/measured_hawkes.py",
                REPO / "src/autonomous_futures/feed/runtime_hawkes_calibration.py",
            )
        },
    }
    try:
        fitted = fit_arrivals(arrivals, SYMBOLS, beta=calibration.beta_per_second)
        result["fit"] = dataclasses.asdict(fitted)
        result["fit_available"] = True
    except ValueError as exc:
        result["fit_available"] = False
        result["reason"] = str(exc)
    path = directory / f"testnet-microstructure-{run_id}.json"
    path.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                "event": "MICROSTRUCTURE_RECORDED",
                "path": str(path),
                "fit_available": result["fit_available"],
                "arrivals": len(arrivals),
                "gaps": gaps,
                "stale_frames": stale,
                "reason": result.get("reason"),
                "spectral_radius": result.get("fit", {}).get("spectral_radius"),
            }
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument(
        "--output", type=Path, default=REPO / "artifacts/qualification/runtime-microstructure"
    )
    parser.add_argument("--hawkes-calibration", type=Path, required=True)
    args = parser.parse_args()
    if not 90 <= args.duration <= 150:
        raise ValueError("Probe duration must be between 90 and 150 seconds")
    calibration = load_runtime_hawkes_calibration(args.hawkes_calibration, REPO)
    asyncio.run(capture(args.duration, args.output, calibration))


if __name__ == "__main__":
    main()
