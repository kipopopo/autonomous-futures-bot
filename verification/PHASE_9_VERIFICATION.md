# Phase 9 Verification — fixed-slot paper maturity evidence

## Scope

This phase adds a read-only maturity evaluator for the existing caller-owned paper observation journal.

```text
No scheduler
No current-clock lookup
No market-data loader
No network
No signal consumer
No ledger mutation
No promotion
No testnet/live authority
```

The existing seven-day evidence requirement is preserved. It is not shortened because more observations are available.

## Delivered

### Fixed UTC cadence

Observations are grouped into deterministic six-hour UTC slots:

```text
00:00Z, 06:00Z, 12:00Z, 18:00Z
```

The default seven-day maturity window requires:

```text
7 days × 4 slots/day = 28 required slots
```

`as_of` is caller-supplied. The evaluator never reads the machine clock.

### Fail-closed report

`evaluate_paper_maturity(...)` returns a typed `PaperMaturityReport` with:

```text
unavailable  → no observations
maturing     → calendar window is still in progress
blocked      → duplicate, missing completed slot, incomplete accounting,
               future timestamp, or binding mismatch
mature       → complete seven-day slot coverage and complete accounting
```

The report exposes first/last slot, maturity end, next required slot, observed-slot count, and explicit reason codes.

Authority fields remain structurally false:

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

### Read-only CLI

Added:

```bash
python -m autonomous_futures.paper.maturity_inspect_cli \
  --observation-path <path> \
  --candidate-id <id> \
  --candidate-artifact-hash <sha256> \
  --as-of <UTC timestamp>
```

`--required-days` is explicit and defaults to the unchanged seven-day gate. The CLI reads the existing journal, emits canonical typed JSON, and does not create an absent journal or append rows.

## TDD evidence

```text
RED: maturity module import missing
GREEN: complete 28-slot seven-day maturity report

RED: maturity inspector CLI import missing
GREEN: mature journal inspection and absent-journal unavailable result
```

Failure drills cover:

```text
in-progress maturity
missing completed slot
incomplete accounting
duplicate fixed slot
empty evidence
absent journal
```

## Verification

```text
Maturity/CLI focused tests: 8 passed
Maturity + observation/ledger regression subset: 30 passed
Locked full suite: 550 passed
Ruff check: passed
Ruff format: passed
Mypy: 134 source files clean
uv lock --check: passed
git diff --check: passed
Direct py_compile of all new Phase 9 files: passed
Runtime import safety scan: passed
```

Full repository compileall was attempted but remains unavailable because pre-existing research/test filenames exceed the Windows path limit while Python tries to create `.pyc` files. This is unrelated to the Phase 9 files; direct compilation of every new file passed. No existing long-path files were renamed or altered in this phase.

## Safety boundary

A `mature` report proves only that the caller-supplied observation journal has the required fixed-slot calendar coverage and complete accounting. It does not prove profitability, promotion, paper activation, testnet readiness, or live execution permission.
