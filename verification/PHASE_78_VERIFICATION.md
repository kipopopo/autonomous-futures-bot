# Phase 78 Verification — Ox Alpha JSON-mode smoke blocker

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Run exactly one real OpenCode Zen smoke after the provider adapter added JSON mode and narrow fenced-JSON normalization.

```text
model: x-preview-f-free
endpoint: https://opencode.ai/zen/v1/chat/completions
response_format: {"type": "json_object"}
credential delivery: encrypted systemd credential
```

## Result

```text
provider request count: 1
HTTP transport: reached provider
adapter result: provider_payload_invalid
Creator proposal generated: no
orders: 0
```

The provider still returned content that was not parseable as either a raw JSON object or the supported single fenced-JSON object. The adapter failed closed. Raw response content, headers, and credentials were not logged or persisted.

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

## Conclusion

OpenCode authentication and transport reachability are working. The remaining blocker is Ox Alpha’s response contract/behavior under the current chat-completions JSON request. Do not retry blindly or accept arbitrary prose as a StrategySpec. A provider-specific response adapter or a different officially supported model/endpoint is required before Creator generation can proceed.

## Verification

```text
local full suite before smoke: 666 passed
local Ruff/format/mypy/lock: passed
```
