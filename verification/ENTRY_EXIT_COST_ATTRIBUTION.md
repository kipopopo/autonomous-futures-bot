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


## Final regression and paper deployment

- Final source commit: `77b747ba17a1194bc09e77d14cce76580ed560f2`; push and exact origin/main SHA verified before rollout.
- Post-commit locked full suite: **1948 passed in 409.54s**.
- Isolated staged VPS regression: **40 passed in 5.64s**. Existing virtualenv invoked directly (not claimed as a new locked sync); relative interpreter invocation emitted sys.prefix warnings. Dependencies/lockfile were not changed.
- Source/tests/scripts staged from candidate archive; runtime database, configuration, credentials and logs were not overwritten. Both services restarted after successful preflight and final post-stop zero-open/zero-dirty gate. Ledger retained 96 events before and after stop.
- Online verified backups: `/opt/autonomous-futures-bot/artifacts/paper_live/backups/exit-attribution-20260908T064148Z-paper-ledger.sqlite3` and same prefix `paper-lifecycle.sqlite3`; each integrity check passed.
- Staged/deployed source manifest: `01f91c6808d47944b6ce7c39deea43fd6c924e099d7265cbcb4668d1901ee72e`, 455 source/test/script files excluding generated bytecode. Algorithm: sorted relative paths, UTF-8 path + NUL + SHA256(file bytes), accumulated SHA256.
- Independent remote readback verified all five changed production files against the exact uploaded archive. Git archive applied CRLF to these files; archive/remote bytes match exactly and normalized text matches committed Git blobs. Raw blob hash comparison initially failed due to this EOL distinction, not source drift.
- Paper PID 695336 and Telegram PID 695342 active/running, NRestarts=0, ExecMainStatus=0.
- Fresh health heartbeat `2026-09-08T06:43:21.810374+00:00`: paper=true, execution_authority=false, live_trading_activation=false, orders_submitted=0; zero positions. Ledger integrity ok, 48 opens/48 closes, dirty intents0. Cash `99.39986399373993908320` matches starting100 plus all closed net PnL exactly at this flat snapshot.
- First inline remote cutover invocation failed shell quoting before Python/action; a syntax-checked uploaded verifier then completed. No repeated service restart from that failed invocation.
- Remote temporary staging and archive removed; absence verified. Backups retained. Remote Git metadata is still the historical checkout; archive/manifest defines deployed source identity.

**Delivered:** cost diagnosis, explicit unknown analytics attribution, durable actual-close reason, integrated recovery-to-analytics regression, commit/push and verified paper rollout. **Not yet observed:** a new natural close produced by this final release; no synthetic trade was inserted to claim runtime attribution evidence. Historical missing exit reasons remain unavailable. No strategy tuning or live activation.
