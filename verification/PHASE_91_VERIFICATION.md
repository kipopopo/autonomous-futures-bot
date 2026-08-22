# Phase 91 Verification — exact Creator JSON field-shape prompt

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Phase 91 addresses the exact safe diagnostics from Phase 90 by tightening only the canonical prompt:

```text
proposal_id starts with proposal- and uses lowercase/digits/hyphens
strategy.dsl_version is integer 1
universe contains symbols array
entry is object {long, short}
exit is object {long, short}
```

The strict Pydantic/StrategySpec validator was not weakened.

## TDD evidence

```text
field-shape prompt tests before change: 3 passed / 1 expected RED behavior
field-shape prompt tests after change:  4 passed
full suite:                            672 passed
Ruff:                                  passed
format:                                passed
mypy:                                  passed
uv lock:                               passed
git diff --check:                      passed
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

Next boundary: one real DeepSeek Creator smoke using these exact field-shape instructions.
