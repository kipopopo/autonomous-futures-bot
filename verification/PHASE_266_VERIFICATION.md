# Phase 266 Verification Report: Bounded Restart Recovery

**Scope:** Local paper-runtime restart recovery only. No remote calls, deployment, restart, credentials, order activity, testnet/live activation, commit, or push.

## Findings

- `LivePaperEngine` rebuilt `active_trades` as empty on every startup while the SQLite ledger retained unmatched opens.
- The ledger persists entry identity, fill, quantity, fees, and slippage, but does not persist the runtime fields needed to safely recreate `ActivePaperTrade`: protective stop/trailing state, watermark/ATR state, and margin reservation/leverage state.
- `PaperLedger` already rejects duplicate open positions by `(candidate_id, symbol)` and the existing Phase 265 cash formula correctly charges only unmatched open entry fees.

## Implemented boundary

- Preserved the uncommitted Phase 265 cash restoration unchanged: `starting_capital + closed net PnL - unmatched open entry fees`.
- Added `PaperRestartRecoveryError` and a startup guard after ledger/account initialization and before monitor/feed/candidate runtime setup.
- If any durable open position exists without trustworthy persisted protective/runtime state, startup logs an explicit error and rejects the engine. The ledger is not modified, no close is fabricated, no entry fee is charged again, no margin reservation is guessed, and no signal/new paper entry can be processed.
- This is intentionally **guarded-not-full-recovery**. It does not claim open-position hydration because the current persistence contract cannot prove the required protective state.

## Strict TDD evidence

- RED: the new regression initially failed during collection because `PaperRestartRecoveryError` did not exist.
- GREEN: `tests/unit/test_phase_266_restart_recovery.py`: `3 passed`.
- Focused regression set (`Phase 265`, `Phase 266`, Phase 258 live paper, SQLite ledger): `26 passed in 2.30s`.

## Canonical gates

All commands ran with `PYTHONPATH`, `PYTHONHOME`, and `VIRTUAL_ENV` unset.

- `uv run --locked pytest -q`: `1934 passed in 403.11s (0:06:43)`.
- `uv run --locked ruff check src tests scripts`: `All checks passed!`
- `uv run --locked ruff format --check src tests scripts`: `452 files already formatted`.
- `uv run --locked mypy src scripts`: `Success: no issues found in 230 source files`.
- `uv lock --check`: passed (`Resolved 67 packages`).
- `git diff --check`: passed.

## Files

- Modified: `src/autonomous_futures/paper/live_engine.py`.
- Added: `tests/unit/test_phase_266_restart_recovery.py`.
- Preserved existing uncommitted Phase 265 files: `tests/unit/test_phase_265_accounting.py`, `verification/PHASE_265_VERIFICATION.md`.

## Remaining boundary

A future phase would need an explicitly designed, additive persistence contract for protective stop/strategy state and margin reservation/leverage state, followed by evidence-backed hydration tests. Until then, an existing open ledger position intentionally blocks startup rather than being forgotten, duplicated, force-closed, or reconstructed speculatively.
