# Phase 76 Verification — Ox Alpha provider response-format blocker

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Run exactly one real OpenCode Zen smoke after switching the pinned research model to `x-preview-f-free`.

```text
base URL: https://opencode.ai/zen/v1
endpoint: /chat/completions
model: x-preview-f-free
credential: encrypted systemd credential
runtime user: afbot-admin
```

## Result

```text
HTTP transport: reached provider successfully
provider request count: 1
adapter result: provider_payload_invalid
Creator proposal generated: no
orders: 0
```

The provider returned a response that did not contain valid JSON content for the strict adapter parser. The JSON decoder failed closed. Raw model content, response body, authorization header, and credential value were not logged or persisted.

This is materially different from the earlier failures:

```text
401: invalid/incorrect staged credential bytes
400: previous model/request access rejected
current: provider reached, but response content is not strict JSON
```

## Cleanup and safety

```text
temporary systemd unit: removed
temporary source root: removed
local temporary files: deleted
credential artifact: retained encrypted, root:root 600
project timers: 0
paper_activation=false
execution_authority=false
live_order_enabled=false
```

## Next blocker

Do not retry blindly. The next implementation slice should add a bounded response-normalization contract—preferably provider JSON mode if officially supported, otherwise a narrow JSON-content extractor with explicit rejection tests—before another provider request.

## Verification

```text
local full suite before this smoke: 665 passed
local Ruff/format/mypy/lock: passed
```
