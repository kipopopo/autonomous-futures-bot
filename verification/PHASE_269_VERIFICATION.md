# Phase 269 Verification — Durable Position Update Protocol

**Decision: LOCAL RELEASE GATES PASS; deployment remains blocked pending parent review.**

## Scope and root cause

Phase 268 identified that a failed mutable protective-state write followed by failed invalidation could leave an older valid SQLite state accepted after restart. The root cause was relying on best-effort deletion and an in-memory latch after the mutation had started.

## Implemented minimum protocol

- Added `paper_position_update_intent` to the existing SQLite ledger database.
- Every open, close, and mutable protective-state update commits a write-ahead dirty marker before account/active-trade/protective-field mutations.
- The marker is cleared only after the durable state/evidence operation and corresponding in-memory management operation complete.
- Startup rejects any committed dirty marker before loading or mutating open positions. No deletion, replacement database, memory-only latch, guessed recovery, or legacy migration was added.
- Marker-write failure occurs before account reservation or active-trade exposure on new opens; the authoritative ledger remains and startup fails closed.
- A previously committed marker remains durable when the state write fails, when marker clearing fails after a successful state write, and across a fresh SQLite reopen. The old state is never accepted while the marker remains. Marker-write failures also latch the engine closed, preventing later signals if a caller catches the exception.
- Existing exact `Decimal` serialization, ledger/account identity checks, immutable candidate artifact/content binding, and legacy fail-closed behavior are preserved.

## Strict regression evidence

- RED: new marker tests initially failed because the protocol methods did not exist and the old implementation accepted/misclassified the recovery path.
- GREEN: focused Phase 265–269 recovery/accounting set: `18 passed in 2.87s`.
- Crash-window coverage uses temporary SQLite files and fresh `LivePaperEngine` instances: marker write failure before account mutation; committed dirty marker after state-write failure; committed dirty marker after clear failure; plus existing open/update/reopen/close/reopen recovery coverage.

## Gates run before final full suite

- `ruff check src tests scripts`: passed.
- `ruff format --check src tests scripts`: `454 files already formatted`.
- `mypy src scripts`: `Success: no issues found in 230 source files`.
- `uv lock --check`: `Resolved 67 packages`.
- `git diff --check`: passed; only normal LF/CRLF working-tree warnings.

## Boundaries and rollout preconditions

- No VPS access, remote write, deployment, restart, credential/.env access, order activity, strategy change, or live/testnet activation was performed.
- Existing legacy open rows without Phase 267 state remain intentionally unrecoverable.
- Final acceptance is evidenced by the locked full pytest run (`1948 passed in 414.97s`), the pushed commit, and exact remote SHA readback.
- Parent review of this durability implementation is required before any VPS remote write or deployment. The VPS and paper runtime were left undisturbed.
