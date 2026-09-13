# Strategy Research Root-Cause Audit — 2026-09-12

## Conclusion

The negative strategy results are **not explained by a detected simulator,
feature-causality, OOS aggregation, or current cached-data defect**. The
highest-ranked surviving explanation is ordinary negative economics for the
fixed hypotheses on the verified immutable scope.

The audit also found a documentation scope discrepancy: an older closure report
mentions `378,211` rows per symbol, while the currently approved
`scope-20260912` bundle contains `10,434` rows per symbol. Those totals belong
to different historical scopes and must not be combined.

## Falsified hypotheses

### 1. Feature lookahead or holdout warm-up defect — not supported

A synthetic current-bar mutation changed the close/high at a decision index.
The same-bar `ema_slope` and signal were unchanged. The production EMA path
uses `ema.diff().shift(shift)` with `shift=1`; the current decision candle is
not included in its own feature.

The production EMA experiment also calculated the full chronological feature
frame before slicing the OOS windows, preserving the prior-bar warm-up while
keeping the warm-up outside OOS rows/trades.

```text
synthetic feature causality:       PASS
same-bar feature mutation:         unchanged
same-bar signal mutation:          unchanged
```

### 2. Simulator fee/exit accounting defect — not supported

The deterministic constant-price probe matched the existing accounting
contract using 100% notional:

```text
starting equity:       100
position fraction:     1.0
fee rate:              0.0004
entry fee:             0.0400
exit fee:              0.0400
total fees:            0.0800
final equity:          99.9200
exit reason:           forced_end_of_window
```

The initial audit fixture incorrectly used a 10% position fraction while
expecting the 100% notional fee result; the actual `0.00400` per-side fee was
correct. The fixture was corrected and the invariant passed.

### 3. OOS window or aggregation mismatch — not supported

The audit recomputed the persisted EMA OOS aggregation from the immutable
5m Parquet frames and the full-history causal feature frame. The recomputed
content hash exactly matched the persisted aggregation:

```text
persisted aggregation hash:   fd28e547d5450f822bfc45c1e4ac6b7783ce98728942d4da4c5f91797e20e348
recomputed aggregation hash:  fd28e547d5450f822bfc45c1e4ac6b7783ce98728942d4da4c5f91797e20e348
qualification hash:           1841ce72220ac3cc9cc261d766708b3a19bfcf9ff94f8439e4882d6236ef28dd
decision:                     rejected
```

The aggregation contains 36 non-overlapping OOS windows: 12 windows × 288
bars for each of BTCUSDT, ETHUSDT, and SOLUSDT. The qualification artifact
contains the same candidate and aggregation bindings and eight failed gates.

### 4. Current cached-data quality defect — not supported

Each current 5m primary artifact was read through the canonical reader after
manifest and Parquet SHA-256 verification:

| Symbol | Rows | First open | Last open | Gaps | Duplicates | Zero-volume bars |
|---|---:|---|---|---:|---:|---:|
| BTCUSDT | 10,434 | 2026-07-01T00:00:00+00:00 | 2026-08-06T05:25:00+00:00 | 0 | 0 | 0 |
| ETHUSDT | 10,434 | 2026-07-01T00:00:00+00:00 | 2026-08-06T05:25:00+00:00 | 0 | 0 | 0 |
| SOLUSDT | 10,434 | 2026-07-01T00:00:00+00:00 | 2026-08-06T05:25:00+00:00 | 0 | 0 | 0 |

Canonical OHLC validation, timestamp ordering, duplicate detection, and
5-minute gap detection all passed for the current bundle.

## Surviving explanation

The fixed hypotheses produce genuinely weak/negative economics on the verified
scope. The latest pure EMA trend result remains:

```text
BTCUSDT: net -3.866554533669341533995245700, PF 0.1794274152339219633981776276
ETHUSDT: net -3.985533442171370319466538510, PF 0.2703143328155538658083496573
SOLUSDT: net -4.718094203779563592431370589, PF 0.1974930568487440569471489283
```

All three symbols passed drawdown/trade/window checks but failed profit factor
and average-return gates. The persisted rejected qualification is therefore
consistent with the raw ledger and reproducible from source data.

## Scope reconciliation

The current immutable bundle is:

```text
bundle hash:       108b5ce688f2c5389ceb60fb1a265d1db313bba184f9dcd4bf0e8541bb4abdaa
registry hash:     ee83e82abbbb0b9f47bf6a87f4577d4689bf6b72b5ed4ac3cf1f8c7f0b7ddba8
rows/symbol:       10,434
```

`STRATEGY_FAMILY_RESEARCH_CLOSURE_20260909.md` reports `378,211` rows per
symbol from an older historical scope. That report is retained as historical
evidence; its row totals are not used in this audit's recomputation.

## Safety

```text
audit mode:                 read-only
source:                     cached_only
provider/exchange calls:    none
candidate registry change:  none
paper mutation:             none
execution authority:        false
promotion state:            unpromoted
scheduler:                  active
paper service:              active
temporary audit root:       absent
```

No fix was applied because no product defect was found. No thresholds,
parameters, features, or simulator semantics were changed.

## Verification

```text
integrity regression:       46 passed
remote root-cause audit:    passed
aggregation recomputation:  exact hash match
runtime state check:        passed
```

## Boundary

Keep the strategy-research cycle closed. Do not rerun these hypotheses or tune
them to reverse the decision. A future research cycle requires a materially
different, explicitly falsifiable thesis and a clearly identified immutable
data scope. Qualification, paper admission, testnet, and live activation remain
blocked.
