# Phase 6M Verification — causal Bollinger mean-reversion qualification

## Result

Phase 6M added the smallest missing causal feature support for
`bollinger_zscore`, then evaluated one fresh Bollinger mean-reversion cohort on
the immutable Phase 6K tail bundle. The feature uses a rolling close mean and
standard deviation, masks zero-width bands, and shifts the derived z-score by
one completed bar before it can produce a signal.

The candidate was rejected by the unchanged strict OOS policy.

## Implementation

```text
feature:              bollinger_zscore
lookback:             24
shift:                1
long entry:           bollinger_zscore < -2.0
short entry:          bollinger_zscore > 2.0
long exit:            bollinger_zscore > -0.5
short exit:           bollinger_zscore < 0.5
```

Added regression coverage proves the feature and signal at candle `t` are
unchanged when only candle `t` is mutated, and the source frame remains
unchanged. Focused feature suite after implementation: `9 passed`.

## Candidate and bindings

```text
candidate:             cand-tail-bollinger-reversion-001
seed:                  73
candidate hash:        41ab999ec61abbaacded8010478bc18e38f04a6df2f4d1b062c1f768294298d
candidate registry:    da9dcb6e894bb2a92f44fa7e8da70e876520299c74bd6ef4ce2c87588ce17bdb
bundle hash:           b69c5db0a0e3c628de905327dd24d9e510368bfe33a7a62221d1f13dd633f5ca
registry hash:         b164c4dbe2a10dda92611eed1187662f8d5c30759eded24206bfd5d79ecc4ce6
source commit:         dfcdbbb
```

## OOS evidence

```text
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
windows:               6 (2 per symbol)
trades:                62
pooled net P&L:        -0.6313191432085378584768903941
average return:        -0.1052198572014229764128150656%
profit factor:         0.5362985919805050696504087483
worst drawdown:        0.6074947664839759649741412256%
aggregation hash:      215721bd9dc8b50fc6919cac802bf51e089aacb75f341fb3fb795edeb46a7513
```

The windows were deterministic midpoint splits over the Phase 6K 5m tail and
were evaluated independently per symbol through the existing cached-only
signal, ledger, and metric boundaries.

## Qualification

```text
decision:               rejected
qualification hash:     693a87002d3fb8d672c559c50a7858456d52096a575605959c987ad4df874cd3
policy:                 phase6m-conservative-v1
```

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

The batch result had one selected/evaluated candidate, zero blocked candidates,
and zero qualified candidates. The rejected evidence was persisted without
mutating candidate or registry lifecycle state.

## Safety state

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

No paper runtime, scheduler, authenticated client, order endpoint, provider
network client, or live execution was started.

## Limitations and decision

The Phase 6K scope is a bounded five-day tail and is not full-history evidence.
This result rejects this Bollinger configuration under the unchanged policy; it
does not establish that every Bollinger parameterization is invalid. Do not
retry seeds blindly or relax gates. A future attempt needs a longer immutable
scope or a separately justified parameter family with a falsifiable thesis.

Recommended runtime for the next phase: `gpt-5.6-luna` via `openai-codex`,
`Medium` effort.
