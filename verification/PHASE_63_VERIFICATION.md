# Phase 63 Verification — DOGEUSDT RSI source-loss rejection

## Runtime

```text
model: GPT-5.6 Luna
provider: OpenAI Codex
effort: Medium
```

## Scope

Phase 63 persists the existing qualification-contract rejection artifact for `cand-doge-rsi-001`, based on a fresh cached-only recomputation over the DOGEUSDT 365-day bundle.

```text
No network
No exchange request
No OOS run
No tuning
No promotion
No paper activation
No order
```

## Rejection evidence

```text
candidate_id: cand-doge-rsi-001
candidate_hash: b2e37711abdeddf034ee6db607e05cd9eeeb705014538235ffad3f8186406a5e
bundle_hash: 30a365020f816f090d2ed66163dbda5f3a2a4490e1b283c6385b4b07cf27ccc3

decision: rejected
qualification_hash: af0cfea94204169536f5fe9aab8a251b420207f41d30b23cdb6660871b8fc97c
source: creator_evaluator

final equity: 56.9252476191262359627341933 USDT
net P&L: -43.0747523808737640372658067 USDT
return: -43.07475238087376403726580670%
trades: 553
failed gates:
- source_net_pnl_nonnegative
- source_return_nonnegative
```

Artifact path:

```text
/var/lib/autonomous-futures/research/dogeusdt-365d/candidate-doge-rsi-001/cand-doge-rsi-001.source-rejection.json
```

## Read-back and safety

```text
bundle/candidate binding: passed
registry/candidate binding: passed
rejection/candidate binding: passed
candidate state: testing (unchanged)
temporary runner removed: true
promotion_state=unpromoted
execution_authority=false
paper_activation=false
```

This rejects only the fixed DOGE RSI specification on this fixed 365-day scope. No general DOGE strategy conclusion is inferred.

## Verification

```text
local locked suite: 644 passed
local ruff/format/mypy/lock: passed
remote source/static verification: unchanged from Phase56 and passed at the deployed source commit
```

Further work requires a materially different DOGE thesis; RSI tuning and OOS follow-up are skipped.
