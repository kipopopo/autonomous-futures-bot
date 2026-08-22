# Phase 125 Verification — Learner/Critic OpenCode transport contract

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Add the provider-facing contract over the already-tested injected Learner/Critic boundary:

```text
LearnerCriticRequest
→ canonical critic prompt
→ existing OpenCodeJsonClient
→ OpenCodeCriticTransport
→ strict LearnerCritic parser
```

The prompt requires:

```text
review_id
research_run_id
candidate_id
decision=revise|stop
exact failure_reason_codes
non-empty revision_actions JSON array
```

No new HTTP client, fallback model, scheduler, persistence, model bytes, promotion, paper activation, or order authority was added.

## TDD evidence

```text
critic/provider tests: 5 passed
full suite:           688 passed
Ruff:                 passed
format:               passed
mypy:                 passed
uv lock:              passed
git diff --check:     passed
```

## Safety

```text
real provider requests: 0
raw output persistence: false
candidate mutation:     0
training execution:     0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
```

This minor contract slice is complete. The next major boundary is one real bounded Learner/Critic OpenCode smoke using persisted qualification feedback.
