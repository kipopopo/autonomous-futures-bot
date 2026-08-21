# Phase 62 Verification — DOGEUSDT RSI testing candidate

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 62 creates one independent DOGEUSDT testing candidate bound to the fresh Phase61 365-day bundle and runs one cached-only source simulation.

```text
No network during research
No exchange request
No OOS run
No qualification
No promotion
No paper activation
No order
```

## Candidate

```text
candidate_id: cand-doge-rsi-001
creator_run_id: doge-rsi-research-001
seed: 62001
state: testing
family: experimental
symbol: DOGEUSDT
feature: prior-bar RSI(14), shift=1
long entry: RSI <= 30
short entry: RSI >= 70
```

Immutable bindings:

```text
bundle_hash: 30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3
candidate_hash: b2e37711abdeddf034ee6db607e05cd9eeeb705014538235ffad3f8186406a5e
registry_hash: d66ddafd21034188a899d97515b1dc1494f6f743860ed411ad33cd965c3fb5e6
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
trades: 553
final equity: 56.9252476191262359627341933 USDT
net P&L: -43.0747523808737640372658067 USDT
return: -43.0747523808737640372658067%
total fees: 16.55769908795756234976022943 USDT
total slippage cost: 4.139424548213103140409071886 USDT
```

This is negative source evidence only; it is not a DOGE qualification result.

## Read-back and safety

```text
candidate/bundle binding: passed
registry/candidate binding: passed
candidate state: testing
temporary runner removed: true
promotion_state=unpromoted
execution_authority=false
paper_activation=false
exchange_access=false
```

Remote artifact root:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/candidate-doge-rsi-001/
```

## Verification

```text
local locked suite: 644 passed
local ruff/format/mypy/lock: passed
remote source/static verification: unchanged from Phase56 and passed at the deployed source commit
```

The next bounded decision is whether to record a source-loss rejection. No RSI tuning or OOS run is justified from this result alone.
