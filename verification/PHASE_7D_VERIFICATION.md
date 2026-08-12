# Phase 7D Verification — durable append-only paper observations

## Decision

Phase 7D adds caller-owned SQLite persistence for already-computed paper observation snapshots. It preserves both accounting-complete and accounting-incomplete snapshots as immutable diagnostic evidence. No execution cycle, activation, order path, scheduler, or network client is added.

## Delivered

`src/autonomous_futures/paper/sqlite_observation.py` provides:

```text
SqlitePaperObservations(explicit_path)
.append(PaperObservation)
.read(candidate_id, candidate_artifact_hash)
```

The adapter has one append-only SQLite table with a sequence key and exact Pydantic JSON payload. It filters reads by the candidate identity/hash binding and restores the complete `PaperObservation` contract on read.

Incomplete snapshots are intentionally not omitted or rewritten:

```text
accounting_complete=false
reason_codes=("open_position_entry_accounting_unavailable",)
```

They remain visible diagnostic evidence and cannot be silently treated as promotion-grade evidence.

## TDD evidence

```text
RED: ModuleNotFoundError: autonomous_futures.paper.sqlite_observation
GREEN: tests/unit/test_paper_sqlite_observations.py — 2 passed
related paper tests: 31 passed
```

Focused tests prove restart-safe persistence of a complete snapshot and ordered persistence/retrieval of an incomplete snapshot followed by a complete one.

The initial implementation behavior passed but was deliberately rewritten to match repository formatting/style before final verification; no behavior or scope expanded.

## Verification

```text
full locked suite: 519 passed
Ruff:              passed
Ruff format:       passed
Mypy:              128 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

The adapter imports only stdlib SQLite/path handling and the paper observation contract. It has no default runtime path, scheduler, executor, activation switch, exchange/network client, testnet route, or live route. `paper_activation`, `execution_authority`, and `exchange_access` remain false.
