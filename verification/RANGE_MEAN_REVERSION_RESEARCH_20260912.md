# Range Mean-Reversion Research — 2026-09-12

## Decision

The fixed `range_mean_reversion` / Bollinger-z-score hypothesis is **REJECTED**
on the cached multi-symbol scope. No provider call, candidate persistence,
registry publication, paper admission, testnet order, or live activation was
performed.

## Hypothesis

Use a pure Bollinger mean-reversion excursion with prior-bar bands:

- feature: `bollinger_zscore`, lookback `20`, shift `1`;
- long entry: `bollinger_zscore < -2.0`;
- short entry: `bollinger_zscore > 2.0`;
- long exit: `bollinger_zscore >= 0.0`;
- short exit: `bollinger_zscore <= 0.0`;
- position fraction `0.10`;
- stop `2.0 ATR`, take-profit `1.0 ATR`, trailing stop disabled;
- taker fee `0.0005`, adverse slippage `0.0001`, starting equity `100`.

The production causal evaluator and deterministic simulator were reused. No
new family code or enum was required; `range_mean_reversion` is the existing
schema-compatible family label.

## Cached scope

- source: immutable canonical 5m Parquet;
- symbols: BTCUSDT, ETHUSDT, SOLUSDT;
- rows per symbol: `378211`;
- evaluated tail: `3456` rows per symbol;
- windows: `12` contiguous windows × `288` bars per symbol;
- data source: cached only; exchange/provider calls: `0`.

## Results

| Symbol | Windows | Trades | Net PnL | Profit factor | Average window return | Worst drawdown |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 164 | -2.288165532238638235944097426 | 0.0651363248827970696 | -0.1906804610198865197% | 0.2871636057327429202% |
| ETHUSDT | 12 | 191 | -2.335294511805785077336396384 | 0.2152004297926072841 | -0.1946078759838154231% | 0.3934393221095903654% |
| SOLUSDT | 12 | 167 | -2.392623158720130901391474996 | 0.1832265955617661711 | -0.1993852632266775751% | 0.3984697964502666667% |

Fixed policy required, independently for every symbol:

- non-negative net PnL;
- profit factor at least `1.05`;
- non-negative average window return;
- worst drawdown at most `15%`;
- at least `5` trades.

All three symbols failed net PnL, profit factor, and average return conditions.
The drawdown cap and minimum-trade condition passed, but that does not offset
the negative-return evidence. The hypothesis is closed; do not retry the same
parameters or relax gates.

## Safety and delivery

- The probe used temporary code only; the temporary file was removed after the
  run.
- Candidate artifact and qualification roots were not written.
- Paper registry, paper ledger, scheduler, testnet, and live state were not
  modified.
- Existing paper containment remains in force: registry quarantined/empty,
  paper entry map empty, breaker state `THROTTLED`, and live authority off.
- Repository gates already passed on the current implementation: **2,194 tests
  passed**, Ruff/format/mypy/lock/diff all passed.

This result is negative research evidence, not a qualification result. The
next strategy attempt requires a materially different falsifiable thesis and a
fresh cached scope; provider retries and paper activation remain unnecessary.
