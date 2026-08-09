# Phase 3AJ Verification — Immutable Research-Run Audit Envelope Persistence

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — immutable, audit-only persistence boundary

## Scope

Phase 3AJ persists the Phase 3AI `ResearchRunAuditEnvelope` through a separate
read/write boundary:

```text
validated in-memory envelope
→ canonical JSON
→ atomic exclusive write-once artifact
→ hash-verified readback
```

Public functions:

```text
write_research_run_audit_envelope(path, envelope)
read_research_run_audit_envelope(path)
```

This is provenance evidence only. It is not a model-quality result, strategy
qualification, promotion, paper-activation decision, or execution permission.

## Persistence guarantees

| Condition | Result |
|---|---|
| Valid envelope | Canonical JSON write and verified readback |
| Same complete envelope | Idempotent existing-path read |
| Changed field, including `prepared_at` | Immutable conflict rejection |
| Caller hash mismatch | Rejected before directory/filesystem work |
| Tampered artifact hash | Domain integrity failure |
| Malformed JSON/schema | `DataQualityError` |
| Missing artifact | `FileNotFoundError` |
| Temp link failure | Temp artifact cleaned in `finally` |
| Concurrent destination race | Existing winner is read and compared |

The writer uses a UUID-suffixed sibling temp path, exclusive `os.link`
publication, and verified readback. The envelope content hash remains
independent of preparation time, but the complete persisted typed artifact still
uses preparation time for write-once identity.

## TDD evidence

### RED

The first focused test failed because the persistence module did not exist:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research_lab.research_run_audit_persistence'
```

### GREEN

Focused Phase 3AJ persistence tests:

```text
5 passed in 0.90s
```

Coverage includes:

```text
verified envelope round-trip
identical-write idempotency
changed preparation timestamp conflict
tampered, malformed, and missing artifact rejection
pre-write hash rejection without directory creation
temporary-file cleanup after link failure
```

Combined Phase 3AF–3AJ research-lab regression:

```text
37 passed in 0.78s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 115 files already formatted
mypy src:                      Success: no issues found in 67 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

Phase 3AJ adds no:

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
317 passed in 6.31s
```

The report update is amended into the Phase 3AJ commit, followed by one final
fresh locked full-suite run before push. Remote SHA and worktree state are then
verified against `origin/main`.
