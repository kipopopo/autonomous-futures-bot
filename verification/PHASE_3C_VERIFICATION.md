# Phase 3c Verification — Cached-Only Learner Evaluation Boundary

**Status:** GREEN.
**Scope:** In-memory, cached-only learner evaluation adapter bound to an
immutable `LearnerArtifact`. No learner training, model mutation, metrics,
promotion, paper activation, execution, filesystem loading, network access, or
exchange access was added.

## Contract

`CachedOnlyLearnerEvaluatorAdapter` accepts only explicit
`LearnerEvaluationWindow` instances containing an in-memory OHLC frame.

Each window is bound to:

- learner ID;
- candidate ID;
- candidate artifact hash;
- symbol;
- bundle hash;
- dataset-registry hash;
- UTC half-open time range.

The adapter verifies every binding before invoking the evaluator callback. It
reuses the existing canonical closed 5m cached-window validator, requiring exact
contiguous coverage and OHLC columns.

The callback receives:

```text
LearnerArtifact
isolated deep-copied pandas DataFrame
LearnerEvaluationWindow
```

The callback must return only identity/row-count evidence for this phase:

```text
window_id
learner_id
candidate_id
symbol
rows_evaluated
```

No learner metrics or model output claims are produced.

## Safety fields

The in-memory `LearnerEvaluationRun` preserves:

```text
data_source="cached_only"
exchange_access=false
```

The adapter has no loader, filesystem path, HTTP client, exchange client, order
route, promotion method, or paper activation method.

## TDD

Added `tests/unit/test_learner_evaluation.py`.

RED was confirmed before implementation:

```text
ModuleNotFoundError: No module named
'autonomous_futures.research.learner_evaluation'
```

Focused GREEN result:

```text
5 passed
```

Covered behavior:

1. deterministic evaluation hash across input ordering and audit timestamps;
2. deep-copy isolation from source windows and callback mutation;
3. exact learner/candidate/bundle/dataset binding;
4. unknown-symbol rejection before callback;
5. callback result identity verification;
6. exact contiguous closed-bar coverage;
7. gap and shifted-range rejection;
8. empty-run rejection;
9. non-UTC window rejection;
10. invalid zero-row result rejection.

## Implementation

Added:

- `src/autonomous_futures/research/learner_evaluation.py`
  - `LearnerEvaluationWindowSpec`;
  - `LearnerEvaluationWindow`;
  - `LearnerWindowEvaluation`;
  - `LearnerEvaluationRun`;
  - `CachedOnlyLearnerEvaluatorAdapter`;
  - deterministic in-memory evaluation hash.
- public exports in `src/autonomous_futures/research/__init__.py`.

The existing candidate-oriented `CachedOnlyEvaluatorAdapter` remains unchanged;
learner evaluation uses a separate adapter so qualification metrics and learner
readiness cannot be conflated.

## Verification

```text
Backend pytest: 182 passed in 5.07s
Ruff check: passed
Ruff format --check: 77 files already formatted
Mypy: Success, no issues found in 43 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
```

No frontend/browser gate was needed because Phase 3c is a backend-only in-memory
boundary with no API or UI change. No persisted learner model or evaluation run
was created in the repository.
