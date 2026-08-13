# Phase 7L Verification — non-creating shared paper-ledger loads

## Decision

Phase 7L fixes the same caller-owned storage violation in the durable paper ledger. `SqlitePaperLedger.load()` previously called its schema-creating SQLite connector for an absent path, so a purported read/rehydration created an empty ledger database.

## Delivered

The shared `load()` method now returns an empty `PaperLedger` before connecting when its explicit SQLite path is absent:

```text
absent path → empty PaperLedger and no SQLite file
existing path → unchanged rehydration and additive migration
append()     → remains the only intentional ledger creator/writer
```

This applies to every direct caller, including the manual paper-observation capture command, without adding a CLI-specific duplicate guard.

## TDD evidence

```text
RED: direct load returned empty entries but created absent-paper-ledger.sqlite3
GREEN: focused ledger/migration/capture/observation tests — 9 passed
related paper tests: 40 passed
```

The new adapter-level regression calls `SqlitePaperLedger(path).load()` on a nonexistent explicit temporary path and asserts empty entries with no created file.

## Verification

```text
full locked suite: 528 passed
Ruff:              passed
Ruff format:       passed
Mypy:              130 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No schema migration behavior for existing databases, append behavior, scheduler, runtime loop, fill/signal engine, market/exchange/network client, credential, activation, testnet, or live route was added. Paper authority remains structurally false.
