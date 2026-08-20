# Phase 40 Verification — offline one-shot live activation token

## Scope

Phase 40 adds a durable, hash-bound one-shot activation token contract. It does not enable live network access or place a live order.

```text
No live endpoint
No credential lookup
No network
No order
No scheduler
```

## Delivered

`LiveActivationToken` is issued only from an approved live design review and binds:

```text
review ID + review hash
symbol
50% max quote notional profile
1% max capital-at-risk profile
2% max daily-loss profile
issued_at / expires_at
remaining_uses=1
```

Token constraints:

```text
state=issued_not_enabled
live_enabled=false
network_allowed=false
expiry <= review expiry
```

`SqliteLiveActivationTokens` provides caller-owned write-once persistence:

```text
same token ID + same content → idempotent
same token ID + changed content → conflict
restart → typed rehydration
absent read → no database creation
```

No token was issued into the real runtime journal in this phase; only offline test fixtures were used.

## TDD evidence

```text
RED: live_activation module import missing
GREEN: one-shot disabled token with bound risk/provenance
GREEN: unapproved/extended-expiry rejection
GREEN: write-once journal behavior
```

## Verification

```text
Activation/live/testnet focused subset: 50 passed
Locked full suite:                    629 passed
Ruff check:                           passed
Ruff format:                          passed
Mypy:                                 161 source files clean
uv lock --check:                      passed
direct py_compile Phase 40 files:      passed
git diff --check:                     passed
live/network actions:                  0
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (historical bounded testnet evidence only)
live_enabled=false
network_allowed=false
new_actions_allowed=false
```

Phase 40 creates the offline token contract only. It does not issue a production token, enable the adapter, read live credentials, deploy a service, or place an order.
