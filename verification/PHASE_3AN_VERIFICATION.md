# Phase 3AN Verification — Deterministic Research-Observation Evaluator Input

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — audit-integrity-only evaluator input

## Scope

Phase 3AN adds `ResearchObservationEvaluationInput`, a deterministic input
contract for a downstream integrity reviewer:

```text
verified ResearchObservationInput
→ observation hash revalidation
→ fixed audit_integrity_only scope
→ deterministic evaluator input hash
```

This is not a model-quality evaluator and does not produce a score, rank,
qualification result, promotion decision, or paper-readiness decision.

Fixed fields:

```text
evaluation_status  = "audit_only"
review_scope       = "audit_integrity_only"
promotion_state    = "unpromoted"
paper_activation   = false
execution_authority = false
```

## Integrity behavior

The builder revalidates the complete upstream observation input before copying
its research-run ID, source hash, and audit count. Tampered observations fail
closed before evaluation-input construction.

The canonical evaluation-input hash excludes only `prepared_at` and its own
hash, preserving deterministic identity across preparation timestamps.

## TDD evidence

### RED

The first focused test failed because the evaluator-input module did not exist:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research_lab.research_observation_evaluation'
```

### GREEN

Focused Phase 3AN suite:

```text
3 passed in 0.62s
```

Coverage includes:

```text
fixed audit-integrity-only scope
exact source observation hash binding
fixed safety fields
tampered observation rejection
canonical hash determinism across preparation timestamps
```

Combined Phase 3AF–3AN research-lab regression:

```text
49 passed in 1.02s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 123 files already formatted
mypy src:                      Success: no issues found in 71 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AN adds no:

```text
provider HTTP/network client
credentials, API keys, base URLs, or provider configuration
raw prompt or raw model-output persistence
scheduler/worker process
generated-code execution
candidate, learner, or registry mutation
qualification, promotion, or paper activation
exchange/order/execution logic
API/UI/dashboard exposure
```

## Final verification

Fresh locked backend suite after commit:

```text
329 passed in 6.61s
```

The report update is amended into the Phase 3AN commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
