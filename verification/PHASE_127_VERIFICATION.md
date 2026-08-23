# Phase 127 Verification — Learner/Critic output budget alignment

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Align the Learner/Critic OpenCode transport default with the proven Creator budget:

```text
critic max_output_tokens: 1024 → 4096
```

The change addresses the real critic metadata result:

```text
HTTP 200
finish_reason=length
content_length=0
```

No retry-policy changes, schema weakening, fallback model, scheduler, or training behavior were added.

## TDD evidence

```text
critic/provider tests before change: 4 passed / 1 expected RED behavior
critic/provider tests after change:  5 passed
full suite:                          688 passed
Ruff:                                passed
format:                              passed
mypy:                                passed
uv lock:                             passed
git diff --check:                    passed
```

## Safety

```text
real provider requests: 0
raw output persistence: false
training calls:         0
candidate mutation:     0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
```

Next major boundary: one real Learner/Critic smoke with the corrected `4096` budget.
