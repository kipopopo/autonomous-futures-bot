# Paper Candidate Registry Fail-Closed Verification — 2026-09-12

## Status

**IMPLEMENTED AND LOCALLY VERIFIED.** The runtime registry quarantine and one
controlled paper-service restart remain for containment activation.

## Finding

The paper registry contained four phase-252 entries, but the candidate-bound
qualification audit found no exact `qualified` artifact for those entries.
The BTC hash matched rejected feedback with three failed paper gates; the
other three entries had no exact candidate-bound qualification artifact. The
running paper engine therefore had stale, non-qualification-grade candidates
available for entries while the scheduler reported zero admissions.

Separately, the hot-reloader only added registry entries and did not remove
stale entry candidates when a valid manifest shrank or became empty.

## Minimal fix

After the candidate registry manifest is fully validated, replace the engine's
entry candidate map and `qualified_symbols` with the manifest's exact
validated set. A valid empty manifest therefore clears stale entry candidates.
Existing `active_trades` objects are not modified, so their original candidate
rules remain available for deterministic exit and reconciliation. Invalid or
incomplete manifests return before replacement and preserve the prior map.
The current invalid registry is quarantined separately; this slice does not
pretend that a hash-only registry entry is a verified qualification artifact.

## Verification evidence

- Empty-registry regression with active-trade retention: **15 registry tests passed**.
- Canonical locked suite: **2,194 passed in 614.03s**.
- Ruff check: **PASS**.
- Ruff format check: **PASS**.
- Mypy: **PASS**.
- `uv lock --check`: **PASS**.
- `git diff --check`: **PASS**.

## Read-only runtime evidence before containment

The paper daemon was active with breaker `THROTTLED`, one active `ETHUSDT`
paper position, zero submitted orders, and live activation disabled. The ledger
was internally consistent with 166 opens, 165 closes, and one active position.
The registry manifest contained four symbol entries, while its entries were
not backed by exact candidate-bound `qualified` artifacts. No live order was
involved.

## Operational boundary

The next action is to preserve the current registry as a backup, publish a
versioned empty registry manifest, and perform one controlled
**paper-service-only** restart. Post-restart verification must require an empty
active-candidate map, preservation or deterministic closure of any existing
position, unchanged ledger integrity, fresh health, `THROTTLED` breaker
continuity, zero orders, and disabled live authority. The autonomous scheduler
remains untouched.
