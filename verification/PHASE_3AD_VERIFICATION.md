# Phase 3AD Verification — Verified Persisted Metric-Quality Qualification Evidence Loader

## Status

**GREEN — Phase 3AD scope verified locally.**

Phase 3AD introduces a read-only loader for the Phase 3AC immutable metric-quality qualification evidence artifact.

```text
persisted metric evaluation run
→ verified observed-only quality review
→ verified persisted metric-quality decision
→ verified decision-only qualification handoff
→ deterministic Phase 3AB qualification reconstruction
→ hash-verified persisted Phase 3AC qualification evidence
→ exact full-chain equality verification
```

The loader does not turn qualification evidence into promotion, paper activation, exchange access, or execution authority.

## Model-tier decision

Runtime used:

```text
model: gpt-5.6-terra
provider: openai-codex
```

This phase is a bounded read-only provenance integration. Existing typed contracts, canonical hashes, verified readers, and full-chain loaders made `terra` appropriate. No silent model switch occurred.

## Delivered API

New module:

```text
src/autonomous_futures/research/learner_metric_quality_qualification_evidence_input.py
```

Public API:

```python
load_verified_learner_metric_quality_qualification_evidence(
    qualification_evidence_path,
    decision_path,
    review_path,
    metric_evaluation_path,
    *,
    learner,
    candidate,
    source_policy,
    qualification_policy,
)
```

The API is re-exported from `autonomous_futures.research`.

## Verification order

1. Read Phase 3AC persisted qualification evidence via the shared canonical-hash reader.
2. Bind the persisted qualification-policy ID and complete canonical policy hash to the caller-supplied qualification policy.
3. Rebuild Phase 3AB qualification evidence using the persisted artifact's exact `evaluated_at` value.
4. The Phase 3AB builder re-enters the verified Phase 3AA decision-input boundary, which calls the Phase 3Z verified persisted decision loader, itself verifying the review and metric-evaluation chain.
5. Compare the fully rebuilt evidence with the persisted evidence exactly.
6. Return the persisted typed artifact only when every value matches.

The persisted audit timestamp is used for reconstruction so equality is deterministic while audit time remains excluded from the content hash.

## Fail-closed behavior

The loader rejects rather than infers an outcome when it encounters:

| Condition | Failure boundary |
|---|---|
| Missing/malformed/tampered qualification artifact | Shared Phase 3AC reader |
| Qualification policy ID/hash drift | Explicit qualification policy binding `DomainViolation` |
| Source metric-quality policy drift | Phase 3Z decision policy binding `DomainViolation` |
| Tampered persisted decision | Shared decision reader hash verification `DomainViolation` |
| Review/metric/learner/candidate provenance drift | Existing verified Phase 3Z chain |
| Valid-hash qualification semantic drift | Exact Phase 3AD evidence-binding `DomainViolation` |

A valid qualification artifact hash is therefore insufficient. For example, a newly written artifact with a recomputed valid hash but a different `windows_evaluated` value is rejected because it differs from deterministic reconstruction of its verified upstream chain.

Unavailable or drifted evidence never becomes a fabricated `rejected` result, zero metric, promotion, paper eligibility, or execution permission.

## Safety boundary

The loader is read-only. It does not write a file, train a learner, call a network/exchange client, route an order, mutate a candidate, import the independent `learner_qualification` contract, access a registry, promote a candidate, activate paper trading, or grant authority.

Returned evidence remains constrained to:

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

`qualified` remains only deterministic qualification evidence under its caller-bound policy. It is not a candidate lifecycle transition or trading authorization.

## Strict TDD evidence

### Vertical RED → GREEN

The first full-chain loader test was added before the module existed. Its focused run failed as expected:

```text
ModuleNotFoundError:
  autonomous_futures.research.learner_metric_quality_qualification_evidence_input
exit code: 4
```

After the minimal read-only loader implementation:

```text
1 passed in 2.07s
```

### Qualification-policy boundary RED → GREEN

A policy-drift test was added after deliberately removing the direct policy-binding branch. It failed with the generic evidence-binding error instead of the required policy-binding error:

```text
Expected: qualification policy binding
Actual: metric quality qualification evidence binding is invalid
```

Reinstating the smallest policy ID/hash check produced:

```text
1 passed in 2.10s
```

### Hash-valid semantic-drift RED → GREEN

An exact-equality test used a new immutable path with a recomputed valid qualification hash but altered `windows_evaluated`. After deliberately removing equality enforcement it failed as expected:

```text
Failed: DID NOT RAISE DomainViolation
```

Restoring the smallest expected-versus-persisted comparison produced:

```text
2 passed in 1.52s
```

## Added regression coverage

`tests/unit/test_learner_metric_evaluation.py` now verifies:

1. valid full-chain load and exact evidence equality;
2. byte preservation for qualification, decision, review, and metric-run source files;
3. caller-supplied qualification-policy drift under a stable policy ID;
4. caller-supplied source metric-quality policy drift under a stable policy ID;
5. upstream persisted decision hash tampering;
6. valid-hash semantic drift at a newly-created immutable qualification path.

Phase 3AC persistence tests continue to cover missing, malformed, hash-tampered, write-once, idempotency, pre-write hash validation, link cleanup, and rejected evidence persistence.

## Verification results

### Focused

```text
48 passed in 2.85s
```

### Related evidence-chain regression

```text
77 passed in 3.75s
```

### Full locked suite

```text
276 passed in 12.59s
```

### Static and reproducibility gates

```text
ruff check: All checks passed
ruff format --check: 102 files already formatted
mypy src: Success: no issues found in 60 source files
uv lock --check: passed
compileall: passed
git diff --check: passed
```

### Safety scan

```text
credentials / secrets / tokens: 0 findings
HTTP / exchange client / order route: 0 findings
write API / os API: 0 findings
learner_qualification / registry / lifecycle fields: 0 findings
```

### Browser verification

Not applicable. Phase 3AD is a backend-only read-only loader; it changes no API, UI, frontend asset, or service route.

## Explicitly deferred

- API/UI exposure of qualification evidence;
- batch/registry qualification processing;
- candidate lifecycle state mutation;
- promotion and paper activation;
- testnet/live execution;
- exchange connectivity or authenticated requests.
