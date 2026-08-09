# Phase 3AT Verification — Deterministic Integrity-Observation Evaluation Input

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — integrity-only deterministic evaluation preparation

## Scope

Phase 3AT adds `ResearchObservationIntegrityEvaluationInput`, a typed
preparation boundary after Phase 3AS:

```text
verified integrity-observation input
→ observation-input hash revalidation
→ fixed audit-integrity-only evaluation input
→ deterministic evaluation-input hash
```

Exact verified provenance is retained:

```text
research_run_id
source_observation_hash
source_review_hash
source_evaluation_input_hash
check_count = 3
```

Fixed semantic limits:

```text
evaluation_status  = "audit_only"
review_scope       = "audit_integrity_only"
promotion_state    = "unpromoted"
paper_activation   = false
execution_authority = false
```

## Integrity behavior

The builder revalidates the entire typed integrity-observation input before
constructing an evaluation preparation. Any unvalidated model-copy tampering
fails closed.

The canonical evaluation-input hash excludes only `prepared_at` and its own
hash, preserving deterministic evidence identity across preparation timestamps.

## TDD evidence

### RED

The first focused test failed because the evaluation-input module did not exist:

```text
ModuleNotFoundError:
No module named
'autonomous_futures.research_lab.research_observation_integrity_evaluation'
```

### GREEN

Focused Phase 3AT suite:

```text
3 passed in 0.64s
```

Coverage includes:

```text
audit-only provenance preservation
fixed integrity-only scope and safety fields
tampered observation rejection
canonical hash determinism across preparation timestamps
```

Combined Phase 3AF–3AT research-lab regression:

```text
68 passed in 1.16s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 135 files already formatted
mypy src:                      Success: no issues found in 77 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AT adds no:

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
348 passed in 7.16s
```

The report update is amended into the Phase 3AT commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
