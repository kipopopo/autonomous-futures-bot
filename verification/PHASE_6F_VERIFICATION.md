# Phase 6F Verification — deterministic candidate and OOS qualification evidence

## Result

Phase 6F produced one explicit deterministic **testing** candidate from a
bounded cached-only strategy hypothesis, evaluated it against the verified
Phase 6D v2 bundle, persisted the OOS aggregation and policy, and ran the
existing persisted qualification flow.

The candidate was rejected by the strict OOS policy. This is valid evidence;
there was no promotion, paper activation, or execution authority.

## Candidate and provenance

```text
candidate_id:          cand-exp-returns-001
creator_run_id:        phase6f-returns-seed-17
research_seed:         17
family:                experimental
symbols:               BTCUSDT, ETHUSDT, SOLUSDT
primary/context:       5m / 15m
feature:               returns, lookback=3, shift=1
signal:                returns > 0 / returns < 0
source:                cached-only v2 DatasetBundle
```

The archived `research/strategy_screen_results.json` was not promoted into a
candidate: it is explicitly screening-only and non-executable. The candidate
was constructed through the typed `CreatorCandidateArtifact` contract instead.

```text
bundle_hash:          ffb21166b9dd55cfeab657f261a546f91a9f19b5cbc89f88ef37bd6991d833f8
dataset_registry:     596d7370b99462bc5d9153e2264267d18b7cf457b85ef0d45f9ce83bfb23e8f0
candidate_hash:       5387f60abd0a768845efeaaf26c7fcdb72d11da381c3efcbad2c4023576b1dda
candidate_registry:   584235d58cc61aaa59be81a22312b17cfe113b3397f8b786b1e1c66f065336c2
```

## OOS evaluation

The existing explicit cached-window evaluator and candidate-window simulator
were used. Six independent windows were evaluated: two per required symbol,
covering the bounded Phase 6D range.

```text
windows:              6
symbols:              3
trades:               2,170
pooled net P&L:       -26.49081716363856606633471387
pooled profit factor: 0.3346554015700810034350828912
average return:       -4.415136193939761011055785645%
worst drawdown:       4.794858491202225085716267087%
aggregation_hash:     e5f14798c1e5e742b635681310e4f45eb622afa4d13cedd87925fe31663c3abe
```

Policy:

```text
policy_id:             phase6f-conservative-v1
minimum_windows:       2
minimum_trades:        10
minimum_profit_factor: 1.10
maximum_drawdown_pct:  0.08
minimum_return_pct:    0
```

## Qualification result

The existing `run_persisted_qualification_batch(...)` runner read the persisted
candidate registry, candidate artifact, aggregation, and policy independently.
It persisted rejected evidence without mutating the candidate or registry.

```text
selected:              cand-exp-returns-001
evaluated:             cand-exp-returns-001
qualified:             none
rejected:              cand-exp-returns-001
blocked:               none
qualification_hash:    78c2aa07545f128f81ada2d55c90bd703bc4c77ccc54222b4984422bbfb61c37
failed gates:          12
```

Failed gates covered pooled and all per-symbol return, drawdown, and profit
factor thresholds. The rejection is expected from the observed negative return
and profit factor below one; no metric was fabricated or coerced into a pass.

## Root-cause fix discovered during real evaluation

Real repeated-trade evaluation exposed order-dependent Decimal summation drift
at the existing simulation/metrics boundaries. Synthetic tests had not reached
that scale. The fix centralizes 80-digit Decimal summation for terminal equity,
fees, slippage, and performance aggregation while retaining exact validators.

New regressions cover repeated realistic Decimal trades in:

```text
tests/unit/test_trade_simulation.py
tests/unit/test_performance_metrics.py
```

The Kainode evaluation used this patch temporarily and Kainode source was
restored to tracked HEAD after evidence generation. The fix remains local and
must be delivered in the phase commit before future remote runs.

## Local verification

```text
focused simulation + metrics suite: 22 passed
```

The fix was verified with the focused and full locked suites before delivery.

## Safety and limitations

```text
data_source="cached_only"
exchange_access=false
promotion_state="unpromoted"
paper_activation=false
execution_authority=false
```

This phase proves one bounded candidate/evaluator/aggregation/qualification
chain and one rejected result. It does not prove strategy quality, profitability,
historical completeness, paper readiness, live readiness, or execution safety.
No API, scheduler, provider client, credential, order endpoint, or paper runtime
was added.

Recommended runtime for the next bounded delivery step: `gpt-5.6-luna` via
`openai-codex`, `Medium` effort.
