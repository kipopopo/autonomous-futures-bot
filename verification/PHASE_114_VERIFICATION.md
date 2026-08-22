# Phase 114 Verification — exact declared-feature expression prompt

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Fix the Phase 113 revision OOS mismatch at the prompt boundary:

```text
expression feature name
= exact FeatureRef.name
```

The prompt now explicitly forbids appending lookback/shift suffixes such as `rsi_14_1`; those values belong only in the feature declaration.

The causal evaluator remains strict and unchanged.

## TDD evidence

```text
prompt/feature tests before change: 19 passed / 1 expected RED behavior
prompt/feature tests after change:  20 passed
full suite:                         679 passed
Ruff:                               passed
format:                             passed
mypy:                               passed
uv lock:                            passed
git diff --check:                   passed
```

## Safety

```text
new provider requests: 0
candidate mutation:    0
trial persistence:     0
OOS evaluation:        0
qualification:         0
orders:                0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
```

Next boundary: rerun one feedback-driven revision chain with exact declared-feature naming.
