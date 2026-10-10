# Project: Phase 314 — Comprehensive Web Dashboard Telemetry Audit & Discrepancy Remediation

## Architecture
- **Backend Telemetry Ingress**: FastAPI (`src/autonomous_futures/api/app.py`) providing `/api/v1/execution/status`, `/api/v1/market/prices`, `/api/v1/market/klines`, and `/api/v1/canary/summary`. Synchronizes live Binance Futures exchange state (`GET /fapi/v2/account`, `GET /fapi/v2/positionRisk`), live 24/7 daemon state from `artifacts/research/phase310/` and `phase311/`, and historical research artifacts.
- **Frontend Telemetry Adapter**: `frontend/src/components/mission-control/adapter.ts` transforming backend REST and WebSocket telemetry into typed UI telemetry contracts, enforcing zero mock leakage, truthful flat position states (`STANDBY / SCANNING (0.00 exposure)`), and genuine order executions (`canary-p310-`, `canary-p311-`).
- **UI Presentation & Provenance Badging**: React 19 + TypeScript + DaisyUI / Tailwind CSS dark theme across 5 primary views (`Dashboard Utama`, `Pasaran & Posisi`, `Log Perdagangan`, `Kawalan Keselamatan`, `Pembelajaran & Autopsi`) and secondary `Arkib Penyelidikan` drawer. Explicit provenance badging (`LIVE EXCHANGE`, `DAEMON 24/7`, `RESEARCH ARTIFACT / SIMULATION`) and consistent Malaysia Time (MYT, GMT+8) relative timestamps.
- **Cryptographic Solvency & Zero Drift**: Continuous mathematical verification of the double-entry balance invariant ($\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$) holding $|\Delta| = 0.00 < 10^{-15}$ USDT.
- **Audit Verification & Zero-Disruption VPS Deployment**: Complete documentation in `AUDIT_TELEMETRY_TRUTHFULNESS.md`, comprehensive Vitest & Pytest quality gates, production bundling, and deployment to Kainode VPS (`147.79.18.15`) reloading only `autonomous-futures-web.service` while `autonomous-futures-trader.service` (Main PID 87549) runs uninterrupted.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Backend btc_macro Multiplier Elimination | Remove linear price multipliers in `/api/v1/market/prices` in favor of real EMAs or truthful daemon indicators | M1 | Survey / R1, R2 |
| 2 | Backend Mark Price Real-Time Synchronization | Synchronize BTC/ETH/SOL mark prices in `load_execution_status` with live Binance ticker prices | M1 | Survey / R2 |
| 3 | Backend Live Exchange Reconciled Feeds | Verify `/api/v1/execution/status` maps wallet, flat positions (0.00 exposure), and genuine orders (`canary-p310/311`) | M1 | Survey / R2 |
| 4 | Backend Pytest Suite for Telemetry Truthfulness | Unit tests in `tests/unit/test_phase_314_telemetry_truthfulness.py` validating 0 mock leakage and zero-drift invariant | M1 | Survey / R4 |
| 5 | Frontend Adapter BTC Trend & Scalper Remediation | Remove fake EMA linear multipliers and hardcoded scalper criteria (1.8, 1.4, 38.5) from `adapter.ts` | M2 | Survey / R1, R2 |
| 6 | Frontend Adapter Bracket Suppression When Flat | Suppress active TP/SL price target lines when position is flat (`STANDBY / SCANNING`) | M2 | Survey / R2 |
| 7 | Frontend Adapter Fallback Order Sanitization | Replace static `ord-p310-` fallbacks with authentic `canary-p310/311` testnet order representations | M2 | Survey / R2 |
| 8 | Executive Trades Page Metrics & PnL Fix | Eliminate hardcoded 100% win rate and 0.00 bps slippage; fix `+-` sign bug on negative realized PnL in `executive-trades-page.tsx` | M2 | Survey / R1 |
| 9 | Executive Safety Page Fallback Purge | Eliminate stale Phase 309 fallbacks (`100.2038`, `0.2038`, `0.0032`) and hardcoded tripwires in `executive-safety-page.tsx` | M2 | Survey / R1 |
| 10 | Consistent MYT Timestamps & Relative Indicators | Format all dashboard timestamps in Malaysia Time (GMT+8) with relative elapsed time indicators | M2 | Survey / R3 |
| 11 | Phase 314 App Header / Footer Version Update | Update `App.tsx` sidebar footer badge from Phase 311 to Phase 314 | M2 | Survey / R3 |
| 12 | Screen-by-Screen UI Provenance Badging | Add `LIVE EXCHANGE`, `DAEMON 24/7`, and `RESEARCH ARTIFACT / SIMULATION` badges to all 5 views | M3 | Survey / R3 |
| 13 | Truth in Labeling for KPIs & Visualizations | Clear labeling distinguishing live exchange wallet/positions from daemon metrics and research backtests | M3 | Survey / R3 |
| 14 | Telemetry Truthfulness Audit Report | Author root `AUDIT_TELEMETRY_TRUTHFULNESS.md` with complete inventory, update intervals, and math formulas | M4 | Survey / R4 |
| 15 | Frontend Vitest Test Suites for Provenance & Zero Mock | Add `telemetry-provenance-badging.test.tsx`, `zero-mock-leakage.challenge.test.tsx`, `adapter-truthfulness-adversarial.test.tsx` | M4 | Survey / R4 |
| 16 | Production Bundle Compilation | Run `npm run build` in `frontend/` ensuring 0 TypeScript and 0 lint errors | M4 | Survey / R4 |
| 17 | Kainode VPS Zero-Disruption Deployment | Deploy bundle to `/opt/autonomous-futures-bot/frontend/dist` and reload `autonomous-futures-web.service` on `147.79.18.15` | M4 | Survey / R4 |
| 18 | Continuous Trader Daemon Invariant Verification | Verify `autonomous-futures-trader.service` (Main PID 87549) continuous runtime with 0s downtime and 0 restarts | M4 | Survey / R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Telemetry Remediation & Truthfulness Ingress | Fix `app.py` btc_macro and mark prices; verify zero-drift and order feeds; pytest tests | None | DONE |
| M2 | Frontend Adapter & Subpage Discrepancy Remediation | Purge fake EMAs/scalper in `adapter.ts`; fix trades page & safety page hardcodes; MYT timestamps | M1 | DONE |
| M3 | Transparent UI Provenance Badging & Truth in Labeling | Implement provenance badges across all 5 views and secondary archive drawer | M2 | DONE |
| M4 | Audit Documentation, Test Verification & VPS Deployment | Author `AUDIT_TELEMETRY_TRUTHFULNESS.md`, run Vitest/Pytest suites, deploy to VPS, verify PID 87549 | M3 | DONE |

