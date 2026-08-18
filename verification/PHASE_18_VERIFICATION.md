# Phase 18 Verification — offline private read-only account reconciliation

## Scope

This phase implements the private testnet boundary offline only. It creates signed request descriptors and pure account reconciliation; it does not send authenticated requests.

```text
No API key supplied to runtime
No secret supplied to runtime
No HTTP/private transport
No account request
No order request
No scheduler
No live endpoint
```

Tests use fake values only.

## Delivered

### Signed account request descriptor

`build_testnet_account_request(...)` creates a typed, read-only descriptor for the official USDⓈ-M Account Information V3 path:

```text
method: GET
path:  /fapi/v3/account
host:   https://demo-fapi.binance.com
```

The descriptor contains:

```text
X-MBX-APIKEY header
canonical signed query
recvWindow validation (1..60000)
timestamp_ms validation
```

The secret is used only to compute the HMAC signature and is not returned, persisted, or logged by the contract. The module has no transport function.

### Account snapshot parser

`parse_testnet_account_snapshot(...)` validates explicit account-shaped JSON into typed:

```text
wallet/available balances
asset rows
position rows
symbol
position amount
entry price
mark price
position side
```

Decimal values are parsed explicitly and finite-value checks are enforced.

### Pure position reconciliation

`reconcile_testnet_account(...)` compares caller-supplied expected positions with the parsed remote snapshot:

```text
reconciled → exact non-zero position match
drift      → missing, unexpected, or mismatched positions
```

It performs no write, close, retry, or order action. The result is `live_enabled=false`.

## TDD evidence

```text
RED: autonomous_futures.testnet_private import missing
GREEN: signed request descriptor, credential omission, account parsing,
exact reconciliation, and drift detection
```

## Verification

```text
Private + Stage A/B + paper focused subset: 44 passed
Locked full suite:                         594 passed
Ruff check:                                passed
Ruff format:                               passed
Mypy:                                      147 source files clean
uv lock --check:                           passed
direct py_compile Phase 18 files:           passed
network/transport import scan:              passed
git diff --check:                           passed
```

Official account documentation anchor:

- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account

No authenticated network smoke was attempted because no credentials were supplied or authorized for runtime use.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

This phase proves only offline signing/request-shape, account parsing, and reconciliation behavior. It does not prove account access, credential validity, private endpoint connectivity, testnet order readiness, or live readiness.
