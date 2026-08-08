# Phase 3U Verification — Caller-supplied Observed-only Learner Metric Quality Review

## Status

**GREEN — Phase 3U scope verified locally.**

This phase adds a narrow quality-review evidence builder over a verified persisted `LearnerMetricEvaluationRun`.

```text
verified persisted metric run
→ explicit caller-supplied reviewer per metric window
→ observed_only review evidence
```

## Implemented

- Added `LearnerMetricQualityReviewMetric` with finite `Decimal` observations.
- Added `LearnerMetricQualityReviewWindowResult` with sorted, unique metric IDs and exact window/symbol identity.
- Added `LearnerMetricQualityReviewEvidence` with:
  - exact learner/candidate/artifact/bundle/dataset bindings;
  - source metric evaluation run ID and content hash;
  - deterministic sorted window observations;
  - `status="completed"`;
  - `review_conclusion="observed_only"`;
  - `data_source="cached_only"`;
  - `exchange_access=false`;
  - `promotion_state="unpromoted"`;
  - `paper_activation=false`;
  - `execution_authority=false`.
- Added `execute_learner_metric_quality_review(...)`.
- The executor reuses the Phase 3T verified loader, passes deep-copied run/window inputs to the caller reviewer, validates returned evidence, rejects identity drift, and computes a canonical SHA-256 content hash.
- Exported the Phase 3U types and functions from `autonomous_futures.research`.

## Tests

Focused Phase 3U/metric suite:

```text
11 passed in 0.88s
```

Related learner evidence regression:

```text
35 passed in 1.18s
```

Full backend regression:

```text
239 passed in 4.60s
```

Coverage includes:

- verified persisted metric input reaches the explicit reviewer;
- reviewer callback receives isolated deep copies;
- reviewer mutation does not alter persisted metric evidence;
- observed-only safety fields remain fixed;
- exact metric-evaluation hash binding is preserved;
- deterministic review hash is unchanged across audit timestamps;
- callback window identity drift is rejected;
- non-finite reviewer output is rejected before evidence is returned.

## Static and repository gates

```text
Ruff: All checks passed!
Format: 96 files already formatted
Mypy: Success: no issues found in 54 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
```

## Safety boundary

This phase does **not**:

- recompute learner performance metrics;
- load OHLCV or model data;
- call a network or exchange client;
- place, modify, or reconcile orders;
- qualify or reject a learner candidate;
- promote a candidate;
- activate paper or live trading;
- grant execution authority;
- add an API or frontend mutation/readiness claim;
- persist a review artifact to a new filesystem path.

The review evidence is returned in memory and is explicitly observational. A later persistence phase must add its own write-once, atomic, hash-verified artifact boundary before this output is treated as durable evidence.

## Browser dogfood

Not applicable. Phase 3U changes backend research-domain contracts only; no API or frontend files were changed.

## Conclusion

Phase 3U successfully creates a caller-supplied, observed-only review evidence boundary over verified cached-only learner metric evidence. It remains separate from qualification, promotion, paper activation, live trading, and order routing.
