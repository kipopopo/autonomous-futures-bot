# Phase 2b Verification — Storage-backed Artifact Inspection

**Status:** GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Read-only metadata/artifact verification. No credentials, authenticated exchange requests, order endpoints, execution authority, or live/paper position state.

## Delivered contract

Added:

```text
GET /api/v1/dataset/components
```

The endpoint verifies every component bound to the persisted dataset bundle before returning metadata. It does not return Parquet rows or expose mutation/execution controls.

## Artifact verification boundary

For each bundle component, the verifier:

1. resolves `artifact_ref` only as a relative POSIX path under the configured artifact root;
2. rejects traversal, absolute references, backslash path ambiguity, missing files, and root escapes;
3. validates the artifact's native immutable manifest/snapshot hash;
4. compares the manifest/snapshot identity against the persisted registry entry;
5. verifies referenced content hashes:
   - kline manifest source-file hashes;
   - funding/mark-price Parquet artifact SHA-256;
   - exchange-filter snapshot file hash;
6. returns only typed inspection metadata.

Supported persisted formats:

```text
kline             → DatasetManifest + all source-file hashes
funding_rate      → DerivativesArtifactManifest + Parquet SHA-256
mark_price        → DerivativesArtifactManifest + Parquet SHA-256
exchange_filters  → ExchangeFilterSnapshot + snapshot/file hashes
```

Incomplete or tampered artifact roots fail closed with:

```text
HTTP 503
{"detail": "dataset artifact integrity verification failed"}
```

## TDD evidence

Initial RED run:

```text
ModuleNotFoundError: No module named 'autonomous_futures.api.artifacts'
```

Focused GREEN result:

```text
9 passed in 0.86s
```

Focused coverage includes:

- kline manifest and all source-file hash verification;
- funding manifest and Parquet hash verification;
- exchange-filter snapshot hash verification;
- missing artifact fail-closed behavior;
- incomplete storage root API behavior;
- registry/component identity binding.

## Actual localhost smoke

A temporary real catalog was built and persisted with:

```text
1 × 5m kline manifest
1 × 15m context manifest
1 × funding-rate artifact + manifest
1 × mark-price artifact + manifest
1 × exchange-filter snapshot
```

An actual Uvicorn process was started on `127.0.0.1`, then exercised over HTTP:

```text
health: 200
components: 200
component_count: 5
kinds: exchange_filters, funding_rate, kline, kline, mark_price
```

The temporary artifact root and smoke script were deleted after verification.

## Full verification

```text
pytest -q
86 passed in 2.81s

ruff check
All checks passed!

ruff format --check
50 files already formatted

mypy src
Success: no issues found in 27 source files

uv lock --check
pass

compileall
pass

git diff --check
pass

secret scan
No findings
```

## Files changed

```text
src/autonomous_futures/api/__init__.py
src/autonomous_futures/api/app.py
src/autonomous_futures/api/artifacts.py
tests/unit/test_artifact_storage.py
```

## Safety and deployment status

- API remains read-only.
- No authenticated exchange client was added.
- No order endpoint was added.
- No database runtime or frontend was started.
- No VPS deployment was performed.
- No credentials were added or used.
