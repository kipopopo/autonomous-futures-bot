# Phase 2j Verification — Causal Cached-Window Evaluation Boundary

**Status:** GREEN.
**Scope:** Causal 15m context materialization and integration with the cached-only evaluator adapter.
**Safety boundary:** no network access, filesystem loader, authenticated exchange client, order, candidate mutation, promotion, paper activation, or live execution.

## Tracer path

```text
cached primary 5m frame
    + cached context 15m frame
    -> context available_at = close_time + 1ms
    -> backward causal merge
    -> isolated CachedEvaluationWindow
    -> CachedOnlyEvaluatorAdapter
    -> deterministic CachedEvaluationRun
```

Added:

```text
src/autonomous_futures/research/causal_evaluation.py
tests/unit/test_causal_evaluation.py
```

Updated:

```text
src/autonomous_futures/research/__init__.py
```

## Causal contract

`materialize_causal_context()` requires:

- primary `timestamp`, `open`, `high`, `low`, `close` columns;
- context `timestamp`, `open`, `high`, `low`, `close`, `close_time` columns;
- timezone-aware timestamps;
- canonical 5m primary cadence;
- canonical 15m context cadence;
- `close_time == context_open + 15m - 1ms`.

Context values are exposed only at:

```text
context_available_at = close_time + 1ms
```

For a context candle opening at `12:00:00`:

```text
5m at 12:00 → unavailable
5m at 12:05 → unavailable
5m at 12:10 → unavailable
5m at 12:15 → available
```

The merge is backward-only and preserves the primary frame's chronological rows. Source primary/context frames are copied and remain unchanged.

## Adapter integration

`CausalCachedEvaluatorAdapter`:

- requires a context frame for every evaluation window;
- materializes causal context before evaluator invocation;
- constructs a new isolated evaluation window;
- delegates to the Phase 2i cached-only adapter;
- preserves `data_source="cached_only"`;
- preserves `exchange_access=false`;
- retains candidate, bundle, dataset registry, symbol, and window identity checks.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.causal_evaluation'
```

Focused GREEN:

```text
5 passed in 0.67s
```

Coverage includes:

- context unavailable before the 15m close boundary;
- prior closed context remains usable;
- invalid context close boundary rejection;
- causal frame delivered to the cached evaluator callback;
- missing context window rejection;
- source frame immutability.

## Important scope boundary

This phase does **not** claim to implement a complete strategy/backtest engine. It deliberately does not fabricate:

- strategy signal interpretation;
- indicator or feature computation;
- walk-forward metrics;
- fees, funding, slippage, leverage, or liquidation accounting;
- qualification decisions;
- promotion or paper activation.

Those require separate deterministic contracts and tests. The current seam ensures any future engine receives only explicitly cached, causally valid evaluation data.

## Quality gates

```text
Backend pytest: 117 passed
Focused causal tests: 5 passed
Frontend Vitest: 9 passed
Ruff check: passed
Ruff format: passed (57 files formatted)
Mypy: Success: no issues found in 34 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 73 files, 0 findings
oxlint: 0 warnings, 0 errors
Vite production build: passed
```
