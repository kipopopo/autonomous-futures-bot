# Phase 108 Verification — strict Creator qualification evidence

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

Rebuild the verified four-window cached OOS aggregation for `cand-doge-trend-breakout-001`, pass it through the existing strict walk-forward qualification policy, and persist the qualification evidence.

```text
persisted candidate
→ cached OOS aggregation
→ strict qualification gates
→ write-once qualification artifact
```

No provider call, candidate mutation, promotion, paper activation, scheduler, or order path was used.

## Actual result

```text
candidate:             cand-doge-trend-breakout-001
cached status:          evaluated
windows evaluated:      4
qualification decision: rejected
qualification count:    1
blocked candidates:     0
failures:               0
provider requests:      0
```

Persisted artifact:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-006/qualification/qualification/cand-doge-trend-breakout-001.json
```

Read-back bindings:

```text
candidate artifact hash:
ad9d1ce3fabc4cd5fb73f912522eb8a62abf2cc55a0d0d480874653c41b6a0a3

bundle hash:
30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3

dataset registry hash:
17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e

oos aggregation hash:
9b6b18aab25ea95149e222696334bcc1b83ab33023a098713219692c5daf4fc8

qualification hash:
713e3d0a4fa606fa31639308df883bf0552d744448fde6bf05a4113ba08a41ec
```

Gate result:

```text
gates: 10
passed: 4
failed: 6
failed reasons:
- oos_average_return_below_threshold
- oos_symbol_average_return_below_threshold
- oos_symbol_drawdown_above_threshold
- oos_symbol_profit_factor_below_threshold
- oos_drawdown_above_threshold
- oos_profit_factor_below_threshold
```

## Safety

```text
candidate state: testing
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
paper/live orders: 0
qualification artifact: rejected evidence only
```

## Cleanup

```text
temporary systemd unit: removed
temporary source root: removed
local temporary files: deleted
project timers: 0
credential artifact: retained encrypted, root:root 600
```

## Conclusion

The first accepted real Creator candidate now completed the full research evidence path through strict qualification and was rejected by deterministic OOS gates. This is not a promotion or paper-activation decision. No automatic retry, tuning, or activation was performed.

## Verification

```text
local full suite before qualification smoke: 676 passed
local Ruff/format/mypy/lock: passed
remote qualification artifact read-back: passed
```
