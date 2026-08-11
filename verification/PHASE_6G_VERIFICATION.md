# Phase 6G Verification — deterministic EMA-slope follow-up candidate

## Result

Phase 6G evaluated a second explicit executable hypothesis after the Phase 6F
returns candidate was rejected. The hypothesis used the existing causal feature
and trade-ledger contracts; no new evaluator, policy relaxation, or execution
path was added.

The candidate was rejected by the same strict OOS policy. No candidate is
qualified, promoted, paper-activated, or executable.

## Candidate and provenance

```text
candidate_id:          cand-exp-ema-slope-001
creator_run_id:        phase6g-ema-slope-seed-29
research_seed:         29
family:                experimental
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
feature:               ema_slope, lookback=24, shift=1
signal:                ema_slope > 0 / ema_slope < 0
causality:             prior-bar shifted feature; fresh-state entries
source:                cached-only Phase 6D v2 DatasetBundle
```

This is distinct from the Phase 6F `returns` hypothesis. The screen-only
family outputs remain screening evidence and were not treated as executable
candidate artifacts.

```text
bundle_hash:          ffb21166b9dd55cfeab657f261a546f91a9f19b5cbc89f88ef37bd6991d833f8
dataset_registry:     596d7370b99462bc5d9153e2264267d18b7cf457b85ef0d45f9ce83bfb23e8f0
candidate_hash:       168b53666dc46f653869f4a5456bff1fd922958e37d01d28da0b138c84a9c7a6
candidate_registry:   058ca9dea4b2d98b25ca5c4ce6aeaa9142bc21fdec7d6e735fe44f6e4686593d
```

## OOS evaluation

The existing explicit cached-window evaluator and candidate-window simulator
were reused with the same bounded range, symbols, fees, slippage, capital, and
qualification policy as Phase 6F.

```text
windows:              6
symbols:              3
trades:               544
pooled net P&L:       -56.27997638488207014267611805
pooled profit factor: 0.5681695310432010933928447696
average return:       -9.379996064147011690446019668%
worst drawdown:       21.81770130461938047341067375%
aggregation_hash:     bab02c59a234d1c20c5f157f649b4e2771a1cf80eaf3144e2bcc2cb62464a1bc
```

Policy remained unchanged:

```text
policy_id:             phase6g-conservative-v1
minimum_windows:       2
minimum_trades:        10
minimum_profit_factor: 1.10
maximum_drawdown_pct:  8
minimum_average_return_pct: 0
```

## Qualification result

The persisted batch runner independently reread the candidate registry,
candidate artifact, aggregation envelope, and policy, then wrote rejected
evidence without changing candidate or registry bytes.

```text
selected:              cand-exp-ema-slope-001
evaluated:             cand-exp-ema-slope-001
qualified:             none
rejected:              cand-exp-ema-slope-001
blocked:               none
qualification_hash:    489c9738ead582b1eaf77d029ad8bfa4542e627681706eb8943ec96bc7822171
failed gates:          12
```

Failed gates covered pooled and per-symbol return, drawdown, and profit-factor
thresholds. This is a deterministic rejection, not unavailable evidence and
not a promotion signal.

## Accounting correction discovered during Phase 6G dogfood

The first remote run exposed a second real Decimal-ordering issue: summing all
signed trade P&L directly can round differently from separately summed gross
profit and gross loss. The canonical ledger is now:

```text
net_pnl = rounded(sum(positive net P&L)) - rounded(sum(abs(negative net P&L)))
```

The simulator result validator, terminal equity, and performance metrics all
use that same boundary. A mixed-sign high-precision regression was added before
the fix and failed as expected, then passed after the fix.

## Verification

```text
Focused simulation/metrics/learner suite: 71 passed
Full local locked suite before delivery:   485 passed
Ruff:                                      passed
Ruff format --check:                       224 files formatted
Mypy:                                      121 source files clean
uv lock --check:                           passed
git diff --check:                          passed
```

The candidate/evidence run used Kainode after it was synchronized to the
committed source at `0807b6c`; the Kainode source was not left with temporary
patches. Temporary runner files were removed after readback.

## Safety and limitations

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

This phase proves a second bounded candidate/evaluator/aggregation/qualification
chain and a second rejected result. It does not prove strategy quality,
profitability, historical completeness, paper readiness, live readiness, or
execution safety. No provider client, scheduler, API/UI runtime, credential,
order endpoint, or paper runtime was added.

Recommended runtime for the next bounded step: `gpt-5.6-luna` via
`openai-codex`, `Medium` effort.
