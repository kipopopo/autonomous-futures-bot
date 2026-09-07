# Phase 267 Verification: Durable Local Paper-Position Recovery

## Scope

Local-only paper-runtime persistence and restart recovery. No deployment, VPS restart, exchange/network action, credentials, commit, push, or strategy tuning.

Preserved the uncommitted Phase 265/266 work and retained the Phase 266 fail-closed behavior for legacy open ledger rows.

## Implemented contract

- Added additive `paper_position_state` persistence in the existing paper-ledger SQLite database.
- Durable state LOAD validates the exact versioned schema, UTC timestamp, finite positive protection/margin values (including optional target/trailing stop when present), strategy JSON object, and SQL row identity/version against the JSON payload.
- State stores the complete original candidate artifact JSON. Startup requires exact candidate ID, artifact hash, and content equality with the supplied candidate artifact; candidate ID alone and current-config substitution are not accepted.
- State is bound to the authoritative ledger open event by trade ID, candidate identity, artifact hash, symbol, side, and quantity. Missing, corrupt, duplicate/ambiguous, orphaned, stale, incompatible, or mismatched state raises `PaperRestartRecoveryError`.
- New opens persist state before the runtime proceeds to lifecycle marking. Protective ratchets and lifecycle marks persist updated mutable state. Successful closes delete the matching state; the ledger remains the authority for the close and rejects a second close.
- Restart restores `active_trades` and margin reservations through `restore_open()` without debiting the already-recorded entry fee. Owned-account cash still uses the Phase 265 reconciliation formula. Injected account cash remains caller-owned while durable reservations are restored.

## Crash behavior

- Ledger open without state: startup rejects, preserving the ledger and preventing guessed hydration, duplicate opens, or signal processing.
- State without an authoritative open, or stale state after a close crash window: startup rejects as orphan/incompatible rather than silently resetting.
- Corrupt or unsupported state version: startup rejects.
- State write failure occurs before the in-memory open is exposed; the exception prevents successful open completion and latches the engine against subsequent entry/signal processing. Close state deletion occurs only after a successful authoritative close; an interrupted deletion leaves an orphan that fails closed on the next startup.
- SQLite state writes use the existing connection/transaction context. Ledger event and state are additive tables, but open-event append and state append are not one SQLite transaction; the safe ordering is deliberate: an open-only crash is fail-closed, never guessed.

## Verification results

Focused RED/GREEN:

- Initial Phase 267 test run: `3 failed` because the new persistence API did not exist.
- Final focused recovery/accounting/review-blocker set: `10 passed` (`Phase 265`, `Phase 266`, `Phase 267`).
- Phase 267 includes actual open → mutable state update → engine restart → restored protection/margin → close → second restart, plus missing/orphan evidence and injected-account boundary tests.
- Existing Phase 258 live-paper and SQLite stress tests: `22 passed`.

Final canonical gates on the final tree:

- `unset PYTHONPATH PYTHONHOME VIRTUAL_ENV && uv run --locked pytest -q`: `1944 passed in 399.59s (0:06:39)`.
- `uv run --locked ruff check src tests scripts`: `All checks passed!`.
- `uv run --locked ruff format --check src tests scripts`: `454 files already formatted`.
- `uv run --locked mypy src scripts`: `Success: no issues found in 230 source files`.
- `uv lock --check`: passed; `Resolved 67 packages`.
- `git diff --check`: passed. Git emitted only normal LF/CRLF working-tree warnings.

## Files

Modified:

- `src/autonomous_futures/paper/live_engine.py`
- `src/autonomous_futures/paper/sqlite_ledger.py`
- `src/autonomous_futures/paper/ledger.py`
- `src/autonomous_futures/paper/circuit_breakers.py`

Added for this phase:

- `tests/unit/test_phase_267_position_recovery.py`
- `verification/PHASE_267_VERIFICATION.md`

Existing uncommitted Phase 265/266 files remain untouched.

## Limitations / deployment boundary

- This is a local implementation only. The production paper daemon and VPS database were not changed or restarted.
- Existing legacy open rows do not have Phase 267 state and remain intentionally unrecoverable; they continue to fail closed under the Phase 266 guard.
- State and ledger events are separate tables in the same SQLite file, with fail-closed crash ordering rather than a speculative migration of historical rows.
- No claim is made about live/testnet authority, profitability, or strategy quality.
