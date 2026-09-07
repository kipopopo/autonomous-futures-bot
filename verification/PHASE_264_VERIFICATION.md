# Phase 264 Verification Report: Paper Trading Reliability & Performance Audit

**Date:** 2026-09-07 15:12 MYT  
**Scope:** Read-only source inspection and bounded read-only VPS audit. No strategy/config tuning, deployment, restart, exchange order, credential or `.env` access.

## Frozen baseline

- Repository baseline before Telegram polish: `ab8b8df` (Phase 263).
- The working-tree change set was restricted to the three Telegram source/test files plus the new Telegram presentation test and verification document; no strategy or trading-engine source was changed.
- Existing accounting contracts inspected: `ReadOnlyLedgerReader` uses SQLite `?mode=ro`, `PRAGMA query_only = ON`, and a 1-second busy timeout; `calculate_reconciled_cash()` defines `starting capital + closed net PnL - open entry fees`.
- Existing phase-263 report was used as historical context only; its prior VPS claims were independently checked below.

## VPS identity and safe route

- Target: `afbot@147.79.18.15`, hostname `kipopopo`, root `/opt/autonomous-futures-bot`.
- SSH key: `C:/Users/thaqi/.ssh/kainode_ed25519_openssh`.
- Pinned ED25519 fingerprint structurally decoded to 32 bytes and matched the live `ssh-keyscan` result exactly: `SHA256:2EHNUWXLj2BPt/163uW942G+grhLoDVxhmtyrw7vdjQ`.
- No service restart, file transfer, package operation, database write, or secret-bearing command was performed.

## Live read-only evidence

Captured from `/opt/autonomous-futures-bot/artifacts/paper_live`:

- `paper-ledger.sqlite3`: 40,960 bytes; one `paper_ledger_events` table; read-only connection confirmed `PRAGMA query_only = 1`.
- 78 events across sequences 1–78: 40 opens and 38 closes, 40 distinct trade IDs.
- Two active opens have no close: one DOGEUSDT and one BTCUSDT trade. No duplicate trade IDs and no malformed open/close multiplicity were found for closed pairs.
- Maximum concurrent active position per symbol was 1; no same-symbol overlap events were found.
- Ledger NULLs: `exit_fee`, `gross_pnl`, and `net_pnl` are NULL on all 40 open rows, as expected for event types; no close-row NULL was reported by the audit.
- Closed per-pair measured results:

| Pair | Closed | Wins | Losses | Net PnL (USDT) | Fees (USDT) | Gross PnL (USDT) |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | 12 | 2 | 10 | -0.1417370047948080 | 0.0960346031348080 | -0.045702401660 |
| DOGEUSDT | 7 | 1 | 6 | -0.11260269139829454720 | 0.05588867380605454720 | -0.0567140175922400 |
| ETHUSDT | 10 | 1 | 9 | -0.2133264570683328 | 0.1102148659923328 | -0.103111591076 |
| SOLUSDT | 9 | 3 | 6 | 0.317469521670924000 | 0.101028006379076000 | 0.41849752805000 |

- Closed net PnL sum: `-0.15019663159051134720` USDT. Open-entry-fee sum: `0.18955066857153618240` USDT. Contract-reconciled cash: `99.66025269983795247040` USDT.
- Health artifact reported cash `100.38931556306482399840` and equity `100.39570527187764799840` USDT; equity-minus-cash was `0.00638970881282400000` USDT.
- The health cash differs from the existing read-only contract by `0.72906286322687152800` USDT. This is a **DEFECT** requiring accounting-contract/reconciliation investigation; it is not silently repaired here. Possible causes are deliberately left as research questions (cash semantics, fee booking, or health snapshot provenance), not asserted facts.
- Safety artifact `zero_order_safety_invariants`: `paper_activation=true`, `execution_authority=false`, `live_trading_activation=false`, `orders_submitted=0`, `zero_private_credentials=true`, `promotion_state=unpromoted`.
- Both `autonomous-futures-paper-live.service` and `autonomous-futures-telegram.service` were active/running with `ExecMainStatus=0`; paper-live `NRestarts=1`, Telegram `NRestarts=0`. Remote `uv` was not on the non-interactive PATH, so no remote test command was run; the audit used the existing project `.venv/bin/python` only for read-only SQLite inspection.
- `ufw status` was unavailable to the non-root `afbot` account (`You need to be root`); firewall posture remains **UNAVAILABLE**, not inferred.

## Decision

- **Observe:** one active position per symbol, no same-symbol overlaps, no duplicate trade IDs, safety flags remain paper-only, and both services are currently active.
- **Defect:** health cash is inconsistent with the repository's explicit reconciled-cash contract by `0.72906286322687152800` USDT.
- **Research:** determine the authoritative cash/equity accounting semantics and provenance before any tuning or promotion decision; obtain a privileged read-only firewall check and a separately approved remote locked test run if needed.

No profitability or strategy-quality claim is made from this bounded sample. The audit does not authorize or perform a fix, restart, deployment, testnet action, or live action.
