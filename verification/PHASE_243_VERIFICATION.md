# Phase 243 Verification — Single Bounded Diagnostic Probe

Date: 2026-09-03 (MYT / UTC+08:00)

Status: **COMPLETED / BOUNDED-PROBE / PROVIDER-REJECTED**

## Runtime and scope

- Remote Creator provider: Google AI Studio OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai`).
- Remote model: `gemma-4-31b-it`.
- Thinking controls: minimal level, thoughts excluded.
- Campaign: `creator-batch-20260903-012`.
- Research run ID: `run-doge-google-gemma-20260903-012`.
- Symbol: `DOGEUSDT`.
- Mode: cached-only research; no exchange access and no execution authority.
- Probe runner: `scripts/probe_google_ai_studio.py`.

The campaign targeted the Google AI Studio provider endpoint using the committed Phase 242 hardened `GoogleAIStudioJsonClient` transport. A single bounded diagnostic probe was issued with `max_retries=0` and `fallback_provider=false` to test provider-side contract behavior and resolve the rejection mode with safe structured diagnostics.

## Exact-source and immutable-input bindings

- Source commit: `eb65a417ed72ebb85461c22bdd0af75e71f2ca94`.
- Immutable bundle SHA-256: `19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816`.
- Dataset registry SHA-256: `583cd7d15cb0a3faf019cb9940f2739578ba9d88d1b62792cb1a9f0a2e8d72bb`.
- Complete historical candidate identity preflight returned `4` forbidden candidate identities, including local canonical strategy identities:
  - `cand-148b5e15c0985f8e513f20636d8330822198c63759f95a946e866c90723291ad`
  - `cand-38c598ba88be7141cc2a361daedc3f68fc30ce2ceeceee7e181f3e77b3190f38`
  - `cand-d1955931522fe61c0c45052b17bbb1b1afebe92af6b7bddf887fa47f8953f744`
  - `cand-febf9237c4a904eda69fb122083bc2f1297640d2094cd7844bb5caa906d014f4`
- Cached market evidence reference bound into request: `bundle/19a55436cd764071c70f068faf1211fe72e70b1cb7803f06ef643b84687f3816`.
- Raw prompts, raw provider responses, authorization headers, Bearer tokens, and exception tracebacks were strictly sanitized and not persisted.

## Provider trial outcome

- Outbound request count: `1`.
- `max_retries`: `0`.
- Fallback provider: `false`.
- HTTP status: `401`.
- Typed trial decision: `rejected`.
- Reason code: `provider_http_error`.
- Safe structured error diagnostic metadata:
  - `status_code`: `401`
  - `error_code`: `http_401`
  - `error_reason`: `http_401_non_mapping_json`
  - `content_kind`: `invalid_payload`
  - `content_length`: `306`
  - `content_sha256`: `dfb14a1ed657c6b6ca36826a7e5bbe086a99b42f52c3f6facaf218c2571d104d`
  - `response_keys`: `[]`
- Candidate count: `0`.
- OOS evaluation windows: `0`.
- Qualification: not run because no candidate was generated.

The provider responded with HTTP 401 Unauthorized (`content_length=306`), captured and typed through Phase 242 error extraction as `error_code=http_401` and `error_reason=http_401_non_mapping_json`. Zero credentials, bearer tokens, or raw prompts appeared in metadata or persisted evidence. Execution stopped immediately at the major boundary without retry, parameter fallback, or provider hopping.

## Evidence readback

Published immutable evidence root (`artifacts/research/phase243/`) contains:

- `artifacts/research/phase243/campaign-summary.json`
- `artifacts/research/phase243/trials/trial-0000-run-doge-google-gemma-20260903-012.json`

Independent readback with canonical local persistence verification (`read_creator_batch_trial_evidence`):

- Persisted evidence hash: `ef2b5eca61c2c740babf5bf28aa2c339342bc97991333b9e519025e11b7c7a80`
- Evidence schema version: `1`
- Campaign status: `creator_rejected`
- Typed trial hash and schema are valid: **PASS**
- Reason is exactly `provider_http_error`: **PASS**
- Request count is `1` and retries are `0`: **PASS**
- Zero raw response fields, bearer tokens, API keys, or prompt text: **PASS**
- Forbidden candidate identity count: `4`: **PASS**

## Safety state

Persisted safety state remains strictly intact:

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
orders=0
```

Zero exchange endpoints were invoked, zero orders were placed, no trading credentials were accessed, and paper/live promotion remains unpromoted and disabled.

## Verification gates

All 6 repository verification gates pass cleanly:

```text
uv run --locked pytest -q                 PASS (792 passed in ~9s)
uv run --locked ruff check src tests scripts      PASS (All checks passed)
uv run --locked ruff format --check src tests scripts PASS (All files formatted)
uv run --locked mypy src                  PASS (Success: no issues found in 183 source files)
uv run --locked uv lock --check           PASS (Resolved 67 packages)
git diff --check                          PASS (Clean diff, no conflict/whitespace markers)
```

## Boundary decision

Phase 243 is closed as bounded probe completed and provider-rejected. The diagnostic trial captured typed safe evidence without credential or prompt leakage, proving that the transport boundary holds under live server interaction. The negative outcome grants no promotion, execution, or paper activation authority. No blind retries or parameter workarounds were attempted.
