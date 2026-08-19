# Frozen Testnet Evidence Operational Handoff

## Current state

```text
paper runtime: complete
bounded testnet lifecycles: 2
account: flat
persisted evidence: complete
new testnet actions: blocked
live_enabled: false
```

The repository is code and verification only. Runtime SQLite evidence is caller-owned outside the repo:

```text
%LOCALAPPDATA%\AutonomousFuturesBot\testnet-lifecycle-audits.sqlite3
%LOCALAPPDATA%\AutonomousFuturesBot\testnet-observations.sqlite3
%LOCALAPPDATA%\AutonomousFuturesBot\testnet-evidence-reviews.sqlite3
%LOCALAPPDATA%\AutonomousFuturesBot\testnet-activation-designations.sqlite3
%LOCALAPPDATA%\AutonomousFuturesBot\testnet-activation-approvals.sqlite3
```

The project `.env` remains ignored and untracked. Never copy it into Git, a report, a ticket, or a chat message.

## Read-only inspection

Use the completion summary against explicit journal paths:

```bash
PYTHONPATH=src uv run --locked python -m autonomous_futures.testnet_completion_cli \
  --audit-path "$LOCALAPPDATA/AutonomousFuturesBot/testnet-lifecycle-audits.sqlite3" \
  --observation-path "$LOCALAPPDATA/AutonomousFuturesBot/testnet-observations.sqlite3" \
  --review-path "$LOCALAPPDATA/AutonomousFuturesBot/testnet-evidence-reviews.sqlite3"
```

Expected frozen state:

```text
status=complete
new_actions_allowed=false
live_enabled=false
nonzero_position_observation_count=0
```

Read paths must not create missing databases. A missing or malformed artifact is unavailable/blocked, never silently treated as healthy.

## Credential hygiene

```text
BINANCE_TESTNET_API_KEY
BINANCE_TESTNET_SECRET_KEY
```

- Keep credentials in an external secret manager or ignored local environment.
- Use testnet/demo credentials only.
- Restrict trusted IPs where supported.
- Disable withdrawals.
- Revoke and regenerate immediately if a value enters chat, logs, screenshots, or Git.
- Never print the secret or include it in a subprocess argument list.

## No-daemon invariant

There is intentionally no running testnet service, scheduler, timer, signal consumer, or unattended retry loop. Do not create a systemd unit or cron job from this handoff.

Any future action must begin with:

```text
new human activation review
fresh expiry
exact symbol/notional scope
account preflight flat/reconciled
explicit one-lifecycle decision
```

The current frozen lock remains authoritative and blocks new actions.

## Backup and retention

Before moving runtime SQLite evidence:

1. Copy each database with SQLite online backup or a consistent offline copy.
2. Run `PRAGMA integrity_check` on the copy.
3. Preserve the original; do not rewrite historical rows.
4. Keep audit, observation, review, designation, and approval journals together.
5. Verify hashes and row counts after restore.

Do not deploy by deleting a directory containing runtime databases, WAL/SHM files, backups, or logs.

## Future VPS handoff gate

Deployment is not complete until the target host proves:

```text
code SHA matches origin/main
runtime database backups verified
SQLite integrity_check=ok
frozen completion summary=complete
nonzero positions=0
new_actions_allowed=false unless separately approved
live_enabled=false
no unexpected service/timer
```

The existing Kainode target is not changed by this handoff. VPS staging, hardening, service creation, and any network automation remain separate approved work.
