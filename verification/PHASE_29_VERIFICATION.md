# Phase 29 Verification — one-lifecycle testnet activation approval

## Scope

Phase 29 records one explicit human activation approval for a tightly bounded future testnet lifecycle.

```text
symbol: BTCUSDT
max quote notional: 100 USDT
scope: one open + one reduce-only close
max open positions: 1
expiry: short, caller-supplied
live_enabled=false
```

No order was sent in Phase 29.

## Delivered

### Activation approval contract

`TestnetActivationApproval` is hash-bound to the scoped designation and frozen evidence review. It contains:

```text
approval ID
approval hash
designation ID/hash
approver
UTC validity window
symbol/max quote scope
scope = one_open_and_reduce_only_close
new_actions_allowed=true
live_enabled=false
```

The approval cannot exceed designation expiry, cannot target another symbol, and cannot become a live approval.

### Durable approval journal

`SqliteTestnetActivationApprovals` is caller-owned and write-once:

```text
same approval ID + same content → idempotent
same approval ID + changed content → conflict
restart → typed rehydration
absent read → no database creation
```

## Actual approval artifact

Persisted outside the repository after verifying the previously frozen stable evidence:

```text
status:              approved_for_one_bounded_lifecycle
designation:         designation-testnet-002
designation hash:    fe21ab3f77525635154f0439560b47325da4a21f081aa26bc4cc28181006960a
approval:            approval-testnet-002
approval hash:       b22da49d2729d1d5952fffb484aa48aa43832e0db36bafa2f927e2b81b479f60
symbol:              BTCUSDT
max quote notional:  100 USDT
new_actions_allowed: true
live_enabled:       false
```

The approval journal is outside the repository and contains no credential or balance.

## TDD evidence

```text
RED: testnet_activation_approval module import missing
GREEN: exact one-lifecycle scope and expiry validation
GREEN: write-once approval journal behavior
```

## Verification

```text
Activation/approval/testnet focused subset: 36 passed
Locked full suite:                         615 passed
Ruff check:                                passed
Ruff format:                               passed
Mypy:                                      155 source files clean
uv lock --check:                           passed
direct py_compile Phase 29 files:           passed
git diff --check:                           passed
new network/order requests:                 0
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (bounded historical testnet scope)
live_enabled=false
approval scope=one_open_and_reduce_only_close
```

The approval is now available for one explicitly bounded lifecycle; no action will be automated or repeated. It does not authorize multi-symbol trading, scheduling, or live execution.
