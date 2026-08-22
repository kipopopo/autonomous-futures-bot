# Phase 85 Verification — stable provider error propagation

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

The real canonical Creator smoke returned generic `provider_error`, which discarded the adapter’s stable `provider_payload_invalid` code. Phase 85 fixes that root cause without exposing raw exception details.

`CreatorGenerator` now:

```text
provider exception with stable provider_* code
→ preserve stable code
provider exception without stable code
→ provider_error
raw exception text
→ never returned or persisted
```

## TDD evidence

```text
Generator tests before fix: 4 passed / 1 expected RED behavior
Generator tests after fix:  5 passed
full suite:                670 passed
Ruff:                      passed
format:                    passed
mypy:                      passed
uv lock:                   passed
git diff --check:          passed
```

## Safety

```text
new real provider requests: 0
raw provider exception:     not exposed
candidate mutation:         0
orders:                     0
execution authority:        false
```

The next real Creator smoke can now report `provider_payload_invalid` rather than collapsing it into `provider_error`, while continuing to fail closed.
