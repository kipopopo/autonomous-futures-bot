# Phase 213 Verification — bounded completion probe with retained credential

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase used the existing encrypted VPS credential as requested and ran exactly one bounded authenticated completion probe. The probe returned HTTP 401, so the process stopped before any Creator campaign or candidate lifecycle stage.

- Verification time: `2026-09-01T06:19:21Z`
- Source commit: `f0c0a74b3f8f8ee4a0b2392003f211fb3c69ea31`
- Host: `147.79.18.15`
- SSH operator: `afbot-admin`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`
- Provider: `opencode`
- Model: `deepseek-v4-flash`

## Preconditions

The pinned SSH route and encrypted credential source were verified without reading credential bytes:

```text
research_timers=0
research_units=0
source_metadata=mode=600 owner=root group=root type=regular file
```

The transient unit ran as `afbot-admin` with `LoadCredentialEncrypted=opencode_api_key:/etc/autonomous-futures/credentials/opencode_api_key`. The raw chat value was not copied into the command, filesystem, log, or artifact.

## Probe result

One tiny authenticated JSON completion request was sent with the exact pinned model, JSON response mode, `temperature=0.0`, `max_tokens=16`, a 90-second timeout, and no curl retry:

```text
completion_probe=status=401;elapsed_seconds=0.795554
curl_exit=0
transient_run_exit=0
```

No response body, authorization header, credential value, or raw request payload was printed or persisted.

## Campaign decision

The completion gate failed closed:

```text
creator_requests=0
candidates=0
oos_windows=0
qualifications=0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
```

No fallback model, automatic retry, credential rotation, scheduler, daemon, paper runtime, testnet order, or live order was started.

## Cleanup

The transient unit was collected and absent after the probe:

```text
unit_after_run=not-found
research_timers_after=0
research_units_after=0
```

## Credential hygiene

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

## Conclusion and next work

Retaining the existing credential did not clear the completion boundary. The provider still returns HTTP 401, so no repository patch can make a campaign safe or valid. Provider-side authorization/entitlement diagnosis remains the next required action; after that changes, run one fresh bounded completion probe before considering a campaign.
