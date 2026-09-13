# Failed-Breakout Re-entry Research — 2026-09-13

## Decision

The fixed **failed-breakout re-entry** hypothesis is **REJECTED** on a fresh
immutable multi-symbol cached scope. BTCUSDT, ETHUSDT, and SOLUSDT each failed
net P&L, profit factor, and average-return gates. No candidate was admitted to
the production registry or paper workflow.

This is negative research evidence, not live-readiness evidence. No threshold
was relaxed, no parameter sweep was run, and no retry was used to reverse the
outcome.

## Hypothesis

The strategy tests whether a wick beyond a prior 20-bar range that closes back
inside the range tends to mean-revert on the next bar.

```text
feature:                 failed_breakout_reentry
lookback / shift:        20 / 1
prior upper:             max(high[t-20:t-1])
prior lower:             min(low[t-20:t-1])
long event at t:         low[t] < lower and high[t] <= upper and
                         lower < close[t] < upper
short event at t:        high[t] > upper and low[t] >= lower and
                         lower < close[t] < upper
entry:                   next candle open, represented by shift=1
long exit:               failed_breakout_reentry < 0
short exit:              failed_breakout_reentry > 0
```

The feature emits `+1` for a long event, `-1` for a short event, and unknown
until the 20-bar prior range is available. The current observation candle is
used only to identify a closed event; the shifted feature makes the next open
actionable. Two-sided range breaches are not classified as either event by the
mutually exclusive wick conditions.

Simulation risk and costs were fixed before evaluation:

```text
starting equity:         100
position fraction:       0.10
ATR lookback:            14
stop / take-profit:      2.0 / 1.0 ATR
trailing stop:           disabled
fee / adverse slippage:  0.0005 / 0.0001
```

## Implementation

Added `failed_breakout_reentry` to the existing `FeatureRef` allowlist and
causal evaluator. The `experimental` family label remains unchanged; no new
execution or promotion authority was introduced.

```text
RED:   unknown feature: failed_breakout_reentry
GREEN: test_failed_breakout_reentry_uses_prior_range_and_next_open
```

The regression mutates the current observation candle and proves its same-bar
feature/signal is unchanged while the next-bar event changes. The source frame
is not mutated.

## Fresh immutable data scope

The previously reported Phase 6K/6N roots were absent, so they were not treated
as available evidence. A new bounded public-data collection was created under a
separate root; the research runner then consumed only the persisted cache.

```text
root:                    research/immutable-data/tail-20260913
symbols:                 BTCUSDT, ETHUSDT, SOLUSDT
primary interval:        5m
context interval:        15m
primary range:           [2026-08-11T04:15:00Z, 2026-09-13T01:15:00Z)
context range:           [2026-08-11T04:00:00Z, 2026-09-13T01:15:00Z)
public server time:      2026-09-13T01:29:57.830000Z
```

Per symbol:

| Symbol | 5m | 15m | Mark-price 5m | Funding events |
|---|---:|---:|---:|---:|
| BTCUSDT | 9,468 | 3,157 | 9,468 | 99 |
| ETHUSDT | 9,468 | 3,157 | 9,468 | 99 |
| SOLUSDT | 9,468 | 3,157 | 9,468 | 99 |

```text
registry hash:           625c0558b79913d98f5f08c5e44f263b0822e0e1b5588bf4dbdf6147fbe680c4
bundle hash:             07a654ebcaa6c40d4399e744ad05a5dee77e4ec61bac2743a2f17380324de7dd
filter snapshot hash:    bd5d91c19bf09b8c3347681fdcdd380a236704cf647fb63962b383a1086965bb
lock hash:               487a92cfe4abbc2ff06bc4ff6e1c1a80b5c981cc6982fa7462f995ca8aef0264
source commit:           d63540a76469b8114de094920c1ba87f742e98e6
```

Collection used unsigned public REST only, no credentials, one attempt per
page (`max_attempts=1`), and no fallback. Every kline, derivative artifact,
manifest, registry, and bundle was reread with hash validation. The downstream
research contract is `data_source=cached_only` and `exchange_access=false`.

The outer collection wrapper returned a cleanup assertion code before its exit
trap ran. The collection itself reported `status=verified`; an independent fresh
readback subsequently passed and confirmed the staging root, checkpoints, and
transient files were absent. No partial scope was accepted.

