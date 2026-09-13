# Trend-Pullback Continuation Research — 2026-09-13

## Decision

The fixed **trend-pullback continuation** hypothesis is **REJECTED** on a
separate February 2026 immutable confirmation scope. BTCUSDT, ETHUSDT, and
SOLUSDT each failed the average-return and profit-factor gates. No candidate was
admitted to the production registry or paper workflow.

This is negative research evidence. No threshold was relaxed, no parameter
sweep was run, and no retry was used to reverse the result.

## Hypothesis

Follow an established causal EMA trend when RSI indicates a pullback against
that trend:

```text
features:
  ema_slope lookback=96 shift=1
  rsi       lookback=14 shift=1

long entry:   ema_slope > 0 and rsi < 45
short entry:  ema_slope < 0 and rsi > 55
long exit:    ema_slope < 0 or rsi > 55
short exit:   ema_slope > 0 or rsi < 45
```

Both features were already supported by the causal evaluator. The candidate
used the existing `experimental` family label; no production feature code or
strategy schema change was required.

Fixed simulation settings:

```text
starting equity:         100
position fraction:       0.10
ATR lookback:            14
stop / take-profit:      1.5 / 3.0 ATR
trailing stop:           1.0 ATR
fee / adverse slippage:  0.0005 / 0.0001
```

## Evidence-scope selection

The previous `tail-20260913` scope was not reused because this thesis was
formulated after that scope's failed-breakout result. Local verification and
remote research-evidence roots contained no recorded February 2026 research
range. A separate immutable scope was therefore collected and bound before
evaluation.

```text
scope root:              research/immutable-data/scope-20260201-20260213
primary range:           [2026-01-31T22:20:00Z, 2026-02-13T00:00:00Z)
context range:           [2026-01-31T22:15:00Z, 2026-02-13T00:00:00Z)
OOS range:               [2026-02-01T00:00:00Z, 2026-02-13T00:00:00Z)
OOS warm-up:             20 prior 5m bars
symbols:                 BTCUSDT, ETHUSDT, SOLUSDT
```

Per symbol:

| Symbol | 5m | 15m | Mark-price 5m | Funding events |
|---|---:|---:|---:|---:|
| BTCUSDT | 3,476 | 1,159 | 3,476 | 36 |
| ETHUSDT | 3,476 | 1,159 | 3,476 | 36 |
| SOLUSDT | 3,476 | 1,159 | 3,476 | 36 |

```text
registry hash:           18c2ca46f48ea1e3d5fc84b0cd28dde5a6a0f4882dae3b9e04ff9337f9ece919
bundle hash:             9f9b65cc3a26b42c5af6d819a98cf523ec64b055f6fa78cd29cccdf4716c2a7d
filter snapshot hash:    bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb
lock hash:               487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264
source commit:           d63540a76469b8114de094920c1ba87f742e98e6
```

The scope collection used unsigned public REST only, no credentials, 25 public
requests, one attempt per page (`max_attempts=1`), and no fallback. All 13
components and their hashes were read back independently. The research runner
then used `data_source=cached_only` and `exchange_access=false`.

## OOS evaluation

The full primary frame, including the 20 prior warm-up bars, was materialized
before slicing the OOS interval. This preserves the causal EMA/RSI history while
keeping warm-up bars outside the evaluated rows and trades.

```text
windows per symbol:      12
bars per window:         288
total windows:           36
bars per symbol:         3,456
total trades:            261
```

Unchanged policy:

```text
minimum windows:         1
minimum trades:          5
minimum profit factor:   1.05
maximum drawdown:        15.0%
minimum average return:  0%
```

## Results

| Symbol | Windows | Trades | Net P&L | Profit factor | Average return | Worst drawdown |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 73 | -0.8458803534131799961699512902 | 0.4979784944869299440269640401 | -0.07049002945109833301416260758% | 0.2310298136318568176195711477% |
| ETHUSDT | 12 | 96 | -0.759658850718557539662394451 | 0.7050944830042718651377686295 | -0.06330490422654646163853287098% | 0.3799368392825428202949174858% |
| SOLUSDT | 12 | 92 | -0.082262203412365754914772846 | 0.9669596215709407749548457936 | -0.006855183617697146242897737125% | 0.2849646787149597458301042449% |
| **Pooled** | **36** | **261** | **-1.687801407544103290747118586** | **0.7499788983152695024439818244** | **-0.04688337243178064696519773858%** | **0.3799368392825428202949174858%** |

Failed gates:

```text
oos_average_return_min
oos_btcusdt_average_return_min
oos_btcusdt_profit_factor_min
oos_ethusdt_average_return_min
oos_ethusdt_profit_factor_min
oos_profit_factor_min
oos_solusdt_average_return_min
oos_solusdt_profit_factor_min
```

Drawdown, minimum-trade, and minimum-window checks passed, but all three
symbols failed the economic gates independently.

## Persisted evidence

```text
candidate:                cand-trend-pullback-continuation-20260913
candidate artifact hash:  de2d63a0b53fb060e38584bd1537703dd301e1b57b94d28812720152ccbff44b
aggregation hash:         6ee81f85a4cf682fa6e9e08a928db84de1335d0ec7d29c5d541a4c601d114c21
qualification hash:       1a90b6833f5134c8d1c8027fe6f8232ff9b66cc0c19086e8392ebd1575411dc4
qualification decision:   rejected
```

Evidence root:

```text
/opt/autonomous-futures-bot/research/strategy-evidence/trend-pullback-continuation-20260913
```

It contains exactly three immutable artifacts: candidate, OOS aggregation, and
qualification. A fresh typed readback verified both features, all expressions,
risk values, candidate/bundle/registry bindings, aggregation binding,
qualification decision, and fixed safety fields.

## Safety and runtime readback

```text
production candidate registry symbols: 0
new candidate admitted:                false
paper mutation:                        none
promotion state:                       unpromoted
paper activation:                      false
execution authority:                   false
research runner exchange access:       false
scheduler:                             active
paper service:                         active
research-related timers:               0
temporary runner/staging roots:         absent
```

No provider/LLM call, paper admission, testnet order, live order, restart, or
circuit-breaker bypass was performed.

## Verification

```text
scope collection readback:      passed
research chain readback:        passed
runtime safety readback:        passed
```

Existing repository quality was already verified at the preceding ref:

```text
full locked pytest:             2,210 passed
GitHub Actions quality:         success
post-report changed-path tests: 43 passed
```

Repository ref remains `69d89ca2f78d92a1e13bae914817e92d4ea34940` before this
report commit.

## Boundary

The trend-pullback continuation thesis is closed unchanged. Do not tune its
lookbacks, RSI thresholds, exits, costs, or gates to reverse this result. Keep
the candidate blocked. Further research requires a materially different thesis
and a separately verified immutable scope; qualification, paper admission,
testnet, and live activation remain blocked.

Recommended runtime for the next bounded phase: `gpt-5.6-luna-900k` via
`openai-codex`, Medium effort.
