# Phase 46 Verification — one bounded production read-only account reconciliation

## Scope

Phase 46 performs exactly one authenticated production read-only account request through the disabled-by-default systemd oneshot.

```text
GET /fapi/v3/account
No POST
No order endpoint
No retry
No scheduler
```

## Fresh token

The previous token was expired. A fresh one-shot token was issued and transferred as non-secret SQLite evidence:

```text
token: token-live-002
state: issued_not_enabled
live_enabled: false
network_allowed: false
```

## Remote execution

```text
unit: autonomous-futures-live-readonly.service
unit state: static (not enabled)
PrivateNetwork: no (required only for this bounded GET)
systemd-analyze verify: passed
start result: success
ExecMainStatus: 0
post-run state: inactive
```

The unit consumed encrypted credentials through `LoadCredentialEncrypted`. Values were not printed or logged.

## Real production read-only result

Safe aggregates only:

```text
status: reconciled
asset_count: 11
nonzero_position_count: 0
network_requests: 1
reason: live_account_reconciled
```

No balance, API key, secret, signed query, or raw private response was persisted in the report.

## Safety checks

```text
project static units: 2
project timers: 0
/order references in project units: 0
live order requests: 0
execution_authority=false
live_enabled=false
```

The read-only service remains disabled/static and is not a scheduler.

## Verification

```text
Local locked full suite:       638 passed
Local Ruff/format/mypy/lock:   passed
Remote tests suite:            630 passed
Remote Ruff/format/mypy/lock:  passed
Remote systemd-analyze verify: passed
```

The remote suite has 630 tests; the local full suite has 638 because 8 research tests depend on large local market-data files intentionally not deployed to VPS.

## Safety status

```text
paper_activation=false
execution_authority=false
read_only_exchange_access=true (one bounded production GET)
live_order_enabled=false
new_order_actions_allowed=false
```

Phase 46 proves one reconciled production account read only. It does not authorize live orders, enable order transport, create a scheduler, or activate the one-shot token for trading.
