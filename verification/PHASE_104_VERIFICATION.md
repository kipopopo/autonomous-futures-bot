# Phase 104 Verification — larger-budget accepted Creator persistence

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
embedded provider model: deepseek-v4-flash
```

## Scope

One fixed-harness real chain with the measured output truncation change:

```text
max_output_tokens=4096
DeepSeek Creator
→ strict Generator
→ write-once trial evidence
→ candidate artifact and registry
→ four-window cached OOS handoff
```

No qualification, promotion, paper, scheduler, or order path was invoked.

## Actual result

```text
provider requests: 1
provider payload:   accepted JSON
Generator:          accepted
candidate:          cand-doge-014
trial:              candidate_accepted_for_testing
cached OOS:         blocked
reason:             cached_evaluation_failed
windows:            0
trades:             0
```

Persisted remote root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/creator-batch-20260822-005
```

Read-back:

```text
candidate artifact hash:
59116faafd65b2782f53e3fe96eb21d503d17abba1d06f685a794a5a144e7d19

bundle hash:
30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3

dataset registry hash:
17f140c77f1911f26dd63bd0d20144149dab7cd424a3760f4b7797d10b61375e
```

## Interpretation

The larger output budget fixed the measured provider truncation (`finish_reason=length`). A real proposal now passed Creator schema validation and was persisted correctly. Cached OOS still returned the existing generic `cached_evaluation_failed` boundary; no OOS metrics were fabricated.

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
local full suite before smoke: 675 passed
local Ruff/format/mypy/lock: passed
remote evidence read-back: passed
```

Next boundary: diagnose the deterministic cached OOS failure for `cand-doge-014`; do not qualify or promote it.
