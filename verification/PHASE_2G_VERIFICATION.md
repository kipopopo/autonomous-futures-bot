# Phase 2g Verification — Verified Creator Registry API

**Status:** GREEN.
**Scope:** Read-only API and UI integration for persisted Creator candidate registry metadata.
**Safety boundary:** no generation engine, evaluator, promotion authority, signal engine, order endpoint, authenticated exchange client, or execution authority.

## Contract

The API route is:

```text
GET /api/v1/creator/registry
```

It supports two fail-closed outcomes:

- `404 creator candidate registry unavailable` when no registry has been published;
- `503 creator candidate registry integrity verification failed` when the registry, artifact reference, artifact hash, or entry binding cannot be verified.

A successful response exposes only:

- verified registry hash;
- candidate count;
- candidate ID;
- artifact hash/reference;
- exact `bundle_hash` and `dataset_registry_hash` bindings;
- strategy ID/family/symbol universe;
- `testing` state;
- Creator run ID and timestamp.

Strategy expressions and execution fields are not exposed by the endpoint. The route is GET-only; there are no mutation/order routes.

## Backend implementation

Added:

```text
src/autonomous_futures/api/creator.py
```

The loader verifies:

1. persisted registry content hash;
2. relative artifact reference and root containment;
3. persisted candidate artifact content hash;
4. candidate ID, strategy ID, family, symbols, state, Creator run ID;
5. exact bundle and dataset-registry bindings.

Added API configuration:

```text
AFBOT_CREATOR_CANDIDATE_REGISTRY_PATH
AFBOT_CREATOR_CANDIDATE_ARTIFACT_ROOT
```

## TDD evidence

Initial RED result before implementation:

```text
3 failed
TypeError: create_app() got an unexpected keyword argument
       'creator_candidate_registry_path'
```

GREEN result:

```text
3 passed in 0.87s
```

Backend cases cover:

- verified metadata-only response;
- missing registry unavailable behavior;
- GET-only method boundary;
- tampered artifact fail-closed behavior.

## Real persisted dogfood

Temporary production fixture used the actual dataset and Creator writers/readers:

```text
Dataset components: 5
Dataset kinds: kline, funding_rate, mark_price, exchange_filters
Creator candidates: 1
Candidate state: testing
Temporary cleanup: true
```

Smoke hashes:

```text
bundle_hash:
88cb663557e4df98ba20116efdabfb9ce763cd109975eef4e67c9b892baec74f

dataset_registry_hash:
debc0e056769d35b0c37e28898bd459f6550e7e157691300826de76e7e7088af

creator_registry_hash:
1c360628f4adc3fcc1a38193a69664f4c9d8c9253524ca46907f5cc4a7324434
```

Loopback API smoke:

```text
/health                         → 200
/api/v1/dataset/bundle          → 200, verified=true, component_count=5
/api/v1/dataset/components     → 200, verified=true, component_count=5
/api/v1/creator/registry        → 200, verified=true, candidate_count=1
```

The temporary Uvicorn/Vite processes, fixture root, and fixture script were removed after verification.

## Frontend behavior

The typed API client treats a missing Creator registry as `null`, so verified dataset foundation status remains visible while Creator output correctly stays unavailable. Integrity failures are not converted into fake success data.

When the registry is verified, Creator displays a read-only metadata panel with:

- `REGISTRY VERIFIED`;
- candidate count and registry hash;
- candidate ID;
- family and symbols;
- Creator run ID;
- artifact reference;
- visible `TESTING` state;
- explicit copy that no qualify/promote/signal/execute action is available.

No generate, approve, reject, evaluate, signal, or order control exists.

Browser smoke on `http://127.0.0.1:4173/#creator`:

```text
Creator registry rendered: pass
Candidate TESTING label: pass
No unsafe action controls: pass
Console errors: 0
JavaScript errors: 0
Visual overflow/broken layout: not observed
GMT+8 presentation: pass
```

Port `5173` was unavailable with Windows `EACCES`; the equivalent smoke ran successfully on temporary port `4173` and was cleaned up.

## Quality gates

```text
Backend pytest: 100 passed
Frontend Vitest: 9 passed
Ruff check: passed
Ruff format: passed (51 files formatted)
Mypy: Success: no issues found in 31 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 67 files, 0 findings
oxlint: 0 warnings, 0 errors
Vite production build: passed
```

## Status boundary

This phase only makes persisted candidate metadata observable after verification. It does not mean any candidate is promoted, live, profitable, executable, or approved for paper/live trading.
