# Phase 6I Verification — range mean-reversion cohort

## Result

Phase 6I evaluated a materially new `range_mean_reversion` hypothesis using
the existing causal `returns` feature. No new simulator, persistence boundary,
exchange client, or paper path was added; the existing typed candidate and
cached-only OOS chain were reused.

The candidate was rejected by the unchanged strict OOS policy.

## Candidate and provenance

```text
candidate_id:          cand-range-mean-reversion-001
creator_run_id:        phase6i-range-reversion-seed-53
research_seed:         53
family:                range_mean_reversion
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
feature:               returns(lookback=1, shift=1)
long entry:            returns < -0.005
short entry:           returns > 0.005
causal semantics:      prior-bar return, fresh-state entries
source:                cached-only Phase 6D v2 DatasetBundle
```

This tests a genuine mean-reversion hypothesis rather than another EMA/regime
seed retry. The `returns` feature is shifted before signal evaluation, and the
candidate remains testing-only.

```text
bundle_hash:          ffb21166b9dd55cfeab657f261a546f91a9f19b5cbc89f88ef37bd6991d833f8
dataset_registry:     596d7370b99462bc5d9153e2264267d18b7cf457b85ef0d45f9ce83bfb23e8f0
candidate_hash:       990e07ce93ecb99716d95a0eb362187d253a082ba33150586578c0ef314e34a4
candidate_registry:   ad37fd6b3bff4cc08013cf9cdb6e4a43a7c42e973577f272d16f43cee46b2092
```

## OOS evaluation

The same six bounded windows, three symbols, starting equity, fee/slippage
model, and qualification policy used by Phases 6F–6H were retained.

```text
windows:              6
symbols:              3
trades:               156
pooled net P&L:       -19.89125834920565053170388709
pooled profit factor: 0.7868761285901652118551273248
average return:       -3.315209724867608421950647848%
worst drawdown:        18.81786891610808867634084882%
aggregation_hash:     be2c79f472b4765e9b8eba018bc7301401f706f9c2da5fb319f5cf260ff363a6
```

The cohort improves pooled loss and profit factor relative to Phase 6H, but it
remains negative, below the `1.10` profit-factor floor, and above the `8%`
drawdown ceiling. BTC also failed the minimum-trade gate.

## Qualification result

Candidate, registry, aggregation, and qualification artifacts were reread on
Kainode through their shared verified readers. The qualification artifact hash
and failed gate identities were confirmed.

```text
selected:              cand-range-mean-reversion-001
evaluated:             cand-range-mean-reversion-001
qualified:             none
rejected:              cand-range-mean-reversion-001
blocked:               none
qualification_hash:    225948e7c310872b7ab9ae476707818553ac84d5b596cbcbf4beefd4da47a0ea
failed gates:          13
```

No candidate lifecycle mutation occurred. Rejected evidence is retained as an
audit result, not converted to unavailable or promotion state.

## Safety and limitations

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

The bundle remains bounded to the pre-outage Phase 6D scope and does not prove
full-history completeness, current-market validity, profitability, paper
readiness, or live readiness. No provider, scheduler, authenticated exchange,
order endpoint, or paper runtime was started.

This is the fourth rejected executable cohort. Further retries in the current
bounded dataset are not justified without a new falsifiable hypothesis and a
new evidence scope. The next safe research step is a separately designed family
or refreshed immutable data scope—not gate relaxation and not paper activation.

Recommended runtime for that bounded research step remains `gpt-5.6-luna`
via `openai-codex`, `Medium` effort.
