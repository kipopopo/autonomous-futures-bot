# Phase 7E Verification — durable open-entry accounting

## Decision

Phase 7E removes the final accounting blocker for open paper observations. Open ledger entries can now carry durable `entry_fee` and `slippage_cost` together. No executor, fill source, scheduler, activation path, exchange client, or network access was added.

## Delivered

`PaperLedgerEntry` now enforces lifecycle-specific accounting:

```text
open:
  entry_fee + slippage_cost must be both present or both absent
  exit_fee / gross_pnl / net_pnl remain rejected

close:
  full entry/exit fees, slippage, gross P&L, and reconciled net P&L remain required
```

Existing legacy open rows with both entry-cost values absent remain auditable; they still make observations incomplete. New fully costed open rows can produce `accounting_complete=true` observations.

## Observation accounting

For open positions with durable entry costs:

```text
equity              = starting equity + realized P&L + unrealized P&L - paid open fees
cumulative fees     = closed fees + open entry fees
cumulative slippage = closed slippage + open entry slippage
```

Slippage is not subtracted from equity a second time: the adverse entry fill already represents its economic effect. Missing paired open costs remain fail-closed with `open_position_entry_accounting_unavailable`.

## TDD evidence

```text
RED 1: open event with entry accounting rejected by shared ledger guard
GREEN 1: ledger/SQLite focused set — 8 passed

RED 2: observation ignored open fee/slippage and remained incomplete
GREEN 2: ledger + observation focused set — 12 passed

related paper tests: 33 passed
```

## Verification

```text
full locked suite: 521 passed
Ruff:              passed
Ruff format:       passed
Mypy:              128 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

All inputs remain caller-supplied strict `Decimal` values. There is no automatic fill generation, mutation beyond caller-appended ledger rows, paper activation, execution authority, exchange access, scheduler, testnet, or live route.
