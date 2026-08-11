# Phase 6Q Verification — causal RSI mean-reversion qualification

## Result

Phase 6Q added the smallest missing causal feature slice for the already
approved `rsi` domain feature, then evaluated one fresh RSI mean-reversion
candidate against the immutable Phase 6N bundle. Existing cached-only
simulation, Decimal accounting, OOS aggregation, and strict qualification gates
were reused unchanged.

The pooled result was positive, but the candidate was rejected because every
required symbol must pass independently. ETHUSDT failed both average return and
profit factor. No candidate was qualified or promoted.

## Feature slice

```text
feature:               rsi
lookback:              14
shift:                 1
calculation:           causal EMA/Wilder-style gains and losses
long entry:            rsi < 30
short entry:           rsi > 70
long exit:             rsi >= 50
short exit:            rsi <= 50
```

The feature implementation preserves the existing `FeatureRef.shift` boundary,
returns bounded RSI observations in `[0, 100]`, handles flat/up-only windows
without non-finite output, and leaves the source frame unchanged.

Focused RED/GREEN evidence:

```text
RED:   DataQualityError: feature is not supported: rsi
GREEN: test_rsi_is_supported_and_uses_only_prior_bars — passed
Focused feature suite: 10 passed
```

## Candidate and evidence bindings

```text
candidate:             cand-scope-rsi-reversion-001
seed:                  97
family label:          experimental (domain-compatible)
bundle hash:           ea3a4145f0a1950d4d1ecafc870accda043115714663026ccafbb423096a6a93
registry hash:         2daa004bb64582bc76338fb75ac6e09608213d85346deacd10cbd5b5c2b075bd
candidate hash:        e66c6f244ac6895ead8d531d071dca1432dbb4808103e5749a3220074eed5be1
candidate registry:    80e5240f2212ec25e3a8e067a2d3f97f3ee585ffc21a0fc9552b491c9d7d4073
aggregation hash:      03e65aca11b7737035683690b04f0c0e05dcd4d6ed988f37af55ed3c7b6945db
qualification hash:    4d8ef6000520d0f41783f293c8380bbb03b0d1eb215c5799d4767982511f962b
policy:                phase6q-conservative-v1
```

## OOS evidence

```text
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
windows:               6 (2 per symbol)
trades:                199
pooled net P&L:        +1.535622286773785766250758751
average return:        +0.2559370477956309610417931253%
profit factor:         1.180490982300733250502181249
worst drawdown:        1.559072935310693446544661802%
decision:              rejected
```

Per-symbol evidence:

```text
BTCUSDT: trades=69, average=+0.1851458881463959435885214005%, PF=1.149625067633327942802777599, DD=0.6529245966916361098058455634%
ETHUSDT: trades=70, average=-0.0109465027526688644985007685%, PF=0.9936757914547649095907449994, DD=1.559072935310693446544661802%
SOLUSDT: trades=60, average=+0.593611757993165804035358744, PF=1.461693807096966468213559254, DD=0.8811650007039758889755782656%
```

Failed gates:

```text
oos_ethusdt_average_return_min
oos_ethusdt_profit_factor_min
```

The positive pooled result is not sufficient: cross-symbol offsetting is
prohibited and ETHUSDT independently fails the unchanged policy.

## Verification and delivery

```text
Feature implementation commit: 8ce9e39
Qualification report commit:   pending in this report commit
Local full suite before report: 487 passed
Remote qualification:           completed at 8ce9e39
Temporary remote runner:        removed
```

The next report commit will run a fresh full locked suite and remote suite at the
same final ref. No production API, provider client, scheduler, paper runtime,
authenticated exchange client, order endpoint, or execution authority was added.

## Safety state

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

## Decision

RSI mean-reversion is the first recent family with positive pooled evidence, but
it is not portable under the strict every-symbol policy. Do not promote it, start
paper observation, or tune ETH parameters on the same evidence scope as a blind
retry. A future RSI continuation requires a materially stated hypothesis or a
fresh immutable scope; gates remain unchanged.

Recommended runtime for the next phase: `gpt-5.6-luna` via `openai-codex`,
`Medium` effort.
