# Phase 10 Verification — durable paper lifecycle telemetry

## Scope

This phase adds caller-injected lifecycle telemetry for existing open paper positions.

```text
No scheduler
No market-data source
No network
No signal consumer
No automatic close
No order route
No promotion or activation
```

Every mark price, mark timestamp, prior peak P&L, and optional stop/take-profit threshold is explicit caller input.

## Delivered

### Pure lifecycle telemetry

`mark_paper_position(...)` derives a typed `PaperLifecycleTelemetry` from one durable open event and explicit caller inputs:

```text
mark price
timestamp
mark-to-market P&L
P&L percentage
peak P&L
whole-second holding duration
stop-loss / take-profit contract
stop-loss hit
take-profit hit
lifecycle status: open | exit_ready
```

P&L uses Decimal arithmetic and the existing LONG/SHORT position semantics:

```text
LONG  = (mark - entry) × quantity
SHORT = (entry - mark) × quantity
```

Threshold validation is directional:

```text
LONG:  stop < entry < take-profit
SHORT: take-profit < entry < stop
```

A hit threshold changes only the read-only lifecycle status to `exit_ready`; it does not close the position or authorize an action.

### Durable mark journal

`SqlitePaperLifecycle` is caller-owned and append-only. It supports:

```text
append telemetry
read exact candidate/hash/trade history
latest exact telemetry after restart
```

Absent reads do not create a database. Existing empty SQLite files are read without schema bootstrap. The journal is separate from the trade ledger, so marks cannot rewrite lifecycle history.

### Manual mark CLI

```bash
python -m autonomous_futures.paper.lifecycle_cli \
  --ledger-path <path> \
  --lifecycle-path <path> \
  --candidate-id <id> \
  --candidate-artifact-hash <sha256> \
  --trade-id <trade-id> \
  --mark-price <decimal> \
  --marked-at <UTC timestamp> \
  --previous-peak-pnl <decimal>
```

Optional thresholds are explicit flags. The CLI reads an existing durable open position, records one telemetry mark, and returns canonical JSON. Missing durable open returns `unavailable` without creating the lifecycle journal. It has no default path, current-clock lookup, market lookup, scheduler, or network access.

## TDD evidence

```text
RED: lifecycle module import missing
GREEN: LONG telemetry with take-profit readiness

GREEN extensions: SHORT P&L/stop readiness, neutral open state,
threshold-contract validation

RED: SQLite lifecycle journal import missing
GREEN: append, restart rehydration, latest read, absent-read purity

RED: lifecycle CLI import missing
GREEN: explicit mark recording and missing-open no-write behavior
```

## Verification

```text
Lifecycle/observation focused subset: 28 passed
Locked full suite:                   559 passed
Ruff check:                          passed
Ruff format:                         passed
Mypy:                                137 source files clean
uv lock --check:                     passed
direct py_compile Phase 10 files:     passed
git diff --check:                    passed
runtime import safety scan:          passed
```

The previously documented repository-wide `compileall` limitation remains: unrelated pre-existing research/test filenames exceed Windows path limits when Python creates `.pyc` files. This Phase 10 direct compilation passes and no long-path legacy files were changed.

## Safety status

Telemetry is observational only:

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

`exit_ready` is a diagnostic flag, not an automatic close instruction or execution permission. Testnet/live work remains a separate approval boundary.
