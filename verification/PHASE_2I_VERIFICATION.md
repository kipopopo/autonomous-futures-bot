# Phase 2i Verification — Deterministic Cached-Only Evaluator Boundary

**Status:** GREEN.
**Scope:** Explicit cached 5m window contract and pure evaluator adapter boundary.
**Safety boundary:** no network access, exchange client, filesystem loader, candidate mutation, promotion, paper activation, signal generation, or order routing.

## Tracer path

```text
CreatorCandidateArtifact
    -> explicit cached in-memory 5m windows
    -> isolated frame copy
    -> injected pure evaluator callback
    -> deterministic CachedEvaluationRun
```

Added:

```text
src/autonomous_futures/research/cached_evaluation.py
tests/unit/test_cached_evaluation.py
```

## Contract

`CachedEvaluationWindowSpec` binds every window to:

- stable window ID;
- uppercase symbol;
- exact `bundle_hash`;
- exact `dataset_registry_hash`;
- UTC half-open time range.

`CachedEvaluationWindow` requires:

- explicit in-memory `pandas.DataFrame`;
- `timestamp`, `open`, `high`, `low`, and `close` columns;
- timezone-aware UTC timestamps;
- contiguous 5m cadence;
- exact coverage of the declared window range;
- no input-frame mutation by the evaluator callback.

The adapter enforces:

- at least one window;
- unique deterministic window identities;
- candidate binding equality for bundle and dataset registry hashes;
- symbol membership in the candidate universe;
- result window/symbol identity equality;
- sorted deterministic output windows;
- isolated callback frame/window copies.

`CachedEvaluationRun` records:

```text
candidate_artifact_hash
bundle_hash
dataset_registry_hash
evaluator_run_id
evaluator_version
windows
data_source = "cached_only"
exchange_access = false
evaluation_hash
```

The evaluation hash excludes only the audit timestamp and its own hash, so equivalent cached evidence remains reproducible across audit times.

## TDD evidence

Initial RED result:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.cached_evaluation'
```

A later RED regression proved the frame-integrity guard was missing:

```text
Failed: DID NOT RAISE DataQualityError
```

Focused GREEN result after implementation:

```text
6 passed in 0.60s
```

Focused coverage includes:

- deterministic evaluation hash;
- deterministic window sorting;
- frame isolation and source immutability;
- explicit cached-only and exchange-disabled flags;
- bundle/dataset binding rejection;
- unknown-symbol rejection;
- callback result identity rejection;
- exact contiguous closed-window coverage;
- timestamp-only frame rejection;
- empty-run rejection;
- non-UTC window rejection.

## Important scope boundary

No strategy logic, indicator calculation, backtest accounting, walk-forward aggregation, or qualification decision is fabricated here. The callback boundary is intentionally injected so the future evaluator must be deterministic and cached-only before its output can be converted into the Phase 2h qualification artifact.

The following remain deferred:

- real cached OHLCV strategy evaluator;
- causal 15m context materialization inside evaluation windows;
- fees, funding, slippage, leverage, liquidation, and trade ledger accounting;
- walk-forward gate aggregation;
- qualification artifact production from evaluator metrics;
- API/dashboard exposure of evaluation results;
- candidate promotion or paper activation.

## Quality gates

```text
Backend pytest: 112 passed
Frontend Vitest: 9 passed
Ruff check: passed
Ruff format: passed (55 files formatted)
Mypy: Success: no issues found in 33 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 71 files, 0 findings
oxlint: 0 warnings, 0 errors
Vite production build: passed
```
