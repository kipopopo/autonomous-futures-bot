# Phase 1b Verification — CSV-to-Parquet Dataset Builder

**Status:** Phase 1b builder slice GREEN; full Phase 1 ingestion remains in progress.
**Execution mode:** Local Windows project environment only.
**Safety boundary:** No exchange credentials, authenticated client, order endpoint, VPS deployment, OpenCode request, or live network fetch was used.

## Delivered

- Added `src/autonomous_futures/data/builder.py`.
- Reads Binance kline CSVs with the cached schema:
  `open_time`, OHLCV, `close_time`, quote volume, trades, taker fields, and `ignore`.
- Converts millisecond open/close times to UTC timestamps.
- Preserves price/volume decimal text as `Decimal` values during normalization.
- Rejects malformed integer/decimal fields and missing raw columns.
- Verifies `close_time == open_time + interval - 1ms`.
- Reuses canonical duplicate and gap validation before writing Parquet.
- Writes a canonical artifact under `canonical/` and a write-once manifest under `manifests/`.
- Binds both raw CSV and canonical Parquet SHA-256 records into `DatasetManifest`.
- Adds explicit `dataset_interval` (`5m` or `15m`) to prevent interval ambiguity.
- Existing canonical artifacts are immutable: identical rebuilds are accepted, changed rows are rejected.
- Legacy `research/` collector remains compatible while the source of truth is under `src/`.

## TDD evidence

RED focused run before implementation:

```text
ModuleNotFoundError: No module named 'autonomous_futures.data.builder'
```

GREEN focused builder run:

```text
3 passed
```

Manifest interval hardening was also tested RED first because `DatasetManifest` did not yet expose `dataset_interval`, then returned to GREEN.

## Cached-data dogfood

The builder was exercised against the real cached file:

```text
source: research/data/BTCUSDT-5m.csv
source_bytes: 44861315
raw_rows: 378211
canonical_rows: 378211
dataset_interval: 5m
time_start: 2023-01-01T00:00:00+00:00
time_end: 2026-08-06T05:30:00+00:00
artifact_bytes: 18868014
```

The Parquet and manifest were written to a temporary directory and cleaned after the run. No Binance request was made.

## Final local quality gates

```text
pytest -q
31 passed in 2.14s

ruff check src tests research
All checks passed!

ruff format --check src tests research
23 files already formatted

mypy src
Success: no issues found in 13 source files

uv lock --check
Resolved 67 packages

python -m compileall -q src tests research
exit 0

git diff --check
exit 0
```

A repository secret-pattern scan found no credential-like patterns in the tracked development files.

## Not yet complete

The following remain for later Phase 1 slices:

- multi-symbol dataset orchestration;
- historical backfill/retry and rate-limit policy;
- funding and mark-price alignment;
- Binance exchange-filter snapshots;
- dataset registry and data-quality API/dashboard;
- VPS staging and service integration.
