# Phase 2o Verification — Deterministic Ledger Performance Metrics

**Status:** GREEN.
**Scope:** Pure deterministic performance metrics calculated from
`TradeSimulationResult` net trade P&Ls and equity curve.
**Safety boundary:** cached simulation artifact only; no network, exchange client,
order endpoint, candidate mutation, promotion, paper activation, or live execution.

## Added contracts

```text
src/autonomous_futures/research/performance_metrics.py
tests/unit/test_performance_metrics.py
```

Exports added through:

```text
src/autonomous_futures/research/__init__.py
```

`TradePerformanceMetrics` exposes:

```text
trade_count
winning_trades
losing_trades
breakeven_trades
win_rate
gross_profit
gross_loss
net_pnl
average_trade_pnl
return_pct
profit_factor
max_drawdown
max_drawdown_pct
peak_equity
final_equity
data_source
exchange_access
```

## Accounting semantics

All trade metrics use **net trade P&L**, including fees and modeled slippage
already recorded by the simulator:

```text
gross_profit = sum(net_pnl where net_pnl > 0)
gross_loss   = sum(abs(net_pnl) where net_pnl < 0)
net_pnl      = gross_profit - gross_loss
profit_factor = gross_profit / gross_loss
```

When there are no losing trades, `profit_factor=None` rather than infinity. This
keeps the persisted metric finite and avoids treating an undefined ratio as a
qualification advantage.

```text
return_pct = net_pnl / starting_equity × 100
average_trade_pnl = net_pnl / trade_count
win_rate = winning_trades / trade_count
```

For drawdown, the running peak starts at starting equity and includes every
cached equity-curve point:

```text
max_drawdown = max(running_peak - equity_point)
max_drawdown_pct = max_drawdown / peak_equity × 100
```

## Validation invariants

The metric model rejects inconsistent artifacts when:

- trade buckets do not sum to total trade count;
- win rate disagrees with trade buckets;
- net P&L disagrees with gross profit/loss buckets;
- average P&L or return percentage is inconsistent;
- profit factor disagrees with gross buckets;
- drawdown percentage disagrees with peak equity;
- final equity disagrees with starting equity plus net P&L;
- Decimal metrics are non-finite.

The result is explicitly marked:

```text
data_source="cached_only"
exchange_access=false
```

## TDD evidence

Initial RED:

```text
ModuleNotFoundError:
No module named 'autonomous_futures.research.performance_metrics'
```

Focused GREEN:

```text
5 passed in 0.69s
```

Tests cover:

- mixed winning, losing, and breakeven ledger;
- net-P&L-based profit factor and return;
- equity-curve drawdown and drawdown percentage;
- no-trade zero metrics;
- undefined profit factor when no loss exists;
- deterministic repeated calculation;
- cached-only safety fields;
- inconsistent metric contract rejection.

## Quality gates

```text
Backend pytest: 143 passed
Focused metrics tests: 5 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (63 files formatted)
Mypy: Success: no issues found in 37 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 79 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- Sharpe, Sortino, Calmar, or annualization;
- funding or leverage accounting;
- liquidation or margin metrics;
- walk-forward aggregation;
- qualification gates or evidence artifact generation;
- promotion, paper activation, or execution authority.
