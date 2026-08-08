# Phase 3d Verification — Causal Learner Input Materialization

**Status:** GREEN.
**Scope:** Deterministic causal input-frame materialization for the future learner.
No learner training, model metrics, model mutation, promotion, paper activation,
execution, filesystem loading, network access, or exchange access was added.

## Contract

`LearnerInputMaterializer` accepts only explicit in-memory primary and context
frames plus a verified `LearnerArtifact` and its bound
`CreatorCandidateArtifact`.

The materializer verifies:

- learner/candidate identity and artifact-hash binding;
- exact bundle hash and dataset-registry binding through the learner contract;
- requested symbol is inside the learner universe;
- learner feature IDs exactly match the candidate's declared feature IDs;
- primary 5m canonical coverage;
- context 15m canonical coverage through the primary window end;
- context values become available only under `close_time_plus_1ms`;
- cached-only and exchange-disabled safety fields.

The output is a typed `LearnerInputWindow` containing:

- primary timestamp/OHLC columns;
- causal `15m` context columns;
- declared prior-bar feature columns;
- no `signal`, entry, exit, promotion, or execution columns;
- immutable window metadata and row-count binding;
- isolated deep-copy access through `copy_frame()`.

The final context bar must cover the full primary window. This prevents
`merge_asof` from silently carrying a stale last context bar beyond the persisted
context artifact's declared coverage.

## Causality

The existing bounded feature implementation was refactored to expose
`materialize_causal_features(...)` as a single source of truth. The signal
 evaluator now consumes that helper, while the learner input path uses the
feature-only result and never evaluates strategy signals.

Feature values retain prior-bar semantics through the existing `FeatureRef.shift`
contract (`shift >= 1`). A current-candle mutation does not alter the feature on
that same candle, while it correctly affects a later candle when causally
available.

## TDD

Added `tests/unit/test_learner_inputs.py`.

RED was confirmed before implementation:

```text
ModuleNotFoundError: No module named
'autonomous_futures.research.learner_inputs'
```

Focused GREEN result:

```text
4 passed
```

Covered behavior:

1. causal learner input and closed-context freshness;
2. current-candle mutation cannot change same-candle feature value;
3. later-candle feature change remains causal;
4. source-frame deep-copy isolation;
5. learner/candidate binding rejection;
6. unknown-symbol rejection;
7. learner/candidate feature-ID mismatch rejection;
8. insufficient context coverage rejection;
9. no signal columns in learner input output.

## Implementation

Added:

- `src/autonomous_futures/research/learner_inputs.py`
  - `LearnerInputWindowSpec`;
  - `LearnerInputWindow`;
  - `LearnerInputMaterializer`.
- `materialize_causal_features(...)` in
  `src/autonomous_futures/research/feature_signals.py`.
- Public exports in `src/autonomous_futures/research/__init__.py`.

No learner model artifact was generated. No input frame was persisted. This phase
only proves the in-memory causal boundary required before a future learner
implementation.

## Verification

```text
Backend pytest: 186 passed in 3.62s
Ruff check: passed
Ruff format --check: 79 files already formatted
Mypy: Success, no issues found in 44 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 0 findings
Execution token scan: none
```

No frontend/browser gate was needed because Phase 3d is backend-only and adds no
API or UI surface.
