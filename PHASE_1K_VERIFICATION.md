# Phase 1k Verification — Immutable Exchange-Filter Snapshots

**Status:** Exchange-filter snapshot slice GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Public market-data only. No credentials, signed requests, account endpoints, order endpoints, demo orders, or live orders were added or used.

## Delivered

- Added `BinancePublicExchangeInfoFetcher` for unsigned `/fapi/v1/exchangeInfo` requests.
- Reused metadata-only transport telemetry; exchangeInfo payloads are not retained by telemetry.
- Added `ExchangeSymbolFilters` with deterministic fields for:
  - contract status and contract type;
  - base, quote, and margin/settle asset;
  - `PRICE_FILTER` minimum/maximum price and tick size;
  - `LOT_SIZE` minimum/maximum quantity and step size;
  - `MARKET_LOT_SIZE` minimum/maximum quantity and step size;
  - `MIN_NOTIONAL`/`NOTIONAL` minimum and optional maximum notional;
  - market-order applicability flags.
- Added `ExchangeFilterSnapshot`:
  - sorted unique symbol records;
  - schema version and venue identity;
  - UTC observation time;
  - deterministic content hash excluding observation time;
  - write-once atomic JSON persistence;
  - tamper detection and conflicting rewrite rejection.
- Added `validate_order_filters(...)` for runtime preflight validation of:
  - `TRADING` contract status;
  - positive finite reference price and quantity;
  - limit price bounds and tick-size alignment;
  - limit/market quantity bounds and step-size alignment;
  - minimum and optional maximum notional.
- This validator only returns filter validation or a typed violation. It does not size positions, choose leverage, create orders, or route execution.
- Exported the new APIs through `autonomous_futures.data`.

## TDD evidence

### ExchangeInfo transport

RED was captured before implementation:

```text
ModuleNotFoundError: No module named 'autonomous_futures.data.exchange_filters'
exit code 2
```

The focused contract suite then passed:

```text
6 passed in 0.68s
```

### Live schema regression

The first live smoke probe exposed a real Binance schema difference:

```text
settleAsset was absent from current symbol records
marginAsset was present instead
```

The bounded response inspection showed:

```text
symbol keys include marginAsset, not settleAsset
MIN_NOTIONAL keys include notional, not minNotional
```

`notional` was already supported. A failing regression was added for `settleAsset → marginAsset`, then the parser was corrected and the complete focused suite passed:

```text
18 passed in 0.69s
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
/fapi/v1/exchangeInfo
```

## Actual final public smoke result

```text
source: https://fapi.binance.com
authenticated: false
server_offset_ms: 1133
request_count: 9
success_count: 9
failure_count: 0
retryable_failure_count: 0
non_retryable_failure_count: 0
average_latency_seconds: 0.222965422202833
max_latency_seconds: 0.5589940999634564
```

Baseline kline checks also passed for:

```text
BTCUSDT × 5m   rows=2   closed_and_gap_free=true
BTCUSDT × 15m  rows=2   closed_and_gap_free=true
ETHUSDT × 5m   rows=2   closed_and_gap_free=true
ETHUSDT × 15m  rows=2   closed_and_gap_free=true
SOLUSDT × 5m   rows=2   closed_and_gap_free=true
SOLUSDT × 15m  rows=2   closed_and_gap_free=true
```

Derivatives checks passed:

```text
mark-price rows: 2
mark-price closed: true
funding rows: 4
funding events sorted: true
```

Exchange-filter snapshot evidence:

```text
snapshot_hash:
bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb

BTCUSDT status=TRADING contract=PERPETUAL
  tick_size=0.10 step_size=0.001 min_qty=0.001 min_notional=50 max_notional=None

ETHUSDT status=TRADING contract=PERPETUAL
  tick_size=0.01 step_size=0.001 min_qty=0.001 min_notional=20 max_notional=None

SOLUSDT status=TRADING contract=PERPETUAL
  tick_size=0.0100 step_size=0.01 min_qty=0.01 min_notional=5 max_notional=None
```

The snapshot hash is stable for equivalent symbol/filter content even when the observation timestamp changes. Symbol ordering is deterministic.

## Final local quality gates

```text
pytest -q
62 passed in 2.43s

ruff check src tests research scripts
All checks passed!

ruff format --check src tests research scripts
38 files already formatted

mypy src
Success: no issues found in 20 source files

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

- [USDⓈ-M Futures Exchange Information](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information)
- [USDⓈ-M Futures market-data REST catalog](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
- [Binance derivatives common filter definitions](https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin/common-definition)
- [Binance Filters reference](https://developers.binance.com/en/docs/products/spot/filters)

## Not proven by this slice

- complete historical exchangeInfo version history;
- authenticated account-level order limits;
- leverage brackets or maintenance-margin tiers;
- dynamic percent-price validation against current mark/reference prices;
- paper execution or order submission;
- VPS/Kainode reachability;
- exchange-filter change monitoring or automatic snapshot refresh scheduling.
