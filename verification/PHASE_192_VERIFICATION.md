# Phase 192 Verification — current full Critic-guided chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run the full chain from `critic-evidence-027` using the complete persisted+historical lineage guard:

```text
Critic-guided Creator revision
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual verified result

```text
source candidate:       cand-doge-regime-breakout-012
critic evidence:        critic-evidence-027
forbidden prior IDs:    30
provider requests:      1
candidate:              cand-doge-regime-breakout-013
trial:                  accepted_for_testing
candidate state:        testing
OOS windows:            4
trades:                 158
pooled net P&L:         +1.5245536278994633494977186 USDT
pooled profit factor:   1.012569520001495155457082704
qualification:          rejected
failed gates:           2
```

Failed gates:

```text
oos_symbol_drawdown_above_threshold
oos_drawdown_above_threshold
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-030
```

Bindings:

```text
candidate artifact hash:
60c965a5f30dc9c04594c9b2323690e00d1b9fceb4b0041b974a7f60cad28fa4

qualification hash:
684456093ba78ca1849ddb4d73f7dff595a552ab5ecd54168c07910fe98d0931
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

This candidate had slightly positive pooled P&L and profit factor above 1, but strict qualification rejected it because both pooled and per-symbol drawdown exceeded the fixed threshold. No promotion, paper activation, or live action follows.
