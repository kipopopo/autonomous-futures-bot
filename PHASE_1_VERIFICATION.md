# Phase 1 Verification — Immutable Data Vertical Slice

**Status:** Phase 1 tracer slice GREEN; full historical ingestion and dashboard/API remain outstanding.
**Execution mode:** Local Windows project environment only.
**Safety boundary:** No exchange credentials, authenticated client, order endpoint, VPS deployment, OpenCode request, or live Binance network fetch was used.

## Delivered

- Migrated the public Binance USDⓈ-M collector source of truth to `src/autonomous_futures/data/public_collector.py`.
- Kept `research/collect_binance_public.py` as a compatibility wrapper for existing offline research tests.
- Preserved the `5m` primary and `15m` context timeframe contract.
- Preserved closed-candle cutoff behavior and public GET-only URL construction.
- Added canonical bar validation:
  - timezone-aware timestamps only;
  - UTC normalization;
  - deterministic sorting;
  - duplicate rejection;
  - interval-gap detection.
- Added canonical Parquet read/write using PyArrow and Zstandard compression.
- Added `DataFileManifest` with SHA-256 file hash and row count.
- Added `DatasetManifest` with symbols, exact time bounds, interval semantics, source files, code version, dependency-lock identity, and manifest hash.
- Manifest content hash excludes creation time so deterministic rebuilds produce the same hash.
- Manifest files are write-once; identical rewrites are accepted, conflicting rewrites are rejected.
- Manifest readers reject tampered content when the stored hash no longer matches.

## TDD evidence

RED focused run before implementation:

```text
ModuleNotFoundError: No module named 'autonomous_futures.data'
```

GREEN focused run after implementation:

```text
5 passed
```

After immutable manifest persistence and tamper detection were added:

```text
6 passed
```

## Final local quality gates

```text
pytest -q
28 passed in 2.17s

ruff check src tests research
All checks passed!

ruff format --check src tests research
21 files already formatted

mypy src
Success: no issues found in 12 source files

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

- public historical backfill execution and rate-limit/retry policy;
- raw-to-canonical conversion for all cached symbols and intervals;
- funding and mark-price alignment;
- Binance exchange-filter snapshots;
- persisted multi-symbol dataset builder and manifest registry;
- data-quality API/dashboard;
- VPS staging and service integration.
