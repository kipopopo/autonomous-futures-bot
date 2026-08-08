# Phase 3X Verification — Explicit Metric Quality Policy Decision Evidence

## Status

**GREEN — Phase 3X scope verified locally.**

This phase adds a typed, deterministic, in-memory quality-policy decision boundary over the verified persisted metric-quality review input from Phase 3W.

It does **not** persist a new decision artifact, qualify a learner, promote a candidate, activate paper trading, or route orders.

## Implemented boundary

New module:

```text
src/autonomous_futures/research/learner_metric_quality_decision.py
```

Public contracts include:

- `LearnerMetricQualityPolicy`
- `LearnerMetricQualityPolicyGate`
- `LearnerMetricQualityObservation`
- `LearnerMetricQualityGateResult`
- `LearnerMetricQualityDecisionEvidence`
- `build_learner_metric_quality_decision(...)`
- `evaluate_persisted_learner_metric_quality(...)`

The persisted evaluator first calls the Phase 3W verified loader:

```text
persisted metric evaluation run
→ persisted metric quality review
→ Phase 3W full provenance/hash/window verification
→ explicit metric quality policy decision
```

## Decision contract

Policy gates support finite `Decimal` thresholds and explicit comparators:

```text
gte
lte
eq
```

The decision evaluates every declared policy gate for every verified review window. It also evaluates a minimum-window gate.

Decision values are deliberately separate from learner qualification:

```text
passed
failed
```

`passed` means only that the supplied metric-quality policy gates passed over the observed evidence. It does not mean `qualified`, `promoted`, `paper-live`, `profitable`, or `executable`.

Missing policy metrics produce an explicit failing gate with:

```text
reason_code="metric_missing"
```

They are not converted to zero, fabricated values, or an inferred learner-quality failure outside the declared policy result.

## Integrity and determinism

The boundary verifies the persisted review content hash before building a decision. It records and binds:

- metric quality review ID/hash;
- metric evaluation run ID/hash;
- learner ID/artifact hash;
- creator candidate ID/artifact hash;
- bundle hash;
- dataset registry hash;
- policy ID/hash;
- per-window observations;
- per-window gate results.

The policy hash is canonical SHA-256 over the policy payload. The decision hash is canonical SHA-256 over the decision payload excluding only `evaluated_at` and `decision_hash`.

Repeated evaluation with identical evidence and policy but different audit timestamps produced the same decision hash.

## Safety boundary

The decision evidence remains explicitly:

```text
status="evaluated"
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The new module contains no credential, network, exchange client, filesystem writer, order route, paper activation, or promotion mutation.

No model training or actual learner generation was performed.

## TDD evidence

RED:

```text
ImportError: learner_metric_quality_decision module was not available
```

GREEN:

```text
22 passed in 1.01s
```

Covered behaviors include:

- passed policy decision over a verified persisted review;
- below-threshold failure;
- missing-metric failure;
- policy and decision hash determinism;
- tampered review rejection before decision construction;
- non-UTC audit timestamp rejection;
- safety-state preservation.

## Verification commands and results

Focused suite:

```text
unset PYTHONPATH; uvx --from 'uv==0.12.2' uv run --locked pytest -q tests/unit/test_learner_metric_evaluation.py
22 passed in 1.01s
```

Related regression:

```text
51 passed in 1.60s
```

Full backend suite:

```text
250 passed in 4.95s
```

Static and reproducibility gates:

```text
Ruff: All checks passed!
Format: 98 files already formatted
Mypy: Success: no issues found in 56 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
Safety scan: 0 findings
```

## Explicitly out of scope

Phase 3X does not:

- persist metric-quality decision evidence;
- call `LearnerQualificationEvidence`;
- set any candidate state;
- qualify or reject a learner candidate for promotion;
- activate paper execution;
- grant execution authority;
- use authenticated exchange access;
- place, cancel, or manage orders.

A future persistence phase must treat this decision as a separate immutable artifact rather than mutating `LearnerMetricQualityReviewEvidence` or `LearnerMetricEvaluationRun`.
