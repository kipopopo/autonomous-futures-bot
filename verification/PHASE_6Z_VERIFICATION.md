# Phase 6Z Verification — paper runtime/ledger reconciliation

## Decision

Phase 6Z adds the smallest reconciliation check: compare caller-injected runtime open trade IDs against injected paper-ledger open rows. It reports drift but never repairs, writes, opens, closes, activates, or routes anything.

## Delivered

`src/autonomous_futures/paper/reconciliation.py` provides:

```text
reconcile_paper_positions(ledger, runtime_open_trade_ids)
```

It returns a typed, deterministic report:

```text
reconciled
runtime_only_trade_ids
ledger_only_trade_ids
reason_codes
```

It detects runtime IDs missing from the ledger, ledger rows absent from runtime state, and duplicate runtime IDs. Equality returns the sole success code `paper_positions_reconciled`.

## TDD evidence

```text
RED:   ModuleNotFoundError: autonomous_futures.paper.reconciliation
GREEN: tests/unit/test_paper_reconciliation.py — 3 passed
related paper tests: 20 passed
```

Focused tests prove exact reconciliation, bidirectional drift reporting without ledger mutation, and duplicate-runtime detection.

## Verification

```text
full locked suite: 508 passed
Ruff:              passed
Ruff format:       passed
Mypy:              125 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No observation snapshot is added: current paper data has no durable ledger adapter, equity baseline, or immutable observation storage, so it could not produce legitimate promotion evidence. No scheduler, executor, activation, database, network/exchange client, or live/testnet path was added. `paper_activation`, `execution_authority`, and `exchange_access` remain false.
