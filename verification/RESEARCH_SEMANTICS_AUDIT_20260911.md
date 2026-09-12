# Research simulator/data semantics audit — 2026-09-11

## Scope

This audit covers the cached-only research path used by
`simulate_candidate_window()`:

- causal feature materialization;
- entry and strategy-exit timing;
- protective stop execution under an opening gap;
- canonical OHLC data validation.

No provider call, paper admission, VPS runtime mutation, testnet order, or live
activation was performed.

## Findings and remediation

### 1. ADX warmup was converted from unknown to zero

The ADX feature used `fillna(0)` before the required prior-bar shift. A bounded
ADX-low entry therefore appeared during indicator warmup. The RED regression
observed an entry at the second bar with no valid ADX history.

Remediation: preserve `NaN` until ADX has enough completed bars. The same
unknown-preserving treatment is applied to the derived `regime_trend` state.

### 2. Research ignored declared strategy exits

The feature evaluator produced only fresh entry signals. The research simulator
therefore ignored `StrategySpec.exit`, while the paper runtime evaluated it. A
bounded regression showed the simulator holding until forced window close instead
of closing at the declared exit condition.

Remediation: materialize `long_exit_condition` and `short_exit_condition`,
validate their referenced features, and evaluate the active side's exit at the
next bar open before reversal handling. Overlapping long/short exit conditions
remain valid because position side disambiguates them.

### 3. Protective stops ignored adverse opening gaps and slippage

A stop triggered on a bar opening beyond the stop was filled at the theoretical
stop price with no exit slippage. This understated loss. The RED regression
changed the expected long stop fill from `97.00` to `89.10` for a `90.00` open
with `1%` slippage.

Remediation: stop and trailing-stop fills use the worse of the bar open and
trigger price, then apply direction-aware slippage. Take-profit fills retain the
configured target-price behavior.

### 4. Cached OHLC geometry was not enforced by the shared canonicalizer

`canonicalize_bars()` checked timestamps but accepted inverted or non-enveloping
OHLC values when all four price columns were present.

Remediation: the shared canonicalizer now rejects non-finite, non-positive, or
geometrically invalid OHLC values. Existing timestamp/open/close-only metadata
frames remain supported.

## Evidence impact

The pinned historical candidate previously asserted as qualified by legacy tests
is now correctly rejected after strategy exits are applied:

- pooled net PnL: `-976.3836683548420434542667350`;
- pooled profit factor: `0E+25`;
- average return: `-3.254612227849473478180889117%`;
- worst drawdown: `4.313755796774210217271333680%`;
- total trades: `5`.

The qualification gates were not relaxed. Existing tests were updated to reflect
this corrected fail-closed result.

## Verification

- research/data/qualification focused suite: **135 passed**;
- exact ADX warmup, strategy-exit overlap, adverse-gap stop, and OHLC geometry
  regressions: **passed**;
- full locked suite: **2,184 passed in 608.44s**;
- Ruff check, format check, mypy, lock check, and `git diff --check`: **passed**.

The result remains research-only. No candidate is admitted or live-ready based
on this audit.
