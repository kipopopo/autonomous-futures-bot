# Phase 211 Verification — provider model and authorization diagnosis

## Status

**BLOCKED / NO CODE CHANGE**

This phase narrowed the Phase 210 completion `HTTP 401` without rotating credentials, changing the provider adapter, adding a fallback, or starting a Creator campaign.

- Verification time: `2026-09-01T05:46:49Z`
- Source commit: `ed44c025c49bbdeacb9f2b17a2075da9c2a7256f`
- Host: `147.79.18.15`
- SSH operator: `afbot-admin`
- Pinned ED25519 fingerprint: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`
- Provider: `opencode`
- Pinned model: `deepseek-v4-flash`

## Findings

### Model availability

A credential-free read of the provider model catalog completed through the pinned SSH route:

```text
catalog_transport=ready
catalog_parse=ready
deepseek_v4_flash_present=true
deepseek_v4_flash_free_present=true
catalog_count=63
```

The pinned model ID is currently published by the provider. Model-ID absence is therefore not the current explanation for the completion failure.

### Local transport contract

The existing unit tests and implementation were inspected without changing them. The shared client already:

- constructs `https://<configured-origin>/chat/completions`;
- sends the exact pinned model ID `deepseek-v4-flash`;
- sends `Authorization: Bearer <in-memory-key>`;
- requests JSON mode with bounded output;
- maps HTTP failures to `provider_http_error` with status-only metadata;
- never includes response bodies or authorization headers in the error value.

No local contract drift was found that explains the live `401`.

### Completion boundary

The Phase 210 bounded authenticated completion probe remains the controlling evidence:

```text
status=401
elapsed_seconds=0.749687
curl_exit=0
```

A public `/models` response does not prove completion authorization. The current evidence narrows the failure to provider credential state, account entitlement, or provider-side authorization policy rather than transport latency or an unpublished model ID.

## Safety outcome

No Creator request or candidate lifecycle stage was entered:

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

No fallback model, automatic retry loop, credential rotation, scheduler, daemon, project service, paper runtime, testnet order, or live order was started.

## Credential hygiene

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

No key, authorization header, raw provider response, or private payload was printed or persisted during this diagnosis.

## Conclusion and next work

The code path does not need a speculative patch. Provider authorization/entitlement must be repaired outside the repository, and the encrypted runtime credential must be replaced through the controlled deployment path without pasting the new value into chat or source control.

After that repair, the next work is exactly one fresh bounded authenticated completion probe. Only a passing probe permits a single bounded cached Creator campaign; a failed probe remains evidence-only.
