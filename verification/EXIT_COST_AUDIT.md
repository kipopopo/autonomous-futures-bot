# Frozen post-release exit/cost audit

## Scope and reproduction

Source runtime: `77b747ba17a1194bc09e77d14cce76580ed560f2`.
Snapshot observed at `2026-09-08T08:20:06.976358+00:00`.
Cohort: ledger events after sequence 96, through sequence 106; four completed
round trips and two unmatched opens excluded from closed-trade metrics.

`exit-cost-snapshot.json` contains original SQLite text/Decimal fields and lifecycle
payloads. Extraction used a read-only connection with attached read-only lifecycle
DB, `query_only=ON`, `busy_timeout=1000`, and one read transaction. This is a frozen
observation, not an atomic cross-database writer commit guarantee. Closed trades
were checked against final lifecycle marks. No service controls or DB writes.

Run offline from repository root:

```bash
python verification/reproduce_exit_cost_audit.py
```

The adjacent verifier rejects duplicate event IDs/sequences, unmatched closes,
entry/close identity drift, nonfinite accounting, mismatched entry fees, and
`net != gross - entry_fee - exit_fee`. Missing final reason remains unavailable.
It groups by exact candidate ID AND artifact hash, symbol and final exit reason.
Raw snapshot SHA256 is included in output; newline conversion changes that byte hash.
This is an audit-specific runnable check, not a new production analytics API.

## Results (USDT)

| Candidate prefix / symbol | Exit | Trades | Gross | Fees | Net |
|---|---|---:|---:|---:|---:|
| cand-09891e9 / DOGEUSDT | strategy_exit | 1 | -0.2330086707311040 | 0.04008680713943005440 | -0.27309547787053405440 |
| cand-1f87c23 / ETHUSDT | stop_loss_hit | 1 | -0.117332447620 | 0.0301709434197584 | -0.1475033910397584 |
| cand-1f87c23 / ETHUSDT | trailing_stop_hit | 1 | 0.100561076352 | 0.0386816777038464 | 0.0618793986481536 |
| cand-fb5550f / BTCUSDT | trailing_stop_hit | 1 | -0.046584517760 | 0.0395754376637440 | -0.0861599554237440 |
| Total | | 4 | -0.2963645597591040 | 0.14851486592677885440 | -0.44487942568588285440 |

## Decision

- The observed loss is not fees alone: aggregate gross PnL is already negative.
- A trailing-stop exit is not necessarily profitable; one of two such exits lost
  before fees. This label describes the trigger, not the outcome.
- Do not subtract slippage again from recorded gross/net; execution costs already
  embedded in fill prices must not be double charged. The snapshot retains the
  original slippage field, but this audit does not establish its full methodology
  or infer a hypothetical no-slippage return.
- Exact entry fill, quantity and time are retained. Historical signal features,
  entry rationale and counterfactual strategy improvements are not reconstructed.
- Four trades do not establish an edge, causal reason for losses, or qualification.
  No tuning, capital change, promotion, new provider run, restart, or deployment.

## Verification

Actual offline execution: repeatability and accounting assertions PASS; Ruff PASS;
existing analytics regression `26 passed in 1.64s`. No production code changed;
full-suite results from the deployed release are historical, not rerun for these
three audit artifacts. Post-commit check is executed separately before delivery.
