# Phase 221 Verification — Google AI Studio bounded completion smoke

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase executed one separately approved, bounded Google AI Studio
completion smoke through the encrypted systemd credential path. The request
reached Google AI Studio and returned HTTP 200, but the structured JSON
contract failed. No retry, fallback, campaign, candidate, qualification,
promotion, paper activation, testnet order, or live order was performed.

- Verification time: `2026-09-01T15:43:28Z`
- Source commit before evidence: `64925f5eda5054bac7eb3e42f5b78a6b038dd480`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Provider: `google_ai_studio`
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai`
- Model: `gemma-4-26b-a4b-it`
- Request count: `1`
- Retry count: `0`

## Safe provider result

Only bounded metadata was retained. The prompt and response body were not
persisted or printed.

```text
http_status=200
response_keys=(choices,created,id,model,object,usage)
choice_count=1
finish_reason=length
content_kind=string
content_length=123
content_sha256=810f0ef9e3d1d284a009e3db0118b784cf029b9a356748024c542900da2b8184
json_object=false
failure_code=provider_payload_invalid
```

The HTTP response proves that the endpoint and encrypted credential delivery
reached a provider response. It does not prove that the selected model
satisfies the required structured-output contract. The bounded request ended
with `finish_reason=length` and no valid JSON object. The second permitted
model, `gemma-4-31b-it`, remains provider-side unverified.

## Credential and transient-unit read-back

```text
credential=present mode=600 owner=root group=root type=regular file
unit_load_state=not-found
matching_units=0
research_timers=0
research_units=0
local_probe_cleanup=PASS
```

The probe source was streamed to the transient unit and was not stored as a
remote project file. The transient systemd unit was collected and verified
absent after execution. The existing systemd encrypted-credential warning
remains an infrastructure caveat: `/var/lib/systemd/credential.secret` is not
located on encrypted media.

## Safety state

```text
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
campaign=not_run
candidates=0
qualifications=0
```

The smoke failure is fail-closed evidence. It does not authorize a Creator
campaign or any execution path. A future attempt requires a materially
changed request hypothesis or provider-side stability evidence, a new bounded
budget, and separate approval; an identical retry is not allowed.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
