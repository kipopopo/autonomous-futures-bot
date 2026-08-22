# Phase 120 Verification — bounded transient OpenCode retry

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Add the smallest retry policy for the measured provider HTTP500 blocker:

```text
500/502/503/504 → one immediate retry
400/401/429/schema/payload errors → no retry
```

No fallback model, scheduler, unbounded loop, or backoff framework was added. The deliberate simplification is one immediate retry only; exponential backoff can be added if measured provider behavior requires it.

## TDD evidence

```text
provider tests before change: 5 passed / 1 expected RED behavior
provider tests after change:  6 passed
full suite:                   681 passed
Ruff:                         passed
format:                       passed
mypy:                         passed
uv lock:                      passed
git diff --check:             passed
```

## Safety

```text
retry cap:          1
raw response body:  never logged
credential/header:  never logged
fallback model:     false
orders:             0
execution authority:false
```

Next boundary: one real latest-feedback revision smoke to validate the bounded 5xx retry, with no automatic downstream persistence unless explicitly included in that smoke.
