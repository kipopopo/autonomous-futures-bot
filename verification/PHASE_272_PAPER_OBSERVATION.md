# Phase 272 — Bounded Post-Deployment Paper Observation

**Decision: OBSERVED — paper-only natural lifecycle completed; live remains blocked.**

## Scope and provenance

- Observation window: `2026-09-08T04:20:40.649222455Z` → `2026-09-08T04:21:56.744316400Z` UTC, with a final ledger readback at `2026-09-08T04:22:06.723578Z` daemon heartbeat.
- Host identity: `afbot@147.79.18.15` (`kipopopo`), ED25519 pin `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`; fresh `ssh-keyscan` matched after structural 32-byte fingerprint validation. Read-only SSH used with `C:/Users/thaqi/.ssh/kainode_ed25519_openssh` and a temporary pinned known-hosts file.
- Deployed source identity remains the Phase 271 archive cutover: candidate `4b7dd4f30b8e70dea04675b5465695d572c63c33`, manifest `9bf0e048049661c9b57d53a199d96f7e87b8b648b5a991e27fe247e212a0e0bd`; remote Git metadata intentionally remains `ab8b8df3fa0d45891ad83c33a9ad06a0931197a8`.
- Runtime source path: `/opt/autonomous-futures-bot`; authoritative ledger: `/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3`.
- Local repository was clean at observation start: `main...origin/main`, no status entries; latest local commit `f182e6b`.

## Results

- Paper service: `active/running`, PID `691484`, `NRestarts=0`, `ExecMainStatus=0` at both observations. Telegram service: `active/running`, PID `691490`, `NRestarts=0`, `ExecMainStatus=0` at both observations.
- Health remained `RUNNING`, circuit breaker `NORMAL`, active positions `0`, margin utilization `0.0%`, reserve buffer `100.0%`, reconnects `0`. Heartbeat advanced from `04:20:36.716969Z` to `04:21:36.721477Z`; feed messages advanced `679562` → `709672` in the bounded interval and later to `721302`.
- Safety flags remained: `paper_activation=true` (the existing paper daemon contract), `execution_authority=false`, `live_trading_activation=false`, `orders_submitted=0`, `zero_private_credentials=true`, `promotion_state=unpromoted`.
- SQLite read-only `PRAGMA integrity_check`: `ok`. Ledger has `82` rows: `41` opens and `41` closes; exact unmatched opens `[]`, orphan closes `[]`. `paper_position_state=0` and `paper_position_update_intent=0`; durable recovery/dirty-intent state is consistent with the flat book.
- A natural post-cutover lifecycle was observed, not fabricated: sequence `81` opened SOLUSDT at `2026-09-08T04:09:59Z`; sequence `82` closed it at `2026-09-08T04:18:08Z` by `trailing_stop_hit`, net PnL `-0.082582418545420800`. This is `41st` open/close, distinct from the historical Phase 271 baseline of `40/40`.
- Decimal reconciliation was executed from authoritative close history: starting `100.00` + sum net PnL `-0.25291206104209204800` = expected cash `99.74708793895790795200`; health cash and equity both exactly matched that value. All `41` closes have complete accounting; summed entry fees `0.20712940728850258240`, exit fees `0.20726978984124546560`, gross PnL `0.1614871360876560`.
- Telegram checkpoint readback (sanitized): `last_sequence=82`, `saved_at_utc=2026-09-08T04:18:15.911604+00:00`, `last_digest_timestamp=1788840182.595923`, `last_daily_report_date=2026-09-07`, `last_margin_alerted=false`; no raw token or chat ID was read or reported. Checkpoint progress covers the post-cutover lifecycle through ledger sequence 82.

## Historical issue / blocker status

- The journal contains a **pre-cutover historical** cash-drift exception at `2026-09-08T03:57:18Z` from old PID `677393` (`actual=100.37721004087410922720`, expected `99.82967035750332875200`). It predates the Phase 271 restart and is not a current service failure. No repair, restart, deletion, or historical rewrite was performed.
- The current bounded observation is not a live/execution qualification. No blocker was found in the observed paper process, feed freshness/progress, ledger integrity, recovery markers, accounting, or notifier checkpoint. Telegram journal lines were not visible to the `afbot` read-only journal view; checkpoint state is the available durable notifier evidence.

## Test scope

- No full `1948`-test rerun (report-only scope). Arithmetic was independently validated with Python `Decimal` against the remote authoritative ledger rows. Read-only SSH, service, health, SQLite, recovery, safety, and checkpoint probes completed; no VPS write/restart/deploy occurred.

## Sanitized reproducible readback

```bash
KH="$LOCALAPPDATA/Temp/afbot-phase272-known_hosts"
ssh-keyscan -T 15 -t ed25519 147.79.18.15 2>/dev/null | ssh-keygen -lf - -E sha256
ssh -i 'C:/Users/thaqi/.ssh/kainode_ed25519_openssh' -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KH" \
  -o HostKeyAlgorithms=ssh-ed25519 -o PubkeyAcceptedKeyTypes=ssh-ed25519 \
  afbot@147.79.18.15 'systemctl show autonomous-futures-paper-live.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus; \
  systemctl show autonomous-futures-telegram.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus'
```

Ledger path for a read-only SQLite URI: `file:/opt/autonomous-futures-bot/artifacts/paper_live/paper-ledger.sqlite3?mode=ro`; query `PRAGMA integrity_check`, event counts, unmatched opens, `paper_position_state`, and `paper_position_update_intent`. Health path: `/opt/autonomous-futures-bot/artifacts/paper_live/paper-daemon-health.json`. Notifier checkpoint path: `/opt/autonomous-futures-bot/artifacts/paper_live/telegram-checkpoint.json`.
