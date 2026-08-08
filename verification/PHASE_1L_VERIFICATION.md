# Phase 1l Verification — Immutable Dataset Registry

**Status:** Dataset-registry slice GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Registry is metadata-only. It does not load credentials, sign requests, size positions, validate account state, or route orders.

## Scope delivered

Added `src/autonomous_futures/data/registry.py` with:

- `DatasetRegistryEntry` for four explicit dataset kinds:
  - `kline`;
  - `funding_rate`;
  - `mark_price`;
  - `exchange_filters`.
- deterministic identity fields:
  - sorted unique symbols;
  - interval where applicable;
  - UTC half-open artifact range where applicable;
  - observation timestamp;
  - schema version;
  - content hash;
  - relative artifact reference;
  - Binance public REST endpoint;
  - unsigned/provenance markers.
- kind-specific contract rules:
  - kline/mark-price require `5m` or `15m` and UTC range;
  - funding-rate has no fabricated fixed interval but requires UTC range;
  - exchange-filter metadata has no fabricated historical range and uses `observed_at`.
- `DatasetRegistry` with:
  - deterministic entry ordering;
  - duplicate logical-identity rejection;
  - content-addressed registry hash excluding `created_at`;
  - UTC audit timestamp.
- atomic write-once persistence:
  - temporary file then replace;
  - identical rewrite accepted;
  - conflicting rewrite rejected;
  - tampered registry hash rejected.
- exact lookup through `find_dataset_entry(...)`.

Public exports were added in `src/autonomous_futures/data/__init__.py`.

## RED → GREEN evidence

Initial focused run before implementation:

```text
pytest tests/unit/test_registry.py -q
ModuleNotFoundError: No module named 'autonomous_futures.data.registry'
exit code: 2
```

After implementation:

```text
pytest tests/unit/test_registry.py -q
3 passed in 0.70s
```

## Dogfood evidence

The registry was built in a temporary output directory from real cached Phase 1 kline inputs:

```text
research/data/BTCUSDT-5m.csv
research/data/ETHUSDT-5m.csv
research/data/SOLUSDT-5m.csv
```

Each input was passed through the existing real `build_kline_dataset(...)` path, producing real `DatasetManifest` hashes. A real public unsigned `/fapi/v1/exchangeInfo` response was also parsed into the existing immutable exchange-filter snapshot.

```text
registry_entries: 4
kline_entries: 3
exchange_filter_entries: 1
registry_hash: 0dd0c1093b58a3ac7c983ba051fa5f686bddbb181d691f6ef768af356b17fba9
btc_manifest_hash: 7d05c928e125c68bb5d7578c0e4b80bc4360fcfa7ffa1c29a344f58888ad58d7
exchange_snapshot_hash: bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb
persisted: true
```

The temporary output was removed after the probe. Exact BTC lookup and registry persistence/readback succeeded.

## Current boundary and next slice

The registry contract supports `funding_rate` and `mark_price`, and unit tests validate both kinds. However, Phase 1j currently provides canonicalization/alignment in memory only; it does not yet provide persisted funding/mark-price artifact writers and manifests. No fake artifact references were inserted into dogfood evidence.

The next safe slice is therefore **Phase 1m: persisted funding/mark-price canonical artifacts**, followed by registering those real hashes in the dataset registry. API integration and paper execution remain deferred.

## Verification

```text
pytest -q
65 passed in 2.55s

ruff check
All checks passed!

ruff format --check
40 files already formatted

mypy src
Success: no issues found in 21 source files

uv lock --check
pass

compileall
pass

git diff --check
pass

secret scan
No findings
```
