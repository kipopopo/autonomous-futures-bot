# Phase 4E Verification — Explicit Source-Lineage Projection

**Date:** 2026-08-10
**Development runtime:** `gpt-5.6-luna` / `openai-codex` / Medium
**Status:** VERIFIED — read-only lineage projection

## Scope

Phase 4E projects the Phase 4D status together with the exact Phase 4C source
records. It preserves source identity for every scope without scoring or
interpreting evidence quality.

```text
Phase 4D status + scoped Phase 4C records
→ status-hash revalidation
→ source availability-hash revalidation
→ exact scope binding
→ deterministic source-lineage projection
```

Each projected lineage item preserves:

```text
scope_id
availability_status
reason
expected_research_run_ids
observed_research_run_ids
summary_hash
availability_hash
```

The projection content hash excludes only audit metadata `projected_at` and the
hash field itself.

## Failure behavior

The projection fails closed for:

```text
status hash mismatch
source availability hash mismatch
scope order/identity mismatch
missing or unexpected source scope
```

`UNAVAILABLE` source records remain `UNAVAILABLE`; no source summary hash is
fabricated and no missing evidence is converted into a positive or negative
quality result.

## Safety boundary

```text
data_source           = "cached_only"
exchange_access       = false
promotion_state       = "unpromoted"
paper_activation      = false
execution_authority  = false
```

No scoring, qualification, promotion, paper activation, provider/network
access, exchange access, scheduler, candidate mutation, or order routing was
added.

## Verification evidence

Focused Phase 4E test, rerun after code push:

```text
3 passed in 0.32s
```

Locked full suite:

```text
pre-commit:  470 passed in 9.47s
post-code-commit: 470 passed in 17.45s
```

Static and repository gates:

```text
ruff check:       passed
ruff format:      passed (214 files already formatted)
mypy src:         passed (116 source files)
uv lock --check:  passed
git diff --check: passed
```

The repository-wide `compileall` gate remains subject to the documented Windows
long-path `.pyc` limitation affecting earlier descriptive Phase 3 modules. It
is not claimed as passed.

## Delivery

```text
Commit: 4201a48 Add explicit evidence lineage projection

HEAD        = 4201a4888a13b771b64d1d89505d8aa395c8a1ac
origin/main = 4201a4888a13b771b64d1d89505d8aa395c8a1ac
worktree: clean at code delivery
```

## What this proves and does not prove

This report proves exact status/source hash revalidation, explicit scope
lineage preservation, deterministic projection, unavailable-state
preservation, cached-only behavior, and the automated verification listed
above.

It does **not** prove strategy quality, profitability, qualification,
promotion eligibility, paper readiness, live readiness, exchange access,
account truth, or permission to execute orders.

Next bounded slice:

```text
Phase 4F:
read-only lineage projection consumer with explicit unavailable propagation
```

Phase 4F must remain evidence-only unless a separate model/effort and safety
decision explicitly expands scope.
