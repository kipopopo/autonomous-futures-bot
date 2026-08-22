# Phase 95 Verification — safe provider metadata propagation

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

The provider client already produced safe metadata, but `CreatorGenerator` discarded it. Phase 95 carries a fixed whitelist through the Generator result.

Allowed fields:

```text
status_code
response_keys
choice_count
finish_reason
content_kind
content_length
content_sha256
```

All arbitrary metadata keys and raw exception text are discarded.

## TDD evidence

```text
Generator tests before change: 5 passed / 1 expected RED behavior
Generator tests after change:  6 passed
full suite:                    673 passed
Ruff:                          passed
format:                        passed
mypy:                          passed
uv lock:                       passed
git diff --check:              passed
```

## Safety

```text
raw provider output:      never returned
credential/header values: never returned
candidate mutation:       0
trial persistence:        0
OOS evaluation:           0
orders:                   0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
```

The next bounded Creator smoke can now report whether a provider payload failure is empty, truncated, malformed, or another safe response shape without exposing content.
