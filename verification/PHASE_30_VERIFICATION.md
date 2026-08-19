# Phase 30 Verification — approved second bounded testnet lifecycle

## Scope

Phase 30 executes the fresh, explicitly approved one-lifecycle BTCUSDT testnet scope:

```text
one symbol: BTCUSDT perpetual
max quote notional: 100 USDT
one open + one reduce-only close
no automation
```

## Activation approval

The previous approval was checked and found expired. It was not reused. A fresh designation and approval were created with a short explicit validity window before any order:

```text
designation: designation-testnet-003
approval:    approval-testnet-003
symbol:      BTCUSDT
max quote:   100 USDT
scope:       one_open_and_reduce_only_close
live_enabled=false
```

## Lifecycle result

```text
preflight account: flat
open:  MARKET BUY FILLED
close: MARKET SELL reduceOnly FILLED
post-close account: flat
```

Order IDs:

```text
open:  28546827479
close: 28546827508
```

The first execution script stopped before POST because it discovered an approval-model field mismatch (`max_open_positions` was not present). No order was sent by that failed attempt. The corrected bounded script then executed exactly the approved lifecycle.

## Evidence freeze

After the close, read-only order/account queries were used to create and freeze the second lifecycle evidence:

```text
audit:             reconciled
audit ID:          audit-testnet-28546827479-28546827508
audit hash:        536a34acc19f9d63f2cf1e8602413f6037eb7677cd0bb718abfe97999b68503b
observation:       stable
observation hash:  072d493b727cfebac332479bc24c67116393d734d86fc948656a94689246c79b
review:            review-testnet-evidence-002
review hash:       18ff3477ca73cfef3823cfc15069906a87bc8b442cb5ddf7caf48bd93a15ff0e
nonzero positions: 0
```

Evidence was persisted outside the repository. No credential, balance, or raw account payload was persisted.

## Verification

```text
Locked full suite:             615 passed
Ruff/format/mypy/lock:         passed
New POST after close:          0
Final account nonzero positions: 0
HEAD/origin equality:          verified after delivery
```

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=true (two explicit bounded testnet lifecycles)
live_enabled=false
new_actions_allowed=false after evidence freeze
```

The activation approval is consumed operationally by this single lifecycle and the resulting evidence is frozen. No unattended execution, scheduler, multi-symbol rollout, or live trading is authorized.
