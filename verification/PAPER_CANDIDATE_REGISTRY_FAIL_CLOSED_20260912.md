# Paper Candidate Registry Fail-Closed Verification — 2026-09-12

## Status

**IMPLEMENTED AND LOCALLY VERIFIED.** Remote source staging and one controlled
paper-service restart remain for runtime activation.

## Finding

The paper engine loaded four filesystem-pinned default candidates when no
candidate mapping was supplied. The hot-reloader validated an empty registry
but only added entries; it did not remove those defaults. As a result, an
empty registry and a scheduler with zero admissions did not prevent new paper
entries.

## Minimal fix

After the candidate registry manifest is fully validated, replace the engine's
entry candidate map and `qualified_symbols` with the manifest's exact validated
set. A valid empty manifest therefore clears stale entry candidates. Existing
`active_trades` objects are not modified, so their original candidate rules
remain available for deterministic exit and reconciliation. Invalid or
incomplete manifests return before replacement and preserve the prior map.

## Verification evidence

- Empty-registry regression with active-trade retention: **15 registry tests passed**.
- Canonical locked suite: **2,194 passed in 614.03s**.
- Ruff check: **PASS**.
- Ruff format check: **PASS**.
- Mypy: **PASS**.
- `uv lock --check`: **PASS**.
- `git diff --check`: **PASS**.

## Read-only runtime evidence before this fix

The paper daemon was active with breaker `THROTTLED`, no active position at the
latest audit, zero submitted orders, and live activation disabled. The ledger
was internally consistent with 165 opens and 165 closes. The candidate registry
manifest contained no symbol entries, while the running engine still reported
four active pinned candidates. This was the observed bypass; no live order was
involved.

## Operational boundary

The next action is a code-only source update followed by one controlled
**paper-service-only** restart. Post-restart verification must require an empty
active-candidate map, flat ledger state, unchanged ledger integrity, fresh
health, `THROTTLED` breaker continuity, zero orders, and disabled live
authority. The autonomous scheduler remains untouched.
