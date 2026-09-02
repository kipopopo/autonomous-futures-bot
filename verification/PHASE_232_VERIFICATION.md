# Phase 232 Verification — strict Decimal provider JSON compatibility

Status: `GREEN / PROVIDER-PROMPT-CONTRACT / EVIDENCE-ONLY`

## Runtime

```text
model:    gpt-5.6-sol
provider: openai-codex
effort:   Medium
```

## Root cause

The Creator prompt requires DSL v2 and `CandidateSimulationRisk` uses strict `Decimal` fields. Google AI Studio's OpenAI-compatible response content is decoded with `json.loads()`, which previously converted decimal JSON numbers into Python `float` values. Strict `CreatorProposal` validation therefore rejected otherwise valid v2 proposals at the schema boundary.

## RED

The new real-transport regression encoded a complete DSL v2 proposal as provider JSON with decimal risk values and passed it through:

```text
GoogleAIStudioJsonClient
→ GoogleAIStudioProposalTransport
→ CreatorGenerator
→ CreatorProposal
```

Before implementation:

```text
2 failed
provider proposal decision: rejected
prompt decimal representation: absent
```

## GREEN

Minimum change:

- decode floating JSON numbers with `json.loads(..., parse_float=Decimal)`;
- require unquoted decimal-point JSON numbers for all risk fields;
- retain strict Pydantic Decimal validation;
- retain the existing model, endpoint, JSON-object envelope, thinking controls, timeout, and zero-retry policy.

Focused verification:

```text
40 passed in 1.73s
```

Full verification:

```text
715 passed in 9.63s
ruff check: PASS
ruff format --check: PASS
mypy: PASS
uv lock --check: PASS
git diff --check: PASS
git show --check HEAD: PASS
```

## Safety

```text
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
remote_provider_requests=0
```

No raw prompt, provider response, credential, secret, API key, or error body was persisted.

Credentials must never be pasted, printed, logged, committed, or included in summaries:
[REDACTED]

## Boundary

This changes the actual Creator request guidance and parser compatibility, so one new bounded remote campaign is materially different from Phase 228. That campaign remains separately finite: one provider request, `max_retries=0`, no fallback, immutable cached data only, independent readback, and no promotion or execution authority.
