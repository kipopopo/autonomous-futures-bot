# Phase 150 Verification — next full Critic-guided lineage chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run the full next-lineage chain from `critic-evidence-013`:

```text
latest Critic evidence
→ Creator revision with seven forbidden historical IDs
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual result

```text
source candidate:       cand-doge-regime-breakout-002
critic evidence:        critic-evidence-013
forbidden prior IDs:    7
provider requests:      1
candidate:              cand-doge-meanrev-003
trial:                  accepted_for_testing
candidate state:        testing
OOS windows:            4
trades:                 240
qualification:          rejected
failed gates:           6
```

OOS aggregation:

```text
pooled net P&L:         -38.8765887775015280798112636 USDT
pooled profit factor:   0.7447947917897344991323056603
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-015
```

Bindings:

```text
candidate artifact hash:
bb09326b3e6e655d16eb2ec4f2fb5f7522d663c1bad83b8f8405f161bdcbc1c3

qualification hash:
9e287367a561245f7ad6b6080bf73db1c1f5eff21484408a416f66adc49dacfa
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

## Safety and cleanup

```text
promotion_state=unpromoted
paper_activation=false
execution_authority=false
orders=0
temporary units/source: removed
local temporary files: deleted
project timers: 0
```

The first copy step used a mismatched temporary directory name; the actual temporary root was copied and read back without another provider request. Cleanup then passed.

## Verification

```text
full suite before chain: 698 passed
Ruff/format/mypy/lock: passed
remote candidate/trial/OOS/qualification readback: passed
lineage guard source parity: passed
```

## Conclusion

The newest Critic-guided candidate completed persistence, cached OOS, and strict qualification, then was rejected on negative evidence. No promotion, paper activation, or live action follows.
