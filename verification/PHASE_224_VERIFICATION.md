# Phase 224 Verification — Gemma 4 thinking-control bounded smoke

## Status

**GREEN / BOUNDED-SMOKE / EVIDENCE-ONLY**

This phase ran exactly one authenticated Google AI Studio request using the
Phase 223 request contract. The request selected `gemma-4-26b-a4b-it`, passed
Gemma 4 thinking control through `extra_body.google.thinking_config`, and
required a JSON object. The provider returned valid structured JSON. No retry,
fallback, campaign, candidate, qualification, promotion, paper activation,
testnet order, or live order was performed.

- Verification time: `2026-09-01T23:21:15Z`
- Source commit: `5f4caf3e196a00a086dcfd473654d81fb7f1aec0`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Provider: `google_ai_studio`
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai`
- Model: `gemma-4-26b-a4b-it`
- Request count: `1`
- Retry count: `0`

## Safe provider result

Only bounded metadata was retained. The prompt, credential, and response body
were not persisted or printed.

```text
http_status=200
response_keys=(choices,created,id,model,object,usage)
choice_count=1
finish_reason=stop
content_kind=string
content_length=15
content_sha256=e28c0a670d4287e370df0c78b03707f75aeeb5bfee3363dc810277b794a022f
json_object=true
status=passed
```

This proves the changed thinking-control request can cross the structured JSON
boundary for `gemma-4-26b-a4b-it` in one bounded smoke. It does not prove the
second permitted model, long-form Creator proposal quality, campaign
readiness, qualification, promotion, or execution readiness.

## Credential and transient-unit read-back

```text
credential=present mode=600 owner=root group=root type=regular file
unit_load_state=not-found
matching_units=0
research_timers=0
research_units=0
local_smoke3_compile=PASS
local_smoke3_cleanup=PASS
local_smoke3_absent=PASS
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

The next distinct provider gate is a separately bounded one-shot smoke for
`gemma-4-31b-it`. That model remains provider-side unverified. No Creator
campaign should start before its required model/provider gates and campaign
approval are satisfied.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
