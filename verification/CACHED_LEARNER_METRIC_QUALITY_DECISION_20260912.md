# Cached Learner Metric-Quality Decision — 2026-09-12

## Decision

The exact v3 learner holdout is **FAILED** under the unchanged explicit metric-quality policy.

```text
minimum windows:              1
max_drawdown_pct:             <= 25
net_pnl:                      >= 0
profit_factor:                >= 1
```

All three symbols pass the drawdown ceiling but fail both economic gates:
`net_pnl >= 0` and `profit_factor >= 1`. This is a deterministic quality
**decision evidence** result. It is not learner qualification, promotion, paper
admission, testnet authority, or live authority.

## Runtime and provenance

```text
model:                        GPT-5.6 Luna
provider:                     OpenAI Codex
Effort:                       Medium
source commit:                f4caba00f53d7c5ccc5e93d9a8e9dc643feb52d8
bundle hash:                  108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:                ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
candidate:                    cand-learner-bootstrap-20260912
candidate artifact hash:      ff820a97555add3c28a7986ac60319536bcd54ad582fc35a6e54097834f0a5ff
learner:                      learner-holdout-20260912
learner artifact hash:        10ba3cba75483d131d67748b3f69395d9426dca90e006eed9f3fe3ff0707fea7
metric evaluation:            learner-holdout-evaluation-v3-20260912
metric evaluation hash:       1867c66fd4bbdb4c2a2788d1fc9ca19ce74687a805ae70cfcfb1c23b76454596
```

The v3 metric run used the chronological 70/30 split already recorded in
`CACHED_LEARNER_HOLDOUT_EVALUATION_20260912.md`:

```text
training: 2026-07-01T00:00:00Z → 2026-07-26T08:35:00Z
holdout:  2026-07-26T08:35:00Z → 2026-08-06T05:30:00Z
symbols:  BTCUSDT, ETHUSDT, SOLUSDT
```

## Policy evidence

```text
policy ID:                    learner-quality-policy-001
policy hash:                  c181c8587fdc525a49bd86d30ce56a642d699d1c85eb9e4c828890284445f500
review ID:                    metric-quality-review-holdout-v4-20260912
review hash:                  34b9865c3c4224708fc986b4abd54cb97255c618cffa73448501cc69e8b0b18a
reviewed at:                  2026-09-12T12:30:00Z
decision ID:                  metric-quality-decision-holdout-v4-20260912
decision hash:                1a50b1bddb2489c55437ed98917d63a615e84dfbe907c62ef5eb90123f46643c
evaluated at:                2026-09-12T13:00:00Z
windows evaluated:            3
```

The corrected review stores the canonical metric IDs exactly as:

```text
max_drawdown_pct
net_pnl
profit_factor
```

The initial decision attempt used non-canonical `observed_*` IDs. It failed
closed with `metric_missing`, was never published, and its temporary root was
deleted. The policy was not weakened. A corrected immutable review was built
from the same verified v3 metric run and the decision was evaluated once against
that review.

## Per-symbol gates

| Symbol | Drawdown observed | Drawdown | Net P&L observed | Net P&L | Profit factor observed | Profit factor |
|---|---:|:---:|---:|:---:|---:|:---:|
| BTCUSDT | 12.59857745717079934037539333 | PASS | -12.59857745717079934037539306 | FAIL | 0.1443020873837945756258686315 | FAIL |
| ETHUSDT | 12.92307148751734472644304287 | PASS | -12.89908015195883833839761693 | FAIL | 0.2314380097556631247065497693 | FAIL |
| SOLUSDT | 13.55508237020295819874891395 | PASS | -13.55508237020295819874891395 | FAIL | 0.2034157423631405484692304732 | FAIL |

Aggregate gate evidence:

```text
minimum_windows:   observed 3 >= 1 — PASS
BTC net_pnl:       -12.59857745717079934037539306 >= 0 — FAIL
BTC profit_factor:  0.1443020873837945756258686315 >= 1 — FAIL
ETH net_pnl:       -12.89908015195883833839761693 >= 0 — FAIL
ETH profit_factor:  0.2314380097556631247065497693 >= 1 — FAIL
SOL net_pnl:       -13.55508237020295819874891395 >= 0 — FAIL
SOL profit_factor:  0.2034157423631405484692304732 >= 1 — FAIL
```

Reason codes are deterministic: `minimum_windows_passed`,
`metric_passed` for the three drawdown gates, and `metric_below_threshold`
for every net-P&L and profit-factor gate.

## Persisted evidence and readback

The corrected review and decision are retained outside source control at:

```text
/opt/autonomous-futures-bot/research/learner-evidence/metric-quality-decision-v2-20260912/review/review.json
/opt/autonomous-futures-bot/research/learner-evidence/metric-quality-decision-v2-20260912/decision/decision.json
```

A fresh-process verifier rebuilt the complete chain:

```text
v3 metric evaluation
→ verified corrected observed-only review
→ persisted metric-quality decision
```

Verified facts:

```text
source bytes preserved:       true
symbols:                      BTCUSDT, ETHUSDT, SOLUSDT
review metric IDs:            max_drawdown_pct, net_pnl, profit_factor
review conclusion:            observed_only
readback:                     pass
```

Temporary remote source/runner/evidence root was removed after verification:

```text
temporary root:               absent
local temporary files:        clean
```

## Safety boundary

```text
data source:                  cached_only
provider/exchange calls:      none
exchange access:              false
qualification:                not run
promotion state:              unpromoted
paper activation:             false
execution authority:          false
testnet/live orders:           0
candidate/learner mutation:   0
```

This failed decision is durable research evidence only. It does not reject the
candidate lifecycle by mutation, but it makes this baseline ineligible for
promotion or paper use under the current policy. Do not tune thresholds or
blindly retrain the same baseline to reverse the result.

## Verification

```text
metric/review focused regression: 53 passed in 2.33s
prior related learner suite:      122 passed
Ruff/format/mypy/lock:             passed on source commit f4caba0
GitHub full quality for f4caba0:   success
fresh-process chain readback:     passed
remote cleanup:                   passed
repository after report commit:  clean and synchronized
```

No production code changed for this decision run. Browser/API dogfood is not
applicable: this was a backend research evidence operation with no UI or HTTP
surface.

## Next boundary

Stop this baseline here. The next justified work is a materially new falsifiable
learner objective or an explicitly approved Critic-evidence training handoff,
with the same cached-only and non-authoritative boundary. No paper, testnet, or
live work follows from this failed decision.
