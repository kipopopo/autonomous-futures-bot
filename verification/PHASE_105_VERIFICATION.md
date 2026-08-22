# Phase 105 Verification — cached OOS expression grammar diagnosis

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Read-only diagnosis of persisted candidate `cand-doge-014` across the immutable DOGEUSDT 5m bundle.

```text
persisted candidate
→ four explicit cached windows
→ existing causal feature evaluator
→ bounded signal parser
```

No provider calls, filesystem writes, candidate mutation, or evaluator bypass occurred.

## Actual result

```text
candidate: cand-doge-014
candidate state: testing
bundle rows: 105120
windows attempted: 4
provider requests: 0
writes: 0
```

All four windows failed identically:

```text
error type: DataQualityError
error: signal expression must use bounded comparisons
```

This is a generated-expression grammar mismatch. The evaluator accepts only bounded comparisons in the form:

```text
feature_name operator numeric_threshold
```

with optional `and` / `or` connectors. The Creator prompt currently does not state this exact grammar strongly enough.

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

The accepted Creator proposal passed schema validation but cannot be evaluated by the current causal signal parser. This is not an OOS performance result. Next implementation should derive or state the evaluator’s exact comparison grammar in the Creator prompt, then run a fresh bounded Creator/OOS chain.

## Verification

```text
local full suite before diagnosis: 675 passed
local Ruff/format/mypy/lock: passed
```
