# Phase 3i Verification — Immutable Prepared Learner-Run Persistence

**Status: GREEN**

**Scope:** persisted read/write boundary for prepared learner-run provenance

**Safety boundary:** cached-only, prepared-only, write-once, no training or execution authority

## Contract

Phase 3i adds verified persistence for the existing prepared-only `LearnerRun`:

- `read_learner_run(path)` validates the JSON domain contract and recomputes `run_hash`;
- `write_learner_run(path, run)` validates the content hash before persistence;
- parent directories are created only for the requested local artifact path;
- persistence uses an atomic temporary file plus exclusive link creation;
- identical rewrites are idempotent;
- conflicting rewrites are rejected as immutable-path violations;
- malformed, missing, or tampered runs fail closed.

The prepared-run constructor remains in-memory and side-effect-free. This phase only
adds the separate persistence boundary required by the read-only evidence API and the
Phase 3h training-evidence envelope.

## TDD Evidence

RED was observed before implementation:

```text
ImportError: cannot import name 'read_learner_run' from
'autonomous_futures.research.learner_runs'
```

Focused GREEN tests:

```text
9 passed
```

Coverage includes:

1. verified persisted readback;
2. repeated identical write idempotency;
3. prepared-only safety fields preserved;
4. content-hash mismatch rejection before write;
5. conflicting audit rewrite rejection;
6. tampered persisted hash rejection;
7. malformed JSON rejection;
8. missing run rejection;
9. Phase 3h evidence helper now uses the shared persisted-run writer/reader.

## Safety Assertions

Persisted runs remain exactly:

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

No training trigger, model generation, metrics, qualification, promotion, paper
activation, exchange client, signed request, or order route was added.

## Verification Results

| Gate | Result |
|---|---:|
| Focused learner-run/evidence tests | 9 passed |
| Backend full pytest | 203 passed |
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

- `src/autonomous_futures/research/learner_runs.py`
  - verified run reader;
  - atomic write-once run writer;
  - public persistence exports.
- `src/autonomous_futures/research/learner_training_evidence.py`
  - uses the shared persisted run verifier.
- `src/autonomous_futures/research/__init__.py`
  - public run persistence exports.
- `tests/unit/test_learner_runs.py`
  - persistence, immutability, tamper, malformed, and missing-run coverage.
- `tests/unit/test_learner_training_evidence.py`
  - uses the real run writer in evidence fixtures.

Phase 3i makes prepared provenance durable and verifiable. It does not imply that
training completed, that a model is useful, that any candidate is qualified, or that
paper/live execution is authorized.
