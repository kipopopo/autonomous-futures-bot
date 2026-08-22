# Phase 72 Verification — encrypted OpenCode credential staging

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

The user supplied a local `.env` path. Only `OPENCODE_API_KEY` was selected by variable name; the `.env` file was not copied and no key value was printed.

Official OpenCode Zen configuration used for the future adapter smoke:

```text
base URL: https://opencode.ai/zen/v1
endpoint: /chat/completions
model: deepseek-v4-flash-free
```

## Encrypted staging

```text
remote artifact: /etc/autonomous-futures/credentials/opencode_api_key.cred
mode: 600
owner: root
 group: root
```

The key was transferred as a temporary single-variable file, encrypted with `systemd-creds` host-key encryption, decrypted only into a temporary verification file, hash-checked without exposing the value, and both remote plaintext temporary files were securely removed.

```text
encrypted staging: passed
decrypt/hash verification: passed
remote plaintext files: 0
local plaintext temp file: deleted
remote project .env: absent
```

Existing systemd host-key caveat remains:

```text
/var/lib/systemd/credential.secret is not on encrypted media
```

This is retained as a hardening caveat; secret handling was not relaxed.

## Boundary exclusions

```text
OpenCode API calls: 0
Creator service: not created
scheduler/timer: not created
candidate mutation: 0
paper activation: false
execution authority: false
exchange orders: 0
```

The future service must map the logical credential name explicitly, for example:

```text
LoadCredentialEncrypted=opencode_api_key:/etc/autonomous-futures/credentials/opencode_api_key.cred
```

No provider smoke was performed in this phase. A separate explicit approval is required before one bounded `deepseek-v4-flash-free` provider request is sent.
