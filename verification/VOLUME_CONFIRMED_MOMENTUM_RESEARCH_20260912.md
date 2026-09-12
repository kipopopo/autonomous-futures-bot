# Volume-confirmed momentum research — 2026-09-12

## Decision

The predeclared `volume_confirmed_momentum` hypothesis is **REJECTED** on the
cached multi-symbol scope. No provider call, candidate persistence, paper
admission, registry publication, testnet order, or live activation was
performed for the research run.

## Hypothesis

Use a causal 5m impulse plus a relative-volume surge:

- long entry: `returns > 0.005 and relative_volume > 1.5`;
- short entry: `returns < -0.005 and relative_volume > 1.5`;
- long exit: `returns <= 0`;
- short exit: `returns >= 0`;
- `returns`: lookback 3, shift 1;
- `relative_volume`: lookback 20, shift 1;
- position fraction `0.1`, stop `1.5 ATR`, take-profit `3.0 ATR`, trailing stop
  `1.0 ATR`;
- taker fee `0.0005`, adverse slippage `0.0001`, starting equity `100`.

The new feature preserves unknown values during zero-volume baselines and uses
only completed prior bars. The explicit family is
`volume_confirmed_momentum`.

## Cached scope

- symbols: BTCUSDT, ETHUSDT, SOLUSDT;
- source: local immutable canonical 5m Parquet bundle;
- rows per symbol: `378211`;
- evaluated tail: `3456` rows per symbol;
- OOS layout: 12 contiguous windows × 288 bars per symbol;
- total windows: `36`;
- volume quality: 8 zero bars, 0 negative bars, 0 non-finite bars in the BTC
  cache probe.

## Results

| Symbol | Windows | Trades | Net PnL | Profit factor | Average return | Worst drawdown |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 6 | -0.1294118180465390410546292902 | 0.0605700712369594213 | -0.0107843181705449201% | 0.0373571277517427177% |
| ETHUSDT | 12 | 19 | -0.2340020590645684202699032021 | 0.4253847406601487452 | -0.0195001715887140350% | 0.0971147970876975282% |
| SOLUSDT | 12 | 13 | -0.2904659506381670626394824468 | 0.0350195584458475261 | -0.0242054958865139219% | 0.1045783093637255176% |
| **Pooled** | **36** | **38** | **-0.6538798277492745239640149390** | **0.2270881664322187314** | **-0.0181633285485909590%** | **0.1045783093637255176%** |

Fixed indicator: **FAIL**. It required non-negative pooled PnL, profit factor
at least `1.05`, non-negative average return, worst drawdown at most `15`, and
at least 5 trades. Every required symbol had negative net PnL and profit factor
below `1.0`.

## Verification

- relative-volume causal/zero-baseline regression: passed;
- explicit family contract and Creator prompt regression: passed;
- full locked suite: `2186 passed`;
- no candidate was qualified or admitted from this hypothesis.

## Code-only VPS stage

After local verification, the six runtime source files needed for this feature
and its semantic dependencies were staged to the VPS. Local and remote
SHA-256 values matched. A read-only SQLite source backup was created and
verified with `PRAGMA integrity_check=ok` before the copy.

The active paper and scheduler processes were not restarted. Post-stage
readback remained: paper `active/running`, `NRestarts=9`; scheduler
`active/running`, `NRestarts=0`; ledger `161 opens / 160 closes`, dirty intents
`0`; scheduler health `33 cycles / 0 admitted`, last
`completed_unadmitted`; execution authority `false`, live activation `false`,
and orders `0`. Remote AST parsing of all staged files passed.

This is source staging only, not activation of the new code in the running
processes. A controlled paper-service restart remains blocked by the current
HALTED state, open paper position, and missing complete resume evidence.

The family is closed for this exact hypothesis and data scope. Do not retry the
same parameters or relax gates to manufacture a pass. Live readiness remains
blocked by the absence of a portable qualified candidate and by the current
paper HALTED state.
