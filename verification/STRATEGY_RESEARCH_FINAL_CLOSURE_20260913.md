# Strategy Research Final Closure and Readiness Gate — 2026-09-13

## Decision

The current autonomous strategy-research cycle is **CLOSED / NOT LIVE-READY**.
All listed multi-symbol strategy hypotheses failed the unchanged economic OOS
policy, and both recorded learner paths failed their quality policies. There is
no portable qualified candidate for paper admission, testnet, or live use.

This report is a read-only consolidation of existing evidence plus the latest
VWAP result. It does not change candidate, paper, scheduler, exchange, or live
state.

## Policy boundary

The unchanged strategy-family OOS policy is:

```text
required symbols:          BTCUSDT, ETHUSDT, SOLUSDT
minimum OOS windows:        1
minimum trades:             5
minimum profit factor:      1.05
minimum average return:     0%
maximum drawdown:           15.0%
```

Research simulations use the existing Decimal accounting contract, starting
equity `100`, position fraction `0.10`, taker fee `0.0005`, and adverse
slippage `0.0001`, with risk parameters explicitly bound by each candidate.
No threshold was relaxed and no auto-tuning or blind seed/parameter retry was
used to manufacture a pass.

## Consolidated strategy evidence

| Hypothesis/family | Evidence scope | Result |
|---|---|---|
| Bollinger-z-score range mean reversion | Existing immutable cached scope; final 3,456-bar OOS tail | BTC/ETH/SOL failed net P&L, profit factor, and average return |
| Earlier Bollinger/RSI range variants | Existing immutable cached scope | No portable multi-symbol pass; isolated SOL RSI indicator result was not admitted |
| Volume-confirmed momentum | Existing immutable cached scope; 36 OOS windows | BTC/ETH/SOL failed fixed economic indicator |
| Donchian channel breakout | Existing immutable cached scope; 36 OOS windows | BTC/ETH/SOL failed net P&L, profit factor, and average return |
| Volatility-compression breakout | Existing immutable cached scope | BTC/ETH/SOL failed fixed indicator |
| ADX/regime trend | Existing immutable cached scope | BTC/ETH/SOL failed fixed indicator |
| Pure EMA trend | Existing immutable cached scope; 36 OOS windows | BTC/ETH/SOL failed profit factor and average return |
| Failed-breakout re-entry | Fresh `tail-20260913` scope; 36 OOS windows | BTC/ETH/SOL failed economic gates; pooled net P&L `-6.912938782084100829351451156`, PF `0.3302741920053343831` |
| Trend-pullback continuation | Fresh February scope; 36 OOS windows | BTC/ETH/SOL failed profit factor and average return; pooled net P&L `-1.687801407544103290747118586`, PF `0.7499788983152695024` |
| VWAP reclaim reversal | Fresh March scope; 36 OOS windows | BTC/ETH/SOL failed profit factor and average return; pooled net P&L `-14.87086508119381572665620932`, PF `0.3908938617473068696` |

The exact parameters, scope hashes, per-symbol metrics, failed gate IDs, and
readback evidence remain in the linked reports:

```text
verification/RANGE_MEAN_REVERSION_RESEARCH_20260912.md
verification/VOLUME_CONFIRMED_MOMENTUM_RESEARCH_20260912.md
verification/DONCHIAN_CHANNEL_BREAKOUT_RESEARCH_20260912.md
verification/STRATEGY_FAMILY_RESEARCH_CLOSURE_20260909.md
verification/EMA_TREND_RESEARCH_20260912.md
verification/FAILED_BREAKOUT_REENTRY_RESEARCH_20260913.md
verification/TREND_PULLBACK_CONTINUATION_RESEARCH_20260913.md
verification/VWAP_RECLAIM_REVERSAL_RESEARCH_20260913.md
```

The February and March strategy cohorts used separate immutable bundle and
registry hashes. The failed-breakout tail was not reused for selecting the
later cohorts.

## Learner evidence

Both recorded learner paths are failed quality evidence:

```text
linear_next_return:  metric-quality policy FAILED
next_bar_direction:  untouched chronological holdout FAILED
```

The directional holdout failed net P&L and profit-factor gates independently for
BTCUSDT, ETHUSDT, and SOLUSDT. Learner evidence does not override deterministic
strategy qualification and does not authorize paper, testnet, or live use.

## Root-cause status

A bounded simulator/data audit was completed before the later strategy probes.
It found no detected defect in:

```text
feature causality/leakage
Decimal simulator/accounting
strategy-exit timing
OOS aggregation
aggregation hash recomputation
current cached-data lineage
```

The audit also identified a historical scope-document mismatch: an older report
referenced `378,211` rows/symbol while the later immutable bundle contained
`10,434` rows/symbol. The scopes were not mixed. Negative results therefore
remain valid evidence for their stated scopes; they are not being reinterpreted
as an unverified simulator failure.

## Qualification and promotion gate

```text
portable qualified candidate:       false
candidate artifacts qualified:     none
production candidate registry:     0 admitted IDs
paper admission:                   blocked
promotion state:                  unpromoted
execution authority:              false
testnet approval/evidence:         absent
live activation:                  false
```

The most recent persistent candidates—failed-breakout, trend-pullback, and
VWAP—are isolated testing/evidence artifacts outside the production candidate
registry. Their qualification decisions are all `rejected` and their candidate
IDs are absent from the production registry.

## Current runtime readiness

Fresh status readback at this closure:

```text
scheduler service:                 active
paper service:                    active
paper circuit-breaker sidecar:    HALTED
paper daemon health:              HALTED
research-related timers:          0
temporary research roots:          absent
paper candidate registry:         empty
submitted orders:                 none from this research work
resume request:                   none
complete ResumeEvidence:          not established
```

The current `HALTED` sidecar/health state is authoritative for this gate. An
older post-restart report recorded `THROTTLED`; the current readback is not
silently normalized back to that older state.

No restart, force-close, force trade, circuit-breaker bypass, resume request,
testnet action, live order, or provider/LLM call was performed for this closure.

## Verification and delivery

```text
strategy reports read/reconciled:       passed
learner reports read/reconciled:        passed
production registry readback:           passed
current paper health readback:          passed
current breaker state readback:         HALTED
source worktree before report:          clean
```

The latest VWAP implementation/report was already verified with focused
research regressions, static gates, fresh remote evidence readback, and the
canonical GitHub quality workflow. This closure adds documentation only; it
does not alter production Python or paper code.

## Next boundary

Do not run another arbitrary strategy family, reuse a prior holdout, change
thresholds after observing outcomes, or treat a negative research result as a
reason to activate paper/testnet/live.

The next legitimate work must be one of these explicitly bounded choices:

1. **Stop strategy research** and retain the current evidence closure; or
2. **Predeclare one materially different, falsifiable thesis** and bind it to a
   separately justified immutable scope; or
3. **Handle paper recovery as a separate safety task**, beginning with
   read-only reconciliation and complete operator-approved `ResumeEvidence`.

Paper recovery is not implied by this report. Testnet/live activation remains
blocked until a portable qualified candidate, healthy paper state, explicit
approvals, fresh reconciliation, and all required safety gates exist.

Recommended runtime for any next bounded evidence-only phase:
`gpt-5.6-luna-900k` via `openai-codex`, Medium effort.
