# Phase 1i Verification — Public Transport Telemetry Hardening

**Status:** Transport telemetry slice GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Telemetry is observational only. No credentials, signed requests, account endpoints, order endpoints, demo orders, or live orders were added or used.

## Delivered

- Added metadata-only `TransportTelemetry` counters.
- Added immutable `TransportTelemetrySnapshot` with:
  - request count;
  - success/failure counts;
  - retryable/non-retryable failure counts;
  - `Retry-After` observation count;
  - HTTP status-code histogram;
  - total, maximum, and average latency.
- Instrumented `BinancePublicKlineFetcher` with injectable monotonic clock and optional shared telemetry.
- Recorded one observation per fetch attempt, including malformed payload failures.
- Preserved existing classified `PublicTransportError` behavior and retry-after values.
- Kept payload rows, headers, URLs with query values, credentials, and exception payloads out of telemetry snapshots.
- Exported telemetry APIs through `autonomous_futures.data`.
- Updated the public smoke probe to share telemetry across the baseline symbol/interval checks.

## TDD evidence

RED:

```text
ImportError: cannot import name 'TransportTelemetry'
exit code 4
```

GREEN focused telemetry tests:

```text
2 passed in 0.56s
```

The focused tests cover:

- deterministic success latency;
- success/failure counters;
- retryable HTTP classification;
- `Retry-After` observation;
- status-code histogram;
- absence of payload metadata.

## Actual public smoke command

```bash
PYTHONPATH=src uvx --from 'uv==0.12.2' uv run --locked \
  python scripts/smoke_public_transport.py
```

## Actual public smoke telemetry result

```json
{
  "source":"https://fapi.binance.com",
  "endpoint_paths":["/fapi/v1/time","/fapi/v1/klines"],
  "authenticated":false,
  "server_offset_ms":1058,
  "telemetry":{
    "request_count":6,
    "success_count":6,
    "failure_count":0,
    "retryable_failure_count":0,
    "non_retryable_failure_count":0,
    "retry_after_observation_count":0,
    "status_code_counts":[],
    "average_latency_seconds":0.24493601665017195,
    "max_latency_seconds":0.26206889998866245
  }
}
```

The six successful checks were:

```text
BTCUSDT × 5m   rows=2   closed_and_gap_free=true
BTCUSDT × 15m  rows=2   closed_and_gap_free=true
ETHUSDT × 5m   rows=2   closed_and_gap_free=true
ETHUSDT × 15m  rows=2   closed_and_gap_free=true
SOLUSDT × 5m   rows=2   closed_and_gap_free=true
SOLUSDT × 15m  rows=2   closed_and_gap_free=true
```

The live smoke run observed no rate-limit response, so `Retry-After` behavior remains proven by injected unit fixtures rather than a deliberately induced public rate-limit event.

## Final local quality gates

```text
pytest -q
50 passed in 2.57s

ruff check src tests research scripts
All checks passed!

ruff format --check src tests research scripts
34 files already formatted

mypy src
Success: no issues found in 18 source files

uv lock --check
Resolved 67 packages

python -m compileall -q src tests research scripts
exit 0

git diff --check
exit 0
```

## Official references

- [Binance USDⓈ-M Kline/Candlestick Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)
- [Binance USDⓈ-M Check Server Time](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Check-Server-Time)
- [Binance USDⓈ-M Market Data REST API catalog](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api)

## Not proven by this slice

- sustained rate-limit behavior;
- real `Retry-After` response capture;
- VPS/Kainode network reachability;
- historical completeness;
- funding/mark-price alignment;
- exchange-filter snapshots;
- any authenticated or execution capability.
