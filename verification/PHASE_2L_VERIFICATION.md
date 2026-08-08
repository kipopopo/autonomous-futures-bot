# Phase 2l Verification — Deterministic Cached Trade Simulation Ledger

**Status:** GREEN.
**Scope:** Deterministic unlevered trade simulation from a cached signal frame, including conservative open fills, signal exits, forced end-of-window close, Decimal-safe fees, slippage, trade ledger, and equity curve.
**Safety boundary:** cached/in-memory data only; no network, filesystem loader, exchange client, order endpoint, candidate mutation, promotion, paper activation, or live execution.

## Simulation path

```text
causal signal frame
    -> canonical 5m OHLC validation
    -> signal at candle t executes at open[t]
    -> opposite signal closes existing position only
    -> no same-candle reverse
    -> forced close at final candle close
    -> immutable Decimal-safe trade ledger + equity curve
```

Added:

```text
src/autonomous_futures/research/trade_simulation.py
tests/unit/test_trade_simulation.py
```

Updated:

```text
src/autonomous_futures/research/__init__.py
```

## Accounting contract

`TradeSimulationConfig` explicitly records:

```text
starting_equity
position_fraction
taker_fee_rate
slippage_rate
```

The current slice is unlevered and uses one position maximum. It does not claim margin or liquidation semantics.

For every trade:

```text
entry fee = entry fill notional × taker fee rate
exit fee  = exit fill notional × taker fee rate
net P&L   = gross P&L - entry fee - exit fee
```

Adverse fills are direction-aware:

```text
long entry  = raw open × (1 + slippage)
long exit   = raw price × (1 - slippage)
short entry = raw open × (1 - slippage)
short exit  = raw price × (1 + slippage)
```

The result validates these invariants:

```text
total_fees == sum(trade.fees)
total_slippage_cost == sum(trade.slippage_cost)
final_equity == last equity-curve point
final_equity == starting_equity + sum(trade.net_pnl)
```

## Candle chronology

- Signals are evaluated at the current candle open because Phase 2k features are prior-bar-only.
- An opposite signal closes an existing position at that candle's open.
- The simulator does not reverse on the same candle after closing.
- A remaining position is forced closed at the final candle close with `forced_end_of_window`.
- No intrabar stop/target logic is included yet, so no unknown OHLC ordering is assumed.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.trade_simulation'
```

Focused GREEN:

```text
7 passed in 0.69s
```

Coverage includes:

- long and short constant-price round trips;
- both-side commission accounting;
- forced final close;
- opposite-signal close without same-candle reverse;
- direction-aware adverse slippage;
- separate fee and slippage totals;
- final-equity and ledger consistency;
- deterministic repeated simulation;
- source signal-frame immutability;
- invalid/missing signal rejection;
- unsafe config and symbol rejection.

Constant-price fee evidence:

```text
starting equity: 100.00
taker fee:       0.04% per side
entry fee:       0.0400
exit fee:        0.0400
net P&L:        -0.0800
final equity:   99.9200
```

## Important scope boundary

This phase does **not** implement or claim:

- leverage or effective leverage caps;
- margin or liquidation accounting;
- funding payments;
- ATR stops/targets/trailing stops;
- intrabar protective-exit precedence;
- walk-forward aggregation;
- Sharpe, drawdown, profit factor, or qualification gates;
- qualification artifact generation;
- promotion, paper activation, or execution authority.

The output is a deterministic research ledger only. It is not profitability evidence and cannot authorize execution.

## Quality gates

```text
Backend pytest: 130 passed
Focused trade simulation tests: 7 passed
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
