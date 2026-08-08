# Phase 3R Verification — Cached-only Learner Performance Metric Adapter

**Status:** GREEN

## Scope

Phase 3R adds `CachedOnlyLearnerMetricAdapter`, an in-memory orchestration boundary that converts an explicit caller-supplied cached simulation callback into deterministic `TradePerformanceMetrics` evidence.

The adapter:

- requires an exact `LearnerArtifact` and matching `CreatorCandidateArtifact` binding;
- accepts only explicit `TradeSimulationResult` output from the caller-supplied simulator;
- calculates metrics through the existing validated `calculate_performance_metrics(...)` path;
- isolates each cached window frame before invoking the simulator;
- sorts and rejects duplicate window identities;
- verifies learner, candidate, bundle, dataset registry and symbol bindings;
- validates result symbol identity;
- emits canonical deterministic `evaluation_hash` evidence;
- preserves `data_source="cached_only"` and `exchange_access=false`.

## Safety boundary

This phase does **not**:

- load model bytes or execute a default ML algorithm;
- fetch filesystem, network or exchange data;
- create authenticated exchange clients or order requests;
- qualify, reject, promote or activate a candidate;
- enable paper/live execution or execution authority;
- expose a mutation or trading API;
- persist metric evidence to disk.

The simulator callback is explicit by design. A future model-specific evaluator must be supplied as a separate, reviewed component and cannot be silently selected by this adapter.

## TDD evidence

RED was verified before implementation:

```text
ModuleNotFoundError: No module named
'autonomous_futures.research.learner_metric_evaluation'
```

After implementation and correction of one test's expected quantity-sized P&L, the focused suite passed:

```text
36 passed
```

The P&L assertion uses the existing simulator contract (`quantity = equity / entry_open`) and exact `Decimal` arithmetic rather than a rounded assumption.

## Verification gates

```text
Full backend pytest:        232 passed in 6.37s
Ruff:                       All checks passed!
Ruff format:                94 files already formatted
Mypy:                       Success: no issues found in 52 source files
uv lock --check:            passed
compileall:                 passed
git diff --check:            passed
Safety diff scan:           0 findings
```

No frontend/browser gate was required because Phase 3R changes no frontend or API files.

## Layman explanation

Yang sudah dibuat: sistem sekarang boleh mengambil keputusan simulasi yang diberikan secara explicit daripada data cached sahaja, semak ia terikat kepada learner/candidate yang betul, dan kira ukuran seperti P&L, drawdown, fees dan trade count secara konsisten.

Yang belum dibuat: sistem belum tahu sama ada model itu bagus untuk promotion, belum qualify atau promote candidate, belum hidupkan paper/live trading, dan belum boleh hantar order.

## Next safe boundary

The next isolated slice is persisted metric-evidence read/write with the same hash, atomic, write-once and fail-closed rules already used by learner evaluation evidence. That persistence must remain evidence-only and must not be interpreted as qualification or execution authority.
