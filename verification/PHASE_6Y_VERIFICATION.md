# Phase 6Y Verification — fail-closed paper safety gate

## Decision

Phase 6Y adds a pure paper-safety evaluator. It cannot authorize paper activation; every result remains blocked.

## Delivered

`src/autonomous_futures/paper/safety.py` provides explicit evidence and a deterministic decision:

```text
PaperSafetyEvidence(candidate identity/hash, qualification hash/decision,
                    zero-OOS-liquidations attestation)
evaluate_paper_safety(request, evidence) -> PaperSafetyDecision
```

The evaluator checks the request/evidence candidate binding, qualification decision, and supplied zero-liquidation attestation. It always returns:

```text
allowed=false
paper_activation=false
execution_authority=false
exchange_access=false
```

A fully matching qualified evidence input receives only `paper_activation_not_authorized`; rejected, liquidated, or mismatched evidence receives deterministic additional blocker codes.

## TDD evidence

```text
RED: ModuleNotFoundError: autonomous_futures.paper.safety
GREEN: tests/unit/test_paper_safety.py — 3 passed
```

One test-fixture correction was required after GREEN: `PaperExecutionRequest` deliberately requires actual `Decimal` values rather than strings. Production validation was not relaxed.

## Verification

```text
related paper tests: 17 passed
full locked suite:   505 passed
Ruff:                passed
Ruff format:         passed
Mypy:                124 source files clean
uv lock --check:     passed
git diff --check:    passed
```

## Scope and safety

No activation transition, executor, scheduler, persistence adapter, database, network/exchange import, live/testnet route, or candidate-state mutation was added. Qualification evidence remains evidence only; a separate human-approved activation design remains required.
