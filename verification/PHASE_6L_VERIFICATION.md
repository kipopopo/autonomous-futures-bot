# Phase 6L Verification — fresh tail cached-only qualification

## Result

Phase 6L ran one fresh persisted candidate qualification against the new Phase
6K post-tail DatasetBundle. The old Phase 6F–6I candidate and aggregation
artifacts were not reused; the candidate, registry, OOS aggregation, and
qualification artifact bind to the Phase 6K tail bundle and registry hashes.

The result is **rejected**. The positive pooled P&L is not sufficient evidence:
there are only two trades, gross loss is zero, profit factor is therefore
undefined, and BTCUSDT/SOLUSDT produce zero trades. Strict gates fail closed.

## Candidate and binding

```text
candidate:             cand-tail-range-reversion-001
family:                range_mean_reversion
feature:               returns, lookback=1, shift=1
seed:                  61
candidate artifact:    0b5d67fd6772e00ee9fda029fee614858ac8f0e22b9bb406a414eba06cbf382a
bundle hash:           b69c5db0a0e3c628de905327dd24d9e510368bfe33a7a62221d1f13dd633f5ca
registry hash:         b164c4dbe2a10dda92611eed1187662f8d5c30759eded24206bfd5d79ecc4ce6
```

The candidate remained `testing`. The qualification flow did not mutate the
candidate, registry, DatasetBundle, or source data.

## OOS evidence

```text
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
windows:               6 (2 per symbol)
total trades:          2
pooled net P&L:        0.2736530037113924108934140907
average return:        0.04560883395189873514890234845%
profit factor:         undefined (pooled gross loss = 0)
worst drawdown:         0.08174391649150895983179760878%
aggregation hash:      22ad3553c36afa8e120efcbf5a0e3ea92cac308bfdf4b79551b2ca31849a8cf8
```

Per-symbol evidence:

```text
BTCUSDT: trades=0, profit_factor=undefined, average_return=0%
ETHUSDT: trades=2, profit_factor=undefined, average_return=0.1368265018556962054467070454%
SOLUSDT: trades=0, profit_factor=undefined, average_return=0%
```

The two OOS windows per symbol were split deterministically at the midpoint of
the Phase 6K 5m tail. Simulation used the existing cached-only causal signal,
trade ledger, Decimal accounting, fees, slippage, and forced-end semantics.

## Qualification

```text
qualification decision: rejected
qualification hash:     8bcb0a8ac8f5c0cbdf2ce806ce66633baa7229b486f494ae8f3d1ade3bab201d
policy:                  phase6l-conservative-v1
```

Failed evidence gates include:

```text
oos_trades_min
oos_profit_factor_min
oos_btcusdt_profit_factor_min
oos_btcusdt_trades_min
oos_ethusdt_profit_factor_min
oos_ethusdt_trades_min
oos_solusdt_profit_factor_min
oos_solusdt_trades_min
```

`profit_factor=null` is preserved as missing/undefined and fails the `gte 1.10`
gate. Zero-trade symbols are not converted to zero-profit or inferred success.

## Safety state

```text
data_source:          cached_only
exchange_access:      false
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
```

No paper runtime, scheduler, authenticated exchange client, order endpoint,
provider network client, or live execution was started. Qualification means
only persisted OOS evidence was evaluated; this candidate was not promoted.

## Limitations and decision

This is a fresh five-day post-tail scope, not a full-history replacement for
the bounded pre-outage Phase 6D bundle. It is too short and too sparse for a
robust profitability conclusion. The correct decision is rejection and evidence
closure, not gate relaxation or repeated seed retries.

Recommended next phase: materially new falsifiable strategy family or a larger
refreshed immutable scope. Runtime remains `gpt-5.6-luna` via `openai-codex`,
`Medium` effort.
