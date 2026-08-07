from __future__ import annotations

import json
import time

from autonomous_futures.data.backfill import BackfillWindow, merge_kline_rows
from autonomous_futures.data.public_collector import fully_closed_end_ms, server_time
from autonomous_futures.data.transport import BinancePublicKlineFetcher, TransportTelemetry

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
INTERVALS = (("5m", 300_000), ("15m", 900_000))


def main() -> None:
    server_ms = server_time()
    local_ms = int(time.time() * 1000)
    telemetry = TransportTelemetry()
    checks: list[dict[str, object]] = []
    for symbol in SYMBOLS:
        for interval, interval_ms in INTERVALS:
            end_ms = fully_closed_end_ms(server_ms, interval_ms) + 1
            start_ms = end_ms - 2 * interval_ms
            rows = BinancePublicKlineFetcher(
                symbol=symbol,
                interval=interval,
                limit=2,
                telemetry=telemetry,
            )(BackfillWindow(start_ms, end_ms))
            validated = merge_kline_rows(
                (rows,),
                start_ms=start_ms,
                end_ms_exclusive=end_ms,
                interval_ms=interval_ms,
            )
            checks.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "rows": len(validated),
                    "first_open_ms": validated[0][0],
                    "last_open_ms": validated[-1][0],
                    "closed_and_gap_free": True,
                }
            )
    snapshot = telemetry.snapshot()
    print(
        json.dumps(
            {
                "source": "https://fapi.binance.com",
                "endpoint_paths": ["/fapi/v1/time", "/fapi/v1/klines"],
                "authenticated": False,
                "server_time_ms": server_ms,
                "local_time_ms": local_ms,
                "server_offset_ms": server_ms - local_ms,
                "checks": checks,
                "telemetry": {
                    "request_count": snapshot.request_count,
                    "success_count": snapshot.success_count,
                    "failure_count": snapshot.failure_count,
                    "retryable_failure_count": snapshot.retryable_failure_count,
                    "non_retryable_failure_count": snapshot.non_retryable_failure_count,
                    "retry_after_observation_count": snapshot.retry_after_observation_count,
                    "status_code_counts": snapshot.status_code_counts,
                    "average_latency_seconds": snapshot.average_latency_seconds,
                    "max_latency_seconds": snapshot.max_latency_seconds,
                },
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
