# VWAP Reclaim Reversal Research — 2026-09-13

## Decision

The fixed **VWAP reclaim reversal** hypothesis is **REJECTED** on a separate
March 2026 immutable confirmation scope. BTCUSDT, ETHUSDT, and SOLUSDT each
failed the average-return and profit-factor gates. No candidate was admitted to
the production registry or paper workflow.

This is negative research evidence. No threshold was relaxed, no parameter sweep
was run, and no retry was used to reverse the result.

## Hypothesis

Trade a closed-candle rejection/reclaim of a volume-weighted price level:

```text
feature: vwap_reclaim lookback=20 shift=1

rolling VWAP: sum(typical_price * volume) / sum(volume)
typical_price: (high + low + close) / 3
long event:    low < VWAP and close > VWAP
short event:   high > VWAP and close < VWAP
```

The rolling calculation uses the current completed candle and the preceding
19 completed candles. The feature is shifted by one bar, so an event observed
on candle `t` can only produce an entry signal for candle `t+1` open. A zero
volume denominator remains unknown; missing volume fails closed.

The thesis is materially different from the previously tested EMA trend,
trend-pullback, Donchian, Bollinger, volume-momentum, failed-breakout, and
range-boundary mechanisms: its reference level is volume-weighted fair value
and its event is a VWAP reclaim/rejection.

Fixed signal expressions:

```text
long entry:   vwap_reclaim > 0
short entry:  vwap_reclaim < 0
long exit:    vwap_reclaim < 0
short exit:   vwap_reclaim > 0
```

Fixed simulation settings:

```text
starting equity:         100
position fraction:       0.10
ATR lookback:            14
stop / take-profit:      2.0 / 1.0 ATR
trailing stop:           0 ATR (disabled)
fee / adverse slippage:  0.0005 / 0.0001
```

All values were fixed before observing the outcome.

## Implementation and causality verification

A minimal causal feature slice was added to the existing contract/evaluator:

```text
src/autonomous_futures/domain/contracts.py
src/autonomous_futures/research/feature_signals.py
tests/unit/test_feature_signals.py
```

The feature test covers:

- prior completed-bar availability and next-open event timing;
- current-candle mutation not changing the same-row feature;
- missing volume rejection; and
- zero-volume VWAP remaining `NaN` with no emitted signal.

```text
feature tests: 19 passed in 0.97s
Ruff lint:     passed
Ruff format:   passed
mypy:          passed
lock check:    passed
git diff:      passed
source commit: 179a87b459f144ac13f6ba827ee527ded9e3dacd
```

## Evidence-scope selection

The previous February scope was not reused. Local and remote research evidence
roots contained no recorded March 2026 research scope before collection. A
separate immutable scope was collected and bound before evaluation.

```text
scope root:              research/immutable-data/scope-20260301-20260313
primary range:           [2026-02-28T22:20:00Z, 2026-03-13T00:00:00Z)
context range:           [2026-02-28T22:15:00Z, 2026-03-13T00:00:00Z)
OOS range:               [2026-03-01T00:00:00Z, 2026-03-13T00:00:00Z)
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
registry hash:           c87a24bce76d719453297d69d462e1c0ffe9f4d2be87bae4245f7a5f002c5836
bundle hash:             59604f0ccba814a9d99fc4dc7e6decb58f015c8158a9eff242d1fb78bbb9051e
filter snapshot hash:    bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb
lock hash:               sha256:487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264
source commit:           179a87b459f144ac13f6ba827ee527ded9e3dacd
```

The scope used the established unsigned public-data adapters, one attempt per
page (`max_attempts=1`), no fallback, and no credentials. All 13 components and
their hashes were independently read back. The research runner then used
`data_source=cached_only` and `exchange_access=false`.

The first collection attempt stopped during its own pre-publication readback
due to a collector argument error. The final root and checkpoints were verified
absent, the call was corrected, and the same fixed scope was collected once
successfully. No partial artifact was accepted.

## OOS evaluation

The complete primary frame, including the 20 prior warm-up bars, was
materialized before slicing the OOS interval. This preserves the causal
lookback while keeping warm-up bars outside evaluated rows and trades.

```text
windows per symbol:      12
bars per window:         288
total windows:            36
bars per symbol:          3,456
total trades:             1,132
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
| BTCUSDT | 12 | 354 | -4.460789819596650835366953695 | 0.3316803566584878841118085187 | -0.3717324849663875696139128078% | 0.5939750284950610057802942400% |
| ETHUSDT | 12 | 386 | -5.313095370396143144480364723 | 0.3865849428148253259094507489 | -0.4427579475330119287066970602% | 0.8586089760002673436403588969% |
| SOLUSDT | 12 | 392 | -5.096979891201021746808890902 | 0.4385414931611908607052477606 | -0.4247483242667518122340742419% | 0.7910711398028087621035951153% |
| **Pooled** | **36** | **1,132** | **-14.87086508119381572665620932** | **0.3908938617473068695593660460** | **-0.4130795855887171035182280372%** | **0.8586089760002673436403588969%** |

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
candidate:                cand-vwap-reclaim-reversal-20260913
candidate artifact hash:  5ef20b4c2cfcec6fb3ec7f80055687de040fcb88cbba77608fadc7e18321b878
aggregation hash:         279d0427868d5174cab07941e4aa4308b9af0fcb6278f5e79bad1d221d123d68
qualification hash:       39d3a16cd85258783879810ad98c6ba0db6d3ec5cc11100547cbbdbf8de69afa
qualification decision:   rejected
```

Evidence root:

```text
/opt/autonomous-futures-bot/research/strategy-evidence/vwap-reclaim-reversal-20260913
```

It contains exactly three immutable artifacts: candidate, OOS aggregation, and
qualification. A fresh typed readback verified the VWAP feature, expressions,
risk values, bundle/registry bindings, aggregation binding, qualification
decision, and fixed safety fields.

## Safety and runtime readback

```text
production candidate registry: 0 admitted IDs
VWAP candidate in registry:    false
new candidate admitted:        false
paper mutation:                none
promotion state:               unpromoted
paper activation:              false
execution authority:           false
research runner exchange:      false
scheduler:                     active
paper service:                 active
research-related timers:       0
temporary runner roots:         absent
production mutation:           none
```

No provider/LLM call, paper admission, testnet order, live order, restart, or
circuit-breaker bypass was performed.

## Verification

```text
scope collection readback:      passed
research chain readback:        passed
production registry readback:   passed
runtime safety readback:        passed
```

The source commit was pushed before collection. Its quality workflow was still
being observed at report preparation; the report commit will trigger the normal
repository quality workflow again.

## Boundary

The VWAP reclaim reversal thesis is closed unchanged. Keep this candidate
blocked. Do not tune its lookback, reclaim rules, risk, costs, or qualification
gates to reverse the result. Further research requires a materially different
falsifiable thesis and a separately verified immutable scope; qualification,
paper admission, testnet, and live activation remain blocked.

Recommended runtime for the next bounded phase: `gpt-5.6-luna-900k` via
`openai-codex`, Medium effort.
