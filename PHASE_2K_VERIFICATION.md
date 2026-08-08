# Phase 2k Verification — Causal Feature and Fresh-Signal Evaluator

**Status:** GREEN.
**Scope:** Deterministic prior-bar-only feature computation and bounded fresh-state signal generation.
**Safety boundary:** cached/in-memory OHLC only; no network, filesystem loader, exchange client, order, candidate mutation, promotion, paper activation, or live execution.

## Tracer path

```text
CreatorCandidateArtifact
    -> canonical cached 5m OHLC frame
    -> prior-bar-only feature columns
    -> bounded comparison expressions
    -> fresh long/short entry states
    -> signal column: -1, 0, +1
```

Added:

```text
src/autonomous_futures/research/feature_signals.py
tests/unit/test_feature_signals.py
```

Updated:

```text
src/autonomous_futures/research/__init__.py
```

## Supported causal features

The bounded evaluator currently supports:

```text
returns
ema_slope
donchian_high
donchian_low
regime_trend
```

All feature values are shifted by the persisted `FeatureRef.shift` and use only completed prior bars:

- returns use prior-bar percentage changes;
- EMA slope uses prior EMA values;
- Donchian high/low use shifted rolling extrema;
- regime trend derives from shifted EMA slope state.

The evaluator validates canonical 5m cadence, required OHLC columns, finite positive OHLC values, unique declared features, and declared expression dependencies.

## Bounded signal semantics

Expressions are parsed without `eval` or code execution. Supported atoms are numeric comparisons such as:

```text
returns > 0
ema_slope < 0
regime_trend == 1
```

Multiple comparisons may be combined with bounded lowercase `and` / `or` operators.

The evaluator emits:

```text
long_condition
short_condition
long_entry
short_entry
signal
```

Entry signals are emitted only on fresh state transitions. A condition remaining true does not emit repeated entries, and returning to neutral does not create an opposite entry. A candle with both long and short conditions is rejected.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.feature_signals'
```

Focused GREEN:

```text
6 passed in 0.64s
```

Coverage includes:

- current-candle mutation cannot change same-candle returns or signal;
- current-candle mutation cannot change same-candle EMA/Donchian/regime features or signal;
- source frame remains unchanged;
- fresh long entries occur only at new long states;
- fresh short entries occur only at new short states;
- neutral transitions do not create opposite entries;
- undeclared expression features are rejected;
- unsupported features are rejected;
- duplicate features are rejected;
- simultaneous long/short conditions are rejected.

## Important scope boundary

This phase does **not** claim to implement:

- a complete strategy-family engine;
- entry/exit trade simulation;
- position sizing;
- fees, funding, slippage, leverage, or liquidation accounting;
- equity, P&L, Sharpe, drawdown, or profit factor;
- walk-forward aggregation;
- qualification artifact generation;
- promotion or paper activation.

The output is a causal signal frame only. It is not profitability evidence and cannot authorize execution.

## Quality gates

```text
Backend pytest: 123 passed
Frontend Vitest: 9 passed
Ruff check: passed
Ruff format: passed (59 files formatted)
Mypy: Success: no issues found in 35 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 75 files, 0 findings
oxlint: 0 warnings, 0 errors
Vite production build: passed
```
