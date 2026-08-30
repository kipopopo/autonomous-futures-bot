# Phase 203 Verification — cached-only Learner evaluation

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Evaluate the persisted bootstrap LearnerArtifact through the existing read-only cached learner evaluator:

```text
persisted LearnerArtifact + model bytes
→ re-materialized causal 5m/15m input
→ explicit model evaluator callback
→ LearnerEvaluationRun
→ immutable persistence/readback
```

No retraining, provider call, exchange access, paper activation, or lifecycle mutation was used.

## Actual remote result

```text
candidate:              cand-doge-regime-gated-meanrev-014
learner:                learner-doge-bootstrap-002
learner artifact hash:  d0aa8260e8c056d6a4f6f42677fc0cf20a9363480e74caa8d26d2a70fdcaefc8
run:                    learner-evaluation-001
evaluation version:     cached-linear-next-return-v1
input window:           input-dogeusdt
symbol:                 DOGEUSDT
rows evaluated:         105120
finite predictions:     105100
positive predictions:   47982
```

The callback loaded the persisted linear next-return model, evaluated predictions from the re-materialized causal declared features, and returned typed `LearnerWindowEvaluation` evidence. Model output values were not printed.

## Persisted evaluation evidence

Remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/learner-evaluation-001
```

```text
evaluation hash:
2c71ab2e2bc8b5cc38023ddd1c2b7e4745408eac829a44308475de3a84d054c1
```

Independent final readback:

```text
readback_equal=true
data_source=cached_only
exchange_access=false
```

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
temporary service/source: removed
local temporary files: deleted
project timers=0
```

## Verification

```text
Learner evaluation/metric focused tests: 55 passed
full suite baseline:                     701 passed
Ruff/format/mypy/lock:                   passed
remote source parity:                   passed
remote evaluation copy/readback:         passed
remote cleanup:                         passed
```

## Honest limitation

This proves cached-only model evaluation provenance and prediction coverage. It does not prove model quality, profitability, learner qualification, Critic-guided retraining, paper readiness, testnet readiness, or live authority. No performance metrics or quality decision was fabricated from prediction counts.

## Conclusion

The persisted bootstrap LearnerArtifact now has a verified cached-only evaluation envelope. The next materially new boundary is a caller-supplied quality review/metric evidence path or a separate Critic-evidence retraining handoff; paper/testnet/live remain blocked.
