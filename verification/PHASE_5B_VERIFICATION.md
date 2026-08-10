# Phase 5B Verification

## Scope

Added `simulate_candidate_window(...)`, the smallest composition boundary for
an exact candidate and explicit cached 5m frame:

```text
CausalFeatureSignalEvaluator
→ simulate_cached_signals
→ TradeSimulationResult
```

The caller must supply the symbol and `TradeSimulationConfig`; no hidden risk,
fee, slippage, or protection defaults were introduced. The function rejects a
symbol outside the candidate universe and does not mutate the source frame.

## Safety

This remains in-memory and cached-only. No candidate/artifact persistence,
qualification decision, promotion, paper activation, exchange/provider access,
or order-routing capability was added.

## Evidence

- Related focused tests: `25 passed in 0.93s`
- Full locked suite: `480 passed in 7.93s`
- Ruff, format, mypy, lock, and diff gates: passed after import-order repair

## Limitation

The Phase 5A aggregation adapter still needs a caller to bind this explicit
simulator to persisted candidate artifacts and validated cached OOS windows.
The existing Windows legacy-module `compileall` path-length limitation remains
unchanged and is not claimed as passed.
