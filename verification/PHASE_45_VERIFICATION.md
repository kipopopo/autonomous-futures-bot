# Phase 45 Verification — manual live preflight unit

## Scope

Phase 45 deploys a disabled-by-default systemd oneshot that reads encrypted credentials through `LoadCredentialEncrypted` and runs a network-isolated preflight.

```text
No scheduler
No enabled service
PrivateNetwork=yes
No live order
```

## Preflight contract

The CLI checks credential file presence only; it never reads or prints credential contents. It evaluates:

```text
production endpoint
credential names present
account reconciled
positions flat
kill switch ready
token expiry/state
```

Default operator assertions are false. Even when static assertions are supplied, the result remains:

```text
status=ready_for_manual_activation
network_allowed=false
live_enabled=false
```

## Remote unit

```text
unit: autonomous-futures-live-preflight.service
release path: /opt/autonomous-futures-bot
unit state: static (not enabled)
active state after run: inactive
PrivateNetwork: yes
systemd-analyze verify: passed
```

The unit loads:

```text
BINANCE_LIVE_API_KEY
BINANCE_LIVE_SECRET_KEY
```

from the encrypted systemd credential artifacts. No network interface is available to the unit.

## Manual execution result

One manual start was run intentionally. It reached the application and returned the expected fail-closed result:

```text
status: blocked
credential names present: both
account_not_reconciled
positions_not_flat
kill_switch_not_verified
token_expired
token_not_enabled
network_allowed=false
```

The unit exited with status `3` because the current one-shot token is expired and no live account preflight assertions were supplied. Failed state was reset; the unit remains disabled/inactive.

## Verification

```text
Local locked full suite:       633 passed
Local Ruff/format/mypy/lock:   passed
Remote tests suite:            625 passed
Remote Ruff/format/mypy/lock:  passed
Remote systemd-analyze verify: passed
Remote encrypted credentials:  present, values not printed
Live/network actions:          0
```

The remote suite has 625 tests because it runs `tests/`; the local full suite includes 8 research tests whose large local market-data files are intentionally not deployed to VPS.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (historical bounded testnet evidence only)
live_enabled=false
network_allowed=false
new_actions_allowed=false
```

Phase 45 proves credential delivery and fail-closed manual preflight only. It does not refresh the expired token, enable live transport, create a scheduler, or place an order.
