# Phase 222 Verification — changed Google AI Studio smoke hypothesis

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase tested one materially changed request hypothesis after Phase 221:
the prompt required one JSON object with no prose or markdown, and the output
budget increased from `32` to `256` tokens. Exactly one authenticated request
was issued to the same explicitly selected model. The response again reached
HTTP 200 but failed the structured JSON boundary. No retry, fallback, campaign,
candidate, qualification, promotion, paper activation, testnet order, or live
order was performed.

- Verification time: `2026-09-01T15:52:05Z`
- Source commit before evidence: `d417ee4d4f24b7d1895af56782c88a76c3f2fd61`
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
content_length=968
content_sha256=c04baf0289507d91113d1f338236afe95aed121ae3b79e845ec9aaca3e2ad3e9
json_object=false
failure_code=provider_payload_invalid
```

The changed output budget did not resolve the failure. The response was longer
than the first attempt and was still truncated, so the provider-side
structured-output contract remains unproven. This evidence does not justify
an identical retry or a Creator campaign. The second permitted model,
`gemma-4-31b-it`, remains provider-side unverified.

## Credential and transient-unit read-back

```text
credential=present mode=600 owner=root group=root type=regular file
unit_load_state=not-found
matching_units=0
research_timers=0
research_units=0
local_changed_probe_cleanup=PASS
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

The next work is not another identical smoke. It requires a new provider
hypothesis derived from the observed generation behavior, review of the
Gemma/OpenAI-compatible structured-output contract, RED tests if the local
contract changes, a new bounded budget, and separate approval. No unattended
retry or fallback is permitted.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
