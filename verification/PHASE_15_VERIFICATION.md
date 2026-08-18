# Phase 15 Verification — offline testnet Stage A contracts

## Scope

Stage A implements offline contracts for a future Binance USDⓈ-M Futures testnet adapter. It does not connect to Binance or use credentials.

```text
No HTTP client
No WebSocket client
No credentials
No signed request transmission
No order router
No scheduler
No testnet order
No live endpoint
```

## Delivered

### Endpoint allow-list

`validate_testnet_rest_url(...)` accepts only HTTPS URLs whose host is the official USDⓈ-M testnet host and whose path is under `/fapi/`.

```text
accepted host: https://demo-fapi.binance.com
```

Production host, HTTP, and unrelated API paths are rejected.

### Offline HMAC signing vector

`sign_testnet_query(...)` deterministically canonicalizes sorted string parameters and computes HMAC-SHA256 using a caller-supplied secret. Tests use only the fake value `test-secret`; no secret is stored or transmitted.

Already-signed queries and empty secrets are rejected.

### Quote-notional and exchange-filter risk contract

`validate_testnet_order(...)` validates:

```text
symbol binding
min/max quantity
step size
minimum quote notional
caller max quote notional
maximum leverage
maximum open positions
one position per symbol
reduce-only requires an existing symbol position
```

It returns explicit quote notional and margin notional. Leverage is applied once:

```text
margin_notional = quote_notional / leverage
```

The decision contains `live_enabled=false` and cannot authorize live trading.

### Error classification

Offline mapping:

```text
503 unknown execution status → reconcile
503 service unavailable     → retry
429                        → retry
418                        → halt
4xx                        → reject
other 5xx                  → retry
```

The unknown execution path never becomes an automatic retry.

### Reconciliation state machine

Offline state decisions:

```text
not_submitted + no exchange state → safe_to_submit
unknown + NEW/PARTIALLY_FILLED/FILLED → reconciled_no_retry
unknown + CANCELED/EXPIRED/REJECTED → retry_allowed
unknown + no exchange state → halt_ambiguous_state
```

No state function performs I/O.

## Official documentation anchor

The Stage 14 design research used the current official USDⓈ-M documentation:

- REST testnet: `https://demo-fapi.binance.com`
- WebSocket testnet: `wss://demo-fstream.binance.com`
- protected account/trade endpoints require API-key authentication
- unknown-status `503` responses require reconciliation before retry

Sources:

- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info
- https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/quick-start

Endpoints must be re-verified immediately before any future network implementation.

## TDD evidence

```text
RED: autonomous_futures.testnet import missing
GREEN: endpoint, signing, risk, error, and reconciliation contracts
```

## Verification

```text
Stage A + paper boundary focused subset: 35 passed
Locked full suite:                      585 passed
Ruff check:                             passed
Ruff format:                            passed
Mypy:                                   145 source files clean
uv lock --check:                        passed
direct py_compile Stage A files:         passed
network/scheduler import scan:           passed
git diff --check:                        passed
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

Stage A proves only offline boundary behavior. It does not prove testnet connectivity, credentials, account readiness, order acceptance, testnet profitability, or live readiness.
