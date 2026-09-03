from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from autonomous_futures.data.alignment import (
    canonicalize_funding_rows,
    canonicalize_mark_price_klines,
)
from autonomous_futures.data.backfill import BackfillWindow, merge_kline_rows
from autonomous_futures.data.builder import KlineInterval
from autonomous_futures.data.exchange_filters import build_exchange_filter_snapshot
from autonomous_futures.data.public_collector import fully_closed_end_ms, server_time
from autonomous_futures.data.transport import (
    BinancePublicExchangeInfoFetcher,
    BinancePublicFundingFetcher,
    BinancePublicKlineFetcher,
    BinancePublicMarkPriceKlineFetcher,
    TransportTelemetry,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
INTERVALS: tuple[tuple[KlineInterval, int], ...] = (("5m", 300_000), ("15m", 900_000))


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

    mark_end_ms = (server_ms // 300_000) * 300_000
    mark_start_ms = mark_end_ms - 600_000
    mark_rows = BinancePublicMarkPriceKlineFetcher(
        symbol="BTCUSDT",
        interval="5m",
        limit=2,
        telemetry=telemetry,
    )(BackfillWindow(mark_start_ms, mark_end_ms))
    mark_canonical = canonicalize_mark_price_klines(
        mark_rows,
        symbol="BTCUSDT",
        interval="5m",
        end_exclusive_ms=mark_end_ms,
    )

    funding_interval_ms = 8 * 60 * 60 * 1_000
    funding_start_ms = (server_ms // funding_interval_ms - 3) * funding_interval_ms
    funding_rows = BinancePublicFundingFetcher(
        symbol="BTCUSDT",
        limit=10,
        telemetry=telemetry,
    )(BackfillWindow(funding_start_ms, server_ms))
    funding_canonical = canonicalize_funding_rows(
        funding_rows,
        symbol="BTCUSDT",
        start_ms=funding_start_ms,
        end_exclusive_ms=server_ms,
    )
    exchange_info = BinancePublicExchangeInfoFetcher(telemetry=telemetry)()
    filter_snapshot = build_exchange_filter_snapshot(
        exchange_info,
        symbols=SYMBOLS,
        observed_at=datetime.fromtimestamp(server_ms / 1000, tz=UTC),
    )
    snapshot = telemetry.snapshot()
    print(
        json.dumps(
            {
                "source": "https://fapi.binance.com",
                "endpoint_paths": [
                    "/fapi/v1/time",
                    "/fapi/v1/klines",
                    "/fapi/v1/markPriceKlines",
                    "/fapi/v1/fundingRate",
                    "/fapi/v1/exchangeInfo",
                ],
                "authenticated": False,
                "server_time_ms": server_ms,
                "local_time_ms": local_ms,
                "server_offset_ms": server_ms - local_ms,
                "checks": checks,
                "derivatives": {
                    "mark_price_endpoint": "/fapi/v1/markPriceKlines",
                    "mark_price_rows": len(mark_canonical),
                    "mark_price_closed": True,
                    "funding_endpoint": "/fapi/v1/fundingRate",
                    "funding_rows": len(funding_canonical),
                    "funding_events_sorted": True,
                },
                "exchange_filters": {
                    "snapshot_hash": filter_snapshot.snapshot_hash,
                    "symbols": [
                        {
                            "symbol": item.symbol,
                            "status": item.status,
                            "contract_type": item.contract_type,
                            "price_tick_size": str(item.price_tick_size),
                            "quantity_step_size": str(item.quantity_step_size),
                            "quantity_min": str(item.quantity_min),
                            "min_notional": str(item.min_notional),
                            "max_notional": (
                                str(item.max_notional) if item.max_notional is not None else None
                            ),
                        }
                        for item in filter_snapshot.symbols
                    ],
                },
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
