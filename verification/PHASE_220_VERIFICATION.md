# Phase 220 Verification — Google AI Studio Provider Migration

**Status:** GREEN / LOCAL-ONLY / EVIDENCE-ONLY.
**Date of evidence:** 2026-09-01T14:57:51Z.
**Execution mode:** Local Windows project environment only.

## Decision

The active provider contract is now Google AI Studio through its official
OpenAI-compatible endpoint:

```text
https://generativelanguage.googleapis.com/v1beta/openai
```

The only permitted model IDs are:

```text
gemma-4-26b-a4b-it
gemma-4-31b-it
```

These IDs were checked against Google's public Gemma/Gemini API documentation:

- https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- https://ai.google.dev/gemma/docs/core
- https://ai.google.dev/gemini-api/docs/openai

OpenCode remains a historical failed provider path, not an active source or
test contract. Probe 040 still records the earlier `provider_transport_error`;
this migration does not claim to repair OpenCode connectivity.

## Scope

- Replaced the active OpenCode JSON client with `GoogleAIStudioJsonClient`.
- Fixed the provider base URL to Google's official OpenAI-compatible endpoint.
- Restricted provider configuration to the two verified Gemma model IDs.
- Renamed Creator and Learner/Critic transports to Google AI Studio names.
- Updated hash-bound research model policy and model-call audit types.
- Pinned provider retry policy to zero; provider calls are single-attempt and
  fail closed.
- Renamed the credential-handling document without staging or reading a Google
  credential.
- Preserved typed rejection, safe transport metadata, raw-response exclusion,
  and evidence-only execution boundaries.

No provider-side request, credential staging, campaign, scheduler, exchange
endpoint, paper activation, testnet order, live order, promotion, or execution
was performed.

## TDD evidence

1. RED: focused collection failed because the Google provider module and renamed
   critic transport did not exist, and the model policy had no Gemma type.
2. GREEN: focused provider, critic, and model-policy/audit tests passed:

```text
56 passed in 1.05s
```

The focused tests cover the official endpoint path, bearer-header construction,
both pinned Gemma IDs, invalid endpoint rejection, JSON parsing, single-attempt
fail-closed behavior, safe transport metadata, and Creator/Critic contracts.

## Verification gates

```text
uv run --locked pytest -q                         707 passed in 13.97s
uv run --locked ruff check src tests               All checks passed
uv run --locked ruff format --check src tests     354 files already formatted
uv run --locked mypy src                           Success: no issues found in 183 source files
uv lock --check                                   passed
targeted changed-file py_compile                  passed
git diff --check                                  passed
```

## Safety and remaining boundary

- `exchange_access=false`.
- `promotion_state=unpromoted`.
- `paper_activation=false`.
- `execution_authority=false`.
- No credential value, raw prompt, raw provider response, authorization header,
  or private payload was persisted or included here.
- Google AI Studio availability has not been provider-side smoke-tested; an
  injected credential and separately approved bounded smoke are still required.
- The provider abstraction remains injection-based; no unattended runtime,
  scheduler, retry loop, or execution authority was added.
- Deterministic cached evaluation, OOS/walk-forward/stress validation,
  qualification, lineage, promotion, paper, testnet, and live gates remain
  mandatory after any future provider success.

## Repository state

The obsolete `src/autonomous_futures/research/opencode_provider.py` module is
removed. Historical verification reports retain their original OpenCode facts
and are not rewritten.
