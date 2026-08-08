# Phase 1j Verification — Funding and Mark-Price Alignment

**Status:** Funding/mark-price data slice GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Public market-data only. No credentials, signed requests, account endpoints, order endpoints, demo orders, or live orders were added or used.

## Delivered

- Added `BinancePublicFundingFetcher` for unsigned `/fapi/v1/fundingRate` requests.
- Added `BinancePublicMarkPriceKlineFetcher` for unsigned `/fapi/v1/markPriceKlines` requests.
- Added bounded limit validation:
  - funding history: maximum 1,000;
  - mark-price klines: maximum 1,500.
- Reused classified transport failures and metadata-only telemetry for both adapters.
- Added `canonicalize_funding_rows(...)`:
  - validates symbol and half-open time range;
  - preserves funding rate and funding mark price as `Decimal`;
  - rejects duplicate events and schema mismatches;
  - sorts by funding timestamp without inventing a fixed cadence.
- Added `canonicalize_mark_price_klines(...)`:
  - validates UTC open/close boundaries and closed requested range;
  - preserves Decimal OHLC values;
  - rejects gaps, duplicates, malformed values, and non-finite decimals;
  - accepts both six-field fixture rows and the actual 12-field Binance kline response shape.
- Added `align_derivatives_to_primary(...)`:
  - requires exact mark-price coverage for every primary 5m bar;
  - uses strict prior-event funding alignment (`allow_exact_matches=False`);
  - preserves `funding_event_time` provenance;
  - does not generically forward-fill before the first event;
  - normalizes pandas timestamp units explicitly before `merge_asof`.
- Exported all new APIs through `autonomous_futures.data`.

## TDD evidence

### Public adapter contract

RED:

```text
ImportError: cannot import name 'BinancePublicFundingFetcher'
exit code 2
```

GREEN:

```text
2 passed in 0.63s
```

### Alignment contract

RED:

```text
ModuleNotFoundError: No module named 'autonomous_futures.data.alignment'
exit code 2
```

Initial implementation exposed a real pandas join-key unit mismatch:

```text
MergeError: datetime64[us, UTC] and datetime64[ms, UTC]
```

The implementation now converts both keys explicitly to millisecond UTC timestamps.

GREEN:

```text
4 passed in 0.71s
```

### Actual Binance schema regression

The first public probe showed that the live mark-price response contains 12 fields, with `close_time` at index 6. A regression test failed against the initial six-field-only parser, then the parser was corrected.

Focused adapter/alignment regression suite after the fix:

```text
11 passed in 0.79s
```

## Final public smoke command

```bash
PYTHONPATH=src uvx --from 'uv==0.12.2' uv run --locked \
  python scripts/smoke_public_transport.py
```

The probe uses only these public endpoints:

```text
/fapi/v1/time
/fapi/v1/klines
/fapi/v1/markPriceKlines
/fapi/v1/fundingRate
```

## Actual final public smoke result

```json
{
  "source":"https://fapi.binance.com",
  "authenticated":false,
  "server_offset_ms":1108,
  "checks":{
    "baseline_symbol_interval_checks":6,
    "rows_per_check":2,
    "closed_and_gap_free":true
  },
  "derivatives":{
    "mark_price_rows":2,
    "mark_price_closed":true,
    "funding_rows":4,
    "funding_events_sorted":true
  },
  "telemetry":{
    "request_count":8,
    "success_count":8,
    "failure_count":0,
    "retryable_failure_count":0,
    "non_retryable_failure_count":0,
    "retry_after_observation_count":0,
    "status_code_counts":[],
    "average_latency_seconds":0.218120950004959,
    "max_latency_seconds":0.3999871000414714
  }
}
```

The six baseline checks were:

```text
BTCUSDT × 5m   rows=2   closed_and_gap_free=true
BTCUSDT × 15m  rows=2   closed_and_gap_free=true
ETHUSDT × 5m   rows=2   closed_and_gap_free=true
ETHUSDT × 15m  rows=2   closed_and_gap_free=true
SOLUSDT × 5m   rows=2   closed_and_gap_free=true
SOLUSDT × 15m  rows=2   closed_and_gap_free=true
```

A prior bounded smoke attempt hit a transient `WinError 10054` TLS reset on the server-time request. A separate `curl` connectivity check succeeded, and the immediately following complete probe passed with the result above. This transient event was not suppressed or counted as a successful smoke run.

## Final local quality gates

```text
pytest -q
55 passed in 2.98s

ruff check src tests research scripts
All checks passed!

ruff format --check src tests research scripts
36 files already formatted

mypy src
Success: no issues found in 19 source files

uv lock --check
Resolved 67 packages

python -m compileall -q src tests research scripts
exit 0

git diff --check
exit 0

secret scan
No findings
```

## Official Binance references

- [Get Funding Rate History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)
- [Mark Price Kline/Candlestick Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data)
- [Mark Price](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price)
- [USDⓈ-M Futures Market Data REST API catalog](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)

## Not proven by this slice

- complete historical funding/mark-price backfill;
- funding payment accounting in the backtest engine;
- VPS/Kainode reachability;
- sustained rate-limit behavior or real `Retry-After` capture;
- exchange-filter snapshots;
- authenticated exchange access or execution readiness.
