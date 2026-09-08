# Phase 271 — Bounded Paper Deployment Verification

**Decision: DEPLOYED — paper-only code cutover completed.**

## Release identity

- Candidate source commit: `4b7dd4f30b8e70dea04675b5465695d572c63c33`.
- Remote deployed artifact: exact candidate archive copied from `.release-4b7dd4f30b8e70dea04675b5465695d572c63c33` into `/opt/autonomous-futures-bot`.
- Deployed source manifest (relative `src`, `tests`, `scripts`, generated caches excluded): `9bf0e048049661c9b57d53a199d96f7e87b8b648b5a991e27fe247e212a0e0bd`.
- Remote staging and deployed-target manifests matched exactly.
- Remote Git metadata remains the pre-cutover checkout `ab8b8df3fa0d45891ad83c33a9ad06a0931197a8`; the deployed code identity is the candidate archive plus the manifest above, not a remote Git checkout mutation.

## Pinned access and permission gate

- Host: `147.79.18.15` (`kipopopo`).
- ED25519 fingerprint verified from fresh `ssh-keyscan`: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`.
- Operator: `afbot`; key: `C:/Users/thaqi/.ssh/kainode_ed25519_openssh`.
- `sudo -n -l` readback confirmed only the narrowly scoped stop permission plus existing autonomous-futures restart/status/journal permissions. No sudoers change was made.

## Gates before cutover

- Fresh pre-stop ledger: `paper_ledger_events` integrity `ok`, 40 opens, 40 closes, unmatched delta `0`.
- Online SQLite backup used `Connection.backup()` while the old service was running: `/opt/autonomous-futures-bot/artifacts/paper_live/backups/deploy-20260908T035702Z-paper-ledger.sqlite3`; backup integrity `ok`, 80 events, 40 KiB.
- Candidate staging compile check passed.
- Candidate isolated recovery/accounting tests: `18 passed in 3.17s` (`phase_265_accounting`, `phase_266_restart_recovery`, `phase_267_position_recovery`, `phase_267_review_blockers`).
- Controlled stop used exactly `/usr/bin/systemctl stop autonomous-futures-paper-live.service`; immediate post-stop ledger remained integrity `ok`, 40 opens, 40 closes, unmatched delta `0`.

## Deployed runtime evidence

- Existing paper unit restarted; existing Telegram unit restarted. No new service, timer, scheduler, credentials, or data transfer was created.
- Paper service: `active/running`, `MainPID=691484`, `NRestarts=0`, `ExecMainStatus=0`.
- Telegram service: `active/running`, `MainPID=691490`, `NRestarts=0`, `ExecMainStatus=0`.
- Import parity: `autonomous_futures.paper.live_engine` imported from `/opt/autonomous-futures-bot/src/autonomous_futures/paper/live_engine.py`.
- Daemon health timestamp: `2026-09-08T04:01:49.837035+00:00`; active positions `0`; active position count `0`.
- Strategy/runtime authority unchanged: symbols `BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT`; starting capital `100.00`; `paper_activation=true`; `execution_authority=false`; `live_trading_activation=false`; `orders_submitted=0`; `zero_private_credentials=true`; `promotion_state=unpromoted`; read-only streams only.
- Post-cutover ledger integrity `ok`; tables now include `paper_position_state` and `paper_position_update_intent`; both counts `0`; ledger events remain 40 opens and 40 closes, unmatched delta `0`.
- Observed post-cutover cash/equity: `99.82967035750332875200` each. No artificial trades were generated.

## Rollback ceiling

The candidate recovery schema is now initialized in the runtime database. Do not roll back to the old code merely by restoring the previous source: old-code compatibility with new persisted recovery state is not assumed. Preserve the runtime database, WAL/SHM files, logs, configuration, secrets, and the verified SQLite backup; any rollback requires an explicit compatibility/recovery decision.

## Safe independent readback

Use the pinned `afbot` key and host fingerprint above, then read only:

```bash
sudo -n -l
systemctl show autonomous-futures-paper-live.service -p MainPID -p NRestarts -p ExecMainStatus -p ActiveState -p SubState
systemctl show autonomous-futures-telegram.service -p MainPID -p NRestarts -p ExecMainStatus -p ActiveState -p SubState
python3 -c 'import sqlite3; c=sqlite3.connect("file:/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3?mode=ro",uri=True); print(c.execute("PRAGMA integrity_check").fetchone()[0]); print(c.execute("select event,count(*) from paper_ledger_events group by event order by event").fetchall())'
```
