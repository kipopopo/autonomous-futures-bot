# Phase 3AQ Verification — Verified Persisted Integrity-Review Loader

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — read-only exact-provenance loader

## Scope

Phase 3AQ adds a typed loader for persisted Phase 3AO/AP integrity reviews:

```text
persisted integrity review
→ shared hash-verified reader
→ caller evaluation-input revalidation
→ exact research-run and source-evaluation hash binding
→ typed audit-only review handoff
```

The loader is read-only and preserves source artifact bytes.

## Integrity behavior

Before reading any caller-bound result, the loader revalidates the supplied
`ResearchObservationEvaluationInput`, including its canonical hash. It then
uses the Phase 3AP verified reader and enforces both:

```text
review.research_run_id
    == evaluation.research_run_id

review.source_evaluation_input_hash
    == evaluation.evaluation_input_hash
```

Invalid caller hashes and valid-but-mismatched upstream evaluation inputs fail
closed with `DomainViolation`.

## TDD evidence

### RED

The first focused test failed because the verified-loader module did not exist:

```text
ModuleNotFoundError:
No module named
'autonomous_futures.research_lab.research_observation_integrity_input'
```

### GREEN

Focused Phase 3AQ suite:

```text
2 passed in 0.94s
```

Coverage includes:

```text
exact persisted-review round-trip
source artifact remains byte-for-byte unchanged
invalid caller evaluation hash rejection
valid-but-mismatched evaluation binding rejection
```

Combined Phase 3AF–3AQ research-lab regression:

```text
59 passed in 0.91s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 129 files already formatted
mypy src:                      Success: no issues found in 74 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AQ adds no:

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
339 passed in 6.72s
```

The report update is amended into the Phase 3AQ commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
