"""Probe the Testnet private stream and REST recovery without placing or logging orders."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from autonomous_futures.execution.account_evidence import observe_account  # noqa: E402
from autonomous_futures.execution.binance_gateway import BinanceFuturesGateway  # noqa: E402
from autonomous_futures.feed.authenticated_user_stream import (  # noqa: E402
    AuthenticatedUserDataStream,
)


async def probe(duration_seconds: float) -> dict[str, Any]:
    if not math.isfinite(duration_seconds) or not 5 <= duration_seconds <= 300:
        raise ValueError("Probe duration must be between 5 and 300 seconds")

    with TemporaryDirectory(prefix="afb-user-stream-probe-") as temporary:
        gateway = BinanceFuturesGateway(testnet=True, offline_mode=False)
        await gateway.sync_clock_drift()
        account_path = Path(temporary) / "exchange-account.json"
        refresh_requested = asyncio.Event()
        event_types: Counter[str] = Counter()
        rest_reconciliations = 0
        connected_once = False

        async def reconcile_on_connect() -> None:
            nonlocal rest_reconciliations
            await observe_account(gateway, account_path)
            rest_reconciliations += 1

        async def record_event(event: dict[str, Any]) -> None:
            event_type = event.get("e")
            if isinstance(event_type, str):
                event_types[event_type] += 1
            refresh_requested.set()

        stream = AuthenticatedUserDataStream(
            gateway,
            on_event=record_event,
            on_reconnect=reconcile_on_connect,
            reconnect_delay_seconds=1,
        )
        stream_task = asyncio.create_task(stream.run())
        deadline = time.monotonic() + duration_seconds
        try:
            while time.monotonic() < deadline:
                if stream.connected:
                    connected_once = True
                if refresh_requested.is_set() and stream.connected:
                    refresh_requested.clear()
                    observed_event_count = stream.event_count
                    await observe_account(gateway, account_path)
                    if stream.mark_reconciled(observed_event_count):
                        rest_reconciliations += 1
                    else:
                        refresh_requested.set()
                await asyncio.sleep(0.1)

            if stream.connected:
                connected_once = True
            return {
                "testnet": True,
                "duration_seconds": duration_seconds,
                "connected_once": connected_once,
                "connected_at_end": stream.connected,
                "reconciliation_required_at_end": stream.reconciliation_required,
                "rest_reconciliations": rest_reconciliations,
                "event_count": stream.event_count,
                "event_types": dict(sorted(event_types.items())),
                "last_error_type": stream.last_error_type,
                "execution_authority": False,
            }
        finally:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=float, default=20)
    args = parser.parse_args()
    try:
        result = asyncio.run(probe(args.duration_seconds))
    except Exception as exc:
        # Do not expose credentials, account values, signed URLs, or private event payloads.
        print(json.dumps({"probe_failed": True, "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
