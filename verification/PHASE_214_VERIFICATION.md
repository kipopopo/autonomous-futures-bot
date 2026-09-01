# Phase 214 Verification — retained-credential completion recheck

## Status

**BLOCKED / EVIDENCE-ONLY**

This phase rechecked the existing encrypted OpenCode credential after the operator requested continued use of it. Exactly one bounded authenticated completion request was sent. It returned HTTP 401, so the process stopped before any Creator campaign.

- Verification time: `2026-09-01T06:24:52Z`
- Source commit: `b094d1a2d1314b53ac44512ef5efcdd3ac2eb32e`
- Host: `147.79.18.15`
- SSH operator: `afbot-admin`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`
- Provider: `opencode`
- Model: `deepseek-v4-flash`

## Preconditions

The SSH route, credential source metadata, and research state were checked before the request:

```text
research_timers=0
research_units=0
source_metadata=mode=600 owner=root group=root type=regular file
```

The probe ran as `afbot-admin` through a collected systemd transient unit with:

```text
LoadCredentialEncrypted=opencode_api_key:/etc/autonomous-futures/credentials/opencode_api_key
```

Credential bytes were not read into the report, printed, or persisted.

## Probe result

The request used the exact pinned model, JSON response mode, `temperature=0.0`, `max_tokens=16`, a 90-second timeout, and `curl --retry 0`:

```text
completion_probe=status=401;elapsed_seconds=0.856930
curl_exit=0
transient_run_exit=0
```

No response body, authorization header, credential value, or raw request payload was retained.

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

No fallback provider/model, automatic retry loop, scheduler, daemon, paper runtime, testnet order, or live order was started.

## Cleanup

The transient unit was collected and verified absent. Research state stayed clean:

```text
unit_after_run=not-found
research_timers_after=0
research_units_after=0
```

## Credential hygiene

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

## Conclusion and next work

The retained credential still fails the authenticated completion boundary with HTTP 401. The next required work is provider-side authorization/entitlement verification or credential replacement through the documented encrypted staging path. After that state changes, run exactly one fresh bounded completion probe; only a passing probe permits a cached Creator campaign.
