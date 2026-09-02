# Phase 231 Verification — successful provider payload metadata contract

Status: `GREEN / LOCAL-CONTRACT / EVIDENCE-ONLY`

## Runtime

```text
model:    gpt-5.6-sol
provider: openai-codex
effort:   Medium
```

## Scope

Phase 231 makes safe response metadata available when Google AI Studio returns HTTP 200 with a valid JSON object that later fails strict Creator or Learner/Critic schema validation.

Before this slice, `GoogleAIStudioJsonClient` computed safe metadata but returned only the parsed mapping. The strict schema boundary therefore emitted `schema_rejected` with field/type diagnostics but without the HTTP/finish/content metadata needed to interpret the response envelope.

The bounded path is now:

```text
HTTP 200 JSON object
→ transient dict-compatible ProviderJsonPayload
→ strict typed parser
→ schema_rejected
→ safe provider metadata + field/type diagnostics
```

The transient payload remains in memory only. Raw prompts, raw provider content, response bodies, headers, credentials, and exception text are not persisted.

## Delivered

Modified:

- `src/autonomous_futures/research/google_ai_studio_provider.py`
- `src/autonomous_futures/research/creator_generator.py`
- `src/autonomous_futures/research/learner_critic.py`
- `tests/unit/test_google_ai_studio_provider.py`
- `tests/unit/test_learner_critic_provider.py`

The provider client now returns a dict-compatible parsed payload carrying only the existing safe metadata:

```text
status_code
response_keys
choice_count
finish_reason
content_kind
content_length
content_sha256
```

Creator and Learner/Critic copy that metadata only onto the current `schema_rejected` result. Successful and binding-mismatch paths remain unchanged under Ponytail/YAGNI.

## TDD evidence

```text
Initial Creator/Critic regressions:          RED — 2 failed
Focused provider/generator/batch/critic:      36 passed
Full locked pytest suite:                     714 passed
Ruff check:                                   passed
Ruff format --check:                          passed
mypy src:                                     passed
uv lock --check:                              passed
git diff --check:                             passed
```

## Safety boundary

```text
provider requests during local verification: 0
remote campaign attempts:                     0
raw provider output stored:                   0
exchange access:                              false
promotion state:                              unpromoted
paper activation:                             false
execution authority:                          false
orders:                                       0
```

No parser rule, proposal schema, prompt, model, retry policy, fallback, qualification gate, promotion rule, paper state, testnet state, or live state changed.

## Next bounded action

After this source is committed and pushed, one materially changed Creator campaign may run from the exact commit against the repaired immutable cache. Its changed hypothesis is safe schema-rejection evidence: unlike Phase 228, the campaign can persist both field/type diagnostics and the already allowlisted successful-response metadata.

That campaign must remain one-shot, `max_retries=0`, cached-only, evidence-only, and fail-closed. A valid candidate may proceed only through the existing deterministic cached evaluation and strict qualification contracts; no promotion, paper activation, testnet execution, or live execution is authorized.
