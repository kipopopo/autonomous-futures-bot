# Phase 207 Verification — persisted Learner metric-quality qualification

## Runtime

```text
model: GPT-5.6 Terra
provider: OpenAI Codex
effort: Medium
```

## Scope

Run the existing verified metric-quality qualification chain against persisted cached-only evidence:

```text
metric evaluation
→ observed-only quality review
→ persisted metric-quality decision
→ verified qualification input
→ immutable qualification evidence
→ verified final-path readback
```

This is qualification **evidence only**. It does not mutate candidate or Learner state, promote anything, activate paper/testnet/live execution, or access an exchange.

## Verified source identities

```text
candidate:       cand-doge-regime-gated-meanrev-014
learner:         learner-doge-bootstrap-002
evaluation:      learner-metric-evaluation-001
review:          metric-quality-review-001
source decision: metric-quality-decision-001 = failed
source policy:   policy-learner-quality-001
```

The runner first failed closed because the caller used an unbound source-policy ID. It inspected only safe persisted policy metadata, corrected the caller ID to the exact persisted binding, and did not relax thresholds or introduce a fallback.

## Qualification result

```text
qualification ID:   metric-quality-qualification-001
qualification:      rejected
qualification hash: c1f087bb536f7a07c48a2b7702e91fea6ef4784a86e1486c298590d4f85362f8
final readback:     true
```

Deterministic gates:

```text
metric_quality_decision: failed
reason: metric_quality_decision_not_passed

minimum_windows: passed
reason: minimum_windows_passed
```

The upstream metric-quality decision remained failed because its observed evidence was below the declared net-P&L and profit-factor thresholds and above the drawdown threshold. This Phase 207 record does not reinterpret the rejection as missing evidence or an execution-state transition.

## Immutable publication and safety

The non-privileged temporary service wrote a hash-verified artifact in an isolated temporary root. The final protected path was absent before publication, then copied once and independently hash-read from the final path.

```text
data_source=cached_only
exchange_access=false
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
project timers=0
active project units=0
remote temporary cleanup=pass
local temporary files remaining=[]
```

## Verification

```text
focused metric/review regressions: 53 passed in 8.27s
remote immutable qualification readback: passed
full-chain policy/provenance reconstruction: passed
```

## Conclusion

`metric-quality-qualification-001` is durable rejected evidence, not learner promotion, paper eligibility, testnet authority, or live authority. The next material boundary is a read-only qualification-evidence consumer/availability view; no paper work is authorized because no Learner or Creator candidate has qualified.
