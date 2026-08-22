# Phase 113 Verification — revision OOS declared-feature diagnosis

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Read-only diagnosis of persisted revision candidate `cand-doge-meanrev-001` across four cached DOGEUSDT windows.

```text
persisted revision candidate
→ immutable cached 5m bundle
→ causal feature evaluator
→ bounded signal parser
```

No provider calls, filesystem writes, candidate mutation, or evaluator bypass occurred.

## Actual result

```text
candidate: cand-doge-meanrev-001
candidate state: testing
bundle rows: 105120
windows attempted: 4
provider requests: 0
writes: 0
```

All four windows failed identically:

```text
error type: DataQualityError
error: signal feature is not declared: adx_14_1, bollinger_zscore_20_1, rsi_14_1
```

## Root cause

The revision proposal used derived feature names with lookback/shift suffixes in entry/exit expressions. The evaluator requires expressions to reference the exact declared `FeatureRef.name`; lookback and shift belong only in the feature object:

```text
correct:   rsi >= 50
incorrect:  rsi_14_1 >= 50
```

This is a Creator prompt contract gap, not missing data or an OOS performance result.

## Safety

```text
candidate artifact: unchanged
trial evidence: unchanged
OOS artifacts: 0
qualification artifacts: 0
paper_activation=false
execution_authority=false
orders=0
provider_requests=0
diagnostic cleanup: passed
```

## Conclusion

Next implementation should state that expressions must use exact declared feature names and must never append lookback/shift suffixes. Strict evaluator validation remains unchanged.

## Verification

```text
local full suite before diagnosis: 678 passed
local Ruff/format/mypy/lock: passed
```
