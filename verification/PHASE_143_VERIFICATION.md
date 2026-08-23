# Phase 143 Verification — Critic-guided strict qualification

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Run strict qualification on the persisted Critic-guided candidate by recomputing its four cached OOS windows:

```text
persisted candidate/OOS
→ deterministic cached aggregation
→ strict qualification policy
→ write-once qualification artifact
→ readback
```

No provider request, training, promotion, paper activation, or order route was used.

## Actual result

```text
candidate:          cand-doge-breakout-001
provider requests:  0
windows evaluated:  4
decision:           rejected
failed gates:       6
qualification hash: bbc13efa03f095c0cbc88f303738bea552b0f8ada78321fab4c9e81447a4762b
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

Persisted qualification artifact:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-012/qualification/cand-doge-breakout-001.json
```

Read-back candidate artifact binding:

```text
candidate artifact hash:
810a81c982c7b01e4693877b02161590beee44f88ca4d323f1553b3c6f73ede7
```

## Safety and cleanup

```text
promotion/paper/live: unchanged and disabled
orders:               0
temporary systemd unit: removed
temporary source root: removed
local temporary files: deleted
project timers:        0
```

The first readback probe asked for fields not declared by the qualification artifact schema and failed with `KeyError`; the corrected probe read only declared fields and passed. No artifact was modified.

## Verification

```text
full suite before qualification: 697 passed
Ruff/format/mypy/lock: passed
remote qualification readback: passed
```

## Conclusion

Critic-guided Creator output now completed the full research gate sequence through strict rejection. It remains negative evidence; no promotion or paper activation follows.
