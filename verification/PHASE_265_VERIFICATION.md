# Phase 265 Verification Report: Accounting Root Cause

**Date:** 2026-09-07 15:34 MYT  
**Scope:** Local accounting root-cause investigation, bounded pinned VPS read-only inspection, and minimum local fix. No remote restart, deployment, database write, order activity, secret/.env access, or commit/push.

## Baseline and safety

- Repository was clean on `main` at `879e615` (`docs: record phase 264 paper audit`) before this phase's changes.
- Trusted host route was independently checked: live ED25519 fingerprint matched the pinned `SHA256:2EHNUWL...7vdjQ`.
- Remote command used only `/opt/autonomous-futures-bot/.venv/bin/python`, SQLite `mode=ro`, `PRAGMA query_only=ON`, one explicit read transaction, and JSON/ledger metadata. No environment dump or secret path was read.

## Root-cause evidence

Phase 264's reported cash defect was not accepted as fact.

The Phase 264 report used a 78-event snapshot with 40 opens and 38 closes and reported open-entry fees of `0.18955066857153618240`. Its own stated contract requires fees only for unmatched open positions. The source implementation in `ReadOnlyLedgerReader.calculate_reconciled_cash()` already uses a left join and `c.sequence IS NULL`, so it does **not** sum entry fees from closed opens.

The pinned VPS read-only snapshot later captured:

- 80 events, sequences 1–80: 40 opens and 40 closes.
- All-open entry-fee sum: `0.18955066857153618240`.
- Unmatched-open entry-fee sum: `0`.
- Closed net PnL: `-0.17032964249667124800`.
- Health heartbeat: `2026-09-07T07:30:25.131811+00:00`.
- Ledger latest event: `2026-09-07T07:26:03+00:00`.
- Health cash/equity: `100.37721004087410922720`.
- Contract cash for that consistent ledger read: `99.82967035750332875200`.
- Health minus contract cash: `0.54753968337078047520`.

Therefore the Phase 264 fee total was the entry-fee sum for **all historical opens**, not unmatched opens. The old `0.72906286322687152800` gap was also snapshot-specific: the ledger had advanced between captures, and the health JSON is an independently atomically replaced file rather than a transactionally coupled SQLite row.

The actual code defect is different and reproducible: `LivePaperEngine` created a fresh `HardenedSharedMarginAccount` with cash reset to starting capital on every daemon start, while reusing a persistent ledger. It did not restore persisted closed net PnL or unmatched-open entry fees before emitting health. This explains the live health/ledger mismatch across daemon sessions; it is not strategy drift or a fee-query defect.

## Local fix

Changed `src/autonomous_futures/paper/live_engine.py` only:

- When the engine owns a newly created account, restore `account.cash` from the persisted ledger using exact `Decimal` arithmetic:
  `starting capital + closed net PnL - unmatched open entry fees`.
- An injected account is left untouched to avoid overwriting caller-owned runtime state.
- No historical rows are changed, no silent repair is performed, and no strategy/config/tuning path is touched.

Added `tests/unit/test_phase_265_accounting.py` with a persisted closed trade regression proving restart cash restores to `101.43` rather than resetting to `100.00`.

## Verification commands and results

- `git status --short --branch && git log -1 --oneline`: initial state clean `main`, `879e615`.
- Pinned SSH key/host scan plus remote read-only SQLite/health probe: completed; no writes or secrets.
- `./.venv/Scripts/python.exe -m pytest tests/unit/test_phase_265_accounting.py::test_engine_restores_account_cash_from_persisted_ledger -q`: genuine RED first (`100.00 != 101.43`), then GREEN (`1 passed`).
- `./.venv/Scripts/python.exe -m pytest tests/unit/test_phase_265_accounting.py tests/unit/test_performance_analytics.py tests/unit/test_phase_258_live_paper.py tests/unit/test_phase_258_sqlite_decimal_stress.py -q`: `49 passed in 20.82s`.
- `./.venv/Scripts/ruff.exe check src/autonomous_futures/paper/live_engine.py tests/unit/test_phase_265_accounting.py`: `All checks passed!`.
- Full suite launched once as the required background notified run: `./.venv/Scripts/python.exe -m pytest -q`: `1931 passed in 386.78s (0:06:26)`.

## Decision and remaining boundary

- Phase 264's claimed all-open fee calculation was a report/audit error, not a defect in `calculate_reconciled_cash()`.
- A real restart-persistence accounting defect was proven and fixed locally with strict RED/GREEN coverage.
- The fix was **not deployed** to the VPS, by authorization boundary. Remote health may remain mismatched until a separately approved deployment/restart sequence.
- Open-position runtime hydration remains a separate boundary: this phase restores cash semantics but does not reconstruct `active_trades`/strategy stop state after restart. No claim is made that restart recovery is fully complete.
- No profitability, strategy-quality, testnet, or live-readiness claim is made.
