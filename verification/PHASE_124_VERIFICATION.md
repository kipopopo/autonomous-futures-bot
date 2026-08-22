# Phase 124 Verification — injected Learner/Critic review contract

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Add a strict, provider-agnostic Learner/Critic review boundary:

```text
CreatorQualificationFailureFeedback
→ LearnerCriticRequest
→ injected critic transport
→ typed LearnerCritique
→ bounded revision actions
```

The critique can only say `revise` or `stop`, preserve the exact failed reason codes, and emit advisory actions. It cannot mutate candidates, produce model bytes, promote, activate paper, or execute orders.

## Contract safety

The request validates:

```text
candidate/feedback binding
sorted unique evidence refs
learner-critic-v1 schema identity
```

The critique validates:

```text
review ID/run/candidate identity
sorted unique failure codes/actions
canonical review hash
cached-only and authority-off fields
```

## TDD evidence

```text
critic tests: 3 passed
full suite:   686 passed
Ruff:         passed
format:       passed
mypy:         passed
uv lock:      passed
git diff --check: passed
```

## Safety

```text
provider requests: 0
training calls:    0
candidate mutation:0
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
```

This is the strict contract before a later real Learner/Critic provider adapter. No model/provider integration is claimed yet.
