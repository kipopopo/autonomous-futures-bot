# Phase 4C Verification — Explicit UNAVAILABLE Evidence Semantics

**Date:** 2026-08-10
**Development runtime:** `gpt-5.6-luna` / `openai-codex` / Medium
**Status:** VERIFIED — fail-closed availability semantics

## Scope

Phase 4C makes absence of research evidence explicit and typed. It does not
turn missing evidence into a zero, a failed quality metric, or an inferred
negative/positive trading result.

```text
no evidence       → UNAVAILABLE / missing_evidence
partial evidence  → UNAVAILABLE / incomplete_evidence
verified complete → AVAILABLE with Phase 4A summary hash
tampered evidence → integrity failure
```

The availability record preserves both expected and observed research-run
identities, evidence count, status, reason, and an audit-independent canonical
`availability_hash`. `assessed_at` is excluded from that content identity.

## Failure behavior

The implementation returns typed `UNAVAILABLE` for:

```text
empty handoff input
missing expected research-run evidence
partial expected-run coverage
```

It raises a fail-closed `DomainViolation` for present but malformed or tampered
handoffs, including canonical handoff-hash mismatch. It never fabricates a
summary hash for unavailable evidence.

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

Focused Phase 4C test, rerun after code push:

```text
4 passed in 0.31s
```

Locked full suite:

```text
pre-commit:  463 passed in 7.61s
post-code-commit: 463 passed in 7.17s
```

Static and repository gates:

```text
ruff check:       passed
ruff format:      passed (210 files already formatted)
mypy src:         passed (114 source files)
uv lock --check:  passed
git diff --check: passed
```

The repository-wide `compileall` gate remains subject to the documented Windows
long-path `.pyc` limitation affecting earlier descriptive Phase 3 modules. It
is not claimed as passed.

## Delivery

```text
Commit: 2a55ecc Add explicit unavailable evidence semantics

HEAD        = 2a55ecc68e81ee4b26c0f4e4ee346cecd47d789a
origin/main = 2a55ecc68e81ee4b26c0f4e4ee346cecd47d789a
worktree: clean at code delivery
```

## What this proves and does not prove

This report proves explicit missing/incomplete evidence semantics, complete
verified evidence availability, tamper rejection, canonical availability
identity, cached-only behavior, and the automated verification listed above.

It does **not** prove strategy quality, profitability, qualification,
promotion eligibility, paper readiness, live readiness, exchange access,
account truth, or permission to execute orders.

Next bounded slice:

```text
Phase 4D:
read-only availability consumer composition and deterministic status reporting
```

Phase 4D must remain evidence-only unless a separate model/effort and safety
decision explicitly expands scope.
