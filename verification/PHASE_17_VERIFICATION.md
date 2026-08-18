# Phase 17 Verification — public read-only testnet connectivity

## Scope

Phase 17 adds one real public GET transport to the Stage B adapter. It does not access private account data or submit orders.

```text
Public exchangeInfo GET only
No API key
No secret
No signed request
No account endpoint
No order endpoint
No WebSocket
No retry loop
No scheduler
```

## Delivered

### Stdlib public transport

`public_testnet_transport(...)` uses Python stdlib `urllib` with:

```text
HTTPS only
allow-listed demo-fapi.binance.com host
/fapi/ path restriction
GET only
10-second timeout
Accept: application/json
no authentication headers
no retry
```

HTTP errors are returned as typed `TestnetResponse` values so the existing classifier can decide `reconcile`, `retry`, `reject`, or `halt`. The adapter itself never retries.

### Official exchange-info parsing

The typed response now preserves:

```text
symbol
status
base asset
quote asset
contract type
```

`get_symbol(...)` returns only `PERPETUAL` contracts, matching the project’s USDⓈ-M perpetual scope.

During the first real smoke, the official response exposed two schema realities that were fixed at the parser boundary:

```text
some identifiers contain underscores, e.g. ETHUSDT_250627
Demo response contains a non-ASCII test symbol, e.g. 测试测试USDT
```

The response parser now preserves exchange identifiers as non-empty strings while order proposals remain separately canonical/risk-validated.

## Real public smoke evidence

Command used an explicit temporary `PYTHONPATH=src` for the repository’s src layout. No credentials or auth headers were provided.

```text
endpoint:        https://demo-fapi.binance.com/fapi/v1/exchangeInfo
result:          ok
symbols:         733
perpetual:       677
first perpetual: BTCUSDT, ETHUSDT, BCHUSDT, XRPUSDT, EOSUSDT
```

This was read-only public metadata access. No account state, order, or position was touched.

## TDD evidence

```text
RED: public_testnet_transport import missing
GREEN: fake urlopen contract, no-auth headers, timeout, JSON decode

Real smoke exposed parser mismatch
GREEN: underscore/non-ASCII response identifiers and PERPETUAL filtering
```

## Verification

```text
Stage A/B + paper boundary focused subset: 40 passed
Locked full suite:                       590 passed
Ruff check:                              passed
Ruff format:                             passed
Mypy:                                    146 source files clean
uv lock --check:                         passed
direct py_compile Phase 17 files:         passed
network/scheduler import scan:            passed
git diff --check:                         passed
real public testnet smoke:                passed
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

This phase proves only public exchange-info reachability and response parsing. It does not prove credentials, account readiness, private reconciliation, order acceptance, testnet profitability, or live readiness.
