# Phase 2q Verification — Strict OOS Qualification Aggregation

**Status:** GREEN.
**Scope:** Strict qualification evidence builder over a validated
`WalkForwardAggregation`.
**Safety boundary:** cached OOS evidence only; no candidate status mutation,
promotion, paper activation, order routing, or execution authority.

## Added contract

```text
src/autonomous_futures/research/qualification_artifacts.py
src/autonomous_futures/research/__init__.py
tests/unit/test_oos_qualification.py
tests/unit/test_qualification_artifacts.py
```

New public contracts:

```text
WalkForwardQualificationPolicy
QualificationSource
build_walk_forward_qualification_artifact(...)
```

Strict OOS artifacts are explicitly marked:

```text
source="walk_forward_oos"
promotion_state="unpromoted"
execution_authority=false
```

## Qualification boundary

The builder accepts only an already validated `WalkForwardAggregation` and
requires exact candidate-universe equality:

```text
candidate.strategy.universe.symbols == aggregation.required_symbols
```

The aggregation layer has already enforced:

```text
split="oos"
data_source="cached_only"
exchange_access=false
```

The qualification builder does not load candles, call exchanges, invoke a
strategy, or infer missing windows.

## Policy and gate semantics

`WalkForwardQualificationPolicy` binds:

```text
policy_id
minimum_windows
minimum_trades
minimum_profit_factor
maximum_drawdown_pct
minimum_average_return_pct
```

The artifact records the policy ID, exact aggregation content hash, pooled
metrics, and per-symbol metrics. Gates include pooled and per-symbol evidence:

```text
oos_windows_min
oos_trades_min
oos_profit_factor_min
oos_drawdown_max
oos_average_return_min
oos_<symbol>_windows_min
oos_<symbol>_trades_min
oos_<symbol>_profit_factor_min
oos_<symbol>_drawdown_max
oos_<symbol>_average_return_min
```

Qualification uses strict AND semantics. Every required symbol must pass every
symbol-specific gate. A strong symbol cannot compensate for a failing symbol.

If profit factor has no loss denominator, the observed value is `None` and the
gate fails closed with:

```text
oos_profit_factor_missing
oos_symbol_profit_factor_missing
```

Decision is derived only from all gate results:

```text
all(gate.passed for gate in gates) → qualified
otherwise                         → rejected
```

A `qualified` result means only that the supplied OOS evidence passed the
specified deterministic policy. It does not mean profitable, paper-live,
promoted, or executable.

## Provenance and hash binding

Strict OOS artifacts bind:

```text
candidate_id
candidate_artifact_hash
bundle_hash
dataset_registry_hash
evaluator_run_id
evaluator_version
qualification_policy_id
oos_aggregation_hash
```

The qualification content hash includes the policy and aggregation bindings.
The aggregation hash is deterministic over the canonical JSON form of the
validated walk-forward aggregation.

Legacy creator qualification artifacts remain readable: optional Phase 2q
binding fields are omitted from the canonical hash when absent, preserving the
historical v1 hash semantics. New strict OOS artifacts always contain both
bindings.

## TDD evidence

Initial RED:

```text
ImportError:
cannot import name 'WalkForwardQualificationPolicy'
```

Focused strict OOS GREEN:

```text
13 passed in 0.71s
```

Tests cover:

- qualified strict OOS artifact construction;
- exact policy and aggregation binding;
- pooled and per-symbol gate generation;
- failed drawdown rejection with stable reason code;
- missing profit-factor rejection;
- candidate-universe mismatch rejection;
- every-symbol AND semantics;
- invalid policy threshold rejection;
- legacy qualification JSON hash/readback compatibility.

## Quality gates

```text
Backend pytest: 156 passed
Focused qualification tests: 13 passed
Frontend Vitest: 9 passed
Frontend lint: 0 warnings, 0 errors
Vite production build: passed
Ruff check: passed
Ruff format: passed (66 files formatted)
Mypy: Success: no issues found in 38 source files
uv lock --check: passed
Python compileall: passed
git diff --check: passed
Secret scan: 114 files, 0 findings
```

## Scope boundary

This phase does **not** implement or claim:

- a real strategy/backtest evaluator;
- candidate registry status updates;
- promotion or paper activation;
- live/testnet execution;
- Sharpe/Sortino/annualization;
- funding, leverage, margin, or liquidation accounting;
- a qualification CLI or API route.
