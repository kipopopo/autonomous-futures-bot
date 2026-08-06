# OpenCode Credential Handling — Autonomous Futures Bot

## Status

- **Selected provider:** OpenCode
- **Selected model:** `deepseek-v4-flash-free`
- **Credential installed on Kainode VPS:** **No**
- **Credential stored in repository / proposal / report / database:** **No**
- **Systemd credential support on Kainode:** **Verified** (`systemd 255`, `systemd-creds` present)

This document deliberately contains no credential value, token, endpoint secret, or authorization header.

## Security decision

The OpenCode API credential is a deployment secret, not an application configuration value. It must never be committed, copied into a `.env.example`, placed in a StrategySpec, stored in PostgreSQL/Parquet/trial records, sent to an LLM, or printed in a log/error/traceback.

Because the credential was supplied through chat, treat that copy as exposed and rotate it in the provider console before production provisioning.

## Prerequisites before installation

Do **not** transfer an LLM credential to the Kainode VPS until all of these are complete:

1. Rotate the current root password.
2. Add and verify a named operator SSH public key.
3. Create a non-root deploy/runtime account.
4. Disable direct root and password-based SSH only after recovery access is verified.
5. Enable a deny-by-default firewall with only approved administration/application ports.
6. Verify the dedicated service account cannot read unrelated project files.

## Intended systemd delivery mechanism

After the security baseline is approved, use systemd encrypted credentials rather than a repository file or a long-lived process environment variable.

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

The service contract will use a logical credential name such as `opencode_api_key`. The application reads its contents from the systemd credential directory and keeps it only in process memory while its HTTP client is active.

## Runtime safeguards

- Validate the exact configured model ID, `deepseek-v4-flash-free`, before a research batch starts.
- If the model is unavailable, malformed, unauthorized, or rate-limited beyond bounded retry policy, persist a `provider_model_unavailable` / provider-failure event and stop that research batch.
- Do not silently switch providers or models.
- Never expose an `Authorization` header in logs, metrics, exception text, trial evidence, or dashboards.
- Keep LLM calls in the research plane only; the credential has no exchange, position, sizing, risk-engine, or order authority.
- Revoke/replace the secret through a controlled deployment change, then verify the service uses the new credential without revealing either value.

## Current deployment state

```text
Kainode security hardening        : not started
OpenCode credential on VPS        : not installed
Autonomous Futures Bot service    : not created
OpenCode API call from VPS        : not made
Exchange credential / order route : not present
```