## OOS evaluation

The runner materialized the full causal 5m frame for each symbol before slicing
the final untouched evaluation tail. This preserves prior history for the first
OOS feature without counting warm-up rows as OOS observations.

```text
OOS range:                2026-09-01T01:15:00Z → 2026-09-13T01:15:00Z
OOS bars per symbol:      3,456
windows per symbol:       12
bars per window:          288
total windows:            36
```

Fixed qualification policy:

```text
minimum windows:          1
minimum trades:           5
minimum profit factor:    1.05
maximum drawdown:         15.0%
minimum average return:   0%
```

## Results

| Symbol | Windows | Trades | Net P&L | Profit factor | Average return | Worst drawdown |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 218 | -2.405419162627350345070024771 | 0.1834693876721542734634069687 | -0.2004515968856125287558353976% | 0.4144783126913663398134637700% |
| ETHUSDT | 12 | 206 | -2.456189838404085641731483581 | 0.2989258911515206453911001475 | -0.2046824865336738034776236318% | 0.4092605696728241634040454481% |
| SOLUSDT | 12 | 207 | -2.051329781052664842549942808 | 0.4703066921783690844956410242 | -0.1709441484210554035458285673% | 0.4561861146624444912168204273% |
| **Pooled** | **36** | **631** | **-6.912938782084100829351451156** | **0.3302741920053343831043307561** | **-0.1920260772801139119264291988%** | **0.4561861146624444912168204273%** |

Failed qualification gates:

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

All three symbols passed drawdown, minimum-trade, and minimum-window checks, but
those checks cannot offset negative returns and sub-threshold profit factors.

## Persisted evidence

```text
candidate:                cand-failed-breakout-reentry-20260913
candidate artifact hash:  b711c99e4ac7a55e4191f5e0772c8c363364e437816c56fb38ff3b1cae62c06d
aggregation hash:         0984a7c49d2a164bd66a50fb9bb4a9e5f1d59986309a3be4790d6990b395069a
qualification hash:       ae2976a60667e1d7f2a5ef2349a589d3e44a9c3a55a63588c343a9d2e0f4530d
qualification decision:   rejected
```

Evidence root:

```text
/opt/autonomous-futures-bot/research/strategy-evidence/failed-breakout-reentry-20260913
```

It contains exactly three immutable artifacts: candidate, OOS aggregation, and
qualification. A fresh typed readback verified the exact strategy expressions,
feature identity, risk values, candidate/bundle/registry bindings, aggregation
binding, qualification decision, and safety fields.

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

The immutable data scope and research evidence are outside the production
candidate registry. No provider/LLM call, paper admission, testnet order, live
order, restart, or circuit-breaker bypass was performed.

## Verification

```text
new feature RED:                 observed expected missing-feature failure
feature/evaluator suite:         17 passed
related cached/OOS suite:        59 passed
full locked pytest after repair: 2,210 passed
Ruff check:                      passed
Ruff format --check:             passed
mypy src scripts:                passed
uv lock --check:                 passed
git diff --check:                 passed
immutable scope readback:        passed
research chain readback:         passed
runtime safety readback:         passed
```

The feature commit's GitHub Actions run `34730432060` initially failed at the
full `Run tests` step on an unrelated hard-coded analytics fixture date. The
same assertion was reproduced from the pre-feature reference `83ce80d`, where
the fixture's Sep 6 trade had fallen outside the notifier's seven-day window
on the current Sep 13 clock. The fixture was corrected to use timestamps
relative to test execution in commit `0e6647d96031e08d23386977b651900feab91b3c`;
its focused analytics suite passed `26 tests`, and the full locked suite then
passed `2,210 tests`. The strategy feature itself was not changed by this
repair.

Implementation commit: `d63540a76469b8114de094920c1ba87f742e98e6`.

## Boundary

The failed-breakout re-entry thesis is closed unchanged. Do not tune its
lookback, wick conditions, costs, exits, or gates to reverse this result. Keep
the candidate blocked. Any future strategy must be materially different and
use an explicitly bound immutable scope; qualification, paper admission,
testnet, and live activation remain blocked.

Recommended runtime for the next bounded phase: `gpt-5.6-luna-900k` via
`openai-codex`, Medium effort.
