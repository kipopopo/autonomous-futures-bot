# Phase 81 Verification — safe provider response diagnostics

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 81 adds safe metadata to `ProviderTransportError` for response-shape diagnosis without exposing provider content or secrets.

For malformed provider content, diagnostics now expose only:

```text
HTTP status
response top-level keys
choice count
finish reason
content kind
content length
content SHA-256
```

Raw response text, authorization headers, and API-key values remain unavailable from the exception/message path.

## TDD evidence

```text
provider tests before change: 4 passed
new metadata test:            passed
provider tests after change:  5 passed
full suite:                   667 passed
Ruff:                         passed
format:                       passed
mypy:                         passed
uv lock:                      passed
git diff --check:             passed
```

## Safety

```text
new real provider requests: 0
raw provider output persisted: false
credential logging: false
fallback model: false
orders: 0
execution authority: false
```

Next provider smoke can report the safe response shape/hash to distinguish empty content, plain text, fenced output, tool content, or another provider schema without leaking the response.
