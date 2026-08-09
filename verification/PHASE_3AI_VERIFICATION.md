# Phase 3AI Verification — In-Memory Research-Run Audit Envelope

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — in-memory, audit-only research boundary

## Scope

Phase 3AI adds the typed in-memory `ResearchRunAuditEnvelope` and builder:

```text
build_research_run_audit_envelope(...)
research_run_audit_content_hash(...)
```

The envelope combines already verified `ModelCallAudit` records for one
research run. It is an observational provenance record only:

```text
verified model-call audits
→ deterministic call ordering
→ exact research-run binding
→ exact policy ID/hash binding
→ bounded audit collection (1..32)
→ canonical envelope hash
```

No persistence, provider client, network call, scheduler, API/UI exposure,
generated-code execution, candidate mutation, qualification, promotion, paper
activation, exchange access, order routing, or execution authority is added.

## Contract

| Field/invariant | Contract |
|---|---|
| `research_run_id` | Valid bounded identifier; every child audit must match |
| `policy_id` / `policy_hash` | Must match every child audit and verified supplied policy |
| `audits` | 1–32 records, sorted by unique `call_id` |
| `status` | Fixed `audit_only` |
| `prepared_at` | Timezone-aware UTC; audit timestamp only |
| `envelope_hash` | SHA-256 over canonical payload excluding only `prepared_at` and self-hash |
| provider access | None |
| persistence | None; in-memory only |

Equivalent envelope content prepared at different UTC times retains the same
content hash, while the preparation timestamp remains visible in the typed
record.

## TDD evidence

### RED

The first focused test imported the intentionally absent module and failed:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research_lab.research_run_audit'
```

### GREEN

The focused Phase 3AI suite passed:

```text
4 passed in 0.64s
```

Coverage includes:

```text
sorted deterministic audit ordering
unique call-ID enforcement
research-run binding drift rejection
policy binding drift rejection
UTC preparation timestamp enforcement through the domain model
deterministic hash across preparation timestamps
```

Combined Phase 3AF–3AI research-lab regression:

```text
32 passed in 0.71s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 113 files already formatted
mypy src:                      Success: no issues found in 66 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AI does not add:

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

The envelope is provenance about supplied audit records, not proof of model
quality, strategy validity, profitability, qualification, promotion, or
execution readiness.

## Final verification

Fresh locked backend suite after commit:

```text
312 passed in 6.41s
```

The report update is amended into the Phase 3AI commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
