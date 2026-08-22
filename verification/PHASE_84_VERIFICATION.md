# Phase 84 Verification — canonical Creator proposal prompts

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 84 adds one canonical prompt builder for the real Creator provider path after Ox Alpha/DeepSeek returned non-schema content.

```text
CreatorGenerationRequest
→ explicit schema/system contract
→ exact bundle/symbol/evidence scope
→ provider messages
```

## Delivered

New module:

```text
src/autonomous_futures/research/creator_prompts.py
```

New tests:

```text
tests/unit/test_creator_prompts.py
```

The prompt builder now explicitly requires:

```text
one JSON object
proposal_id
research_run_id
hypothesis
expected_regime
novelty_reason
strategy DSL fields
no markdown/code fences/prose/URLs/secrets/tools/orders
```

It validates the bundle hash and uppercase symbol before prompt construction, and includes the exact research-run/evidence references in the user message.

## TDD evidence

```text
prompt tests: 2 passed
full suite:   669 passed
Ruff:         passed
format:       passed
mypy:         passed
uv lock:      passed
git diff --check: passed
```

## Safety

```text
new provider requests: 0
raw model output:      none
candidate mutation:    0
orders:                0
execution authority:   false
```

The next boundary should use this canonical prompt in one bounded DeepSeek Creator smoke. If the model still fails schema validation, preserve the rejection and stop—do not accept arbitrary prose.
