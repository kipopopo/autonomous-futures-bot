# Phase 270 — Bounded Paper Deployment Verification

**Decision: BLOCKED — candidate not activated.**

## Candidate and source gates

- Candidate: `4b7dd4f30b8e70dea04675b5465695d572c63c33`.
- Local checkout and `origin/main` were clean and at the exact candidate before this report.
- Focused recovery/position tests: `168 passed, 1770 deselected`.
- Prior full locked suite evidence: `1948 passed`; this deployment did not rerun the full suite.

## Recovery and shutdown review

- Candidate initializes `paper_ledger_events`, `paper_position_state`, and `paper_position_update_intent` with `CREATE TABLE IF NOT EXISTS`.
- Startup checks committed dirty intents before restoring positions and rejects missing/orphan/incompatible persisted state through `PaperRestartRecoveryError`.
- Daemon handles SIGTERM through an asyncio stop event, closes the feed, stops the monitor, reconciles balances, and writes a clean shutdown checkpoint. `systemd` has `TimeoutStopSec=30s` and `Restart=always`.
- An isolated remote temporary-DB smoke against the staged candidate passed: `ISOLATED_EMPTY_SCHEMA_OK`.

## Remote preflight

- Host identity matched the previously verified pinned ED25519 fingerprint; access used the previously verified `afbot` route and key path.
- Remote host: `kipopopo`; target: `/opt/autonomous-futures-bot`.
- Remote checkout before any cutover: `ab8b8df3fa0d45891ad83c33a9ad06a0931197a8`, clean.
- Python: `3.14.7`.
- Paper service was active with `MainPID=677393`, `ExecMainStatus=0`, `NRestarts=1`; Telegram service was active.
- Fresh read-only ledger query before cutover found 40 opens and 40 closes, with `integrity_check=ok`; legacy recovery tables were absent as expected. Health showed zero active positions and paper-only safety flags (`orders_submitted=0`, `execution_authority=false`, `live_trading_activation=false`, `paper_activation=true`, `promotion_state=unpromoted`, `zero_private_credentials=true`).

## Staging and blocker

- Exact candidate archive was staged under a temporary release subtree, without touching runtime data, WAL/SHM, logs, configuration, credentials, or services.
- Staging and isolated schema smoke passed; the temporary subtree was removed and verified absent.
- Activation was blocked at the required controlled-quiescence gate: `sudo systemctl stop autonomous-futures-paper-live.service` could not run because the verified SSH operator requires an interactive sudo password. No password was guessed or supplied.
- The daemon therefore remained on the old code. No remote code cutover, restart, database migration, or service change occurred.

## Rollback boundary

No new schema/runtime writes occurred on the VPS, so no rollback was attempted. If a future cutover writes the new recovery schema, old-code rollback must not be assumed safe until compatibility and recovery behavior are explicitly verified.
