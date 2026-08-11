# Phase 6R Verification — RSI regime-aligned mean-reversion qualification

## Decision

Phase 6R tested a materially stated continuation of the Phase 6Q RSI family:
mean-reversion entries are allowed only when the causal `regime_trend` agrees
with the direction of the dip.

The candidate was rejected fail-closed. The pooled positive P&L is sparse and
profit factor is undefined; ETHUSDT and SOLUSDT produced zero trades.

## Hypothesis

```text
candidate:       cand-scope-rsi-regime-001
seed:            103
family:          experimental (domain-compatible)
long entry:      rsi < 30 and regime_trend > 0
short entry:     rsi > 70 and regime_trend < 0
long exit:       rsi >= 50
short exit:      rsi <= 50
features:        regime_trend(14, shift=1), rsi(14, shift=1)
```

Both features are approved by the existing domain contract. The bounded
expression parser and causal evaluator were reused unchanged; no production
feature schema, simulator, gate, or threshold was modified.

## Evidence bindings

```text
bundle hash:       ea3a4145f0a1950d4d1ecafc870accda043115714663026ccafbb423096a6a93
registry hash:     2daa004bb64582bc76338fb75ac6e09608213d85346deacd10cbd5b5c2b075bd
candidate hash:    37c0d27ec2775ddb226cea379ce11d9da484a2efbcd4225a08b30f81a595ffac
candidate registry:097531f24c32f2a54cd5d1d30b132fcd1f4110e47a5d959cbd633d2360abe5d9
aggregation hash:  c3023e450ffcac8149a5fca6378cfa94f0857330651b74d32e2ec870b03223c2
qualification hash:eaeeaeb62ab14bf6bd6eaa7dfa4e1e309ab154e92a531975119ed37bd8a58fc7
policy:            phase6r-conservative-v1
```

The immutable Phase 6N scope was reused read-only:

```text
2026-07-01T00:00:00Z → 2026-08-11T04:15:00Z
6 OOS windows, 2 per symbol
```

## OOS result

```text
pooled trades:     1
pooled net P&L:    +0.3795841662404797601199400300
average return:    +0.06326402770674662668665667167%
profit factor:     undefined
worst drawdown:    0.4613401172186246558067545151%
decision:          rejected
```

Per-symbol evidence:

```text
BTCUSDT: trades=1, average=+0.1897920831202398800599700150%, PF=undefined
ETHUSDT: trades=0, average=0%,                              PF=undefined
SOLUSDT: trades=0, average=0%,                              PF=undefined
```

Failed gates include pooled profit factor, pooled minimum trades, BTCUSDT
minimum trades/profit factor, and ETHUSDT/SOLUSDT minimum trades/profit factor.
Positive pooled P&L does not override sparse-evidence or per-symbol gates.

## Execution and safety

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

No API, provider client, scheduler, authenticated exchange client, order
endpoint, paper runtime, or execution authority was added. The temporary
remote runner was removed after execution. Local `research/phase6r_run.py` is
also removed before delivery.

## Verification

The runner used the project `.venv`, `PYTHONPATH=src`, the exact Phase 6N
parquet artifacts, explicit window boundaries, and the existing Decimal ledger
and strict qualification builder. The first two remote attempts failed before
evidence due to import/timestamp-shape setup issues; no partial qualification
was accepted until the corrected runner completed and immutable readback
succeeded.

Recommended runtime for the next phase remains: `gpt-5.6-luna` via
`openai-codex`, `Medium` effort.
