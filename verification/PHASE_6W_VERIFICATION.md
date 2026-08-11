# Phase 6W Verification — deterministic paper fill calculator

## Decision

Phase 6W adds a pure, paper-only round-trip fill calculator. It accepts only
the default-blocked `PaperExecutionRequest` contract and an explicit exit mark
price. It does not persist trades, open a position, activate paper mode, call a
network/exchange client, or route an order.

## Delivered

`src/autonomous_futures/paper/fills.py` provides:

```text
simulate_paper_round_trip(request, exit_mark_price)
```

The calculator uses deterministic adverse fills:

```text
LONG:  entry = mark × (1 + slippage), exit = mark × (1 - slippage)
SHORT: entry = mark × (1 - slippage), exit = mark × (1 + slippage)
```

It calculates exact Decimal gross P&L, entry/exit fees, total fees, explicit
slippage cost, and net P&L. The typed result remains non-authoritative:

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

## TDD evidence

```text
RED:   ModuleNotFoundError: autonomous_futures.paper
GREEN: tests/unit/test_paper_fills.py — 3 passed
related paper contracts + fills:       10 passed
```

The focused tests prove LONG and SHORT adverse fills, both fees, slippage cost,
net-P&L reconciliation, fixed safety flags, and rejection of a non-positive
exit mark price.

## Verification

```text
full locked suite: 498 passed
Ruff:              passed
Ruff format:       passed
Mypy:              122 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No ledger, database, scheduler, service, API, position lifecycle, paper
activation, testnet/live route, exchange import, or network call was added.
The next bounded slice is injected durable paper-ledger design and restart
recovery; it remains blocked by default until a distinct safety transition is
implemented and approved.
