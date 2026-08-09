# Phase 3AK Verification — Verified Persisted Research-Run Audit Input

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — read-only persisted provenance handoff

## Scope

Phase 3AK adds:

```text
load_verified_research_run_audit_envelope(path, *, policy)
```

The loader composes the Phase 3AJ persisted envelope reader with exact policy
and pinned-role verification:

```text
verified persisted envelope
→ verified caller policy hash
→ exact envelope policy ID/hash binding
→ every audit role exists in policy
→ every audit provider/model matches the pinned role
→ typed read-only envelope handoff
```

The loader does not write, mutate source artifacts, call a provider, fetch data,
run a scheduler, execute generated code, qualify/promote candidates, activate
paper trading, access an exchange, or route orders.

## Integrity and fail-closed behavior

| Condition | Result |
|---|---|
| Valid envelope and exact policy | Returns typed envelope unchanged |
| Invalid caller policy hash | `DomainViolation` before persisted read |
| Envelope policy ID/hash drift | `DomainViolation` |
| Valid envelope/policy without the audit role | `DomainViolation` |
| Provider/model pin drift | `DomainViolation` |
| Missing/malformed/tampered envelope | Delegated fail-closed persistence reader result |

The successful path preserves source artifact bytes. A valid envelope hash is
not sufficient authority: the supplied policy and every child audit binding are
verified independently.

## TDD evidence

### RED

The first focused test failed because the input module did not exist:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research_lab.research_run_audit_input'
```

### GREEN

Focused Phase 3AK tests:

```text
3 passed in 0.66s
```

Coverage includes:

```text
verified persisted round-trip with source-byte preservation
invalid caller policy hash rejected before read
validly re-hashed policy/role drift rejected
```

Combined Phase 3AF–3AK research-lab regression:

```text
40 passed in 0.77s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 117 files already formatted
mypy src:                      Success: no issues found in 68 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AK adds no:

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
320 passed in 6.74s
```

The report update is amended into the Phase 3AK commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
