# Phase 189 Verification — current full Critic-guided chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run the full chain from `critic-evidence-026` using the complete persisted+historical lineage guard:

```text
Critic-guided Creator revision
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual verified result

```text
source candidate:       cand-doge-regime-breakout-011
critic evidence:        critic-evidence-026
forbidden prior IDs:    29
provider requests:      1
candidate:              cand-doge-regime-breakout-012
trial:                  accepted_for_testing
candidate state:        testing
OOS windows:            4
trades:                 631
pooled net P&L:         -15.7155338519787390476900905 USDT
pooled profit factor:   0.9389614581346027430852725486
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
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-029
```

Bindings:

```text
candidate artifact hash:
1ffd2e8bc56f854e3ba2db99ae0fdc921a1af0eae0128e7e6bafcd6ad195e702

qualification hash:
087ff0ba204a6c565ee5e6260965f7bbbdb9f5a1e15269f8228701e71585c184
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

The current Critic-guided candidate completed persistence, cached OOS, and strict qualification, then was rejected on negative pooled/per-symbol evidence. No promotion, paper activation, or live action follows.
