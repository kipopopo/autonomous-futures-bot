# Phase 12 Verification — paper cohort human-review readiness

## Scope

This phase adds a read-only cohort summary over explicit `PaperHealthReport` values.

```text
No candidate discovery
No automatic promotion
No persistent activation
No scheduler
No market-data loader
No network
No order route
No testnet/live authority
```

The summary is a diagnostic checkpoint for human review only.

## Delivered

### Exact cohort contract

The caller supplies the expected candidate bindings:

```text
candidate_id + candidate_artifact_hash
```

The summarizer validates that every report:

- belongs to an expected binding;
- appears at most once;
- is not silently substituted for a missing candidate.

Unexpected or duplicate reports are `blocked`.

### Cohort readiness states

```text
unavailable              → no reports supplied
not_ready                → missing, maturing, attention, unavailable,
                            or non-mature candidate evidence
blocked                  → invalid binding or blocked candidate report
ready_for_human_review   → every expected candidate is healthy, mature,
                            and accounting-complete
```

The report includes:

```text
expected/reported counts
healthy/mature/attention/maturing/blocked counts
missing candidate IDs
all_mature
all_accounting_complete
per-candidate status and reason codes
```

`ready_for_human_review` is deliberately not a promotion or testnet status.

### Explicit JSON CLI

```bash
python -m autonomous_futures.paper.cohort_cli \
  --expected-path <expected-bindings.json> \
  --reports-path <health-reports.json>
```

Both files are caller-supplied local JSON. The CLI validates them through the existing typed contracts and returns canonical JSON. It writes no state.

## TDD evidence

```text
RED: cohort module import missing
GREEN: all-healthy cohort readiness summary

GREEN extensions: missing/attention not-ready, blocked candidate,
duplicate report block, unavailable cohort

RED: cohort CLI import missing
GREEN: explicit JSON healthy summary and invalid JSON error
```

## Verification

```text
Cohort/health/lifecycle focused subset: 35 passed
Locked full suite:                    573 passed
Ruff check:                           passed
Ruff format:                          passed
Mypy:                                 141 source files clean
uv lock --check:                      passed
direct py_compile Phase 12 files:      passed
git diff --check:                      passed
runtime import safety scan:           passed
```

The known repository-wide Windows `compileall` limitation remains confined to unrelated pre-existing overlong research/test filenames. Direct compilation of all Phase 12 files passed.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

This phase proves only cohort observability and human-review readiness accounting. It does not prove profitability, promotion eligibility, testnet readiness, or live execution permission.
