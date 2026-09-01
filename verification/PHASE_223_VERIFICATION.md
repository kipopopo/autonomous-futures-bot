# Phase 223 Verification — Gemma 4 thinking control contract

## Status

**GREEN / LOCAL-ONLY / EVIDENCE-ONLY**

This phase investigated the repeated provider result:
`HTTP 200 + finish_reason=length + invalid JSON`. The two bounded provider
runs showed the failure persisted when the output budget changed from `32` to
`256`, with the second response growing to `968` characters. The local
provider contract now explicitly disables Gemma 4 thinking output for
JSON-bound calls before any further remote smoke.

- Verification time: `2026-09-01T23:13:22Z`
- Source commit before evidence: `6977efb597cb1e7285299b5fd2ad871c6a7eeeb6`
- Provider: `google_ai_studio`
- Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai`
- Models covered by the client contract: `gemma-4-26b-a4b-it`, `gemma-4-31b-it`
- Remote requests in this phase: `0`

## Root-cause hypothesis

The repeated truncation pattern is consistent with Gemma 4 thinking output
consuming the bounded completion budget before the JSON result. A larger
budget alone did not resolve the behavior:

```text
Phase 221: max_tokens=32  -> HTTP 200, finish_reason=length, JSON=false
Phase 222: max_tokens=256 -> HTTP 200, finish_reason=length, JSON=false
```

Google's OpenAI-compatibility documentation supports passing Gemini-specific
thinking configuration through `extra_body.google.thinking_config`. Google's
Gemma documentation identifies `minimal` as the disabled-thinking level for
Gemma 4. Sources consulted:

- https://ai.google.dev/gemini-api/docs/openai
- https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- https://ai.google.dev/gemma/docs/core/model_card_4

## Local contract change

`GoogleAIStudioJsonClient` now sends this safe, explicit request extension for
every JSON-bound Gemma 4 call:

```text
extra_body.google.thinking_config.thinking_level=minimal
extra_body.google.thinking_config.include_thoughts=false
```

The client does not send `reasoning_effort` alongside this control. The
provider remains single-attempt and fail-closed; raw responses and
credentials remain excluded from persistence and logs.

## TDD and verification

RED was observed before implementation:

```text
KeyError: 'extra_body'
```

After the minimum provider change, focused tests passed:

```text
13 passed in 0.74s
```

Full local verification passed:

```text
uv run --locked pytest -q                         708 passed in 13.08s
uv run --locked ruff check src tests               All checks passed
uv run --locked ruff format --check src tests     354 files already formatted
uv run --locked mypy src                           Success: no issues found in 183 source files
uv lock --check                                   passed
changed-file py_compile                            passed
git diff --check                                  passed
```

## Boundary and next gate

No remote provider request, credential read-back, campaign, candidate,
qualification, promotion, paper activation, testnet order, or live order was
performed in this phase. The next remote smoke, if separately approved, must
be one bounded request using this changed contract; it must not retry the
previous payload. `gemma-4-31b-it` remains provider-side unverified.

```text
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
```

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]
