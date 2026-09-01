# Phase 215 Verification — provider account and encrypted credential boundary

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase performed a read-only provider-account check and a network-isolated
runtime credential-shape check after the Phase 214 completion probe returned
HTTP 401. No credential value was read into the report, displayed, persisted, or
sent through chat.

- Verification time: `2026-09-01T06:54:54Z`
- Source commit: `478482ef5e7fbcc284df6a7b44ae0bc466b29814`
- Provider: `opencode`
- Pinned model: `deepseek-v4-flash`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`

## Provider account observation

The authenticated OpenCode workspace was inspected without changing account
state:

```text
Zen workspace: authenticated
Zen balance: positive
DeepSeek V4 Flash: listed
DeepSeek V4 Flash Free: listed
Autonomous Futures Bot API key: listed (value hidden)
September 2026 usage: no usage data
```

The account-side workspace therefore has the selected model family and an API
key record. The empty usage history is consistent with the VPS calls being
rejected before billable completion usage was recorded.

## Encrypted runtime credential observation

A temporary `systemd-run` unit was executed with `PrivateNetwork=yes` and the
existing `LoadCredentialEncrypted` mapping. The unit read only the transient
credential file and emitted a shape classification, never the value:

```text
credential_shape=nonempty_sk_prefix
unit_after_cleanup=not-found
research_timers=0
```

This rules out an empty or obviously malformed decrypted credential delivery.
It does not prove that the hidden staged value is the same current value as the
provider key record, and it does not override the provider's HTTP 401.

## Controlling completion evidence

The latest authenticated completion probe remains:

```text
completion_probe=status=401;elapsed_seconds=0.856930
creator_requests=0
candidates=0
oos_windows=0
qualifications=0
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
```

No response body, authorization header, raw prompt, credential value, or private
provider payload was retained.

## Decision and next gate

Local transport, model listing, provider-account access, encrypted credential
presence, and transient cleanup are verified. Completion authorization is not.

The next required action is operator-side re-staging of the exact current API
key through the documented hidden-input/encrypted systemd path, or provider-side
key replacement if the current full value is unavailable. Do not paste the
replacement into chat. After the staged value changes, run exactly one fresh
bounded completion probe. A failed probe remains evidence-only; only `2xx`
permits one cached Creator campaign.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
