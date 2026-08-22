# Phase 73 Verification — one bounded OpenCode provider smoke

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 73 performs exactly one real OpenCode Zen OpenAI-compatible request through the encrypted systemd credential path.

```text
base URL: https://opencode.ai/zen/v1
endpoint: /chat/completions
model: deepseek-v4-flash-free
credential delivery: LoadCredentialEncrypted
runtime user: afbot-admin
```

The smoke prompt contained no market data, secrets, exchange data, or repository content. It requested only a bounded JSON status response.

## Result

```text
provider requests: 1
HTTP result: 401 Unauthorized
adapter result: provider_http_error
Creator proposal generated: no
orders: 0
```

The adapter correctly converted the HTTP failure to the stable `provider_http_error` code. No response body, authorization header, API-key value, or raw exception was logged.

## Credential/runtime verification

```text
encrypted credential artifact: present
credential mode: 600
credential owner: root:root
temporary systemd unit: removed
temporary source root: removed
temporary plaintext files: 0
local temporary files: deleted
project timers: 0
```

The earlier credential-identity mismatch was fixed by aligning the encrypted filename with the logical systemd credential name. The final request reached the provider and was rejected with 401.

## Safety status

```text
paper_activation=false
execution_authority=false
live_order_enabled=false
new_order_actions_allowed=false
```

No retry was sent. The key/provider account must be checked or replaced before another smoke; automatic retry or fallback model/provider is not permitted.

## Verification

```text
local full suite: 665 passed
local Ruff/format/mypy/lock: passed
```
