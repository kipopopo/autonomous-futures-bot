# Donchian Channel Breakout Research — 2026-09-12

## Decision

The fixed `donchian_channel_breakout` hypothesis is **REJECTED** on the cached
multi-symbol scope. No provider call, candidate persistence, registry
publication, paper admission, testnet order, or live activation was performed.

## Implementation

Added the schema-compatible family and causal `donchian_breakout` feature:

- family: `donchian_channel_breakout`;
- feature: signed binary breakout, lookback `20`, shift `1`;
- long entry: `donchian_breakout > 0.5`;
- short entry: `donchian_breakout < -0.5`;
- long exit: `donchian_breakout < 0.5`;
- short exit: `donchian_breakout > -0.5`.

The feature compares each decision with the prior Donchian high/low channel,
preserves warmup unknowns, emits fresh long/short states, and does not use the
current decision candle's range. The source frame remains unchanged.

## Cached scope and fixed policy

- source: immutable canonical 5m Parquet;
- symbols: BTCUSDT, ETHUSDT, SOLUSDT;
- rows per symbol: `378211`;
- evaluated tail: `3456` rows per symbol;
- windows: `12` contiguous windows × `288` bars per symbol;
- position fraction: `0.10`;
- stop/take-profit/trailing: `1.5 / 3.0 / 1.0 ATR`;
- taker fee: `0.0005`;
- adverse slippage: `0.0001`;
- starting equity per window: `100`;
- gates: non-negative net PnL, profit factor `>=1.05`, non-negative average
  window return, worst drawdown `<=15%`, and at least `5` trades per symbol.

## Results

| Symbol | Windows | Trades | Net PnL | Profit factor | Average window return | Worst drawdown |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 236 | -3.159705050960676350896513629 | 0.1024163835247494419 | -0.2633087542467230292% | 0.38614763003773717395% |
| ETHUSDT | 12 | 208 | -2.901717213100706029721923076 | 0.1945327572277495634 | -0.2418097677583921691% | 0.48203136116568906670% |
| SOLUSDT | 12 | 218 | -3.120737335454145645614264291 | 0.1709387755597797364 | -0.2600614446211788038% | 0.38295147979998343975% |

All three symbols failed net PnL, profit factor, and average-return gates.
Drawdown and minimum-trade gates passed, but cannot offset the negative-return
evidence. The family is closed; do not retry these parameters or relax gates.

## Verification and safety

- Donchian contract/prompt/causality targeted tests: **4 passed**.
- Related contract/evaluator tests: **48 passed**.
- Ruff check, format check, mypy, lock check, and diff check: **PASS**.
- Local full pytest was intentionally stopped at approximately `65%` after the
  user confirmed GitHub Actions is the post-push full quality gate; it is not
  reported as a local pass.
- The temporary cached probe was deleted after execution.
- The probe made no provider, exchange, paper-ledger, registry, testnet, or live
  mutation.

The next full quality result belongs to the GitHub Action for the pushed commit.
This negative result is research evidence only, not qualification or promotion.
