# Phase 13 Verification — immutable paper human-review checkpoint

## Scope

This phase records an explicit human review of a paper cohort readiness report.

```text
No promotion
No persistent activation
No testnet/live authority
No scheduler
No market-data loader
No network
No order route
```

The checkpoint is an audit record only.

## Delivered

### Hash-bound review checkpoint

`PaperReviewCheckpoint` stores:

```text
review ID
reviewer ID
UTC review timestamp
decision
review notes
canonical SHA-256 of the complete cohort report
complete embedded cohort report
```

Supported decisions:

```text
accept_paper_observation
needs_attention
reject
```

The acceptance decision is structurally fail-closed: it is rejected unless the embedded report has:

```text
cohort_status == ready_for_human_review
```

The checkpoint hash is recomputed during validation, so changing the embedded cohort report without changing the hash is rejected.

### Write-once journal

`SqlitePaperReviews` provides caller-owned append-only persistence:

```text
identical retry of review_id → idempotent success
conflicting retry of review_id → rejected
restart → typed checkpoint rehydration
absent read → no SQLite file creation
```

Historical review records are never rewritten.

### Explicit review CLI

```bash
python -m autonomous_futures.paper.review_cli \
  --report-path <cohort-report.json> \
  --review-path <review-journal.sqlite3> \
  --review-id <review-id> \
  --reviewer-id <reviewer-id> \
  --reviewed-at <UTC timestamp> \
  --decision <accept_paper_observation|needs_attention|reject> \
  --review-notes <text>
```

Malformed input and acceptance of an unready report return canonical `invalid_input` before creating the review journal.

## TDD evidence

```text
RED: review module import missing
GREEN: hash-bound checkpoint and ready-only acceptance

RED: SQLite review journal import missing
GREEN: restart rehydration, idempotent retry, conflict rejection,
absent-read purity

RED: review CLI import missing
GREEN: explicit checkpoint recording and unready-acceptance no-write guard
```

## Verification

```text
Review/cohort/health focused subset: 41 passed
Locked full suite:                  579 passed
Ruff check:                         passed
Ruff format:                        passed
Mypy:                               144 source files clean
uv lock --check:                    passed
direct py_compile Phase 13 files:    passed
git diff --check:                    passed
runtime import safety scan:         passed
```

The known repository-wide Windows `compileall` limitation remains confined to unrelated pre-existing overlong research/test filenames. Direct compilation of all Phase 13 files passed.

## Safety status

```text
paper_activation=false
execution_authority=false
exchange_access=false
```

`accept_paper_observation` means only that a human reviewed the paper evidence for continued paper observation. It is not promotion, testnet approval, live approval, or an order permission.
