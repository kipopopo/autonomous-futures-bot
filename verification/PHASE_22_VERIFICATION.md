# Phase 22 Verification — one bounded testnet lifecycle

## Scope

Phase 22 performs one explicit USDⓈ-M Demo Trading lifecycle on BTCUSDT perpetual:

```text
preflight account flat
→ one MARKET BUY
→ private account verification
→ one reduce-only MARKET SELL
→ private account verification
```

No live endpoint, scheduler, WebSocket, multi-symbol rollout, or retry loop was used.

## Preflight

Live public metadata supplied the exact filters and price:

```text
symbol:          BTCUSDT
contract:        PERPETUAL
minimum notional: 50 USDT
market step:     0.0001
reference price: 64494.00
quantity:        0.0008
quote notional:  51.595360 USDT
leverage:        1
```

The private account preflight was flat before the opening request. Stage A quote-notional and filter gates passed.

## Lifecycle result

### Opening request

```text
endpoint:  POST /fapi/v1/order
side:      BUY
quantity:  0.0008 BTC
response:  FILLED
```

### Recovery event

The first post-open account parse exposed a real response-shape defect: Binance omitted `entryPrice` and `markPrice` on the active position row. The process did not retry the opening order.

Raw read-only inspection confirmed exactly one position:

```text
symbol:       BTCUSDT
positionSide: BOTH
positionAmt:  0.0008
```

The parser was fixed to treat those two fields as optional while keeping position amount and side required. A regression test was added.

### Closing request

```text
endpoint:  POST /fapi/v1/order
side:      SELL
reduceOnly: true
quantity:  0.0008 BTC
response:  FILLED
```

### Final reconciliation

```text
nonzero positions: []
```

The testnet account returned flat after the close. No live account or live endpoint was accessed.

## Credential handling

```text
source: local ignored .env
values printed: no
values persisted: no
withdrawal action: none
```

## Verification

```text
Testnet/private/order focused subset: 18 passed
Locked full suite:                    597 passed
Ruff check:                           passed
Ruff format:                          passed
Mypy:                                 148 source files clean
uv lock --check:                      passed
direct py_compile:                    passed
git diff --check:                     passed
open response:                        FILLED
close response:                       FILLED
final nonzero positions:              none
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (bounded testnet lifecycle only)
live_enabled=false
```

This phase proves one bounded testnet lifecycle and recovery-aware account reconciliation. It does not authorize unattended execution, multi-symbol trading, scheduler deployment, production/live routing, or live credentials.
