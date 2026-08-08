# Phase 3AB Verification — Verified Metric-Quality Qualification Evidence

## Status

**GREEN — Phase 3AB scope verified locally.**

Phase 3AB introduces a separate **in-memory learner qualification evidence boundary** whose sole valid upstream path is:

```text
persisted metric evaluation
→ verified observed-only metric-quality review
→ verified persisted metric-quality decision
→ verified qualification-input handoff
→ policy-bound qualification evidence
```

It does **not** persist its output in this phase. Qualification-evidence persistence, read-only API/UI exposure, promotion, paper activation, and execution authority remain separate future phases.

## Model-tier decision

Runtime used:

```text
model: gpt-5.6-terra
provider: openai-codex
```

The phase was assessed as medium-high complexity: it introduces actual qualification semantics while preserving distinct source-policy, qualification-policy, provenance, and safety-state contracts. `terra` was appropriate for this bounded backend evidence slice. No silent model routing occurred.

## Delivered contract

New backend module:

```text
src/autonomous_futures/research/learner_metric_quality_qualification.py
```

New public types/functions:

```python
LearnerMetricQualityQualificationPolicy
LearnerMetricQualityQualificationGateResult
LearnerMetricQualityQualificationEvidence
build_verified_learner_metric_quality_qualification_evidence(...)
learner_metric_quality_qualification_policy_content_hash(...)
learner_metric_quality_qualification_content_hash(...)
```

The builder accepts persisted decision/review/metric paths plus explicit learner, candidate, source policy, qualification policy, and UTC evaluation timestamp. It can only construct its input through:

```python
build_verified_learner_metric_quality_qualification_input(...)
```

That handoff delegates to the Phase 3Z verified decision loader, so the builder does not independently read raw JSON or duplicate its full-chain verification behavior.

## Separate decision semantics

The source metric-quality decision remains copied as:

```text
source_decision = "passed" | "failed"
```

The Phase 3AB decision is separate:

```text
qualification decision = "qualified" | "rejected"
```

A qualification policy is required and has its own canonical hash. It binds to the expected source metric-quality policy ID/hash and declares `minimum_windows >= 1`.

The two canonical gates are:

```text
metric_quality_decision: source_decision must be "passed"
minimum_windows: verified input windows_evaluated >= policy minimum_windows
```

Therefore a source decision of `passed` is **not** automatically `qualified`. A passed source decision with insufficient verified windows produces durable-shaped, in-memory `rejected` evidence. A source-policy ID/hash mismatch is an integrity failure, not a fabricated rejection.

## Provenance binding

Evidence binds exactly to:

```text
qualification input ID/hash
decision ID/hash
review ID/hash
metric-evaluation run ID/hash
learner ID/artifact hash
candidate ID/artifact hash
bundle hash
dataset-registry hash
source policy ID/hash
qualification policy ID/hash
source decision
verified window count
```

Both policy and evidence hashes use canonical sorted JSON and SHA-256. The qualification content hash excludes only `evaluated_at` and `qualification_hash`, so equivalent evidence is deterministic across audit timestamps.

## Safety boundary

The new module is backend-only and in-memory. It has no persistence functions, raw artifact reader/writer, HTTP client, exchange client, credential handling, order route, candidate/registry mutation, `learner_qualification.py` call, paper activation, promotion transition, or execution authority.

Fixed evidence fields remain:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

`qualified` means only that this explicit metric-quality qualification policy's evidence gates passed. It is not a profitability claim, promotion, paper-trading permission, or execution permission.

## Strict TDD evidence

### RED

Focused test run before implementation:

```text
ModuleNotFoundError:
  autonomous_futures.research.learner_metric_quality_qualification
exit code: 2
```

The failure was the missing Phase 3AB module expected by the new tests.

### Added focused coverage

`tests/unit/test_learner_metric_evaluation.py` now covers:

1. qualified evidence from a verified passed source decision;
2. deterministic qualification hashes across two UTC audit timestamps;
3. independent source-file byte preservation for decision, review, and metric artifacts;
4. rejected evidence when source decision is `failed`;
5. rejected evidence when a passed source decision fails the distinct minimum-window qualification gate;
6. fail-closed source-policy binding/hash drift;
7. non-UTC evaluation timestamp rejection;
8. preserved `unpromoted` and no-execution safety state.

## Verification results

### Focused

```text
37 passed in 4.00s
```

### Related provenance regression

```text
66 passed in 5.76s
```

Coverage included metric evaluation, existing learner qualification, learner quality review, training evidence, learner evaluation, and learner-run contracts.

### Full locked suite

```text
265 passed in 15.37s
```

### Static and reproducibility gates

```text
ruff check: All checks passed
ruff format --check: 101 files already formatted
mypy src: Success: no issues found in 59 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
```

### Safety scan

The Phase 3AB module had zero findings for:

```text
credentials / secrets / tokens
HTTP or exchange clients
order endpoints
raw read/write persistence calls
existing learner_qualification module usage
```

### Browser verification

Not applicable: this phase changes only backend in-memory evidence contracts. No API, UI, frontend asset, or HTTP runtime path was added.

## Explicitly deferred

- immutable persistence/readback for Phase 3AB qualification evidence;
- verified persisted qualification-evidence loader;
- API/UI exposure;
- candidate lifecycle mutation;
- promotion;
- paper activation;
- live/testnet execution authority;
- exchange connectivity or order routing.
