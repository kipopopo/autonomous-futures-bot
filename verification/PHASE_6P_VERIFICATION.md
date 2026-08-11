# Phase 6P Verification — pure regime-trend qualification

## Result

Phase 6P evaluated one materially new pure regime-trend continuation cohort
against the Phase 6N longer immutable bundle. The existing causal feature,
cached-only simulator, Decimal ledger, OOS aggregation, and strict qualification
policy were reused unchanged. No Bollinger, EMA-slope, range, or seed retry was
performed.

The candidate was rejected. No candidate was qualified or promoted.

## Candidate and thesis

```text
candidate:             cand-scope-regime-trend-001
seed:                  89
family label:          experimental (domain-compatible)
thesis:                follow the prior completed regime trend directly
feature:               regime_trend
lookback:              96
shift:                 1
long entry:            regime_trend > 0
short entry:           regime_trend < 0
long exit:             regime_trend < 0
short exit:            regime_trend > 0
primary/context:       5m / 15m
```

The feature is already supported by the allowlisted causal evaluator. The
`StrategySpec` domain currently permits `experimental` as the family label, so
no production schema change was introduced merely to name this bounded cohort.

## Evidence bindings

```text
bundle hash:           ea3a4145f0a1950d4d1ecafc870accda043115714663026ccafbb423096a6a93
registry hash:         2daa004bb64582bc76338fb75ac6e09608213d85346deacd10cbd5b5c2b075bd
candidate hash:        a9f527f58e4b0608b1b7e780bab4ba006be32e924784ffad965a311ccce7d337
candidate registry:    09a514f6bb2dcdc18886674eb817e6c6e6da98086ad583925955ac01064dbb30
aggregation hash:      977b2a41b71e5d99005370778c4b9f9cfcceabd8e1aa077d88be7ed77853ac58
qualification hash:    21d1b3db747a3da0d895ad642b4aa0c00a8f04279d7d54413c784e70afbbd626
policy:                phase6p-conservative-v1
```

## OOS evidence

```text
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
windows:               6 (2 per symbol)
trades:                1,109
pooled net P&L:        -15.01203872897614336688424234
average return:        -2.50200645482935722781404039%
profit factor:         0.3334482134004375174083217003
worst drawdown:        3.423848311596035306018486643%
decision:              rejected
```

Per-symbol evidence:

```text
BTCUSDT: trades=359, average=-2.502044010818040681887661161%, PF=0.2796405148241800091353830719, DD=3.107925119841838204953669849%
ETHUSDT: trades=357, average=-2.481639461920962172677975770%, PF=0.3325250274362069059172477820, DD=2.750568879703883728708089967%
SOLUSDT: trades=393, average=-2.522335891749068828876484236%, PF=0.3802144365873951084847697969, DD=3.423848311596035306018486643%
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

The batch contained one selected/evaluated candidate, zero blocked candidates,
and zero qualified candidates. All three symbols independently failed average
return and profit-factor gates. The modest drawdown does not offset negative
return or PF failure.

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

This pure regime-trend thesis fails across all three symbols on the materially
longer Phase 6N scope. Together with the prior rejected cohorts, the result does
not justify paper activation. Gates remain unchanged.

Do not retry this seed, relabel the result as qualified, or add execution work.
The next research attempt requires a genuinely different falsifiable domain or
new evidence scope; repeated indicator variants under the same simulator are not
sufficient justification.

Recommended runtime for the next phase: `gpt-5.6-luna` via `openai-codex`,
`Medium` effort.
