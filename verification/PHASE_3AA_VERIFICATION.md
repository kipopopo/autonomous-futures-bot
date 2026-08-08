# Phase 3AA Verification — Verified Metric-Quality Qualification Input Handoff

## Status

**GREEN — Phase 3AA scope verified locally.**

This phase adds a narrow, in-memory handoff from a fully verified persisted metric-quality decision to a future qualification boundary.

It does **not** create learner qualification evidence and does not change candidate state.

## Model-tier decision

This phase was completed with the active `gpt-5.6-luna` model.

The complexity is **medium-high but bounded**: the handoff is safety-sensitive, but the verified loader, canonical hashing and binding patterns already exist. A stronger tier should be considered before a future phase that combines this boundary with API/UI, registry batch qualification, actual walk-forward evaluation, promotion state transitions, paper activation or execution authority.

No model switch was performed silently.

## Implemented boundary

New module:

```text
src/autonomous_futures/research/learner_metric_quality_qualification_input.py
```

Public contract:

```python
LearnerMetricQualityQualificationInput
build_verified_learner_metric_quality_qualification_input(...)
learner_metric_quality_qualification_input_content_hash(...)
```

The builder accepts persisted decision/review/metric paths plus caller-bound learner, candidate and policy inputs. It first calls the Phase 3Z verified decision loader, then constructs an in-memory handoff.

## Explicit semantics

The handoff preserves the original metric-quality outcome:

```text
decision = "passed" | "failed"
```

It explicitly prevents qualification interpretation:

```text
status="verified_decision_only"
qualification_status="not_evaluated"
```

Therefore:

```text
passed != qualified
failed != rejected learner
```

The existing `learner_qualification.py` module is not called or modified by this phase.

## Integrity and determinism

The handoff binds:

- decision ID/hash;
- metric-quality review ID/hash;
- metric evaluation run ID/hash;
- learner and learner-artifact hash;
- candidate and candidate-artifact hash;
- bundle and dataset-registry hashes;
- policy ID/hash;
- original decision outcome;
- evaluated window count.

A deterministic input hash is computed over the canonical handoff payload, excluding only `prepared_at` and `input_hash`. Repeated handoff preparation with different UTC preparation timestamps produces the same input hash.

The builder rejects non-UTC `prepared_at` values before creating the handoff.

## Safety boundary

The handoff is in-memory and read-only. It does not persist, mutate or promote anything.

Fixed safety fields:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The new module contains no credential, network, exchange client, order route, learner qualification call, promotion mutation, paper activation or execution authority.

## TDD evidence

RED:

```text
ModuleNotFoundError: learner_metric_quality_qualification_input was not available
```

GREEN:

```text
Focused: 32 passed in 2.67s
Related: 61 passed in 4.68s
```

Covered behaviors include:

- passed decision preserved without qualification;
- failed decision preserved without converting it to learner rejection;
- deterministic handoff hash across preparation timestamps;
- UTC preparation-time validation;
- decision/review/metric source-byte preservation;
- safety-field preservation;
- existing Phase 3T–3Z regression coverage.

## Verification commands and results

Full backend suite:

```text
unset PYTHONPATH; uvx --from 'uv==0.12.2' uv run --locked pytest -q
260 passed in 8.66s
```

Static and reproducibility gates:

```text
Ruff: All checks passed!
Format: 100 files already formatted
Mypy: Success: no issues found in 58 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
Safety scan: 0 credential/network/exchange/order findings
```

Browser dogfood: **not applicable** — backend-only in-memory contract; no API/UI or service route changed.

## Explicitly out of scope

Phase 3AA does not:

- build `LearnerQualificationEvidence`;
- call `build_learner_qualification_evidence`;
- interpret `passed` as `qualified`;
- interpret `failed` as learner rejection;
- evaluate training quality again;
- run walk-forward or trade simulation;
- mutate learner/candidate/registry state;
- persist a new qualification artifact;
- expose API/UI;
- promote or activate paper/live execution;
- grant execution authority;
- use authenticated Binance access.

A later qualification phase must consume this handoff only through an explicit, separately reviewed authority boundary.
