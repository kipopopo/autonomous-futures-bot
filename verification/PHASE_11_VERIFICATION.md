# Phase 11 Verification — read-only aggregate paper health

## Scope

This phase adds a read-only aggregate report across the existing observation journal and lifecycle-mark journal.

```text
No scheduler
No current-clock lookup
No market-data loader
No network
No signal consumer
No lifecycle mutation
No automatic close
No promotion/testnet/live authority
```

All time and freshness limits are explicit caller inputs.

## Delivered

### Aggregate health contract

`aggregate_paper_health(...)` combines:

```text
latest bound paper observation
fixed-slot maturity status
latest lifecycle mark per trade
mark age against explicit maximum age
stale mark flags
stop/take-profit exit readiness
```

Health states are:

```text
unavailable  → no observation evidence
maturing     → seven-day fixed-slot gate is still in progress
healthy      → mature, complete accounting, no stale/exit-ready issue
attention    → stale mark, exit-ready diagnostic, or missing telemetry for an open position
blocked      → binding/time/accounting/maturity integrity failure
```

The report includes exact latest equity/drawdown/open count, lifecycle P&L and age, reason codes, and false-only authority fields.

`exit_ready` and `attention` remain diagnostic. They never close a position or create execution permission.

### Candidate-wide lifecycle read

`SqlitePaperLifecycle.read_candidate(...)` provides an exact candidate/hash-bound read across all trades. It reuses the same append-only journal and does not change the schema.

### Read-only health CLI

```bash
python -m autonomous_futures.paper.health_cli \
  --observation-path <path> \
  --lifecycle-path <path> \
  --candidate-id <id> \
  --candidate-artifact-hash <sha256> \
  --as-of <UTC timestamp> \
  --max-mark-age-seconds <integer>
```

The CLI reads both caller-owned journals, emits canonical JSON with `status`, and leaves row counts unchanged. Absent journals return `unavailable` without creating files.

## TDD evidence

```text
RED: aggregate health module import missing
GREEN: healthy mature candidate with lifecycle mark age

GREEN extensions: stale/exit-ready attention, maturing state,
unavailable evidence, incomplete-accounting block

RED: health CLI import missing
GREEN: real SQLite healthy aggregate and absent-journal behavior
```

## Verification

```text
Health/lifecycle/observation focused subset: 28 passed
Locked full suite:                         566 passed
Ruff check:                                passed
Ruff format:                               passed
Mypy:                                      139 source files clean
uv lock --check:                           passed
direct py_compile Phase 11 files:            passed
git diff --check:                           passed
runtime import safety scan:                passed
```

The repository-wide compileall limitation documented in Phase 9/10 remains confined to unrelated pre-existing overlong research/test filenames on Windows. Direct compilation of all Phase 11 files passed.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

This report proves observability and evidence integrity only. It does not prove profitability, promotion eligibility, testnet readiness, or live execution permission.
