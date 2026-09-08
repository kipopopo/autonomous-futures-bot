# Phase 276 — Bounded Paper Performance Audit

Snapshot: 2026-09-08T05:47:14.338238+00:00

## Scope
Main-session read-only transactional SQLite observation of the deployed paper ledger. Runtime unchanged; no restart, strategy tuning, order calls or live activation. Selected ledger fields only; mode=ro, query_only=ON, busy_timeout=1000. No health cash equality claim: the cash below is ledger-derived at this snapshot.

## Cohorts and validation
The verified cutover baseline ended at sequence 80 with 40 complete trades. Cohorts use each trade's OPEN sequence, not close time. Unique opens, unique closes, open/close binding and every closed trade gross minus both fees equals net were asserted with Decimal. Closed-only metrics exclude unrealized PnL. Fees are recorded entry plus exit commissions; no unrecorded funding or additional cost assumptions are inserted. Gross price PnL must not be interpreted as frictionless market edge.

## Snapshot results
```json
{
  "observed_at": "2026-09-08T05:47:14.338238+00:00",
  "events": 94,
  "all": {
    "closed": 46,
    "wins": 7,
    "win_rate_pct": "15.21739130434782608695652174",
    "gross_pnl": "-0.0345726520502760",
    "fees": "0.58622518401735597600",
    "net_pnl": "-0.62079783606763197600",
    "profit_factor": "0.4757510592355375751173493849"
  },
  "pre_cutover": {
    "closed": 40,
    "wins": 7,
    "win_rate_pct": "17.5",
    "gross_pnl": "0.2088931148076560",
    "fees": "0.37922275730432724800",
    "net_pnl": "-0.17032964249667124800",
    "profit_factor": "0.7678477265787239713468195170"
  },
  "post_cutover": {
    "closed": 6,
    "wins": 0,
    "win_rate_pct": "0",
    "gross_pnl": "-0.2434657668579320",
    "fees": "0.20700242671302872800",
    "net_pnl": "-0.45046819357096072800",
    "profit_factor": "0E+20"
  },
  "post_by_symbol": {
    "DOGEUSDT": {
      "closed": 2,
      "wins": 0,
      "win_rate_pct": "0",
      "gross_pnl": "-0.0051640689979320",
      "fees": "0.07363545726357112800",
      "net_pnl": "-0.07879952626150312800",
      "profit_factor": "0E+20"
    },
    "SOLUSDT": {
      "closed": 4,
      "wins": 0,
      "win_rate_pct": "0",
      "gross_pnl": "-0.23830169786000",
      "fees": "0.133366969449457600",
      "net_pnl": "-0.371668667309457600",
      "profit_factor": "0E+18"
    }
  },
  "unmatched_count": 2,
  "ledger_reconciled_cash": "99.37126192284085150560"
}
```

## Decision
Operational restart recovery has prior evidence, but positive economic edge is NOT established. All six completed post-cutover trades lost after costs. Both gross price PnL and fees contribute to the post-cutover loss; fees alone do not explain it. Only SOLUSDT and DOGEUSDT have completed post-cutover trades in this snapshot; BTCUSDT/ETHUSDT closed-trade performance is unavailable, not zero performance. Two positions remain open and are excluded from closed-trade metrics. Profit factor is based on net winning/losing trades; zero wins with positive losses gives zero, not undefined.

The short, small sample cannot establish persistent performance, statistical significance, market-regime coverage or a causal effect of the reliability deployment. No promotion or strategy change is justified by this audit. Next useful work is a bounded offline attribution of entry/exit behavior and cost assumptions using existing contracts, not another restart or blind parameter tuning.

## Verification
Arithmetic and identity assertions executed in the main session against the selected real snapshot. Report-only change; no full test rerun required for runtime-code regression evidence. No synthetic trade data, external state writes or daemon changes.
