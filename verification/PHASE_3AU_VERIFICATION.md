# Phase 3AU Verification — Deterministic Integrity-Observation Review Result

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — non-authoritative integrity-only review result

## Scope

Phase 3AU adds a distinct review-result contract for the Phase 3AT lineage:

```text
verified integrity-observation evaluation input
→ evaluation-input hash revalidation
→ fixed integrity-only checks
→ deterministic review result/hash
```

`ResearchObservationIntegrityEvaluationReview` is deliberately distinct from
the Phase 3AO review type. It binds this new lineage to:

```text
research_run_id
source_evaluation_input_hash
source_observation_hash
```

The result proves only the fixed boundary contract:

```text
review_status = "verified"
check_ids = (
  "audit_only_status",
  "audit_integrity_scope",
  "safety_locks",
)
promotion_state     = "unpromoted"
paper_activation    = false
execution_authority = false
```

It is not a quality result, strategy evaluation, candidate decision,
qualification, promotion, paper-readiness, or execution permission.

## Integrity behavior

The public reviewer reconstructs the supplied typed evaluation input through
its hash-validating model before building a result. A model-copy change to its
fixed count fails closed before result generation.

The canonical review hash excludes only `reviewed_at` and its own hash. Equal
verified evidence therefore receives the same review identity regardless of
preparation time.

## TDD evidence

### RED

The first focused test failed because the result module did not exist:

```text
ModuleNotFoundError:
No module named
'autonomous_futures.research_lab.research_observation_integrity_evaluation_result'
```

### GREEN

Focused Phase 3AU suite:

```text
3 passed in 0.78s
```

Coverage includes:

```text
fixed audit-boundary-only verified result
exact evaluation and observation provenance
tampered evaluation-input rejection
canonical hash determinism across review timestamps
```

Combined Phase 3AF–3AU research-lab regression:

```text
71 passed in 1.24s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 137 files already formatted
mypy src:                      Success: no issues found in 78 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AU adds no:

```text
provider HTTP/network client
credentials, API keys, base URLs, or provider configuration
raw prompt or raw model-output persistence
scheduler/worker process
generated-code execution
candidate, learner, or registry mutation
quality scoring, qualification, promotion, or paper activation
exchange/order/execution logic
API/UI/dashboard exposure
```

## Final verification

Fresh locked backend suite after commit:

```text
351 passed in 7.19s
```

The report update is amended into the Phase 3AU commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
