# Phase 1n Verification — Unified Dataset Bundle Registry

**Status:** Unified bundle slice GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Metadata-only research/data-plane artifact binding. No credentials, signed requests, account truth, sizing, leverage, order routing, or live execution was added.

## Scope delivered

Added `src/autonomous_futures/data/bundle.py` with:

- `DatasetBundle` model bound to a complete `DatasetRegistry` hash;
- deterministic sorted bundle components;
- exact symbol-universe validation;
- one `5m` kline component per symbol;
- one `5m` mark-price component per symbol;
- one event-based funding-rate component per symbol with coverage over the bundle range;
- one exchange-filter snapshot covering the complete symbol universe;
- atomic write-once bundle persistence;
- deterministic bundle hash excluding audit-only `created_at`;
- hash verification and tamper detection on readback;
- exact component lookup.

The public APIs are exported through `src/autonomous_futures/data/__init__.py`.

## Temporal contract

`DatasetBundle.time_start` and `time_end` use a UTC half-open coverage range:

```text
[time_start, time_end)
```

The existing kline `DatasetManifest` records `time_end` as the last candle open time. Therefore, for a `5m` bundle:

```text
kline manifest time_end = bundle time_end - 5 minutes
mark-price artifact time_end = bundle time_end
funding artifact range must contain [bundle time_start, bundle time_end)
```

This prevents an inclusive/exclusive timestamp mismatch from silently creating a false alignment claim.

## RED → GREEN evidence

Initial focused run before implementation:

```text
pytest tests/unit/test_bundle.py -q
ModuleNotFoundError:
autonomous_futures.data.bundle
exit code: 2
```

Focused GREEN result after implementation and contract correction:

```text
pytest tests/unit/test_bundle.py -q
4 passed in 0.72s
```

The tests cover:

- complete multi-symbol bundle construction;
- registry-hash binding;
- missing mark-price component rejection;
- insufficient funding coverage rejection;
- incomplete exchange-filter universe rejection;
- write-once persistence;
- conflicting rewrite rejection;
- tamper/hash mismatch detection.

## Dogfood evidence

A bounded real-data dogfood was run in a temporary directory:

- two rows from each real cached `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` 5m CSV;
- public Binance `/fapi/v1/markPriceKlines` for the same range and symbols;
- public Binance `/fapi/v1/fundingRate` for coverage around the same range and symbols;
- public Binance `/fapi/v1/exchangeInfo` for the complete three-symbol universe;
- all canonical artifacts and manifests persisted before registry/bundle binding;
- temporary output removed after verification.

```text
symbols: BTCUSDT, ETHUSDT, SOLUSDT
bundle_start: 2026-08-06T05:25:00+00:00
bundle_end_exclusive: 2026-08-06T05:35:00+00:00
components: 10

registry_hash:
8d4fede44fb06ef51522c535cf9634a49e30b71d75e631bc8bcbbb775ea25fe3

bundle_hash:
bf43616adfe378a79e486e871c228d43d1857023c2c0a6cc34457dd2281dcbad

exchange_filter_hash:
bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb

public transport:
requests=6
successes=6
failures=0
persisted=true
```

The bundle contains exactly:

```text
3 kline components
3 mark-price components
3 funding-rate components
1 exchange-filter component
```

This proves bounded endpoint/parser compatibility and deterministic artifact binding for the slice. It does not prove complete historical funding/mark-price ingestion or trading readiness.

## Verification

```text
pytest -q
74 passed in 2.68s

ruff check
All checks passed!

ruff format --check
42 files already formatted

mypy src
Success: no issues found in 23 source files

uv lock --check
pass

compileall
pass

git diff --check
pass

secret scan
No findings
```
