# Phase 156 Verification — current full Critic-guided chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run the next full chain from `critic-evidence-015`:

```text
latest Critic evidence
→ Creator revision with nine forbidden historical IDs
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual result

```text
source candidate:       cand-doge-regime-breakout-004
critic evidence:        critic-evidence-015
forbidden prior IDs:    9
provider requests:      1
candidate:              cand-doge-meanrev-004
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
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-017
```

Bindings:

```text
candidate artifact hash:
25e3f9d2de8caabf260f05e8149d1a394340e7f0fd67bbcadf3992f6e4a94933

qualification hash:
e5a4b70a07ca209e9984904a2adc280e783fdd6b2d9b2609a81c3d6f60cf723b
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
project timers=0
```

## Verification

```text
full suite before chain: 698 passed
Ruff/format/mypy/lock: passed
remote candidate/trial/OOS/qualification readback: passed
lineage guard source parity: passed
```

## Conclusion

The latest Critic-guided candidate completed the full research gate sequence and was strictly rejected on negative evidence. No promotion, paper activation, or live action follows.
