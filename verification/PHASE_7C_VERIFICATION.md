# Phase 7C Verification — read-only paper observation snapshot

## Decision

Phase 7C adds a pure, read-only paper observation calculator. It derives a snapshot from a durable-ledger view plus caller-supplied equity/mark inputs. It does not persist snapshots, execute a cycle, activate paper mode, repair state, or create any exchange/network path.

## Delivered

`src/autonomous_futures/paper/observation.py` provides:

```text
observe_paper_ledger(ledger, candidate binding, starting equity,
                     previous peak equity, explicit marks, observed_at)
```

For the bound candidate only, it derives:

```text
realized P&L          from durable closed net P&L
unrealized P&L        from explicit marks on current opens
equity / peak / drawdown
open-position count / quote exposure
cumulative close fees / cumulative close slippage
accounting completeness / deterministic reason code
```

The observation uses high-precision `Decimal` arithmetic. Drawdown remains a non-positive fraction. Missing marks for an open symbol fail closed.

## Accounting completeness

Closed-only snapshots are complete because Phase 7B requires full durable close accounting. Open events currently lack entry-fee/slippage accounting, so snapshots with any open position intentionally return:

```text
accounting_complete=false
reason_codes=("open_position_entry_accounting_unavailable",)
```

This is diagnostic-only and cannot serve as promotion evidence. It avoids silently substituting incomplete open-cost data.

## TDD evidence

```text
RED: ModuleNotFoundError: autonomous_futures.paper.observation
GREEN: tests/unit/test_paper_observation.py — 3 passed
related paper tests: 29 passed
```

Focused tests prove closed accounting/peak derivation, open-position explicit-mark exposure and incompleteness, and missing-mark rejection. A test expectation was changed to assert the documented high-precision drawdown formula rather than a manually truncated decimal literal.

## Verification

```text
full locked suite: 517 passed
Ruff:              passed
Ruff format:       passed
Mypy:              127 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No SQLite observation-journal table, scheduler, executor, activation, runtime loop, order route, exchange client, network client, testnet route, or live route was added. `paper_activation`, `execution_authority`, and `exchange_access` remain false.
