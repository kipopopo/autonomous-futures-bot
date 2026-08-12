# Phase 6X Verification — injected paper ledger hydration

## Decision

Phase 6X adds the smallest restart-safe lifecycle core: a caller-injected,
append-only paper ledger that reconstructs current open exposure from prior
events. It does **not** add a filesystem writer, SQLite schema, database
migration, service, scheduler, or paper activation.

## Delivered

`src/autonomous_futures/paper/ledger.py` provides:

```text
PaperLedgerEntry(event=open|close, explicit paper position fields)
PaperLedger(injected_entries).open_positions()
PaperLedger.append(entry)
```

The ledger validates its entire injected history during construction and keeps
an append-only event sequence. It rejects:

```text
duplicate open candidate/symbol exposure
reused open trade IDs
close without a matching open
close whose candidate/hash/symbol/side/quantity differs from the open
close timestamp preceding its open
```

Thus a new runtime instance can hydrate from caller-provided prior ledger
events and refuses a duplicate open for an already exposed candidate/symbol.

## TDD evidence

```text
RED:   ModuleNotFoundError: autonomous_futures.paper.ledger
GREEN: tests/unit/test_paper_ledger.py — 4 passed
related paper contracts/fills/ledger: 14 passed
```

Focused tests cover rehydration, duplicate-open rejection, valid close/history
preservation, and close-without-open rejection.

## Verification

```text
full locked suite: 502 passed
Ruff:              passed
Ruff format:       passed
Mypy:              123 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

The ledger has no storage/network/exchange imports and cannot activate paper
mode or route any order. Durable persistence must be a later, caller-owned
adapter with a real production storage contract; adding one now would be unused
speculative infrastructure. `paper_activation`, `execution_authority`, and
`exchange_access` remain false.
