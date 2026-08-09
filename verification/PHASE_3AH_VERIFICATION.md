# Phase 3AH Verification — Verified Persisted Model-Call Audit Loader

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — read-only provenance loader boundary

## Scope

Phase 3AH adds one read-only loader:

```text
load_verified_model_call_audit(audit_path, *, policy)
```

It consumes the Phase 3AG shared persisted-audit reader and verifies that the
persisted `ModelCallAudit` is bound to the exact supplied `ResearchModelPolicy`:

```text
verified persisted audit hash
→ verified caller policy hash
→ exact policy ID/hash binding
→ audit role exists in policy
→ exact pinned provider/model binding for that role
→ return typed audit
```

The loader performs no write, provider call, scheduler operation, generated-code
execution, lifecycle mutation, qualification, promotion, paper activation,
exchange access, or order routing.

## Integrity and fail-closed behavior

| Condition | Result |
|---|---|
| Valid persisted audit and matching verified policy | Returns typed audit unchanged |
| Caller policy hash is invalid | `DomainViolation` before persisted read |
| Audit policy ID/hash differs from supplied policy | `DomainViolation` |
| Audit role is absent from supplied policy | `DomainViolation` |
| Audit provider/model differs from role policy | `DomainViolation` |
| Missing/malformed/tampered persisted audit | Delegated fail-closed result from Phase 3AG reader |

A hash-valid audit cannot obtain authority by copying a different valid policy
hash. The loader independently checks policy identity and verifies that the
persisted audit role is represented in that specific policy. Source artifact
bytes are preserved during a successful verified load.

## TDD evidence

### RED

The initial test imported the intentionally absent loader module and failed:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research_lab.model_audit_input'
```

### GREEN and regression matrix

Focused Phase 3AH tests:

```text
4 passed in 0.67s
```

Coverage includes:

```text
verified persisted round-trip with source-byte preservation
valid policy-hash drift with same policy ID
validly re-hashed audit referencing a role missing from policy
unverified caller policy hash rejected before audit read
```

Combined Phase 3AF–3AH research-lab regression:

```text
28 passed in 0.72s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 111 files already formatted
mypy src:                      Success: no issues found in 65 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AH adds no:

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
308 passed in 6.42s
```

The report update is amended into the Phase 3AH commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
