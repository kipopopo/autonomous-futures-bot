# Phase 1h Verification — Public Binance Transport Smoke Evidence

**Status:** Public-only network smoke probe PASS.
**Execution mode:** Local Windows project environment.
**Date of evidence:** 2026-08-07 session runtime.
**Safety boundary:** No API key, secret, signed request, authenticated client, account endpoint, order endpoint, demo order, or live order was used.

## Scope

The reproducible probe is:

```text
scripts/smoke_public_transport.py
```

It uses the project's existing `BinancePublicKlineFetcher`, `server_time`, `BackfillWindow`, and `merge_kline_rows` APIs. It calls only:

```text
GET https://fapi.binance.com/fapi/v1/time
GET https://fapi.binance.com/fapi/v1/klines
```

The probe requests two candles per symbol/interval and validates the result through the strict half-open window merge path. Symbols and intervals match the current research baseline:

```text
symbols:   BTCUSDT, ETHUSDT, SOLUSDT
intervals: 5m, 15m
```

## Actual command

```bash
PYTHONPATH=src uvx --from 'uv==0.12.2' uv run --locked \
  python scripts/smoke_public_transport.py
```

## Actual result

```json
{
  "source":"https://fapi.binance.com",
  "endpoint_paths":["/fapi/v1/time","/fapi/v1/klines"],
  "authenticated":false,
  "server_time_ms":1786073930813,
  "local_time_ms":1786073929762,
  "server_offset_ms":1051,
  "checks":[
    {"symbol":"BTCUSDT","interval":"5m","rows":2,"first_open_ms":1786073100000,"last_open_ms":1786073400000,"closed_and_gap_free":true},
    {"symbol":"BTCUSDT","interval":"15m","rows":2,"first_open_ms":1786071600000,"last_open_ms":1786072500000,"closed_and_gap_free":true},
    {"symbol":"ETHUSDT","interval":"5m","rows":2,"first_open_ms":1786073100000,"last_open_ms":1786073400000,"closed_and_gap_free":true},
    {"symbol":"ETHUSDT","interval":"15m","rows":2,"first_open_ms":1786071600000,"last_open_ms":1786072500000,"closed_and_gap_free":true},
    {"symbol":"SOLUSDT","interval":"5m","rows":2,"first_open_ms":1786073100000,"last_open_ms":1786073400000,"closed_and_gap_free":true},
    {"symbol":"SOLUSDT","interval":"15m","rows":2,"first_open_ms":1786071600000,"last_open_ms":1786072500000,"closed_and_gap_free":true}
  ]
}
```

## Evidence interpretation

PASS:

- DNS/TLS/HTTP path to `fapi.binance.com` was reachable from the local environment.
- Binance server-time endpoint returned a valid integer timestamp.
- Public USDⓈ-M kline endpoint returned valid list payloads for all six symbol/interval checks.
- All six pages passed exact-window, UTC/open-time cadence, duplicate, and closed-bar validation.
- The local/server clock difference was approximately `+1,051 ms` for the script run.
- No authentication material was present in the request path or parameters.

Not proven by this smoke test:

- complete historical coverage;
- long-running rate-limit behavior;
- retry-after handling against a real rate-limit response;
- VPS/Kainode network reachability;
- funding/mark-price alignment;
- exchange-filter snapshots;
- account access, order routing, demo trading, or live trading.

## Official references

- [Binance USDⓈ-M Kline/Candlestick Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)
- [Binance USDⓈ-M Check Server Time](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Check-Server-Time)
- [Binance USDⓈ-M Market Data REST API catalog](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api)

## Next bounded slice

Add transport telemetry without changing the public-only boundary:

- request endpoint/path and symbol/interval labels;
- latency measurement;
- response status classification;
- retryable/non-retryable counters;
- `Retry-After` observation;
- no payload logging and no credential logging.

Telemetry must remain observational and testable with injected transports; it must not add authenticated access or order capability.
