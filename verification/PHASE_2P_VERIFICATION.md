# Phase 2p Verification — Deterministic Walk-Forward OOS Aggregation

**Status:** GREEN.
**Scope:** Deterministic aggregation of explicit per-window performance metrics for
out-of-sample walk-forward evidence.
**Safety boundary:** cached metric artifacts only; no network, exchange client,
order endpoint, candidate mutation, promotion, paper activation, or live execution.

## Added contracts

```text
src/autonomous_futures/research/walk_forward.py
tests/unit/test_walk_forward.py
```

Exports added through:

```text
src/autonomous_futures/research/__init__.py
```

The contract binds each window to:

```text
window_id
symbol
split
window_start
window_end
TradePerformanceMetrics
```

## OOS boundary

Aggregation accepts only windows with:

```text
split="oos"
data_source="cached_only"
exchange_access=false
```

Training and validation windows are rejected. This prevents a caller from
silently mixing in-sample or tuning evidence with out-of-sample performance.

The aggregation does not execute strategies, load files, access the network, or
invent missing windows.

## Deterministic ordering and guards

Input windows are sorted by:

```text
(symbol, window_start, window_end, window_id)
```

The boundary rejects:

- empty window input;
- unsorted or duplicate required symbols;
- symbols outside the required universe;
- missing required symbols;
- symbols below `minimum_windows` coverage;
- duplicate `(symbol, window_id)` bindings;
- overlapping OOS windows for the same symbol;
- non-UTC or non-positive window ranges;
- metric/window symbol mismatch;
- non-cached or exchange-accessible metric artifacts.

Gaps between non-overlapping windows are permitted and remain explicit. The
aggregator does not pretend that a gap has been covered.

## Aggregation semantics

Per-symbol and pooled summaries are calculated from the already validated
per-window net metrics:

```text
pooled_gross_profit = sum(window.gross_profit)
pooled_gross_loss   = sum(window.gross_loss)
pooled_net_pnl      = pooled_gross_profit - pooled_gross_loss
pooled_profit_factor = pooled_gross_profit / pooled_gross_loss
```

When pooled gross loss is zero, pooled profit factor is `None`, not infinity.
Return aggregation is explicitly an arithmetic mean of window `return_pct`
values. It is **not** a compounded portfolio return and is not presented as one.
Worst drawdown is the maximum of the bound window drawdown values:

```text
worst_max_drawdown = max(window.max_drawdown)
worst_max_drawdown_pct = max(window.max_drawdown_pct)
```

No qualification pass/fail decision is produced by this phase.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.walk_forward'
```

Focused GREEN:

```text
6 passed in 0.67s
```

Tests cover:

- deterministic ordering independent of input order;
- pooled net P&L and profit factor;
- per-symbol summaries;
- train/validation rejection;
- duplicate window rejection;
- overlapping window rejection;
- missing required symbol rejection;
- minimum OOS window coverage;
- invalid timestamp and metric-symbol binding rejection.

## Quality gates

```text
Backend pytest: 149 passed
Focused walk-forward tests: 6 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (65 files formatted)
Mypy: Success: no issues found in 38 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 112 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- strategy execution or walk-forward window generation;
- Sharpe, Sortino, Calmar, or annualization;
- funding, leverage, margin, or liquidation accounting;
- qualification gates or candidate admission;
- promotion, paper activation, or execution authority.
