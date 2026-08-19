# Phase 39 Verification — offline live adapter hard gate

## Scope

Phase 39 adds an offline live order descriptor and an injected-transport boundary. It never owns or opens an HTTP connection.

```text
No live endpoint call
No live credential lookup
No order
No scheduler
No production transport
```

## Delivered

### Production-only descriptor

`build_live_order_request(...)` creates a typed `POST /fapi/v1/order` descriptor only when:

```text
HTTPS production host is exactly fapi.binance.com
path is under /fapi/
API key is explicit
signing secret is explicit
quantity is finite and positive Decimal
timestamp is positive integer
```

Demo/testnet and non-HTTPS endpoints are rejected.

### Hard activation gate

`send_live_order_request(...)` accepts an injected transport for offline testing, but the current review contract is:

```text
state=reviewed_not_activated
live_enabled=false
network_allowed=false
```

Therefore the function raises before transport invocation. Regression test confirms:

```text
transport calls: 0
```

The request descriptor itself also remains `live_enabled=false`.

## TDD evidence

```text
RED: live_adapter module import missing
GREEN: production-only descriptor and invalid quantity rejection
GREEN: reviewed_not_activated blocks transport before send
```

## Verification

```text
Live-adapter/testnet focused subset: 47 passed
Locked full suite:                 626 passed
Ruff check:                        passed
Ruff format:                       passed
Mypy:                              160 source files clean
uv lock --check:                   passed
direct py_compile Phase 39 files:   passed
git diff --check:                  passed
live/network actions:               0
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

Phase 39 proves only the offline descriptor and hard pre-transport gate. It does not activate live access, read live credentials, deploy a service, or place an order.
