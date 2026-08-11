# Phase 6O Verification — fresh Bollinger qualification on longer scope

## Result

Phase 6O evaluated one fresh causal Bollinger mean-reversion candidate against
the separate Phase 6N immutable bundle. The prior Phase 6M candidate,
aggregation, and qualification artifacts were not reused or modified. The
existing cached-only simulator, Decimal ledger, OOS aggregation, and strict
qualification policy were reused unchanged.

The candidate was rejected. No candidate was qualified or promoted.

## Candidate and causal strategy

```text
candidate:             cand-scope-bollinger-reversion-001
seed:                  79
feature:               bollinger_zscore
lookback:              24
shift:                 1
long entry:            bollinger_zscore < -2.0
short entry:           bollinger_zscore > 2.0
long exit:             bollinger_zscore > -0.5
short exit:            bollinger_zscore < 0.5
primary/context:       5m / 15m
```

The feature remains prior-bar causal and uses the existing feature/simulation
boundary. No simulator or gate semantics were changed for this phase.

## Evidence bindings

```text
bundle hash:           ea3a4145f0a1950d4d1ecafc870accda043115714663026ccafbb423096a6a93
registry hash:         2daa004bb64582bc76338fb75ac6e09608213d85346deacd10cbd5b5c2b075bd
candidate hash:        2114f3e10abb5bda4e6c288a1ff4d10506dfc8c81e27f0a789794902ea172392
candidate registry:    2760b8eb0cfff399819c9e2da3389675ade19d7b2661624bb9ed0dc540468723
aggregation hash:      f15f13f0a82ff2d106e5ce19092e0dc9aaf7caaf9f0ee152d8472ccb0aa7d2c2
qualification hash:    895c5f87d6853c84eaed7fbd951037f3c91ecb7b19118b7b68a56d7c306469b1
policy:                phase6o-conservative-v1
```

## OOS evidence

```text
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
windows:               6 (2 per symbol)
trades:                559
pooled net P&L:        -0.55106993003006179763649295
average return:        -0.09184498833834363293941549267%
profit factor:         0.9608827199363433344362474888
worst drawdown:        0.9931388471556658564250952909%
decision:              rejected
```

Per-symbol evidence:

```text
BTCUSDT: trades=187, average=-0.1656244327317741286096600280%, PF=0.9119654943389647492197781535, DD=0.7737958595345423167299895946%
ETHUSDT: trades=188, average=-0.3201975759248985284266396095%, PF=0.8839362294860246300323988207, DD=0.9931388471556658564250952909%
SOLUSDT: trades=184, average=+0.2102870436416417582180531595%, PF=1.087486488854539745067471368, DD=0.9010166879749538949392184561%
```

Failed gates:

```text
oos_average_return_min
oos_btcusdt_average_return_min
oos_btcusdt_profit_factor_min
oos_ethusdt_average_return_min
oos_ethusdt_profit_factor_min
oos_profit_factor_min
oos_solusdt_profit_factor_min
```

The result contained one selected/evaluated candidate, zero blocked candidates,
and zero qualified candidates. Rejection is due to negative pooled/average
return and profit factor below `1.10`; SOLUSDT also remains below the strict
profit-factor gate despite positive average return.

## Safety state

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

No candidate lifecycle mutation, paper runtime, scheduler, authenticated client,
order endpoint, provider network client, or live execution was started.

## Decision and limitations

The longer 42-day scope materially increases trade evidence versus Phase 6M's
five-day tail, but this Bollinger configuration still fails the unchanged strict
policy on pooled and per-symbol performance. This does not prove all Bollinger
parameterizations invalid; it does show that this fixed causal configuration has
not produced qualification evidence across the tested scopes.

Do not relax gates or retry seeds blindly. The next strategy attempt must be a
materially new falsifiable family, or a separately justified parameter thesis
with an explicit evidence reset. Paper activation remains blocked.

Recommended runtime for the next phase: `gpt-5.6-luna` via `openai-codex`,
`Medium` effort.
