# Phase 117 Verification — revision cached OOS success

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

One complete feedback-driven revision chain with the final prompt contract:

```text
persisted rejected qualification feedback
→ revision Creator
→ accepted new candidate
→ write-once trial/candidate registry
→ four cached OOS windows
```

Strict qualification remains a separate next boundary.

## Actual result

```text
source candidate:       cand-doge-trend-breakout-001
revision candidate:     cand-doge-meanrev-002
provider requests:      1
Generator:              accepted
trial:                  candidate_accepted_for_testing
OOS status:             evaluated
windows:                4
trades:                 2
pooled net P&L:         -20.22816317282546609228450918 USDT
pooled profit factor:   0E+26
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-009
```

Read-back candidate artifact hash:

```text
912840681bae4354b530a25c0bc9b0f513913ec74b7f3acbf4764a673f37dbcb
```

## Interpretation

The revision is executable through the deterministic cached evaluator, but evidence is weak and negative: only two trades, negative pooled P&L, and zero profit factor. This is not a quality pass and no promotion/activation inference is allowed.

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
local full suite before smoke: 680 passed
local Ruff/format/mypy/lock: passed
remote evidence read-back: passed
```

Next boundary: pass `cand-doge-meanrev-002` through strict qualification and persist the expected rejected evidence.
