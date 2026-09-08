# Phase 273 — Offline Daemon Restart Rehearsal

**Decision: SYNTHETIC REHEARSAL PASSED; real VPS open-position restart remains the next operator gate.**

## Scope

- No VPS mutation, service restart, deployment, forced trade, live/testnet activity, strategy tuning, credentials, or provider/network call was performed.
- Used the deployed-equivalent `run_phase_259_live_paper_daemon` entry point and `LivePaperEngine` against isolated temporary SQLite files.
- Used an offline empty mock feed only; the rehearsal did not claim exchange or VPS provenance.

## Rehearsal result

- Seeded two durable open paper positions through the real engine path: `BTCUSDT LONG` and `ETHUSDT SHORT`.
- Persisted and restored daemon-owned state through a fresh daemon startup: quantity, margin, leverage, watermark, peak P&L, stop, target, trailing multiplier, ATR, and candidate hash-bound state.
- Daemon startup completed with `daemon_status=SHUTDOWN_CLEAN` after the bounded offline run; no open exposure was altered by shutdown.
- Fresh post-start engine restored both sides and restored cash as `99.9680000001600320` without recreating entry fees or ledger entries.
- Post-restart management closed both positions through the real `execute_close` path.
- Second fresh restart restored a flat book.
- Final isolated ledger: exactly `4` events (`2` opens, `2` closes); position-state rows empty; duplicate fee/entry check passed.

## Verification

- Canonical focused recovery/accounting/daemon tests: `19 passed in 9.29s`.
- Temporary ad-hoc verifier: passed; deleted after execution. It exercised the real daemon startup caller, not only engine mocks.
- No full suite rerun: report-only change; prior locked full-suite evidence remains `1948 passed`.

## Evidence boundaries and next gate

- **Observed locally:** deployed-equivalent daemon startup, both long/short durable restoration, persisted protective/margin/cash continuity, close lifecycle, second restart flatness, exact event cardinality, no duplicate fees/entries.
- **Synthetic:** all temporary SQLite state and mock feed behavior.
- **NOT YET OBSERVED:** restart recovery with an open position on the actual VPS/runtime database and its real systemd process. That remains a separately approved operational boundary; do not perform it under this phase.
