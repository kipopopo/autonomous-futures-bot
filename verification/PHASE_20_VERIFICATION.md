# Phase 20 Verification — offline testnet order-test descriptor

## Scope

Phase 20 defines an offline descriptor for the USDⓈ-M `/fapi/v1/order/test` capability. It does not send a POST request.

```text
No order-test POST
No order router
No retry
No scheduler
No live endpoint
No new credentials
```

## Delivered

### Mandatory risk gate

`build_testnet_order_test_request(...)` first runs the existing quote-notional and exchange-filter validation. A blocked risk decision raises before any request descriptor is created.

The gate retains:

```text
symbol/filter binding
quantity/step/min-notional checks
quote-notional cap
leverage cap
open-position limit
one-position-per-symbol rule
reduce-only state rule
```

### Signed request descriptor

For an approved proposal it produces a typed descriptor only:

```text
method: POST
path:  /fapi/v1/order/test
host:   https://demo-fapi.binance.com
order:  MARKET
client ID prefix: afbot-test-
```

The descriptor contains the API-key header and signed query, but no sender/transport. The secret is used only inside HMAC generation and never appears in the descriptor.

`live_enabled` is structurally false.

## TDD evidence

```text
RED: autonomous_futures.testnet_order_test import missing
GREEN: risk-approved signed descriptor
GREEN: risk-blocked proposal rejected before descriptor creation
```

## Verification

```text
Order-test/private/Stage A-B + paper subset: 46 passed
Locked full suite:                         596 passed
Ruff check:                                passed
Ruff format:                               passed
Mypy:                                      148 source files clean
uv lock --check:                           passed
direct py_compile Phase 20 files:            passed
network/sender/scheduler import scan:       passed
git diff --check:                           passed
actual POST requests sent:                   0
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (read-only testnet/private smoke boundary only)
live_enabled=false
```

This phase proves only offline order-test request construction and risk gating. It does not prove order-test acceptance, testnet position mutation, order lifecycle correctness, profitability, or live readiness.
