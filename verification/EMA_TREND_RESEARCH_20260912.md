# EMA Trend Family Research — 2026-09-12

## Decision

The predeclared pure EMA trend hypothesis is **REJECTED** on the immutable
multi-symbol cached scope. The candidate remains testing-only and was not added
to the production candidate registry or paper workflow.

```text
schema family label:       experimental
thesis:                    pure EMA trend-following
feature:                   ema_slope
lookback / shift:          20 / 1
long entry:                ema_slope > 0
short entry:               ema_slope < 0
long exit:                 ema_slope < 0
short exit:                ema_slope > 0
```

The `experimental` label is intentional: the current strict `StrategySpec`
enum does not contain a pure-EMA family, and the real thesis is preserved in
the candidate ID, feature, expressions, run ID, and this report. No schema
widening was used for a one-cohort probe.

## Scope and fixed gates

```text
bundle hash:               108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:             ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
symbols:                   BTCUSDT, ETHUSDT, SOLUSDT
OOS windows/symbol:       12 × 288 bars
OOS windows total:         36
accounting:                equity 100.00; position fraction 0.10
fees / slippage:           0.0005 / 0.0001
ATR stop/target/trail:     1.5 / 3.0 / 1.0
```

The OOS range is the established final 3,456 cached 5m bars per symbol. EMA
features were calculated from the full chronological cached frame with
`shift=1`, then OOS windows were sliced for simulation. No current decision
candle's close was used for its own EMA slope.

Unchanged strategy-family qualification gates:

```text
minimum windows:           1
minimum trades:            5
minimum profit factor:     1.05
maximum drawdown:          15.0%
minimum average return:    0%
```

## Results

| Symbol | Windows | Trades | Net P&L | Profit factor | Average return | Worst drawdown |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 347 | -3.866554533669341533995245700 | 0.1794274152339219633981776276 | -0.3222128778057784611662704751% | 0.4955192814793127532713869700% |
| ETHUSDT | 12 | 364 | -3.985533442171370319466538510 | 0.2703143328155538658083496573 | -0.3321277868476141932888782093% | 0.5215742245399351413591641300% |
| SOLUSDT | 12 | 371 | -4.718094203779563592431370589 | 0.1974930568487440569471489283 | -0.3931745169816302993692808824% | 0.6431057582911656931895384879% |

All three symbols passed the drawdown, minimum-trade, and minimum-window
gates, but all failed profit factor and average return. The candidate was
therefore rejected by the existing strict AND qualification logic.

## Persisted evidence

```text
candidate:                 cand-ema-trend-20260912
candidate artifact hash:   c4584588b23654709d08adb0e572a1022a24cd9a9e78786bc3d5fc007354cb81
creator run:               run-ema-trend-20260912
evaluator run:             ema-trend-oos-20260912
evaluator version:         ema-trend-v1-oos
aggregation hash:          fd28e547d5450f822bfc45c1e4ac6b7783ce98728942d4da4c5f91797e20e348
qualification hash:        1841ce72220ac3cc9cc261d766708b3a19bfcf9ff94f8439e4882d6236ef28dd
qualification decision:    rejected
qualification policy:      policy-strategy-family-oos-standard
```

Evidence root:

```text
/opt/autonomous-futures-bot/research/strategy-evidence/ema-trend-20260912
```

It contains only the isolated candidate artifact, persisted walk-forward
aggregation, and qualification artifact. No production candidate registry
entry was created.

A fresh remote process read back all three typed artifacts, rechecked candidate,
bundle, registry, OOS window count, strategy expressions, aggregation binding,
qualification binding, and safety fields. The idempotent reread returned the
same hashes without a second evaluation.

## Safety and runtime

```text
data source:               cached_only
exchange access:           false
provider/LLM calls:        none
candidate registry change: none
paper mutation:            none
qualification decision:    rejected
promotion state:           unpromoted
execution authority:       false
scheduler:                 active
paper service:             active
research-related timers:   0
related transient units:   0
temporary roots:            absent
testnet/live orders:        none
```

## Failure handling

The initial runner completed persistence but failed only while printing the
persisted aggregation envelope as if it were the inner aggregation object. No
artifact was lost and no second evaluation was run. The corrected idempotent
runner read the existing candidate, aggregation, and qualification artifacts
and completed successfully.

## Verification

```text
feature/evaluator/qualification regression: 29 passed
ruff check:                                  passed
ruff format --check:                         passed
mypy:                                        passed
uv lock --check:                             passed
git diff --check:                            passed
remote fresh typed readback:                 passed
remote runtime-state readback:               passed
```

## Boundary

This hypothesis is closed for this immutable scope. Do not retry EMA parameters,
relax gates, or add it to paper. Any further research requires a materially
new, explicitly falsifiable thesis; qualification, promotion, testnet, and live
execution remain blocked.
