# Phase 56 Verification — XRPUSDT high-ADX trend testing candidate

## Runtime

```text
model: GPT-5.6 Terra
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 56 tests one materially different, deterministic XRPUSDT hypothesis against the exact Phase52 cached bundle.

```text
No network
No exchange request
No tuning/retry
No OOS run
No qualification
No promotion
No paper activation
No order
```

## Candidate thesis

```text
candidate_id: cand-xrp-trend-001
creator_run_id: xrp-trend-research-001
seed: 56001
state: testing
family: experimental
symbol: XRPUSDT
feature contract: prior-bar 5m EMA slope(48) + ADX(14), shift=1
long entry: ADX >= 25 and EMA slope > 0
short entry: ADX >= 25 and EMA slope < 0
```

This is a fixed high-ADX trend-continuation hypothesis, distinct from the rejected RSI mean-reversion candidate. It does not claim to use 15m context; its signals are current supported, prior-bar 5m features.

Immutable bindings:

```text
bundle_hash: 68f2962b8a4aef3f8c0fd301b01e3043afce89f4686aeb9c0017046e3fad6ded
candidate_hash: 6eebd5a81cd367a6affbde7368b376e44da1814194bd7cb02883cd4f44af327a
registry_hash: 72e45c749a3f42d2f6a5dde9741a13e4b2c3d438d62f831299d1f4f3ab5c371c
```

## Cached-only source simulation

```text
starting equity: 100 USDT (research baseline, not account balance)
position fraction: 50%
taker fee: 0.04% per side
adverse slippage: 0.01% per side
leverage: none
ATR protection: disabled
```

Actual result:

```text
trades: 325
final equity: 88.59866912722064630400276907 USDT
total fees: 11.27351140279995517200735555 USDT
total slippage cost: 2.818377877605572869263582341 USDT
```

This is loss-making source evidence. It is not qualified and must not proceed to OOS, paper, or live activity.

## Read-back and safety

```text
candidate bundle binding: passed
registry entry binding: passed
candidate state: testing
temporary runner removed: true
paper_activation=false
execution_authority=false
exchange_access=false
```

Remote artifacts remain outside Git:

```text
/var/lib/autonomous-futures/research/xrpusdt-90d/candidate-xrp-trend-001/
```

## Verification

```text
local locked suite: 644 passed
local ruff/format/mypy/lock: passed
remote suite: 636 passed
remote ruff/format/mypy/lock: passed
```

A later phase may persist a source-loss rejection. It must not tune this candidate or claim broader XRP strategy failure.
