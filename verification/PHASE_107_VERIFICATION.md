# Phase 107 Verification — first successful Creator cached OOS evaluation

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

One fixed-harness real chain with the aligned feature set and bounded signal grammar:

```text
max_output_tokens=4096
DeepSeek Creator
→ strict Generator
→ write-once trial evidence
→ candidate artifact and registry
→ four explicit cached OOS windows
→ deterministic simulation
→ OOS aggregation
```

No qualification, promotion, paper, scheduler, or order path was invoked.

## Actual result

```text
provider requests: 1
Generator:          accepted
candidate:          cand-doge-trend-breakout-001
trial:              candidate_accepted_for_testing
OOS status:         evaluated
windows:            4
trades:             699
```

Aggregated cached-only result:

```text
pooled net P&L:     -7.0396458735139669894125653 USDT
profit factor:      0.9743662456128034802007724563
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-006
```

Read-back:

```text
candidate artifact hash:
ad9d1ce3fabc4cd5fb73f912522eb8a62abf2cc55a0d0d480874653c41b6a0a3

trial evidence hash:
6024ced44ec7b8e2c092578ca3b0dcab2262e3c30fca82c832951b75073f3eed

bundle hash:
30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3

dataset registry hash:
17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
```

## Interpretation

This is a real cached OOS result, not a qualification result. The negative pooled P&L and profit factor below one are evidence against immediate qualification. No automatic rejection/promotion was performed by this smoke.

## Safety and cleanup

```text
candidate state: testing
promotion_state=unpromoted
paper_activation=false
execution_authority=false
exchange_access=false
qualification artifacts: 0
orders: 0
temporary systemd unit: removed
temporary source root: removed
local temporary files: deleted
project timers: 0
credential artifact: retained encrypted, root:root 600
```

## Verification

```text
local full suite before smoke: 676 passed
local Ruff/format/mypy/lock: passed
remote evidence read-back: passed
```

Next boundary: pass this verified cached OOS aggregation through the existing strict Creator qualification handoff and persist the resulting rejected evidence, without promotion or paper activation.
