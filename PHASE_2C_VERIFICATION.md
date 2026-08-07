# Phase 2c Verification — Bounded Read-only Dataset Query API

**Status:** GREEN.
**Execution mode:** Local Windows project environment.
**Safety boundary:** Read-only verified artifact queries. No credentials, authenticated exchange requests, order endpoints, execution authority, or live/paper position state.

## Delivered contract

Added:

```text
GET /api/v1/dataset/rows
```

Required selectors:

```text
kind:     kline | funding_rate | mark_price
symbol:   uppercase exchange symbol
interval: 5m | 15m for kline/mark_price; omitted for funding_rate
start:    UTC-aware range start
end:      UTC-aware exclusive range end
limit:    1..1000, default 100
```

The query is half-open:

```text
[start, end)
```

The selected component must be present in the verified bundle and the requested range must fit that component's persisted coverage. Kline coverage accounts for the final closed bar boundary; funding and mark-price preserve their native event/range semantics.

## Reader and serialization behavior

The API reuses the existing canonical readers:

```text
kline        → read_canonical_parquet
mark_price   → read_mark_price_artifact
funding_rate → read_funding_artifact
```

Response values are JSON-safe and deterministic:

- `Decimal` values serialize as strings, preserving exactness;
- UTC timestamps serialize with `Z` suffix;
- pandas/numpy scalar values are normalized;
- unsupported or malformed values fail closed with HTTP 503.

The API verifies the complete bundle-bound artifact set before reading rows. It does not create a parallel persistence or integrity model.

## Guardrails

```text
limit < 1 or limit > 1000  → HTTP 422
result exceeds limit       → HTTP 422
range outside component    → HTTP 422
naive/non-UTC timestamps   → HTTP 422
unknown component          → HTTP 404
missing/tampered artifact  → HTTP 503
POST /api/v1/dataset/rows  → HTTP 405
```

Exchange-filter snapshots remain metadata-only and are intentionally excluded from row queries.

## TDD evidence

Initial RED run:

```text
ModuleNotFoundError: No module named 'autonomous_futures.api.query'
```

Focused GREEN result after the service and route implementation:

```text
13 passed in 0.90s
```

Focused coverage includes:

- exact Decimal and UTC JSON serialization;
- kline half-open filtering;
- component coverage rejection;
- hard result limit rejection;
- missing catalog fail-closed behavior;
- GET-only API boundary;
- artifact inspection and query integration.

## Actual localhost smoke

A temporary complete catalog was persisted with real canonical files for:

```text
1 × 5m primary kline
1 × 15m context kline
1 × funding-rate Parquet artifact
1 × mark-price Parquet artifact
1 × exchange-filter snapshot
```

An actual Uvicorn process was started on `127.0.0.1` and queried over HTTP:

```text
health: 200
kline query: 200
kline rows: 2
kline close values: 100.125, 100.250
mark_price query: 200, rows: 2
funding_rate query: 200, rows: 1
result over limit: 422
POST query route: 405
```

The temporary artifact root and smoke script were deleted after verification.

## Full verification

```text
pytest -q
90 passed in 2.89s

ruff check
All checks passed!

ruff format --check
52 files already formatted

mypy src
Success: no issues found in 28 source files

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
src/autonomous_futures/api/query.py
tests/unit/test_api.py
tests/unit/test_query.py
```

## Safety and deployment status

- API remains read-only.
- No authenticated exchange client was added.
- No order, signal, account, or execution endpoint was added.
- No database runtime or frontend was started.
- No VPS deployment was performed.
- No credentials were added or used.
