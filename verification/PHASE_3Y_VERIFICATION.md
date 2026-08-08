# Phase 3Y Verification — Immutable Metric Quality Decision Persistence

## Status

**GREEN — Phase 3Y scope verified locally.**

This phase persists `LearnerMetricQualityDecisionEvidence` as a separate immutable artifact after the Phase 3X in-memory decision boundary.

It does not mutate metric evaluation runs or metric-quality reviews, and it does not qualify a learner, promote a candidate, activate paper trading, or route orders.

## Implemented persistence

Added to:

```text
src/autonomous_futures/research/learner_metric_quality_decision.py
```

Public functions:

```python
read_learner_metric_quality_decision(path)
write_learner_metric_quality_decision(path, evidence)
```

The research package exports both functions through:

```text
src/autonomous_futures/research/__init__.py
```

## Persistence contract

The writer and reader enforce:

- canonical JSON content hashing;
- SHA-256 decision-hash verification;
- deterministic serialization with sorted keys;
- UTC audit timestamp validation through the evidence model;
- atomic temporary-file creation;
- unique temporary filename per write;
- exclusive `os.link` creation of the final path;
- identical-write idempotency;
- conflicting rewrite rejection, including audit-time-only changes;
- cleanup of temporary files after success and link failure;
- fail-closed handling for missing, malformed, and tampered artifacts;
- hash mismatch rejection before filesystem work.

The persisted artifact remains separately bound to:

```text
review ID/hash
metric evaluation run ID/hash
learner/artifact identity
candidate/artifact identity
bundle hash
dataset registry hash
policy ID/hash
observations
gate results
```

The decision hash excludes only `evaluated_at` and `decision_hash`, so identical evidence and policy evaluated at different audit times retain the same content hash while the persisted records remain immutable and conflict-safe.

## Safety boundary

The persisted decision evidence retains:

```text
status="evaluated"
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The implementation contains no credential, network, authenticated exchange client, order route, promotion mutation, paper activation or training call.

This artifact is quality-policy evidence only. `passed` is not `qualified`, `promoted`, `paper-live`, `profitable`, or `executable`.

## TDD evidence

RED:

```text
ImportError: read_learner_metric_quality_decision was not available
```

GREEN:

```text
26 passed in 1.31s
```

Persistence tests cover:

- verified round trip;
- identical write idempotency;
- immutable conflict on changed audit time;
- tampered hash rejection;
- malformed JSON rejection;
- missing path handling;
- pre-write hash mismatch rejection;
- temporary-file cleanup after link failure;
- canonical decision hash preservation.

## Verification commands and results

Focused metric/evidence suite:

```text
unset PYTHONPATH; uvx --from 'uv==0.12.2' uv run --locked pytest -q tests/unit/test_learner_metric_evaluation.py
26 passed in 1.31s
```

Related regression:

```text
55 passed in 2.19s
```

Full backend suite:

```text
unset PYTHONPATH; uvx --from 'uv==0.12.2' uv run --locked pytest -q
254 passed in 8.24s
```

Static and reproducibility gates:

```text
Ruff: All checks passed!
Format: 98 files already formatted
Mypy: Success: no issues found in 56 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
Safety scan: 0 credential/network/exchange/order findings
```

## Explicitly out of scope

Phase 3Y does not:

- expose an API or UI endpoint;
- load or persist learner qualification evidence;
- update candidate state;
- promote or reject a learner candidate for trading;
- activate paper execution;
- grant execution authority;
- access Binance authentication or order endpoints;
- perform actual learner training or model generation.

The next downstream boundary, if required, must load this persisted artifact through a separate verified reader and retain the separation between metric-quality evidence, learner qualification, promotion authority, paper activation and order authority.
