# Phase 241 Verification — Experimental Creator Campaign

Date: 2026-09-03 (MYT / UTC+08:00)

Status: **COMPLETED / NEW-FAMILY / PROVIDER-REJECTED**

## Runtime and scope

- Agent runtime: `gpt-5.6-luna` via `openai-codex`, effort `ultra`.
- Campaign family: `experimental`.
- Remote Creator provider: Google AI Studio OpenAI-compatible endpoint.
- Remote model: `gemma-4-31b-it`.
- Thinking controls: minimal level, thoughts excluded.
- Campaign: `creator-batch-20260903-011`.
- Symbol: `DOGEUSDT`.
- Mode: cached-only research; no exchange access and no execution authority.

The family pin required `returns` as the causal signal in both long and short entry expressions and rejected Bollinger/Donchian entry drivers. This was a materially different family boundary from the rejected range and regime-gated campaigns. No candidate was accepted because the provider envelope failed before a proposal existed.

## Exact-source and immutable-input bindings

- Source commit: `f463daea3a2fae3931356172abe614217a4f95db`.
- Source archive SHA-256: `04f77162f81151e44f4c883d4378e4b09e4d454919f3e5ee7dadd15a9fc3df77`.
- Immutable bundle SHA-256: `19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816`.
- Dataset registry SHA-256: `583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb`.
- The remote runner imported the exact extracted source and verified runtime imports before the campaign.
- Market data was loaded through the verified dataset bundle/registry and artifact inspector. No exchange endpoint was called.
- Complete historical candidate identity preflight returned `4` forbidden candidate identities, including local canonical strategy identities.
- Four prior rejected qualification hashes were bound into the request evidence references.

Raw prompts, raw provider responses, authorization material, and exception messages were not persisted.

## Provider result

- Outbound request count: `1`.
- `max_retries`: `0`.
- Fallback provider: `false`.
- HTTP status: `400`.
- Typed trial decision: `rejected`.
- Reason code: `provider_http_error`.
- Finish reason: unavailable because the provider returned no valid completion envelope.
- Safe response body metadata: `content_kind=bytes`, `content_length=435`, content hash retained only as typed safe metadata.
- Candidate count: `0`.
- OOS evaluation windows: `0`.
- Qualification: not run because no typed candidate existed.

A `400` provider response is a hard stop. The identical request was not retried, no payload workaround was attempted, and no fallback model was used.

## Evidence readback

Published immutable evidence root contained exactly:

- `campaign-summary.json`
- `trials/trial-0000-run-doge-google-gemma-20260903-011.json`

Independent readback with the canonical local source verified:

- campaign status is `creator_rejected`;
- typed trial hash and schema are valid;
- reason is exactly `provider_http_error`;
- request count is `1` and retries are `0`;
- no raw response field/file is present;
- canonical identity snapshot count is `4`;
- prior rejected qualification binding count is `4`.

## Safety and cleanup

Persisted safety state remains:

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
```

Independent cleanup checks passed:

```text
matching remote campaign processes=0
transient systemd unit=not-found
remote transient paths absent=PASS
local transient artifacts absent=PASS
```

No paper activation, testnet activation, production promotion, live execution, or order submission occurred.

## Verification gates

The exact-source repository was clean and at parity with `origin/main` before this report. The post-report commit received a fresh locked verification run:

```text
uv run --locked pytest -q                 PASS
uv run --locked ruff check src tests      PASS
uv run --locked ruff format --check src tests PASS
uv run --locked mypy src                  PASS
uv lock --check                           PASS
git diff --check                          PASS
```

## Boundary decision

Phase 241 is closed as provider-rejected. The negative evidence is not a qualification result and grants no promotion or execution authority. Do not repeat the identical `400` request while provider request shape/account state is unchanged. Any future provider attempt requires a separately verified, bounded diagnosis or an explicit provider-side/request-contract change; no blind retry is justified.
