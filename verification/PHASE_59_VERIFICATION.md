# Phase 59 Verification — XRPUSDT Bollinger source-loss rejection

## Runtime

```text
model: GPT-5.6 Terra
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 59 creates and evaluates one new, testing-only candidate on the fresh 365-day XRPUSDT immutable bundle, then immediately records its negative source evidence through the existing write-once rejection artifact.

```text
No network during research
No exchange request
No tuning/retry
No OOS run
No promotion
No paper activation
No order
```

## Candidate thesis

```text
candidate_id: cand-xrp-bollinger-001
creator_run_id: xrp-bollinger-research-001
seed: 59001
state: testing
family: experimental
feature: prior-bar Bollinger z-score(20), shift=1
long entry: z-score <= -2
short entry: z-score >= 2
```

This is a distinct mean-reversion thesis; it is not an RSI or EMA/ADX parameter variation.

```text
bundle_hash: f71e1288de701bccd015fb6152357f113acdef17d4985d018798da97e6de92f6
candidate_hash: f326df077471b8a155747b0d93bf10d9b28084d881a2ef4830c54f4fc55175b7
registry_hash: 7304974ef2a03ad2cf042b4cf7dbb343b633e29d9446e4e333ba904f9ab3ac6f
```

## Cached-only source result and rejection

Simulation configuration remains the explicit research baseline:

```text
starting equity: 100 USDT
position fraction: 50%
taker fee: 0.04% per side
adverse slippage: 0.01% per side
leverage: none
ATR protection: disabled
```

```text
trades: 1,740
final equity: 37.2091116573391649278041173 USDT
net P&L: -62.7908883426608350721958827 USDT
return: -62.79088834266083507219588270%
total fees: 40.91576145635639791264835401 USDT
total slippage: 10.22894024762723309139004782 USDT

decision: rejected
qualification_hash: fb52e4a46297bac70b1a1ba2cd920c2814fdae4631513c0e24c9dee5cfbbbb64
failed gates:
- source_net_pnl_nonnegative
- source_return_nonnegative
```

## Read-back and safety

```text
candidate/bundle binding: passed
registry/candidate binding: passed
rejection/candidate binding: passed
candidate state: testing
promotion_state=unpromoted
execution_authority=false
temporary runner removed: true
```

Remote artifacts remain outside Git:

```text
/var/lib/autonomous-futures/research/xrpusdt-365d/candidate-xrp-bollinger-001/
```

The three prior 90-day candidates/rejections are isolated from this fresh bundle. This candidate's rejection is only evidence against this exact Bollinger specification on this exact 365-day scope.

## Verification

```text
local locked suite: 644 passed
local ruff/format/mypy/lock: passed
remote source/static verification: unchanged from Phase56 and passed at the deployed source commit
```

Further XRP work must not tune the rejected RSI, trend, or Bollinger candidates. The next safe research decision is a genuinely new thesis or a different market/data-scope question.
