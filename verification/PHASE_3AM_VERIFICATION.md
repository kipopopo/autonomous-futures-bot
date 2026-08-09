# Phase 3AM Verification — Downstream Research-Observation Consumer Input

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — audit-only consumer input boundary

## Scope

Phase 3AM adds the in-memory `ResearchObservationInput` consumer boundary:

```text
verified ResearchRunAuditHandoff
→ revalidate handoff hash
→ audit-only observation input
→ deterministic input hash
```

The consumer accepts a typed verified handoff only. It does not read raw JSON,
reconstruct audits, infer model quality, or call any provider.

Fixed safety facts:

```text
observation_status  = "audit_only"
promotion_state     = "unpromoted"
paper_activation    = false
execution_authority = false
```

## Integrity behavior

The consumer revalidates the complete `ResearchRunAuditHandoff` before copying
its evidence facts. A handoff altered through an unvalidated model copy fails
with a domain integrity error. The input binds to the exact source handoff hash
and audit count.

The canonical input hash excludes only `prepared_at` and its own hash, so
identical handoff evidence remains deterministic across preparation timestamps.

## TDD evidence

### RED

The first focused test failed because the consumer module did not exist:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research_lab.research_run_observation'
```

### GREEN

Focused Phase 3AM suite:

```text
3 passed in 0.67s
```

Coverage includes:

```text
verified handoff-only input construction
exact source handoff hash preservation
fixed audit-only safety fields
tampered handoff rejection
canonical hash determinism across preparation timestamps
```

Combined Phase 3AF–3AM research-lab regression:

```text
46 passed in 1.03s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 121 files already formatted
mypy src:                      Success: no issues found in 70 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AM adds no:

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
326 passed in 6.32s
```

The report update is amended into the Phase 3AM commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
