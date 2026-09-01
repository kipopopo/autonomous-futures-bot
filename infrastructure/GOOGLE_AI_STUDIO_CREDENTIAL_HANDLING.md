# Google AI Studio Credential Handling — Autonomous Futures Bot

## Status

- **Selected provider:** Google AI Studio
- **Permitted models:** `gemma-4-26b-a4b-it`, `gemma-4-31b-it`
- **OpenAI-compatible base URL:** `https://generativelanguage.googleapis.com/v1beta/openai`
- **Google AI Studio credential staged by this migration:** **No**
- **Credential stored in repository / proposal / report / database:** **No**
- **Kainode systemd credential support:** previously verified (`systemd 255`, `systemd-creds` present)

This document deliberately contains no credential value, token, authorization header, or private payload.

## Security decision

The Google AI Studio API credential is a deployment secret, not an application configuration value. It must never be committed, copied into a `.env.example`, placed in a StrategySpec, stored in PostgreSQL/Parquet/trial records, sent to an LLM, or printed in a log/error/traceback.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

The application receives the key through dependency injection. The provider config does not load credentials from repository files, prompts, trial records, or persisted evidence.

## Prerequisites before staging

Do **not** transfer a Google AI Studio credential to Kainode until all of these are complete:

1. Confirm the Google AI Studio project and billing/quota posture outside this repository.
2. Confirm the exact model IDs with a bounded provider-side availability check.
3. Verify the non-root deployment/runtime account and recovery access.
4. Verify the encrypted systemd credential path and its filesystem protection.
5. Verify the service cannot read unrelated project files.
6. Keep exchange credentials and order endpoints absent from the research service.

## Intended systemd delivery mechanism

Use systemd encrypted credentials rather than a repository file or a long-lived process environment variable.

```text
root-only encrypted source credential on disk
              │
              ▼
    systemd LoadCredentialEncrypted
              │
              ▼
private runtime credential file in $CREDENTIALS_DIRECTORY
              │
              ▼
non-root Autonomous Futures Bot service reads the key at startup
```

Use a logical credential name such as `google_ai_studio_api_key`. The application reads the value only in process memory while the HTTP client is active. The key must not appear in command arguments, logs, metrics, exception text, evidence, or dashboards.

## Runtime safeguards

- Validate the exact configured base URL and selected model ID before a research batch starts.
- Permit only `gemma-4-26b-a4b-it` and `gemma-4-31b-it`; no silent model substitution.
- If the model is unavailable, malformed, unauthorized, or transport-failed, persist only safe failure metadata and stop that research batch.
- Do not silently switch providers or models.
- Never expose an `Authorization` header or response body in logs, metrics, exception text, trial evidence, or dashboards.
- Keep LLM calls in the research plane only; the credential has no exchange, position, sizing, risk-engine, or order authority.
- Provider migration does not bypass deterministic evaluation, OOS/walk-forward/stress checks, qualification, lineage, promotion, paper, testnet, or live gates.

## Current deployment state

```text
Google AI Studio code path        : implemented and locally tested
Google AI Studio credential       : not staged by this migration
Remote deployment/configuration   : not changed by this migration
Provider-side smoke                : not run; requires separately staged key
Exchange credential / order route : not present
Paper/live execution              : disabled
```
