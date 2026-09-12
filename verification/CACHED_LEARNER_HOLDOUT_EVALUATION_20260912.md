# Cached Learner Holdout Evaluation — 2026-09-12

## Decision

The explicit `linear_next_return` learner baseline is **REJECTED as a useful
model candidate** on the chronological 70/30 holdout. All three symbols lost
after fees and slippage, with profit factors below `0.24`.

This is observed-only learner evidence. It is not a qualification, promotion,
paper-admission, or live-readiness decision.

## Runtime and provenance

```text
source contract commit: b1e7b7a34b508378069e771b2249e5dc2dae95a4
bundle hash:            108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:          ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
candidate:              cand-learner-bootstrap-20260912
candidate hash:         ff820a97555add3c28a7986ac60319536bcd54ad582fc35a6e54097834f0a5ff
learner:                learner-holdout-20260912
learner hash:           10ba3cba75483d131d67748b3f69395d9426dca90e006eed9f3fe3ff0707fea7
model family:           linear_next_return
model hash:             bef3f623a7ab659ddc81f92a41c5ff8d2ddb7bb0d36783b0a6f42f56bac0a944
```

The model was trained only on the first `70%` of each symbol's primary frame
and evaluated on the final `30%`. The model objective was
`next_bar_close_return` from the causal `returns` feature with shift `1`.

```text
training range:         2026-07-01T00:00:00Z → 2026-07-26T08:35:00Z
holdout range:          2026-07-26T08:35:00Z → 2026-08-06T05:30:00Z
training rows/symbol:   7,303
holdout rows/symbol:    3,131
symbols:                BTCUSDT, ETHUSDT, SOLUSDT
```

The explicit simulation policy was identical across symbols:

```text
starting equity:        100
position fraction:      0.10
taker fee rate:         0.0005
slippage rate:          0.0001
ATR lookback:           14
stop / target / trail:  1.5 / 3.0 / 1.0
```

## Holdout metrics

| Symbol | Trades | Net PnL | Return | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 1,050 | -12.59857745717079934037539306 | -12.59857745717079934037539306% | 0.1443020873837945756 | 12.59857745717079934037539333% |
| ETHUSDT | 1,024 | -12.89908015195883833839761693 | -12.89908015195883833839761693% | 0.2314380097556631247 | 12.92307148751734472644304287% |
| SOLUSDT | 1,040 | -13.55508237020295819874891395 | -13.55508237020295819874891395% | 0.2034157423631405485 | 13.55508237020295819874891395% |

All symbols independently fail economic usefulness. No gate was relaxed and no
second seed or parameter retry was run.

## Persisted evidence

```text
prepared run:           run-learner-holdout-20260912
prepared run hash:      0c6d291c35f948375e73ddc9af0368789af0028ef878f9b65517c51a6a3966d7
metric schema:          evaluation_version=2
evaluation run:         learner-holdout-evaluation-v3-20260912
evaluation hash:        1867c66fd4bbdb4c2a2788d1fc9ca19ce74687a805ae70cfcfb1c23b76454596
review:                 metric-quality-review-holdout-v3-20260912
review hash:            1ebd7e4a20b107ed565b607874e87d63911d828ebe5d8521fe04a02c50bc0157
review conclusion:      observed_only
```

Remote evidence is retained outside source control under:

```text
research/learner-evidence/evaluation-v3-20260912/
```

The evidence includes the holdout UTC bounds per symbol, model artifact,
prepared run, metric evaluation, and observed-only quality review. Every
artifact was read back through its shared verifier and bound to the exact
bundle, dataset registry, candidate, and learner hashes.

## Integrity correction

The first evaluation attempt was not accepted. The metric evaluation schema did
not persist per-window UTC bounds, so its holdout chronology could not be proven.
The contract was corrected in `b1e7b7a`:

- `LearnerMetricWindowEvaluation` now persists validated UTC `time_start` and
  `time_end`;
- the metric evaluation schema is version `2`;
- the adapter copies bounds from the input window;
- old version-1 evidence remains preserved but unavailable/historical and was
  not rewritten.

A second attempt persisted the bounds but was also quarantined: its temporary
trainer changed the process-wide Decimal precision, producing metrics that
validated only in-process and failed fresh-process readback. The final v3 run
uses `localcontext()` for fitting only; the simulator and persistence run under
the normal context. Independent readback passed.

## Verification

```text
learner metric/review focused tests: 53 passed
all learner related tests:           122 passed
Ruff check:                          passed
Ruff format:                         passed
Mypy:                                passed
uv lock check:                       passed
changed-module py_compile:           passed
git diff/show check:                 passed
GitHub Actions for b1e7b7a:          quality success
remote bundle components:            13 / 13 verified
remote evaluation/review readback:   passed
temporary runner/source roots:       removed
```

Local repository-wide `compileall` was not used as a pass claim: Windows hit the
known pre-existing long-module-name `.pyc` race in unrelated `research_lab`
files. The pushed GitHub quality workflow provides the full Linux test,
compile, lint, format, and type gate.

## Safety boundary

```text
data_source:          cached_only
exchange_access:      false
provider/LLM calls:   none
candidate registry:   unchanged
qualification:        none
promotion state:      unpromoted
paper activation:     false
execution authority:  false
testnet/live orders:   none
```

The baseline is not eligible for learner promotion or paper use. Do not blindly
retrain this same baseline or tune thresholds to reverse the holdout result.
The next justified learner boundary is an explicitly approved Critic-evidence
training handoff or a deterministic policy-decision contract; both remain
read-only and separate from candidate qualification.
