# Entry/exit and cost attribution — diagnosis and analytics correction

## Scope and provenance
Main-session analysis; no cron, subagents, tuning, forced trades or VPS changes. User authorized takeover of the pre-existing failing analytics test. Read-only transactional ledger query at the documented pinned VPS, with mode=ro/query_only/busy_timeout. Cohort = trades whose open sequence is >80; eight completed trades in the returned snapshot, close sequences82 through96. Latest selected lifecycle mark was read separately and is not an atomic cross-database snapshot. Audit assembled at 2026-09-08T06:23:02.933490+00:00. This newer cohort does not rewrite Phase276's six-trade snapshot.

## Actual attribution
| Close seq | Symbol / side | Seconds | Gross PnL | Fees | Net PnL | Latest lifecycle |
|---|---|---:|---:|---:|---:|---|
| 82 | SOLUSDT SHORT | 489 | -0.04740597872000 | 0.035176439825420800 | -0.082582418545420800 | open / lifecycle_open |
| 84 | SOLUSDT SHORT | 218 | -0.09580567728000 | 0.035756560794192000 | -0.131562238074192000 | open / lifecycle_open |
| 87 | SOLUSDT LONG | 300 | -0.03116561188800 | 0.031665465002630400 | -0.062831076890630400 | open / lifecycle_open |
| 89 | SOLUSDT SHORT | 112 | -0.06392442997200 | 0.030768503827214400 | -0.094692933799214400 | open / lifecycle_open |
| 90 | DOGEUSDT SHORT | 735 | 0.0353956890672200 | 0.03967515844689836000 | -0.00427946937967836000 | open / lifecycle_open |
| 92 | DOGEUSDT LONG | 153 | -0.0405597580651520 | 0.03396029881667276800 | -0.07452005688182476800 | open / lifecycle_open |
| 95 | DOGEUSDT SHORT | 600 | 0.0104245631502400 | 0.00794494902775694080 | 0.00247961412248305920 | open / lifecycle_open |
| 96 | BTCUSDT SHORT | 1356 | 0.026103137760 | 0.0079209220749120 | 0.0181822156850880 | exit_ready / take_profit_hit |

```json
{
  "closed": 8,
  "gross_pnl": "-0.2069380659476920",
  "fees": "0.22286829781569766880",
  "net_pnl": "-0.42980636376338966880",
  "net_winners": 2,
  "positive_gross_but_net_loss": 1
}
```

Money uses Decimal; each gross minus both commissions equals net exactly. Slippage is reported by the ledger separately but already incorporated in fills: do not subtract it again from net. Positive gross turning negative after commissions occurs in the recovered DOGE trade. Losses on other trades cannot be explained solely by commissions. These short observations are not OOS qualification or proof of persistent edge.

## Root cause and minimal correction
`LivePaperEngine.execute_close` receives exit_reason but only writes it to the info log. Its final persisted lifecycle mark is recomputed from fixed stop/target; it does not durably preserve the passed trailing/signal reason. Seven selected latest marks remain lifecycle_open; BTC's take_profit_hit mark is evidence of a trigger condition, not a new typed final-close reason contract. The exact causes of the other exits are unavailable from these persisted marks and must not be inferred from price geometry.

Analytics incorrectly turned missing reason evidence into normal_close. Corrected reader fallback and TradeRecord construction/deserialization defaults to unavailable. Explicit supplied reasons are preserved. Added missing-field deserialize regression alongside the existing mixed known/missing lifecycle reader test. RED failures demonstrated both fallback paths before correction; focused26 PASS and Ruff/format/mypy230/lock/diff gates PASS.

## Boundaries
No strategy change is supported by this small sample. Historical missing reasons cannot be backfilled by guesses. TUI's separate legacy display fallback must not be used as evidence for this audit. No deployment or daemon restart performed.

## Integrated root fix

The same milestone now preserves the supplied exit reason in the existing append-only lifecycle store after a successful runtime close, using lifecycle_status=closed and the exact reason_codes tuple. The typed lifecycle and health contracts accept the new terminal status. No extra database, migration table, strategy authority or price execution change was added. The existing dirty-intent protocol still surrounds the final lifecycle write, and no prior marks are rewritten.

The real open/update/restart/close/restart regression first failed because the stored final mark remained open. After correction it reads the final closed mark and its exact reason through SQLite, then reads the same reason through the analytics consumer and proves the subsequent engine is flat with two ledger events. Focused accounting/recovery tests: 40 passed in 3.05s. Ruff, format, mypy (230 source files), lock and diff gates pass. The earlier analytics-only snapshot passed 1948 tests in 416.73s; full verification of this expanded final source is pending, not covered by that earlier run.

Compatibility boundary: older code whose lifecycle Literal excludes closed cannot consume new final marks. Any code rollout must include the lifecycle/health/analytics readers together; no automatic old-code rollback or restart with unmatched legacy evidence is authorized by this report.
