# Phase 153 Verification — current full Critic-guided lineage chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run the full chain from `critic-evidence-014`:

```text
latest Critic evidence
→ Creator revision with eight forbidden historical IDs
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual result

```text
source candidate:       cand-doge-meanrev-003
critic evidence:        critic-evidence-014
forbidden prior IDs:    8
provider requests:      1
candidate:              cand-doge-regime-breakout-004
trial:                  accepted_for_testing
candidate state:        testing
OOS windows:            4
trades:                 5198
qualification:          rejected
failed gates:           6
```

OOS aggregation:

```text
pooled net P&L:         -193.5363466361237310679070169 USDT
pooled profit factor:   0.6593618112189156889050497046
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-016
```

Bindings:

```text
candidate artifact hash:
0715746e6af2060d715659e4b03f2e73f993a777c448970a46e2f936fdd2aad0

qualification hash:
b121d296eb3384d5f817cbe17b2f11a4d426cb06ae25b233ce962053f87d00c2
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

The wrapper initially referenced the wrong temporary directory; the actual temp root was copied and read back without a provider rerun. Cleanup then passed.

## Verification

```text
full suite before chain: 698 passed
Ruff/format/mypy/lock: passed
remote candidate/trial/OOS/qualification readback: passed
lineage guard source parity: passed
```

## Conclusion

The newest Critic-guided candidate completed the full research gate sequence and was strictly rejected on strongly negative evidence. No promotion, paper activation, or live action follows.
