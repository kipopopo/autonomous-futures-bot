# Phase 2a Verification — Read-only FastAPI Dataset API

**Status:** GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Metadata-only API. No credentials, authenticated exchange requests, order endpoints, execution authority, or live/paper position state.

## Delivered contract

Added a read-only FastAPI vertical slice:

```text
GET /health
GET /api/v1/dataset/bundle
GET /api/v1/dataset/registry
```

The API factory accepts explicit persisted bundle/registry paths, or reads:

```text
AFBOT_DATASET_BUNDLE_PATH
AFBOT_DATASET_REGISTRY_PATH
```

The default app remains importable without a dataset deployment. Dataset routes fail closed with HTTP 503 when the catalog is missing, malformed, tampered, or not registry-bound.

## Integrity boundary

Before returning dataset metadata, the catalog verifier:

1. verifies the persisted registry hash;
2. verifies the persisted bundle hash;
3. requires `bundle.registry_hash == registry.registry_hash`;
4. checks every bundle component against the persisted registry entry identity and full value;
5. returns metadata only—no Parquet rows and no order/execution fields.

The health response explicitly declares:

```json
{
  "status": "ok",
  "service": "autonomous-futures-data-api",
  "paper_safe": true,
  "execution_authority": false
}
```

There is no POST order route. `POST /api/v1/dataset/bundle` returns `405`, and `GET /api/v1/order` returns `404`.

## TDD evidence

Initial RED run before API package implementation:

```text
ModuleNotFoundError: No module named 'autonomous_futures.api'
```

Focused GREEN result:

```text
4 passed in 2.61s
```

Focused tests cover:

- paper-safe health boundary;
- no write/order route surface;
- verified bundle metadata response;
- verified registry metadata response;
- tampered bundle fail-closed behavior with HTTP 503.

## Full verification

```text
pytest -q
81 passed in 2.61s

ruff check
All checks passed!

ruff format --check
48 files already formatted

mypy src
Success: no issues found in 26 source files

uv lock --check
pass

compileall
pass

git diff --check
pass

secret scan
No findings
```

## Actual localhost smoke

A real Uvicorn process was started on loopback with a temporary verified registry/bundle, exercised over HTTP, then terminated and cleaned up:

```text
health: 200
bundle: 200
registry: 200
component_count: 5
paper_safe: True
execution_authority: False
```

The temporary catalog and smoke script were deleted after verification. No generated API data was added to the repository.

## Files added

```text
src/autonomous_futures/api/__init__.py
src/autonomous_futures/api/app.py
src/autonomous_futures/api/catalog.py
tests/unit/test_api.py
```

## Deferred scope

This slice intentionally does not include:

- Parquet row/query endpoints;
- authenticated exchange access;
- order, signal, execution, or account endpoints;
- database runtime;
- frontend/dashboard;
- VPS deployment.
