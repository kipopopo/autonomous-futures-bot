# Learner Direction Holdout — 2026-09-12

## Result

The persisted `next_bar_direction` learner was evaluated once on the untouched
chronological holdout and failed the unchanged metric-quality policy.

```text
objective:              next_bar_direction
target:                 close[t+1] > close[t]
model family:           next_bar_direction_bucket
learner version:        next-bar-direction-v1
holdout rows/symbol:    3,131
symbols:                BTCUSDT, ETHUSDT, SOLUSDT
```

All three symbols passed the drawdown ceiling but failed both economic gates:
`net_pnl >= 0` and `profit_factor >= 1`.

| Symbol | Trades | Net P&L | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|
| BTCUSDT | 979 | -11.44187627108928217711004441 | 0.1468456615039850116122784473 | 11.44947779161089034873306386 |
| ETHUSDT | 968 | -11.92342365348026587940245933 | 0.2197784294683929796481376514 | 11.92342365348026587940245933 |
| SOLUSDT | 993 | -12.30316819575750654715937487 | 0.2103244382515266389345891891 | 12.32205996037111535746724145 |

## Exact lineage

```text
bundle hash:                108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:              ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
candidate:                  cand-learner-bootstrap-20260912
output learner hash:        682d5c1c245efde6236b738c37b1a3ea35634c671870c386a4911b1e2c19315f
training link:              critic-training-evidence-learner-quality-critic-direction-20260912
training link hash:         4d3694e7779e6ca3f95d35e0389c19255df63cd1d023b430504caf3ccadda31c
model artifact hash:        d63f2e9f02aa745dd62ff13822fd1bf65a965e3690cb5e9d0f12780c968ba80e
```

The holdout begins exactly at the training-window end. The runner included one
prior completed bar only to calculate the first holdout `returns` feature, then
removed that warm-up row before evaluation. No holdout target or future close
was used to generate a signal.

## Persisted evidence

```text
evaluation root:            /opt/autonomous-futures-bot/research/learner-evidence/direction-evaluation-20260912
evaluation run:              learner-direction-holdout-20260912
evaluation hash:             2f196133b5f5c7dd515c12f98bd5089e6dfa8c2c08d237f7af5af4205211f4b5
quality review:              metric-quality-review-direction-holdout-20260912
quality review hash:         9f4358d31436277f5d4546c6bc3d6c5fc2b26e04348e090c5bbb84f4dad7d771
quality decision:            metric-quality-decision-direction-holdout-20260912
quality decision hash:       aa384a82e11a549a3b87cd89dfe22ba154c67ea4cce4fc27cf167c2db41594d3
quality decision:            FAILED
policy hash:                 c181c8587fdc525a49bd86d30ce56a642d699d1c85eb9e4c828890284445f500
```

The decision contains three passing drawdown gates and six failed economic
gates. Metric IDs are canonical: `max_drawdown_pct`, `net_pnl`, and
`profit_factor`. No `observed_*` aliases were introduced.

A separate fresh Python process verified the full chain:

```text
Critic evidence
→ Critic-bound directional training link
→ output learner artifact
→ cached holdout metric run
→ observed-only quality review
→ unchanged policy decision
```

Fresh typed readback passed, including candidate/learner/bundle/registry hashes,
window identities, exact UTC bounds, model identity, metric identities, and
policy binding.

## Safety boundary

```text
data source:                  cached_only
provider/exchange calls:      none
exchange access:              false
candidate registry mutation:  none
candidate/learner mutation:   none
qualification:                not run
promotion state:              unpromoted
paper activation:             false
execution authority:          false
testnet/live orders:           none
scheduler:                    active
paper service:                active
research-related timers:      0
transient-related units:      0
temporary roots:              absent
```

The failed quality decision does not qualify, promote, admit, or activate the
learner. Thresholds were not relaxed and no automatic retraining was triggered.

## Execution notes

The first evaluation invocation persisted the metric run and ended before the
review stage. A continuation invocation reused that exact metric run and wrote
only the missing review and decision artifacts. It did not re-simulate the
holdout or create a second evaluation run. One reviewer assertion failed before
writing because the typed metric object was mistaken for a tuple; the reviewer
was corrected and fresh readback passed.

## Verification

```text
inference/learner focused regression:  81 passed
ruff check:                            passed
ruff format --check:                   passed
mypy:                                  passed
uv lock --check:                       passed
git diff --check:                      passed
remote holdout runner:                 completed
remote fresh chain verifier:           passed
remote runtime-state verifier:         passed
```

The inference implementation was pushed as `6019d81`. Its GitHub Actions
quality conclusion was not retrievable because the public GitHub API rate limit
was exhausted; no success is claimed here. Local gates and independent remote
readback are the verified evidence.

## Decision boundary

This learner remains blocked. Do not tune thresholds, reuse the same objective
blindly, or infer paper/testnet/live readiness from this result. The next
research step requires a separately specified falsifiable objective or a stop
in research; it does not authorize qualification or execution.
