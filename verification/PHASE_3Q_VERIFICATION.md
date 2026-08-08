# Phase 3q Verification — Persisted Cached-only Learner Evaluation Evidence

**Status:** GREEN

## Scope

Phase 3q adds immutable persistence for the existing in-memory `LearnerEvaluationRun`. The slice records deterministic evaluation provenance only; it does not create model-quality metrics, run training, qualify a learner, promote a candidate, activate paper trading, or route orders.

## Layman summary

### Sudah dibuat

- Existing cached-only learner evaluation runs can now be persisted as JSON.
- A persisted run is accepted only when its canonical content hash matches the stored `evaluation_hash`.
- The writer is atomic and write-once:
  - identical evidence is idempotent;
  - changed evidence cannot overwrite the existing path.
- Reads fail closed for missing, malformed, or tampered evidence.
- Audit timestamp changes do not change the deterministic content hash, but a changed complete record is still rejected at an immutable path.
- The persisted contract preserves cached-only and non-authoritative safety fields.

### Belum dibuat

- Actual learner model-quality metrics or a default ML evaluator.
- Automatic training, reviewer invocation, qualification, promotion, or paper activation.
- Live trading, order routing, authenticated exchange access, or execution authority.
- API/UI exposure for evaluation-run evidence.

## Technical implementation

### `src/autonomous_futures/research/learner_evaluation.py`

Added:

- `learner_evaluation_content_hash(...)` for canonical verification;
- `read_learner_evaluation_run(...)`;
- `write_learner_evaluation_run(...)`.

The persistence contract:

- canonical JSON hash excludes only `evaluated_at` and `evaluation_hash`;
- malformed/invalid JSON maps to `DataQualityError`;
- missing paths map to `FileNotFoundError`;
- hash mismatch maps to `DomainViolation`;
- existing conflicting content maps to immutable-path `DomainViolation`;
- writes use a temporary file plus exclusive hard-link creation;
- successful writes are read back and verified.

### Public exports

The new hash/read/write functions are exported through:

```text
src/autonomous_futures/research/__init__.py
```

No API route, frontend component, configuration, exchange client, credential path, or execution module was changed.

## Safety contract

Persisted evaluation runs retain:

```text
data_source = "cached_only"
exchange_access = false
```

The existing learner artifact and candidate bindings remain recorded as exact hashes and identities. This evidence does not grant:

```text
promotion_state = "promoted"
paper_activation = true
execution_authority = true
```

## TDD evidence

RED was confirmed before implementation: test collection failed because `read_learner_evaluation_run` and `write_learner_evaluation_run` did not exist.

GREEN coverage verifies:

- verified persistence round-trip;
- identical write idempotency;
- changed audit timestamp preserving content hash;
- conflicting immutable rewrite rejection;
- tampered hash rejection;
- missing evidence handling.

## Verification results

- Focused learner evaluation/related suites: **29 passed in 1.39s**.
- Full backend suite: **228 passed in 5.62s**.
- Ruff check: **All checks passed!**
- Ruff format: **92 files already formatted**.
- Mypy: **Success: no issues found in 51 source files**.
- `uv lock --check`: passed.
- `compileall`: passed.
- `git diff --check`: passed.
- Changed-diff safety scan: **0 findings** for credential, signed-request, order, `execution_authority=true`, or `paper_activation=true` patterns.

Frontend/browser verification was not applicable because Phase 3q changes no API or frontend files.

## Boundary statement

Phase 3q makes evaluation provenance durable and verifiable. It does not claim that a learner is accurate, profitable, qualified, promoted, paper-live, live, or executable.
