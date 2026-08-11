# Phase 6S Verification — ADX-gated RSI qualification

## Decision

Phase 6S is **qualified as research evidence** under the unchanged strict
cached-only policy. This is not promotion, paper activation, or execution
authority.

The materially new thesis was a low-ADX RSI range-reversion family:

```text
long:  rsi < 30 and adx < 20
short: rsi > 70 and adx < 20
exit:  rsi >= 50 / rsi <= 50
```

Both features are causal with `shift=1`; only prior completed bars are used.
The immutable Phase 6N scope was reused read-only, with a fresh candidate,
registry, run ID, seed, aggregation, and qualification artifact root.

## Qualification evidence

```text
candidate:          cand-scope-rsi-adx-001
creator run:        phase6s-scope-rsi-adx-seed-107
seed:               107
OOS windows:        6 (2 per symbol)
trades:             39
pooled net P&L:     +5.777224535992551235427709859
average return:    +0.9628707559987585392379516433%
profit factor:      4.870774363919642091595510446
worst drawdown:     0.8410242297374457586501392127%
decision:           qualified
```

Per-symbol gates:

```text
BTCUSDT: trades=15, average=+0.7206835853482000267384381735%, PF=3.313699538559618251626133320, DD=0.7917652618601403938026788116%
ETHUSDT: trades=10, average=+0.9050532163533989500798933335%, PF=3.292201947651466724570640957, DD=0.8410242297374457586501392127%
SOLUSDT: trades=14, average=+1.262875466294676640895523423%, PF=32.62197042618757380440060368, DD=0.6156961538909343655134980015%
```

All required-symbol trade, average-return, profit-factor, drawdown, and
window gates passed. Policy thresholds were unchanged:

```text
minimum trades:          10
minimum average return:  0%
minimum profit factor:   1.10
maximum drawdown:        8%
minimum windows:         2
```

## Immutable artifacts

Remote root:
`research/immutable-data/phase6s/`

```text
candidate artifact hash:      2b426bd9bf3b827ce42bcd8ca9c2200b5d110e3d79fb95df14ad94f8685faa52
aggregation artifact hash:    cc1a0bd456828ec3f8ec6ec2705bcf787758e337a9a93a579612e8ec0bfdf4ce
qualification artifact hash:  999f0fbc96629aa66b6090a89d4d376c2d689f98445386f79507f25ef8247de0
```

The candidate, aggregation, and qualification files were read back on Kainode
and persisted under the fresh Phase 6S root. The temporary runner was removed
locally and remotely.

## Verification

```text
Local focused feature suite: 11 passed
Local full locked suite:     488 passed
Remote project suite:        488 passed via .venv/bin/python -m pytest -q
Local Ruff:                  passed
Local format:                passed
Local mypy:                  121 source files clean
Local lock/diff checks:      passed
Exact remote commit:         146b6a281f82a958f50839d0fd46b4b41343b3e7
```

Remote `uv` was not available on PATH, so a remote `uv run --locked` result is
not claimed. The remote `.venv` interpreter suite passed and the project
checkout was synchronized to the exact pushed commit before execution.

## Safety boundary

Qualification is evidence only. No candidate lifecycle or execution state was
mutated by the runner.

```text
promotion_state:      unpromoted
paper_activation:     false
execution_authority:  false
exchange_access:      false
data_source:          cached_only
```

Paper observation remains blocked until a separate human-approved activation
phase reviews this evidence and confirms the paper-safety prerequisites.
