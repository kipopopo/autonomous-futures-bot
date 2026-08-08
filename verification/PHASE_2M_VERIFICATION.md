# Phase 2m Verification — Deterministic ATR Protective Exits

**Status:** GREEN.
**Scope:** Prior-bar-only ATR stop-loss/take-profit protection integrated into the cached trade simulator.
**Safety boundary:** cached/in-memory data only; no network, filesystem loader, exchange client, order endpoint, candidate mutation, promotion, paper activation, or live execution.

## Contract

`TradeSimulationConfig` now supports:

```text
atr_lookback
stop_atr_multiplier
take_profit_atr_multiplier
```

Protection is disabled by default when both multipliers are zero, preserving the
Phase 2l ledger behavior.

When protection is enabled:

- ATR is computed exactly from Decimal OHLC values;
- ATR at candle `t` uses true ranges from candles strictly before `t`;
- current candle high/low/close cannot change the protection distance used at its open;
- a signal before ATR warm-up is skipped rather than opened unprotected;
- long and short stop/target geometry is inverse and direction-aware;
- protection exits fill at the triggered protection price without additional slippage;
- stop-loss is checked before take-profit when both extrema are crossed;
- a protective exit has precedence over an opposite signal on the same candle;
- a protective exit prevents same-candle reversal.

## Chronology

For an open long:

```text
stop   = entry_fill - prior_ATR × stop_multiplier
target = entry_fill + prior_ATR × target_multiplier
```

For an open short:

```text
stop   = entry_fill + prior_ATR × stop_multiplier
target = entry_fill - prior_ATR × target_multiplier
```

Conservative same-candle precedence:

```text
long:  low <= stop  -> stop_loss before high >= target -> take_profit
short: high >= stop -> stop_loss before low <= target  -> take_profit
```

This avoids assuming a favorable intrabar path when both OHLC extrema are
present in the same candle.

## TDD evidence

Initial RED:

```text
7 legacy tests passed
4 new risk tests failed because ATR config fields did not exist
```

Focused GREEN:

```text
11 passed in 0.66s
```

The new tests cover:

- target distance from prior ATR despite an extreme current candle range;
- stop-first precedence when stop and target both cross;
- inverse short target geometry;
- no unprotected entry before ATR warm-up.

## Quality gates

```text
Backend pytest: 134 passed
Focused simulator tests: 11 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (61 files formatted)
Mypy: Success: no issues found in 36 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 77 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- trailing stops or watermark management;
- leverage, margin, or liquidation;
- funding payments;
- exchange execution or order routing;
- walk-forward aggregation;
- performance qualification metrics;
- qualification artifact generation;
- promotion, paper activation, or execution authority.
