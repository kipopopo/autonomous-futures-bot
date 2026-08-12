# Phase 7B Verification — durable paper close accounting

## Decision

Phase 7B closes the accounting prerequisite for a future read-only paper observation: every new paper `close` event must carry complete, reconciled accounting. No observation snapshot, executor, activation, or scheduler is added here.

## Delivered

`PaperLedgerEntry` now requires every close event to contain:

```text
entry_fee
exit_fee
slippage_cost
gross_pnl
net_pnl
```

The close is rejected unless all fields are present, fees/slippage are non-negative, P&L is finite, and:

```text
net_pnl == gross_pnl - entry_fee - exit_fee
```

Open events reject any close accounting fields. `SqlitePaperLedger` persists and rehydrates these exact Decimal values as text, converting only at the storage boundary.

The SQLite initialization is additive: existing Phase 7A event tables receive the five nullable accounting columns through `ALTER TABLE`; historical close rows without those fields fail closed during ledger validation rather than being silently used as accounting evidence.

## TDD evidence

```text
RED: close events accepted missing accounting; accounting fields were forbidden
GREEN: close accounting contract and persisted mapping — 9 passed
legacy schema additive migration: 1 passed
related paper tests: 26 passed
```

A missing `Decimal` import was exposed by Pydantic deferred annotations and fixed. Mypy then required explicit narrowing after the existing fail-closed completeness guard.

## Verification

```text
full locked suite: 514 passed
Ruff:              passed
Ruff format:       passed
Mypy:              126 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No snapshot/journal rows, equity baseline, runtime executor, activation, scheduler, exchange/network client, testnet route, or live route was added. The durable ledger now has the necessary closed-trade accounting substrate; a future observation component must still receive explicit equity and mark inputs and remain read-only.
