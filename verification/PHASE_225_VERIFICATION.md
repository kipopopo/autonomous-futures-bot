# Phase 225 Verification — Gemma 4 31B thinking-control bounded smoke

## Status

**GREEN / BOUNDED-SMOKE / EVIDENCE-ONLY**

This phase ran exactly one authenticated Google AI Studio request using the
Phase 223 request contract against the second permitted model,
`gemma-4-31b-it`. The request passed Gemma 4 thinking control through
`extra_body.google.thinking_config` and required a JSON object. The provider
returned valid structured JSON. No retry, fallback, campaign, candidate,
qualification, promotion, paper activation, testnet order, or live order was
performed.

- Verification time: `2026-09-01T23:31:06Z`
- Source commit: `8aeb2c52bdf2054a6b897fc7e8eaf727308307b1`
- SSH operator: `afbot-admin`
- Host: `147.79.18.15`
- Provider: `google_ai_studio`
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai`
- Model: `gemma-4-31b-it`
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
content_length=19
content_sha256=19a0f40b46fe9872ded0902f9f7614db2e22f37ea4d22362524b85795a62ad49
json_object=true
status=passed
```

This proves the changed thinking-control request crosses the structured JSON
boundary for `gemma-4-31b-it` in one bounded smoke. Together with Phase 224,
both permitted Gemma 4 model IDs now have provider-side transport and minimal
structured-output evidence. This does not prove long-form Creator proposal
quality, campaign readiness, qualification, promotion, or execution
readiness.

## Credential and transient-unit read-back

```text
credential=present mode=600 owner=root group=root type=regular file
unit_load_state=not-found
matching_units=0
research_timers=0
research_units=0
local_smoke4_compile=PASS
local_smoke4_cleanup=PASS
local_smoke4_absent=PASS
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

Both model smoke gates are now complete. The next action, if separately
approved, is a finite Creator campaign using cached immutable market data and
the existing provider/evidence boundaries. It must remain bounded, produce no
execution authority, and stop fail-closed on any provider or structured-output
failure.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
