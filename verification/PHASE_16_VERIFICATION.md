# Phase 16 Verification — offline Stage B read-only testnet adapter

## Scope

Stage B advances the testnet boundary only through an injected fake transport. It validates the public read-only exchange-info contract without granting network access or credentials.

```text
No real HTTP transport
No WebSocket transport
No API key
No secret
No account/private endpoint
No order endpoint
No scheduler
No live endpoint
```

## Delivered

### Injected transport contract

`TestnetReadOnlyClient` accepts a caller-provided transport:

```text
(method, URL, query) → TestnetResponse
```

The client itself performs only one explicit public `GET` contract call:

```text
GET https://demo-fapi.binance.com/fapi/v1/exchangeInfo
```

Tests use a local fake transport and record the exact method, URL, and empty query. No HTTP library is imported.

### Typed exchange-info validation

The adapter validates the response into:

```text
TestnetExchangeInfo
  └── TestnetExchangeSymbol
        symbol
        status
        base_asset
        quote_asset
```

Malformed body/symbol rows are rejected. Symbol lookup is exact and missing symbols fail closed.

### Error handling

Non-200 responses are classified through the Stage A offline classifier. The adapter raises `TestnetReadOnlyError` with a disposition and never retries:

```text
503 unknown → reconcile
503 unavailable → retry disposition only
429 → retry disposition only
4xx → reject
```

The `retry` disposition is data for a future orchestrator; this adapter does not perform it.

### Environment isolation

The client accepts only the official USDⓈ-M testnet base URL. Production base URLs are rejected before transport invocation.

## TDD evidence

```text
RED: autonomous_futures.testnet_readonly import missing
GREEN: injected GET, typed exchange info, symbol lookup,
malformed response rejection, production URL rejection,
error disposition without retry
```

## Verification

```text
Stage A/B + paper boundary focused subset: 39 passed
Locked full suite:                         589 passed
Ruff check:                                passed
Ruff format:                               passed
Mypy:                                      146 source files clean
uv lock --check:                           passed
direct py_compile Stage B files:            passed
network/scheduler import scan:             passed
git diff --check:                           passed
```

The adapter remains Python 3.11-compatible; no newer `type` alias syntax was introduced.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

Stage B proves only an offline, public read-only adapter contract. It does not prove real testnet connectivity, account access, credentials, exchange-info freshness, order acceptance, or live readiness. Real connectivity remains a separately approved action.
