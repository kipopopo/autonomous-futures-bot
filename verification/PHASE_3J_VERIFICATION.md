# Phase 3j Verification — Read-only API Shared Learner-Run Verification

**Status: GREEN**

**Scope:** converge the read-only Learner API on the immutable persisted-run reader

**Safety boundary:** GET-only, cached-only, fail-closed, no training or execution authority

## Contract change

`src/autonomous_futures/api/learner.py` no longer parses `LearnerRun` JSON or recomputes
its hash independently. `load_verified_learner_run(...)` now calls the shared
`read_learner_run(path)` persistence verifier from the research boundary.

This removes duplicate hash/JSON validation logic between the persistence layer,
Phase 3h evidence reader, and the read-only API. The existing exact run-to-learner
artifact binding remains enforced after the shared read succeeds.

The API behavior remains observational:

- missing run: `404 learner run unavailable`;
- malformed, tampered, or invalid-hash run: `503 learner run integrity verification failed`;
- valid prepared run: verified metadata only;
- POST/PUT/PATCH/DELETE learner routes remain unavailable.

## TDD / Regression Evidence

The focused API fixture now persists runs through `write_learner_run(...)`, rather than
ad-hoc JSON. Added coverage for malformed persisted run rejection.

Focused tests:

```text
15 passed
```

Coverage includes:

1. verified prepared-run HTTP response;
2. missing-run unavailable response;
3. tampered-hash fail-closed response;
4. malformed persisted-run fail-closed response;
5. GET-only route behavior;
6. shared persisted-run writer/reader integration;
7. exact run-to-artifact binding remains enforced.

## Safety Assertions

The exposed run model remains:

```text
status="prepared"
output_artifact_hash=null
training_metrics=null
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

No model training, metrics generation, qualification, promotion, paper activation,
exchange client, signed request, or order route was added.

## Verification Results

| Gate | Result |
|---|---:|
| Focused API/run/evidence tests | 15 passed |
| Backend full pytest | 204 passed |
| Ruff check | passed |
| Ruff format | 87 files already formatted |
| Mypy | passed — no issues in 48 source files |
| `uv lock --check` | passed |
| Python compileall | passed |
| `git diff --check` | passed |
| Public import smoke | passed |
| Frontend Vitest | 32 passed |
| Frontend lint | passed — 0 warnings, 0 errors |
| Frontend production build | passed |

## Files

- `src/autonomous_futures/api/learner.py`
  - shared `read_learner_run(...)` integration;
  - duplicate run JSON/hash verification removed.
- `tests/unit/test_learner_api.py`
  - real persisted-run writer fixture;
  - malformed-run HTTP regression.

Phase 3j is a verification-boundary convergence only. It does not imply that any
learner has completed training, that a model is useful, that a candidate is
qualified, or that paper/live execution is authorized.
