# Phase 204 Verification — cached-only Learner metric evaluation

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Convert the persisted bootstrap model's predictions into a deterministic cached trade ledger through the existing metric adapter:

```text
LearnerArtifact + causal cached frame
→ explicit model predictions
→ cached signal ledger with fees/slippage
→ TradePerformanceMetrics
→ LearnerMetricEvaluationRun
→ immutable persistence/readback
```

No provider/exchange call, retraining, quality decision, qualification, paper activation, or live execution was used.

## Actual remote result

```text
candidate:              cand-doge-regime-gated-meanrev-014
learner:                learner-doge-bootstrap-002
metric evaluation:     learner-metric-evaluation-001
evaluation version:     cached-linear-next-return-metric-v1
symbol:                 DOGEUSDT
rows evaluated:         105120
trade count:            10479
winning trades:         5654
losing trades:          4825
net P&L:                -99.1376223041917105380727001 USDT
return:                 -99.13762230419171053807270010%
profit factor:          0.5857591556917013240863825774
max drawdown:           99.15732429115140182183293478%
```

The ledger used the existing explicit `TradeSimulationConfig` with starting equity 100 USDT, 50% position fraction, 0.0004 taker fee, and 0.0001 slippage. Metrics were calculated from the validated net trade ledger.

## Persisted metric evidence

Remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/learner-metric-evaluation-001
```

```text
evaluation hash:
e7d2f2c2fbc011aa82a4684258ca8d78487ae178c3a1c050decd7369b6ec133d
```

Independent final readback:

```text
readback:        true
data_source:     cached_only
exchange_access: false
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
metric adapter focused tests: 48 passed
full suite baseline:          701 passed
Ruff/format/mypy/lock:        passed
remote source parity:         passed
remote metric copy/readback:   passed
remote cleanup:               passed
```

## Honest limitation

This is in-sample cached metric evidence because the bootstrap model was trained over the same cached scope. The strongly negative result is not a model-quality pass. No quality reviewer, model qualification, paper readiness, testnet readiness, or live authority was inferred.

## Conclusion

The bootstrap LearnerArtifact now has a persisted, hash-verified trade-performance envelope. The next materially new boundary is an observed-only caller-supplied metric-quality review of this envelope or a separate Critic-evidence retraining handoff; paper/testnet/live remain blocked.
