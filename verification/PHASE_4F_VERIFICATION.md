# Phase 4F Verification — Read-Only Lineage Consumer and Unavailable Propagation

**Date:** 2026-08-10
**Development runtime:** `gpt-5.6-luna` / `openai-codex` / Medium
**Status:** VERIFIED — explicit source-status propagation

## Scope

Phase 4F consumes the verified Phase 4E lineage projection and exposes a
smaller read-only consumer summary. It revalidates the projection hash,
preserves `AVAILABLE`/`UNAVAILABLE`, and carries source availability hashes
forward without interpretation.

```text
Phase 4E lineage projection
→ projection-hash revalidation
→ explicit status propagation
→ source availability-hash projection
→ deterministic consumer summary
```

When every unavailable source has the same reason, that exact reason is
propagated. Mixed unavailable reasons retain the aggregate projection reason;
no reason is converted into a quality score or inferred trading result.

## Failure behavior

The consumer fails closed for a tampered projection hash. It does not fabricate
source lineage, convert `UNAVAILABLE` into `AVAILABLE`, or replace missing
evidence with zero values.

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

Focused Phase 4F test, rerun after code push:

```text
3 passed in 0.32s
```

Locked full suite:

```text
pre-commit:  473 passed in 7.78s
post-code-commit: 473 passed in 7.06s
```

Static and repository gates:

```text
ruff check:       passed
ruff format:      passed (216 files already formatted)
mypy src:         passed (117 source files)
uv lock --check:  passed
git diff --check: passed
```

The repository-wide `compileall` gate remains subject to the documented Windows
long-path `.pyc` limitation affecting earlier descriptive Phase 3 modules. It
is not claimed as passed.

## Delivery

```text
Commit: a9a16db Add lineage consumer unavailable propagation

HEAD        = a9a16dbcf2af8e83aff352e6d3d1249aaefb8807
origin/main = a9a16dbcf2af8e83aff352e6d3d1249aaefb8807
worktree: clean at code delivery
```

## What this proves and does not prove

This report proves projection-hash verification, exact unavailable propagation,
source availability-hash preservation, cached-only behavior, and the automated
verification listed above.

It does **not** prove strategy quality, profitability, qualification,
promotion eligibility, paper readiness, live readiness, exchange access,
account truth, or permission to execute orders.

Next bounded slice:

```text
Phase 4G:
read-only evidence lineage completeness and deterministic gap reporting
```

Phase 4G must remain evidence-only unless a separate model/effort and safety
decision explicitly expands scope.
