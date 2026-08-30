# Phase 202 Verification — cached-only Learner bootstrap boundary

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
 effort: Medium
```

## Scope

Open the first real Learner boundary after Creator/Critic closure:

```text
cached primary 5m + context 15m
→ causal materialization
→ explicit caller-supplied trainer
→ immutable model/LearnerArtifact
→ prepared LearnerRun
```

No default trainer, provider call, exchange access, paper activation, or live execution was added.

## TDD and shared fix

The new bootstrap test first failed with the expected missing-module error:

```text
ModuleNotFoundError: autonomous_futures.research.learner_bootstrap
```

The minimal bootstrap boundary then passed its focused tests. The first remote smoke exposed a real shared pandas 3 timestamp-unit mismatch (`datetime64[ms, UTC]` versus `datetime64[us, UTC]`) in `materialize_causal_context`. A mixed-precision regression was added, the shared merge keys were normalized to microseconds, and the corrected source was pushed at `9c9e63e`.

## Actual remote smoke

Executed from the pushed source with `PrivateNetwork=yes` and cached files only:

```text
candidate:              cand-doge-regime-gated-meanrev-014
learner:                learner-doge-bootstrap-002
model family:           linear_next_return
learner version:        learner-bootstrap-v1
feature IDs:            adx, bollinger_zscore, regime_trend, rsi
input window:           input-dogeusdt
input symbols:          DOGEUSDT
cached rows:            105120
training rows:          105099
```

A deterministic NumPy least-squares trainer fit next-bar return from the causal declared features and returned JSON model bytes through the explicit `LearnerTrainingOutput` callback. No raw model bytes were printed.

## Persisted and verified artifacts

Remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/learner-bootstrap-002
```

```text
LearnerArtifact hash:
d0aa8260e8c056d6a4f6f42677fc0cf20a9363480e74caa8d26d2a70fdcaefc8

model file hash:
61a021eaed3c955e4041f9fed84793b9e1fdba0f051db6b26d5168dda80dc9aa

model reference:
bootstrap/doge-linear-next-return-002.json

prepared run hash:
12321a14d93deb92d44a4261f9ea1f5a0e4001f79453e72daa53455258ec56a7
```

Independent final readback verified:

```text
learner_readback_equal=true
run_readback_equal=true
prepared_status=prepared
training_metrics=None
output_artifact_hash=None
```

## Safety

```text
state=testing
status=prepared
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
project timers=0
temporary units/source: removed
local temporary files: deleted
```

## Verification

```text
bootstrap focused tests:       2 passed
causal/learner related tests:  26 passed
full suite after code commit:  701 passed
Ruff/format/mypy/lock:         passed
remote source parity:          passed
remote artifact readback:      passed
remote cleanup:                passed
```

## Honest limitation

This is a real cached-only baseline model artifact and prepared-run provenance, not a completed Critic-guided retraining evidence envelope. No learner quality metrics, model review, learner qualification, paper activation, testnet observation, or live authority was inferred.

## Conclusion

The project now has a real explicit cached-only Learner bootstrap path that creates and verifies model bytes, a hash-bound testing `LearnerArtifact`, and a prepared `LearnerRun`. The next materially new boundary is model evaluation/quality review or a separately specified Critic-evidence training handoff; paper/testnet/live remain blocked.