## Interface Contracts
### Backend `GET /api/v1/market/prices`
- Response Schema:
  ```json
  {
    "BTCUSDT": 82790.1,
    "ETHUSDT": 2450.5,
    "SOLUSDT": 154.2,
    "btc_macro": {
      "ema50_1h": 83120.0,
      "ema200_1h": 81800.0,
      "regime": "BULLISH ALIGNED",
      "source": "binance_futures_live"
    }
  }
  ```

### Backend `GET /api/v1/execution/status`
- Response Schema:
  ```json
  {
    "status": "ok",
    "starting_equity_usdt": 100.0,
    "current_equity_usdt": 100.0,
    "unencumbered_cash_usdt": 100.0,
    "allocated_margin_usdt": 0.0,
    "unrealized_pnl_usdt": 0.0,
    "realized_pnl_usdt": 0.0,
    "aggregate_exposure_usdt": 0.0,
    "cash_reserve_pct": 100.0,
    "zero_balance_drift_verified": true,
    "drift_usdt": 0.0,
    "positions": {
      "BTCUSDT": { "symbol": "BTCUSDT", "position_qty": 0.0, "state": "STANDBY / SCANNING" },
      "ETHUSDT": { "symbol": "ETHUSDT", "position_qty": 0.0, "state": "STANDBY / SCANNING" },
      "SOLUSDT": { "symbol": "SOLUSDT", "position_qty": 0.0, "state": "STANDBY / SCANNING" }
    },
    "recent_orders": [...]
  }
  ```

### Frontend Provenance Badging
- UI Badge Component / Token:
  - `LIVE EXCHANGE`: Emerald badge (`bg-emerald-500/10 text-emerald-400 border-emerald-500/20`)
  - `DAEMON 24/7`: Cyan badge (`bg-cyan-500/10 text-cyan-400 border-cyan-500/20`)
  - `RESEARCH ARTIFACT / SIMULATION`: Purple / Amber badge (`bg-purple-500/10 text-purple-400 border-purple-500/20`)

## Code Layout
- `src/autonomous_futures/api/app.py`: Backend FastAPI routes, price feeds, execution status
- `tests/unit/test_phase_314_telemetry_truthfulness.py`: Pytest suite for backend telemetry truthfulness
- `frontend/src/components/mission-control/adapter.ts`: Frontend telemetry adapter and data normalizer
- `frontend/src/components/executive-trades-page.tsx`: Trade history page and execution log
- `frontend/src/components/executive-safety-page.tsx`: Safety controls and circuit breaker status
- `frontend/src/components/mission-control/overview-kpis.tsx`: Executive KPI cards
- `frontend/src/components/mission-control/market-positions-card.tsx`: Market watch and active positions
- `frontend/src/components/mission-control/scalper-radar-card.tsx`: Scalper confluence radar
- `frontend/src/components/mission-control/strategy-evolution-radar.tsx`: Strategy evolution radar
- `frontend/src/App.tsx`: Main application shell, navigation tabs, and footer badge
- `AUDIT_TELEMETRY_TRUTHFULNESS.md`: Root telemetry audit report
- `frontend/src/components/__tests__/`: Vitest test suites
