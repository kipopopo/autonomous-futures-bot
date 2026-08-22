# Phase 97 Verification — Creator condition and veto prompt contract

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Phase 97 addresses the safe schema diagnostics from Phase 96 by tightening only prompt instructions for:

```text
entry.long and entry.short: strings
exit.long and exit.short: strings
vetoes: non-empty array of strings
```

The strict StrategySpec validator remains unchanged.

## TDD evidence

```text
condition/veto prompt tests before change: 4 passed / 1 expected RED behavior
condition/veto prompt tests after change:  5 passed
full suite:                               674 passed
Ruff:                                     passed
format:                                   passed
mypy:                                     passed
uv lock:                                  passed
git diff --check:                         passed
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

Next boundary: one real DeepSeek Creator smoke using the complete prompt-shape contract.
