# Phase 2n Verification — Deterministic ATR Trailing Protection

**Status:** GREEN.
**Scope:** Prior-bar-only ATR trailing-stop/watermark protection integrated into the cached trade simulator.
**Safety boundary:** cached/in-memory data only; no network, filesystem loader, exchange client, order endpoint, candidate mutation, promotion, paper activation, or live execution.

## Contract

`TradeSimulationConfig` now supports:

```text
atr_lookback
stop_atr_multiplier
take_profit_atr_multiplier
trailing_atr_multiplier
```

Trailing protection is disabled by default when `trailing_atr_multiplier=0`.
The result contract is versioned as `simulation_version=2` because trailing
watermark state changes simulation semantics.

For a long position:

```text
watermark[t] = highest completed-safe high through candle t-1
trail[t]     = watermark[t] - prior_ATR[t] × multiplier
```

For a short position:

```text
watermark[t] = lowest completed-safe low through candle t-1
trail[t]     = watermark[t] + prior_ATR[t] × multiplier
```

Watermarks initialize at the actual modeled entry fill, never from the entry
candle's earlier extrema.

## Conservative chronology

Each candle follows this order:

```text
1. Freeze trailing level from prior watermark and prior ATR
2. Test current high/low against fixed and trailing protection
3. If no protective exit, process opposite signal at current open
4. If still open, ratchet watermark using current candle extrema
5. Use the ratcheted watermark beginning with the next candle
```

This prevents the defective sequence:

```text
current high/low -> ratchet watermark -> test same candle
```

When multiple stop-like levels are already crossed in one candle, the
conservative adverse level is selected:

- long: lowest triggered stop price;
- short: highest triggered stop price;
- target is only considered when no stop-like level triggered.

Trailing exits are recorded as `exit_reason="trailing_stop"` and use the
triggered protection price without additional slippage.

## TDD evidence

Initial RED:

```text
11 existing tests passed
4 new trailing tests failed because trailing config did not exist
```

Focused GREEN:

```text
15 passed in 0.67s
```

The new tests cover:

- long current-candle high cannot manufacture same-candle trailing exit;
- short current-candle low cannot manufacture same-candle trailing exit;
- long watermark is used only from the completed prior candle;
- trailing-only signal before ATR warm-up does not open a position;
- forced close remains terminal when no prior trailing level was breached;
- long trailing exit occurs on the next candle after watermark ratcheting.

## Quality gates

```text
Backend pytest: 138 passed
Focused simulator tests: 15 passed
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

- leverage, margin, or liquidation;
- funding payments;
- exchange execution or order routing;
- walk-forward aggregation;
- performance qualification metrics;
- qualification artifact generation;
- promotion, paper activation, or execution authority.
