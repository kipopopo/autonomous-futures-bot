# Phase 3AG Verification — Immutable Model-Call Audit Persistence

**Date:** 2026-08-09
**Development runtime:** `gpt-5.6-terra` / `openai-codex` / Medium
**Status:** VERIFIED — backend evidence persistence boundary only

## Scope

Phase 3AG persists the existing `ModelCallAudit` domain record as immutable,
hash-verified evidence. The phase adds only two explicit APIs in
`autonomous_futures.research_lab.model_audit`:

```text
read_model_call_audit(path)
write_model_call_audit(path, audit)
```

The writer verifies the supplied canonical audit hash before any filesystem
work, serializes deterministic JSON, writes through a UUID-suffixed sibling
temporary file, publishes with exclusive `os.link`, removes the temporary file
in `finally`, and verifies the published artifact via the shared reader.

## Integrity contract

| Condition | Result |
|---|---|
| Verified valid JSON audit | Returns typed `ModelCallAudit` |
| Identical evidence at existing path | Idempotent verified readback |
| Any typed evidence drift at existing path, including `observed_at` | `DomainViolation` immutable conflict |
| Caller-supplied audit hash mismatch | `DomainViolation` before directory/temp-file creation |
| Persisted hash mismatch | `DomainViolation` integrity failure |
| Malformed JSON/schema | `DataQualityError` fail-closed |
| Missing artifact | `FileNotFoundError` |
| Generic exclusive-link failure | Raises source failure and cleans temporary file |

`observed_at` remains excluded from `audit_hash`, so equivalent audit content
at another audit time has the same content hash. It remains a distinct typed
record and cannot rewrite an occupied immutable path.

## TDD evidence

### RED

The first persistence test imported the intentionally absent APIs and failed:

```text
ImportError: cannot import name 'read_model_call_audit'
```

A subsequent integrity test exposed an incorrect error normalization where a
tampered hash was reported as malformed evidence:

```text
Expected: DomainViolation / hash mismatch
Actual:   DataQualityError / invalid persisted model call audit
```

### GREEN

The narrow reader/writer implementation and error normalization were added.
The focused persistence suite then passed:

```text
6 passed in 0.65s
```

Research-lab policy, in-memory audit, and persistence regression suite:

```text
24 passed in 0.66s
```

## Static and reproducibility checks

```text
ruff check src tests:          passed
ruff format --check src tests: 109 files already formatted
mypy src:                      Success: no issues found in 64 source files
uv lock --check:               passed
python -m compileall -q src tests: passed
git diff --check:              passed
```

## Safety boundary preserved

This phase does not add or invoke:

```text
provider HTTP/network client
credentials, API keys, base URLs, or provider configuration
raw prompt or raw model-output persistence
generated-code execution
scheduler or worker process
candidate/learner/registry mutation
qualification or promotion
paper activation
exchange access, order routing, or execution authority
API or dashboard exposure
```

Persisted records remain non-authoritative research audit evidence. They do
not change any candidate or learner state, and no provider call is made by the
reader or writer.

## Not applicable

No frontend/API routes or browser runtime changed in Phase 3AG; frontend build
and browser dogfood are therefore not applicable to this backend-only evidence
persistence slice.

## Final verification

Fresh locked full backend suite after the report:

```text
304 passed in 7.12s
```

Final `git diff --check` passed. The uncommitted Phase 3AG diff contains only:

```text
src/autonomous_futures/research_lab/model_audit.py
tests/unit/test_research_lab_model_audit_persistence.py
verification/PHASE_3AG_VERIFICATION.md
```

Phase 3AG is ready for explicit commit/push authorization.
