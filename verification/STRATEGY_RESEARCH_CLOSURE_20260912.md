# Strategy Research Closure — 2026-09-12

## Decision

The current cached strategy-research cycle is **CLOSED / NOT LIVE-READY**.
Every tested multi-symbol strategy hypothesis failed the unchanged OOS policy
on at least one required economic gate. No candidate is eligible for paper,
testnet, live, or promotion.

This closure is evidence-only. It does not change candidate state, paper state,
execution authority, or live activation.

## Fixed scope and policy

```text
bundle:                     108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry:                   ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
symbols:                    BTCUSDT, ETHUSDT, SOLUSDT
OOS layout:                 final 3,456 5m bars/symbol; 12 × 288 windows
minimum windows:            1
minimum trades:             5
minimum profit factor:      1.05
maximum drawdown:           15.0%
minimum average return:     0%
accounting:                 equity 100.00; position fraction 0.10
fees / slippage:            0.0005 / 0.0001
```

No threshold was relaxed and no blind parameter/seed retry was used.

## Rejected strategy hypotheses

| Hypothesis | Evidence | Result |
|---|---|---|
| Bollinger-z-score range mean reversion | `RANGE_MEAN_REVERSION_RESEARCH_20260912.md` | BTC/ETH/SOL failed net P&L, PF, and average return |
| Volume-confirmed momentum | `VOLUME_CONFIRMED_MOMENTUM_RESEARCH_20260912.md` | BTC/ETH/SOL failed fixed indicator |
| Donchian channel breakout | `DONCHIAN_CHANNEL_BREAKOUT_RESEARCH_20260912.md` | BTC/ETH/SOL failed net P&L, PF, and average return |
| Volatility-compression breakout | `STRATEGY_FAMILY_RESEARCH_CLOSURE_20260909.md` | BTC/ETH/SOL failed fixed indicator |
| ADX/regime trend | `STRATEGY_FAMILY_RESEARCH_CLOSURE_20260909.md` | BTC/ETH/SOL failed fixed indicator |
| Pure EMA trend, `ema_slope(20,1)` | `EMA_TREND_RESEARCH_20260912.md` | BTC/ETH/SOL rejected; 8 qualification gates failed |

The EMA cohort is the latest persisted strategy candidate:

```text
candidate:                  cand-ema-trend-20260912
candidate artifact hash:    c4584588b23654709d08adb0e572a1022a24cd9a9e78786bc3d5fc007354cb81
aggregation hash:           fd28e547d5450f822bfc45c1e4ac6b7783ce98728942d4da4c5f91797e20e348
qualification hash:         1841ce72220ac3cc9cc261d766708b3a19bfcf9ff94f8439e4882d6236ef28dd
decision:                   rejected
```

The isolated positive SOL RSI result in the older closure evidence was not
portable: BTC and ETH failed the same hypothesis. It was not admitted.

## Learner plane

The learner also failed independently:

```text
linear_next_return metric-quality decision:  FAILED
next_bar_direction holdout decision:         FAILED
```

The latest directional learner holdout was negative for all three symbols;
its full evidence remains at `LEARNER_DIRECTION_HOLDOUT_20260912.md`. Critic
feedback and learner artifacts are research evidence only and do not override
failed deterministic policy decisions.

## Runtime and safety readback

```text
research output:             outside production candidate registry
candidate registry change:   none
paper mutation:              none
scheduler:                   active
paper service:               active
research-related timers:     0
related transient units:     0
temporary roots:              absent
execution authority:         false
promotion state:             unpromoted
paper activation:            false
testnet/live orders:          none
provider/exchange calls:     none for this closure
```

## Verified delivery

```text
latest implementation/report ref:  83ce80dfd9daaba624a2b0745d748d58a51eac3e
local post-commit regression:       29 passed
Ruff / format / mypy / lock / diff: passed
EMA fresh typed readback:           passed
EMA runtime-state readback:         passed
```

## Boundary

Stop the current strategy-research cycle here. Do not rerun these hypotheses,
change thresholds, tune parameters, or admit the testing artifacts to paper.
Resume research only with a materially different, explicitly falsifiable
thesis and a new immutable evidence scope or an explicitly justified root-cause
correction. Live activation remains blocked.
