# Phase 100 Verification — cached OOS failure diagnosis

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Read-only diagnosis of the persisted accepted candidate from Phase 99 against the immutable DOGEUSDT 5m bundle.

```text
persisted candidate
→ four explicit cached windows
→ existing candidate_window_simulation
→ causal feature evaluator
```

No provider call, filesystem write, candidate mutation, or evaluator bypass was used.

## Actual result

```text
candidate: cand-doge-breakout-001
candidate state: testing
bundle rows: 105120
windows attempted: 4
provider requests: 0
writes: 0
```

All four windows failed at the same deterministic feature-capability check:

```text
error type: DataQualityError
error: feature is not supported: relative_volume
```

The persisted candidate’s prompt-derived StrategySpec declared `relative_volume`, which exists in the broad domain `ALLOWED_FEATURES` set but is not implemented by the current causal cached evaluator’s `_SUPPORTED_FEATURES` set.

## Root cause

```text
prompt/domain allowed feature set
≠
cached evaluator implemented feature set
```

This is a real code contract mismatch, not missing data, provider failure, or an OOS performance result.

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
local/remote diagnostic temp cleanup: passed
```

## Conclusion

The previous `cached_evaluation_failed` result is now explained. No OOS metrics may be reported for this candidate. Next implementation should make Creator prompting/evaluation capability consistent—preferably constrain generated features to the evaluator-supported subset or add a separately tested feature implementation—before another Creator run.

## Verification

```text
local full suite before diagnosis: 674 passed
local Ruff/format/mypy/lock: passed
```
