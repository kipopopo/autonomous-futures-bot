# Phase 7A Verification — caller-owned durable SQLite paper ledger

## Decision

Phase 7A adds the minimal durable storage required for legitimate restart recovery: a caller-owned SQLite adapter for append-only paper ledger events. It does not select a default path, start a runtime, activate paper mode, or add any exchange/network route.

## Delivered

`src/autonomous_futures/paper/sqlite_ledger.py` provides:

```text
SqlitePaperLedger(explicit_path)
.append(PaperLedgerEntry)
.load() -> PaperLedger
```

One stdlib SQLite table stores the paper event sequence. On every append, the adapter rehydrates the existing sequence into the established `PaperLedger`, validates the next lifecycle transition, then inserts it in the same transaction. Invalid duplicate opens therefore never reach durable storage.

`load()` rebuilds the established in-memory ledger, including current open positions, from ordered durable rows. Decimal values are stored as exact text and converted to `Decimal` only at the SQLite boundary; the domain’s strict Decimal contract remains unchanged.

## TDD evidence

```text
RED: ModuleNotFoundError: autonomous_futures.paper.sqlite_ledger
GREEN initially exposed strict Decimal rehydration from SQLite text
GREEN after storage-boundary conversion: 3 passed
related paper tests: 23 passed
```

Focused tests prove open-event persistence and restart hydration, close-history preservation after reopening storage, and duplicate-open rejection without a second persisted row.

## Verification

```text
full locked suite: 511 passed
Ruff:              passed
Ruff format:       passed
Mypy:              126 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

The adapter imports only `sqlite3`, `Decimal`, `Path`, and paper-ledger types. It is caller-owned: no default data path, service, scheduler, executor, safety authorization, paper activation, exchange client, network client, testnet route, or live route exists. `paper_activation`, `execution_authority`, and `exchange_access` remain false.
