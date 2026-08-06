# Phase 1c Verification — Multi-Symbol Dataset Collection

**Status:** Phase 1c collection slice GREEN; funding/mark-price alignment and live backfill remain outstanding.
**Execution mode:** Local Windows project environment only.
**Safety boundary:** No exchange credentials, authenticated client, order endpoint, VPS deployment, OpenCode request, or network fetch was used.

## Delivered

- Added `src/autonomous_futures/data/collection.py`.
- Added `DatasetCollectionManifest` with:
  - sorted symbol identity;
  - dataset interval;
  - child `DatasetManifest` records;
  - code/dependency identity;
  - stable content hash excluding creation time;
  - write-once persistence and tamper verification.
- Added `build_kline_collection` orchestration.
- All source CSVs are preflighted before the first artifact write.
- Child datasets are built deterministically in sorted symbol order.
- Collection validation requires:
  - child symbols to match collection symbols;
  - child intervals to match;
  - child start times to align;
  - child end times to align.
- Exported collection APIs through `autonomous_futures.data`.

## TDD evidence

RED focused run before implementation:

```text
ModuleNotFoundError: No module named 'autonomous_futures.data.collection'
```

GREEN focused collection run:

```text
2 passed in 8.85s
```

The tests cover:

- deterministic BTCUSDT/ETHUSDT/SOLUSDT ordering;
- child manifest linkage;
- stable collection hash on identical rebuild;
- persisted collection manifest round-trip;
- canonical artifact creation for every symbol;
- fail-fast source preflight with no partial output directory when ETHUSDT has a gap.

## Cached-data dogfood

The collection builder was exercised against the three real cached files:

```text
symbols:          BTCUSDT, ETHUSDT, SOLUSDT
dataset_interval: 5m
rows per symbol:  378211
time_start:       2023-01-01T00:00:00Z
time_end:         2026-08-06T05:30:00Z
collection_hash:  09c8516fa689071155d73ca830666c848fbbe24d7bb92f546d2444941384545a
```

Temporary Parquet artifact sizes:

```text
BTCUSDT: 18868014 bytes
ETHUSDT: 17604108 bytes
SOLUSDT: 16289821 bytes
```

The temporary output directory was cleaned after the run. No Binance request was made.

## Final local quality gates

```text
pytest -q
33 passed in 2.28s

ruff check src tests research
All checks passed!

ruff format --check src tests research
25 files already formatted

mypy src
Success: no issues found in 14 source files

uv lock --check
Resolved 67 packages

python -m compileall -q src tests research
exit 0

git diff --check
exit 0

secret scan
No findings
```

## Not yet complete

The following remain for later Phase 1 slices:

- historical backfill/retry and rate-limit policy;
- funding and mark-price alignment;
- Binance exchange-filter snapshots;
- persistent dataset registry and data-quality API/dashboard;
- VPS staging and service integration.
