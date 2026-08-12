# Phase 7I Verification — immutable paper-observation authority locks

## Decision

Phase 7I closes the last concrete observation integrity gap found during Ponytail review. Persisted `PaperObservation` snapshots previously accepted ordinary booleans for paper activation, execution authority, and exchange access. A malformed/manual journal payload could therefore represent authority as true even though every other paper boundary is hard blocked.

## Delivered

`PaperObservation` now uses structural false-only authority fields:

```text
paper_activation:   Literal[False]
execution_authority: Literal[False]
exchange_access:    Literal[False]
```

Any typed construction or journal rehydration that supplies true for any of these fields fails validation. Normal snapshots, capture, inspection, and append-only persistence remain unchanged.

## TDD evidence

```text
RED: PaperObservation accepted paper_activation=true
GREEN: focused observation safety/regression set — 9 passed
related paper tests: 37 passed
```

The new regression constructs a real typed observation with `paper_activation=true` and asserts a Pydantic validation failure.

## Verification

```text
full locked suite: 525 passed
Ruff:              passed
Ruff format:       passed
Mypy:              130 source files clean
uv lock --check:   passed
git diff --check:  passed
```

## Scope and safety

No engine, scheduler, runtime loop, capture behavior, read behavior, ledger/table migration, mark source, exchange/network client, credential, activation transition, testnet, or live route was introduced. The remaining proposed engine would be a permanent no-op because `PaperSafetyDecision.allowed` is structurally false; it is intentionally not added pending a separate explicit activation design/approval.
