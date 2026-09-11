# Strategy-family research closure — 2026-09-09

## Decision

The post-provider research boundary remains **NOT LIVE-READY**. Two bounded
Google AI Studio Creator/Critic cycles produced candidates, but both failed the
existing OOS qualification gates. A cached-only family probe then tested two
predeclared range-mean-reversion variants and one ADX-regime hypothesis on the
actual VPS Parquet bundle. No candidate was persisted into the paper registry,
no paper candidate was adopted, and no order authority was enabled.

Do not relax thresholds, auto-retry the same family, or use this evidence for
live activation.

## Runtime and data scope

- VPS source/runtime: `/opt/autonomous-futures-bot`, project Python 3.14 venv.
- Cached symbols available in this bundle: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`.
  `DOGEUSDT-5m.parquet` is absent from the VPS research root and was not
  fabricated or silently substituted.
- Each available symbol contains **378,211** canonical 5m rows.
- Family probe used the final **3,456 rows** per symbol: 12 contiguous OOS
  windows × 288 bars (12 days), range `2026-07-25T05:35:00+00:00` through
  `2026-08-06T05:30:00+00:00`.
- Accounting: starting equity `100.00`, position fraction `0.10`, taker fee
  `0.0005`, adverse slippage `0.0001`.
- All probe artifacts were written outside the repository source tree under
  `/opt/autonomous-futures-bot/artifacts/paper_live/family-probe-*`.
- `data_source=cached_only`, `exchange_access=false`,
  `paper_activation=false`, `execution_authority=false`.

The fixed policy indicator below uses the existing thresholds: pooled net PnL
≥ 0, pooled profit factor ≥ 1.05, average return ≥ 0, worst drawdown ≤ 15.0,
and at least 5 trades. Passing this indicator is **not** a qualification or
admission artifact; no candidate was admitted.

## Cached family results

| Symbol | Hypothesis | Windows / trades | Pooled net PnL | Pooled PF | Avg return | Worst DD | Fixed policy |
|---|---|---:|---:|---:|---:|---:|---|
| BTCUSDT | Bollinger z-score ±1.5 | 12 / 92 | -0.731214 | 0.589042 | -0.060934 | 0.311410 | FAIL |
| BTCUSDT | RSI 30/70 | 12 / 23 | -0.472674 | 0.530104 | -0.039390 | 0.303263 | FAIL |
| ETHUSDT | Bollinger z-score ±1.5 | 12 / 88 | -1.342521 | 0.489162 | -0.111877 | 0.425139 | FAIL |
| ETHUSDT | RSI 30/70 | 12 / 25 | -0.342976 | 0.717287 | -0.028581 | 0.531744 | FAIL |
| SOLUSDT | Bollinger z-score ±1.5 | 12 / 96 | -0.412250 | 0.779077 | -0.034354 | 0.499588 | FAIL |
| SOLUSDT | RSI 30/70 | 12 / 23 | 0.123919 | 1.124272 | 0.010327 | 0.412888 | PASS indicator only |

The isolated SOL RSI result is not portable evidence: BTC and ETH fail the same
hypothesis, so it cannot create a multi-symbol paper candidate.

## ADX-regime hypothesis

Predeclared hypothesis: `adx >= 25` plus causal `regime_trend` direction, with
exit on regime neutral/opposite. Same 12-window scope and fixed accounting:

| Symbol | Trades | Pooled net PnL | Pooled PF | Avg return | Worst DD | Fixed policy |
|---|---:|---:|---:|---:|---:|---|
| BTCUSDT | 103 | -1.608318 | 0.252780 | -0.134027 | 0.485088 | FAIL |
| ETHUSDT | 111 | -1.834511 | 0.389079 | -0.152876 | 0.521033 | FAIL |
| SOLUSDT | 98 | -1.607179 | 0.393665 | -0.133932 | 0.506491 | FAIL |

This family is closed for this exact hypothesis and data scope. No threshold
was relaxed and no parameter search was performed.

## Volatility-compression breakout family

The next major slice added the smallest causal implementation required for a
new family: `StrategySpec.family="volatility_compression_breakout"`, Creator
prompt support, and a prior-bar-only `bollinger_width` feature defined as
`4 * rolling_std / rolling_mean`, shifted by the declared feature shift. The
feature and family identity were covered by RED→GREEN tests; the related
focused suite passed **40 tests**, Ruff/format/mypy/lock/diff gates passed.

The production VPS source was not replaced for this probe. A temporary source
overlay ran the exact project venv against the same cached Parquet scope:

| Symbol | Trades | Pooled net PnL | Pooled PF | Avg return | Worst DD | Fixed policy |
|---|---:|---:|---:|---:|---:|---|
| BTCUSDT | 73 | -1.289989 | 0.392991 | -0.107499 | 0.607749 | FAIL |
| ETHUSDT | 70 | -0.989890 | 0.589301 | -0.082491 | 0.603972 | FAIL |
| SOLUSDT | 65 | -1.701089 | 0.360415 | -0.141757 | 0.479169 | FAIL |

The predeclared hypothesis used `bollinger_width <= 0.04`, z-score breakout
at `±1.5`, and `adx >= 20`, with exits at z-score neutral or ADX below 15.
It failed all three required symbols. No candidate was persisted, admitted,
hot-reloaded, or sent to paper execution.

The existing Windows concurrency-churn regression had a timing-sensitive
assertion: a 1.8-second daemon budget occasionally processed only 102–104 of
120 queued frames while still shutting down cleanly. The test budget was
raised to 5.0 seconds; the daemon and its semantics were unchanged. The exact
regression passed after the correction.

## Provider-cycle evidence

Two explicitly bounded provider cycles preceded the offline family probe:

1. `provider-cycle-20260909T081918Z-5b498f`: `google_ai_studio`,
   `gemma-4-31b-it`, OOS net PnL `-1.978258065055483744607391235`, PF
   `0.2086356779300791`, 92 trades / 3 windows, rejected.
2. `provider-cycle-20260909T082421Z-73f23a`: same provider/model, OOS net PnL `-2.537885045728945847378384533`,
   PF `0.1982533065034465`, 107 trades / 3 windows, rejected.

Each cycle used one Critic call and one Creator call through the non-retry,
no-fallback governors. Neither candidate reached paper admission.

## Runtime safety read-back

At final observation:

- Scheduler: `active/running`, PID `743899`, `NRestarts=0`.
- Paper daemon: `active/running`, PID `702991`; no restart performed by this
  research work.
- Paper ledger: 56 opens / 56 closes, sequence 112, dirty intents 0.
- Active paper positions: 0; circuit breaker remains `HALTED` (fail-closed).
- Safety: `orders_submitted=0`, `execution_authority=false`,
  `live_trading_activation=false`, `promotion_state=unpromoted`.

## Next boundary

Do not run another Creator/Critic retry against these rejected hypotheses.
The volatility-compression slice is also rejected on the current cached scope.
The next useful work is a root-cause audit of simulator/data semantics or a
new family design with cross-symbol gates from the start. Live account
activation remains blocked until a portable qualified candidate, healthy paper
state, and fresh live review/preflight exist.
