# Phase 74 Verification — corrected OpenCode credential smoke blocker

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

The replacement `OPENCODE_API_KEY` was restaged from the local `.env` through encrypted systemd credentials. The `.env` value used matching outer quotes; the staging extractor was corrected to remove only that dotenv quoting wrapper, without logging the key.

```text
credential artifact: /etc/autonomous-futures/credentials/opencode_api_key
mode: 600 root:root
decrypt/hash verification: passed
remote plaintext files: 0
local plaintext temp: deleted
```

## Provider outcomes

This boundary made two manual, bounded provider POST attempts:

```text
attempt 1: HTTP 401 Unauthorized
          cause: quoted dotenv wrapper had been included in staged bytes

attempt 2: HTTP 400 Bad Request
          corrected unquoted key reached provider authentication
          request was rejected by provider request/model schema
```

The second result indicates credential authentication is no longer the primary blocker. The adapter returned the stable `provider_http_error` code and did not expose the provider response body or authorization header.

```text
Creator proposal generated: no
orders: 0
fallback provider/model: no
automatic retry: no
```

## Cleanup and safety

```text
temporary systemd unit: removed
temporary source root: removed
remote plaintext: 0
local plaintext/temp files: deleted
project timers: 0
credential artifact: retained encrypted, root:root 600
paper_activation=false
execution_authority=false
live_order_enabled=false
```

## Limitation and next action

No further provider request is authorized in this phase. The OpenCode adapter request contract must be reconciled with the current Zen model/API behavior—likely request fields or model availability—using official documentation or a provider-side diagnostic that does not expose secrets. Do not retry blindly.

## Verification

```text
local full suite: 665 passed
local Ruff/format/mypy/lock: passed
```
