# Phase 77 Verification — bounded provider JSON normalization

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 77 fixes the response-format blocker from the Ox Alpha smoke without making another provider request.

The adapter now sends:

```json
"response_format": {"type": "json_object"}
```

and accepts exactly these response content forms:

```text
raw JSON object
one ```json fenced JSON object
```

Surrounding prose, malformed JSON, missing choices, and non-object content remain rejected as `provider_payload_invalid`.

## TDD evidence

```text
provider tests before change: 2 passed / 2 expected RED behaviors
provider tests after change:  4 passed
full suite:                  666 passed
Ruff:                        passed
format:                      passed
mypy:                        passed
uv lock:                     passed
git diff --check:            passed
```

## Safety

```text
new real provider requests: 0
raw response persistence:   false
credential logging:         false
fallback model:             false
orders:                     0
execution authority:        false
```

The next boundary may run one real `x-preview-f-free` smoke to validate whether OpenCode accepts JSON mode and returns usable Creator content.
