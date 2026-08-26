# Phase 174 Verification — corrected full Critic-guided chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

The first full-chain attempt in this boundary emitted valid runtime metrics but its copied batch root was absent on later readback. That attempt was treated as unverified and discarded; its candidate was not used as evidence. A separated bounded rerun then completed service execution, artifact copy, readback, and cleanup.

The verified rerun used:

```text
critic-evidence-021
+ complete historical candidate/proposal guard
→ Creator revision
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual verified result

```text
source candidate:       cand-doge-meanrev-007
critic evidence:        critic-evidence-021
forbidden prior IDs:    24
provider requests:      1 (verified rerun)
candidate:              cand-doge-regime-breakout-009
trial:                  accepted_for_testing
candidate state:        testing
OOS windows:            4
trades:                 1126
pooled net P&L:         -34.3270170464645543992347278 USDT
pooled profit factor:   0.9070888620455312231861631096
qualification:          rejected
failed gates:           6
```

Failed gates:

```text
oos_average_return_below_threshold
oos_symbol_average_return_below_threshold
oos_symbol_drawdown_above_threshold
oos_symbol_profit_factor_below_threshold
oos_drawdown_above_threshold
oos_profit_factor_below_threshold
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-024
```

Bindings:

```text
candidate artifact hash:
4dd3b8c4eb3ca0eef10d981db3a462dd727b29e2a4fd8ceb2e4c38c476941e7c

qualification hash:
6f73fe02fb6dcf0fcfe832e6c6876a735492f342845f410c3353e1fe82845a77
```

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
temporary units/source: removed
local temporary files: deleted
project timers=0
```

## Verification

```text
full suite before chain: 698 passed
Ruff/format/mypy/lock: passed
remote candidate/trial/OOS/qualification copy: passed
remote readback of summary/candidate/qualification: passed
remote cleanup: passed
```

## Conclusion

The separated rerun provides fully verified persistence, cached OOS, and strict qualification evidence for a new candidate. The candidate was rejected on negative pooled/per-symbol evidence. No promotion, paper activation, or live action follows.
