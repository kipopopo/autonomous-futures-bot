# Phase 28 Verification — bounded testnet activation designation

## Scope

Phase 28 defines a future activation designation after frozen evidence. It does not activate or unlock testnet actions.

```text
No network
No order
No cancel
No scheduler
No live endpoint
```

## Delivered

### Scoped designation

`TestnetActivationDesignation` binds to the accepted testnet evidence review and records:

```text
designation ID
review ID/hash
designer and UTC designation window
one explicit symbol
max quote notional
max_open_positions = 1
expiry
state = designated_not_activated
new_actions_allowed = false
live_enabled = false
designation SHA-256
```

The factory rejects expired windows, mismatched symbols, and non-accepted evidence reviews.

This is a prepared governance artifact, not a permission to send orders. The existing post-freeze lock remains authoritative and continues to block new actions.

### Durable journal

`SqliteTestnetActivationDesignations` is caller-owned and write-once:

```text
same designation ID + same content → idempotent
same designation ID + changed content → conflict
restart → typed rehydration
absent read → no database creation
```

## TDD evidence

```text
RED: testnet_activation module import missing
GREEN: scoped non-activated designation and expiry validation
GREEN: write-once journal retry/conflict/absent-read behavior
```

## Verification

```text
Activation/freeze/testnet focused subset: 33 passed
Locked full suite:                      612 passed
Ruff check:                             passed
Ruff format:                            passed
Mypy:                                   154 source files clean
uv lock --check:                        passed
direct py_compile Phase 28 files:        passed
git diff --check:                       passed
new network/order requests:             0
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (historical bounded testnet evidence only)
live_enabled=false
new_actions_allowed=false
state=designated_not_activated
```

This phase prepares an explicit future scope but does not activate it. A separate human activation decision and implementation gate are still required before any new testnet order.
