# Phase 3Z Verification — Verified Persisted Metric Quality Decision Loader

## Status

**GREEN — Phase 3Z scope verified locally.**

This phase adds a read-only verified loader for the persisted metric-quality decision artifact from Phase 3Y.

The loader does not qualify a learner, promote a candidate, activate paper trading, or route orders.

## Implemented boundary

New module:

```text
src/autonomous_futures/research/learner_metric_quality_decision_input.py
```

Public function:

```python
load_verified_learner_metric_quality_decision(
    decision_path,
    review_path,
    metric_evaluation_path,
    *,
    learner,
    candidate,
    policy,
)
```

The function is exported through:

```text
src/autonomous_futures/research/__init__.py
```

## Verification chain

The loader performs the following sequence:

```text
metric evaluation run
→ Phase 3T verified metric-run input
→ Phase 3W verified metric-quality review
→ Phase 3Y hash-verified persisted decision
→ policy ID/hash verification
→ deterministic decision recomputation
→ full evidence comparison
```

The supplied learner, candidate and policy remain caller-bound inputs. No filesystem mutation occurs during loading.

## Integrity checks

The loader rejects:

- missing, malformed or tampered metric evaluation evidence;
- missing, malformed or tampered metric-quality review evidence;
- missing, malformed or tampered decision evidence;
- learner/candidate/artifact binding drift;
- metric-run/review window identity drift;
- policy ID drift;
- policy threshold/comparator drift through policy hash mismatch;
- persisted decision gate/observation/decision semantic drift even when the artifact has a newly valid decision hash.

The final semantic check rebuilds the expected decision with the persisted audit timestamp and compares it with the persisted evidence. This prevents a hash-valid but policy-inconsistent decision from entering a downstream boundary.

## Safety boundary

The loader is read-only and preserves the decision artifact's safety fields:

```text
status="evaluated"
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The new module contains no credential, network, exchange client, order route, promotion mutation, paper activation or training call.

A `passed` metric-quality decision remains evidence only. It is not `qualified`, `promoted`, `paper-live`, `profitable`, or `executable`.

## TDD evidence

RED:

```text
ModuleNotFoundError: learner_metric_quality_decision_input was not available
```

Initial GREEN attempt exposed an invalid test setup: it tried to overwrite an immutable decision path. The test was corrected to persist semantic drift at a separate path, preserving the Phase 3Y write-once contract.

Final GREEN:

```text
29 passed in 1.65s
```

Covered behaviors include:

- valid full-chain loader round trip;
- decision/review/metric artifact byte preservation;
- policy ID/hash drift rejection;
- semantic decision drift rejection despite a valid recomputed decision hash;
- existing Phase 3T–3Y integrity and persistence regressions.

## Verification commands and results

Focused suite:

```text
unset PYTHONPATH; uvx --from 'uv==0.12.2' uv run --locked pytest -q tests/unit/test_learner_metric_evaluation.py
29 passed in 1.65s
```

Related regression:

```text
58 passed in 3.44s
```

Full backend suite:

```text
unset PYTHONPATH; uvx --from 'uv==0.12.2' uv run --locked pytest -q
257 passed in 8.90s
```

Static and reproducibility gates:

```text
Ruff: All checks passed!
Format: 99 files already formatted
Mypy: Success: no issues found in 57 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
Safety scan: 0 credential/network/exchange/order findings
```

## Explicitly out of scope

Phase 3Z does not:

- expose an API or UI endpoint;
- call learner qualification policy/evidence;
- mutate candidate state;
- promote or reject a candidate for trading;
- activate paper execution;
- grant execution authority;
- use authenticated Binance access;
- perform learner training or model generation.

The next downstream phase may define how this verified decision is consumed by a separate qualification evidence boundary, but it must retain the distinction between metric-quality policy evidence, learner qualification, promotion authority, paper activation and order authority.
