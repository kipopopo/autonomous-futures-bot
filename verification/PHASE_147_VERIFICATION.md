# Phase 147 Verification — full latest-lineage Critic-guided research chain

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Run the full corrected latest-lineage chain using the current Critic evidence and complete historical forbidden-ID snapshot:

```text
latest Critic evidence
→ Creator revision with six forbidden prior IDs
→ candidate/trial persistence
→ four cached OOS windows
→ strict qualification
```

## Actual result

```text
source candidate:       cand-doge-breakout-001
critic evidence:        critic-evidence-012
forbidden prior IDs:    6
provider requests:      1
candidate:              cand-doge-regime-breakout-002
trial:                  accepted_for_testing
candidate state:        testing
OOS windows:            4
trades:                 631
qualification:          rejected
failed gates:           6
```

OOS aggregation:

```text
pooled net P&L:         -15.7155338519787390476900905 USDT
pooled profit factor:   0.9389614581346027430852725486
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-014
```

Bindings:

```text
candidate artifact hash:
209eb2004db11624e712df8e540160e7d69f48784fab31cb6bdd79f68533bd99

qualification hash:
95a347c021ff215986dae7026902af7738a6cdd84832c07f4177c202678bf33c

bundle hash:
30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3

dataset registry hash:
17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
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
temporary systemd unit: removed
temporary source root: removed
local temporary files: deleted
project timers: 0
```

## Verification

```text
full suite before chain: 698 passed
Ruff/format/mypy/lock: passed
remote candidate/trial/OOS/qualification readback: passed
lineage guard source parity: passed
```

## Conclusion

The latest Critic evidence now drives a complete new Creator research attempt without repeating known historical candidate IDs. The new candidate was persisted, evaluated, and strictly rejected on negative evidence. No promotion, paper activation, or live action follows.
