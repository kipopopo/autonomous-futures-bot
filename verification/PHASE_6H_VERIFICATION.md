# Phase 6H Verification — regime-gated family closure

## Result

Phase 6H evaluated a third explicit executable cohort after the Phase 6F
returns and Phase 6G EMA-slope candidates were rejected. The cohort used the
existing `regime_gated_breakout` family contract with prior-bar causal features.

It was rejected by the unchanged strict OOS policy. This is the final bounded
retry in the current executable feature domain; no blind seed retry or policy
relaxation follows from this result.

## Candidate and provenance

```text
candidate_id:          cand-regime-gated-ema-001
creator_run_id:        phase6h-regime-gated-seed-41
research_seed:         41
family:                regime_gated_breakout
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
features:              regime_trend(96, shift=1), ema_slope(24, shift=1)
long entry:            regime_trend > 0 and ema_slope > 0
short entry:           regime_trend < 0 and ema_slope < 0
causality:             prior-bar shifted features; fresh-state entries
source:                cached-only Phase 6D v2 DatasetBundle
```

The screen-only family output was not promoted into this artifact. This was an
explicit typed candidate hypothesis evaluated through the existing cached-only
composition.

```text
bundle_hash:          ffb21166b9dd55cfeab657f261a546f91a9f19b5cbc89f88ef37bd6991d833f8
dataset_registry:     596d7370b99462bc5d9153e2264267d18b7cf457b85ef0d45f9ce83bfb23e8f0
candidate_hash:       ff8ef615328ae628a940cb7a3ac2ba8b7617799df17998b041607484d1fb5606
candidate_registry:   48ee2708a814875d8ce0ace5de092683f7c5c9a6be60367a8397ce676d8de2cf
```

## OOS evaluation

The same six bounded windows, three symbols, capital, fee/slippage model, and
qualification policy were used as Phases 6F and 6G.

```text
windows:              6
symbols:              3
trades:               274
pooled net P&L:       -22.09451710476073893481998413
pooled profit factor: 0.7414205776554659904516808905
average return:       -3.682419517460123155803330687%
worst drawdown:       17.93195840385027795058813141%
aggregation_hash:     23f9100e3079e07aae39eef5b7781a676cd20d2d6e0b76d7eac2317e2456bb10
```

The result is directionally better than the prior two cohorts but remains
negative, below the profit-factor threshold, and above the drawdown limit.

## Qualification result

Persisted registry, candidate, aggregation, policy, and qualification evidence
were independently reread and hash-verified.

```text
selected:              cand-regime-gated-ema-001
evaluated:             cand-regime-gated-ema-001
qualified:             none
rejected:              cand-regime-gated-ema-001
blocked:               none
qualification_hash:    6a601f98023cbe70ba09e9b5b5702b1c3cf295527e007951ea5f8e33cc46f710
failed gates:          11
```

No candidate or registry mutation occurred. Rejection is durable evidence, not
an unavailable result and not a promotion signal.

## Cohort closure decision

Three explicit executable cohorts have now been evaluated under the same
strict policy:

```text
Phase 6F: returns                         rejected
Phase 6G: ema_slope                       rejected
Phase 6H: regime_gated_breakout           rejected
```

The next step must be a materially new research domain with a new provenance
and feature/evaluator contract—for example a properly implemented breakout or
mean-reversion family with normalized features and explicit multi-timeframe
context. It must not be another seed retry of the current `returns` /
`ema_slope` domain. Paper execution remains blocked because no candidate has
qualified.

## Safety and limitations

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

This phase does not prove profitability, historical completeness, paper
readiness, live readiness, or execution safety. No provider client, scheduler,
API/UI runtime, credential, order endpoint, or paper runtime was added.

Recommended runtime for the next architecture/family slice: `gpt-5.6-luna`
via `openai-codex`, `Medium` effort. Escalation is not required yet because the
next safe step remains a bounded research-family contract, not paper/execution
architecture.
