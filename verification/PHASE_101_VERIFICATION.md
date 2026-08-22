# Phase 101 Verification — align Creator features with cached evaluator

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Fix the Phase 100 root cause at the shared boundary:

```text
cached evaluator SUPPORTED_FEATURES
→ canonical Creator prompt
```

The prompt no longer derives feature instructions from the broader domain `ALLOWED_FEATURES` set. The evaluator’s existing supported set is now the single source for Creator feature generation.

```text
relative_volume: excluded from Creator prompt
rsi:             retained
```

No evaluator feature implementation was added and no StrategySpec validation was weakened.

## TDD evidence

```text
prompt/feature tests before change: 5 prompt + 11 feature tests / 1 expected RED behavior
prompt/feature tests after change:  17 passed
full suite:                         675 passed
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

Next boundary: rerun one bounded Creator → persistence → cached OOS chain. The existing persisted candidate remains unchanged and is not retroactively requalified.
