# Phase 3f Verification — Explicit Learner Training/Output Artifact Boundary

**Status:** GREEN.
**Scope:** Explicit trainer callback boundary that produces one verified immutable learner model artifact.
No default trainer, network/exchange access, metrics, promotion, paper activation, or execution authority is introduced.

## Contract delivered

Added `src/autonomous_futures/research/learner_training.py`:

- `LearnerTrainingOutput` explicit output contract;
- `LearnerTrainer` callback type;
- `execute_learner_training(...)` boundary;
- non-empty model bytes requirement;
- relative POSIX model artifact path guard;
- explicit model family and learner version;
- SHA-256 computed by the boundary, not trusted from callback metadata;
- isolated deep-copied input frames passed to the callback;
- exact prepared-run, learner-artifact, candidate, window, symbol, feature, and range binding;
- atomic/write-once model-byte persistence;
- existing immutable `LearnerArtifact` writer used for JSON artifact persistence;
- idempotent identical output;
- conflicting model bytes rejected;
- cleanup of a newly-created model file when artifact persistence fails.

The boundary has no built-in model or training algorithm. Training only occurs when the caller explicitly supplies a trainer callback.

## TDD evidence

RED was observed before implementation:

```text
ModuleNotFoundError: No module named
'autonomous_futures.research.learner_training'
```

Focused GREEN tests:

```text
3 passed
```

Coverage includes:

1. explicit callback receives prepared run and isolated frames;
2. callback mutation cannot change cached input windows;
3. model bytes hash exactly to the persisted artifact hash;
4. persisted model and JSON artifact can be verified by existing read path;
5. identical output is idempotent;
6. conflicting model bytes at an immutable model reference are rejected;
7. unsafe model references are rejected;
8. prepared-run binding tampering is rejected.

## Full verification

```text
pytest: 193 passed in 3.86s
Ruff: passed
Format: 83 files already formatted
Mypy: Success: no issues found in 46 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
secret scan: 0 findings
execution token scan: none
```

## Safety decision

This phase permits an explicitly supplied trainer callback to produce a model artifact, but it does **not** claim model quality or readiness. The resulting learner artifact remains:

```text
state="testing"
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
data_source="cached_only"
exchange_access=false
```

No metrics, qualification evidence, promotion transition, paper execution, or order route is created.
