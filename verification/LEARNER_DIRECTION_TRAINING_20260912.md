# Learner Direction Training — 2026-09-12

## Result

One deterministic learner training run completed from the verified Critic
review. The objective is:

```text
objective:          next_bar_direction
target:             close[t+1] > close[t]
feature:            returns (causal shift=1)
model family:       next_bar_direction_bucket
learner version:    next-bar-direction-v1
observations:       21,900
symbols:            BTCUSDT, ETHUSDT, SOLUSDT
```

The model is a research artifact only. It is not evaluated, qualified,
admitted to paper, promoted, or authorized for testnet/live execution.

## Exact lineage

```text
bundle hash:                108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:              ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
candidate:                  cand-learner-bootstrap-20260912
candidate artifact hash:    ff820a97555add3c28a7986ac60319536bcd54ad582fc35a6e54097834f0a5ff
source learner:             learner-holdout-20260912
source learner hash:        10ba3cba75483d131d67748b3f69395d9426dca90e006eed9f3fe3ff0707fea7
Critic evidence:            learner-quality-critic-evidence-holdout-v4-setup2-20260912
Critic evidence hash:       308402cbae6f151747123b89b81d7c07cc8ece89119a3d27f15a46964517bf7f
```

The Critic evidence was verified against the exact failed metric-quality
request before the trainer was called. The training link binds the Critic
evidence, prepared run, source learner, output learner, candidate, bundle,
registry, input windows, and objective.

```text
prepared run:               run-learner-quality-critic-direction-20260912
prepared run hash:          69afd06e05efd18fd973e7772024bd8ac6d9f803c5b41fbd62d2c2913160329e
training evidence:          training-evidence-learner-quality-critic-direction-20260912
training evidence hash:     fcae1858ee4610de836c60c1564808ba3c81ce7278df7fc27cd1863daf702d6d
output artifact hash:       682d5c1c245efde6236b738c37b1a3ea35634c671870c386a4911b1e2c19315f
model artifact hash:        d63f2e9f02aa745dd62ff13822fd1bf65a965e3690cb5e9d0f12780c968ba80e
```

Input windows:

```text
input-btcusdt-direction-20260912
input-ethusdt-direction-20260912
input-solusdt-direction-20260912
```

## Persistence and readback

Published evidence root:

```text
/opt/autonomous-futures-bot/research/learner-evidence/direction-training-20260912
```

A separate fresh Python process re-read the typed training link and output
learner artifact, re-verified the complete chain, and validated the model JSON
objective, target definition, causal feature, symbol set, bucket set, and
positive observation count.

```text
fresh-process readback:      pass
model observations:          21,900
source:                      cached_only
provider/exchange calls:     none
```

The run used the exact immutable 5m/15m bundle manifests and verified each
manifest hash, Parquet SHA-256, and declared row count before materialization.
No fallback or retry was used after the corrected run succeeded.

## Failed-closed attempts

Two setup attempts produced no trusted artifact and were cleaned:

1. Direct SSH writer could not create the root-owned research staging path.
2. The delegated run initially resolved manifest source files relative to the
   `manifests/` directory instead of the interval artifact root.

The corrected runner printed `status=completed` and `published=true`. Its outer
SSH wrapper returned `1` only because it checked the staging path before its
EXIT cleanup trap ran. A separate verifier then returned exit `0`; no duplicate
training run was launched.

## Runtime safety

```text
scheduler:                    active
paper service:                active
research-related timers:      0
transient-related units:      0
temporary roots:              absent
execution authority:          false
promotion state:              unpromoted
paper activation:             false
testnet/live order:            none
```

No scheduler pause, paper mutation, candidate registry mutation, qualification,
promotion, provider request, exchange request, or order occurred for this
training run.

## Verification gates

```text
focused learner/Critic regression:  80 passed
ruff check:                          passed
ruff format --check:                 passed
mypy:                                passed
uv lock --check:                     passed
git diff --check:                    passed
```

Implementation commits:

```text
cdbd27d  feat: bind directional learner training to critic evidence
db5e8b8  fix: close critic training lineage readback
```

The `cdbd27d` GitHub quality run completed successfully. The `db5e8b8` quality
run was observed in progress; subsequent GitHub API polling hit the public API
rate limit and the public Checks page exposed no conclusion. Local gates and
fresh remote artifact verification passed; GitHub status for `db5e8b8` remains
unverified rather than claimed successful.

## Next boundary

Run a new deterministic cached-only holdout evaluator for
`next_bar_direction`, bound to this training link. Until that evaluator and its
quality decision pass, this learner remains blocked from qualification, paper,
testnet, and live paths.
