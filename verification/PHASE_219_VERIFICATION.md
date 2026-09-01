# Phase 219 Verification — Safe Provider Transport-Error Classification

**Status:** GREEN / EVIDENCE-ONLY.
**Date of evidence:** 2026-09-01T14:10:47Z.
**Execution mode:** Local Windows project environment only.
**Runtime:** gpt-5.6-luna / openai-codex / Medium.

## Scope

Phase 219 adds one bounded diagnostic field to the existing fail-closed OpenCode
transport error. A caught `httpx.HTTPError` now exposes only its exception type,
for example `ReadTimeout`, as `transport_error_type`. The exception message,
response body, request payload, authorization value, and any other raw detail
remain excluded.

The shared Creator and Learner/Critic evidence boundaries allow-list this field
so the diagnostic survives typed rejection mapping without widening the raw
provider-output surface.

No retry policy, fallback provider, campaign, scheduler, exchange endpoint,
execution path, candidate registry write, qualification, promotion, paper
activation, testnet order, or live order was added or used.

## TDD evidence

1. RED: the new OpenCode transport test failed because transport errors had
   empty metadata; the new Creator/Critic expectations failed because the new
   field was not allow-listed.
2. GREEN: focused provider, Creator, and Learner/Critic tests passed:

```text
21 passed in 0.77s
```

The regression assertions verify that `ReadTimeout` is retained while the
sentinel transport-error message and an unrelated `secret` metadata field do
not escape.

## Changed files

- `src/autonomous_futures/research/opencode_provider.py`
  - Adds `transport_error_type` to metadata for caught `httpx.HTTPError`.
- `src/autonomous_futures/research/creator_generator.py`
  - Preserves only the new safe metadata key.
- `src/autonomous_futures/research/learner_critic.py`
  - Preserves only the new safe metadata key for the sibling path.
- `tests/unit/test_opencode_provider.py`
  - Covers transport exception classification and message non-leakage.
- `tests/unit/test_creator_generator.py`
  - Covers safe metadata propagation.
- `tests/unit/test_learner_critic.py`
  - Covers safe metadata propagation through the Critic boundary.

## Verification gates

```text
uv run --locked pytest -q                         704 passed in 13.62s
uv run --locked ruff check src tests               passed
uv run --locked ruff format --check src tests     354 files already formatted
uv run --locked mypy src                           Success: no issues found in 183 source files
uv lock --check                                   passed
targeted changed-file py_compile                  passed
git diff --check                                  passed
```

The repository-wide cache-writing `compileall` command was also attempted. It
fails on pre-existing overlong generated `research_lab` filenames because
Windows cannot create the corresponding `.pyc` paths. No changed file is among
the failures; direct compilation of all six changed files passed. This known
checkout limitation is not treated as a Phase 219 regression.

## Safety and remaining boundary

- `exchange_access=false`.
- `promotion_state=unpromoted`.
- `paper_activation=false`.
- `execution_authority=false`.
- No credentials, provider response bodies, or raw request payloads were
  persisted or included in this report.
- Probe 040 remains `provider_transport_error`; this phase does not claim to
  repair provider connectivity.
- Campaign 041 remains cancelled/not run; candidate, OOS, qualification, and
  order counts remain zero.
- No remote command, provider request, VPS deployment, scheduler, daemon,
  exchange access, paper execution, testnet execution, or live execution was
  performed.

## Next gate

Future provider work still requires a materially different provider hypothesis
or independently obtained provider stability evidence with a fresh bounded
budget. This diagnostic slice does not authorize a new probe or campaign.
