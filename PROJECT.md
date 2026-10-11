# Project: Phase 316 — Institutional English Standardization & Zero-Disruption VPS Deployment

## Architecture
- **Backend Telemetry Ingress**: FastAPI (`src/autonomous_futures/api/canary.py`, `app.py`) providing `/api/v1/canary/evolution`, `/api/v1/canary/summary`, `/api/v1/execution/status`. Provides 100% clean institutional English descriptors for macro gating (`Active BTC Macro Trend Filter`), live progress events (`Heartbeat & Market Ingress`, `Continuous Double-Entry Ledger Audit`, `Candidate Strategy Health Evaluation`, `Parameter Genome Mutation`, `Shadow Simulation & OOS Promotion Gate`), and OOS qualification gates while preserving backward-compatible JSON schema keys (`explanation_ms`, `oos_gate`, `recent_events`).
- **Frontend Telemetry Adapter & State**: `frontend/src/components/mission-control/adapter.ts` normalizing API data, formatting relative timestamps (`Just now`, `5s ago`, `12m ago`), and providing typed English contracts for all 5 primary views.
- **UI Shell & Navigation**: React 19 + TypeScript + DaisyUI / Tailwind CSS dark theme across 5 primary views (`Executive Overview`, `Live Positions & Markets`, `Trade Log & Executions`, `Risk Controls & Solvency`, `Strategy Evolution & Autopsy`) and collapsible `Research Archives (23 Phases)` drawer.
- **Evolution State Machine & Confluence Radar**: Dynamic 5-stage pipeline (`1. Market Ingress`, `2. Candidate Health Evaluation`, `3. Trade Autopsy & Attribution`, `4. Genome Mutation Staging`, `5. OOS Qualification Gate & Promotion`), OOS hurdle tracking (`0/5 required trades`, `Sharpe ≥ 15% hurdle`), and macro gating status banners.
- **Continuous Solvency & Micro-Capital Governance**: Continuous double-entry mathematical balance conservation ($\text{Cash} + \text{Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$) holding $|\Delta| = 0.00 < 10^{-15}$ USDT, with micro-capital boundaries ($\le \$5.00$ child cap, $\le \$25.00$ exposure ceiling, $\ge 75\%$ cash floor, $\le \$3.00$ daily loss limit).
- **Quality Gates & VPS Daemon Continuity**: 100% Vitest (41+ files, 396+ tests) and Pytest (108+ files) pass rates, 0 TypeScript/lint build errors, non-disruptive deployment to Kainode Linux VPS (`147.79.18.15`), and continuous runtime of trader daemon (`autonomous-futures-trader.service`, Main PID 87549) with zero restarts.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Backend Evolution Macro Gating Localization | Update `_build_macro_gating_state` and model defaults in `canary.py` to institutional English | M1 | Survey / R3 |
| 2 | Backend Dynamic OOS Gate Explanations | Update `oos_explanation` strings (waiting, qualified, evaluating) in `canary.py` | M1 | Survey / R3 |
| 3 | Backend Recent Events Localization | Update 5 `recent_events` items (Heartbeat, Solvency Audit, Health Eval, Mutation, OOS Gate) in `canary.py` | M1 | Survey / R3 |
| 4 | Backend Schema Compatibility & Solvency | Preserve `explanation_ms` key and verify $|\Delta| < 10^{-15}$ USDT zero drift in `canary.py` | M1 | Survey / R3 |
| 5 | Frontend Navigation & Shell Localization | Update primary navigation tabs, mobile drawer, footer, and loading/error states in `App.tsx` | M2 | Survey / R1 |
| 6 | Top Bar & Mission Control Header Localization | Update instant refresh button, Telegram status, and sync badges in `mission-control-header.tsx` | M2 | Survey / R1 |
| 7 | Executive KPI Cards Localization | Update 4 KPI cards (Equity & Balance, Realized PnL & Win Rate, Exposure & Sizing, Health & Solvency) in `kpi-cards.tsx` | M2 | Survey / R1 |
| 8 | Market Positions & Candlestick Drawer Localization | Update card labels, ATR bracket metrics, chart toggles in `market-positions-card.tsx` & `pair-candlestick-chart.tsx` | M2 | Survey / R1 |
| 9 | Order Feed Table Localization | Update table headers, unit labels, empty states in `order-feed-table.tsx` | M2 | Survey / R1 |
| 10 | Research Archive Drawer Localization | Translate all 23 phase titles, categories, search placeholders in `research-archive-drawer.tsx` | M2 | Survey / R1 |
| 11 | Provenance Badges & Adapter Formatting | Update data source tooltips in `provenance-badge.tsx` and English relative time in `adapter.ts` | M2 | Survey / R1 |
| 12 | Strategy Confluence Radar Localization | Translate BTC Macro Trend, 15m Scalper Checklist, Hawkes Microstructure Hazard in `strategy-confluence-radar.tsx` | M3 | Survey / R2 |
| 13 | Strategy Evolution Radar Localization | Translate OOS scorecards, attribution gauges, health badges in `strategy-evolution-radar.tsx` | M3 | Survey / R2 |
| 14 | Dynamic 5-Stage Evolution Pipeline Localization | Translate 5 stages, cycle indicators, telemetry boxes in `evolution-page.tsx` | M3 | Survey / R2 |
| 15 | Secondary Subpages Localization | Translate detailed views in `executive-positions-page.tsx`, `executive-trades-page.tsx`, `executive-safety-page.tsx` | M3 | Survey / R1, R2 |
| 16 | Frontend Vitest Test Assertions Alignment | Update assertions across all 10 identified Vitest test files to pass 100% | M4 | Survey / R4 |
| 17 | Backend Pytest Assertions Alignment | Update assertions across all 5 identified Pytest test files to pass 100% | M4 | Survey / R4 |
| 18 | Production Bundle Build Verification | Run `npm run build` in `frontend/` ensuring 0 TypeScript diagnostics errors and 0 lint failures | M4 | Survey / R4 |
| 19 | Kainode VPS Production Bundle Hot-Sync | Deploy production dist to `/opt/autonomous-futures-bot/frontend/dist` on `147.79.18.15` and reload web service | M5 | Survey / R5 |
| 20 | Daemon Zero-Disruption & PID 87549 Invariant | Verify `autonomous-futures-trader.service` continuous operation with Main PID 87549, 0 restarts, zero drift | M5 | Survey / R5 |
| 21 | Opaque-Box E2E Testing Suite | Author and execute comprehensive 4-tier E2E testing suite validating 100% English UI and API contracts | E2E | Dual Track |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Telemetry & API Event Localization | Localize `canary.py` macro gating, OOS explanations, and recent events to institutional English while preserving schema keys | None | DONE |
| M2 | Frontend Navigation Shell & Executive Overview Localization | Localize `App.tsx`, `kpi-cards.tsx`, `market-positions-card.tsx`, `order-feed-table.tsx`, `research-archive-drawer.tsx`, `provenance-badge.tsx`, `adapter.ts` | M1 | DONE |
| M3 | Evolution State Machine, Confluence Radar & Subpages Localization | Localize `strategy-confluence-radar.tsx`, `strategy-evolution-radar.tsx`, `evolution-page.tsx`, `executive-positions-page.tsx`, `executive-trades-page.tsx`, `executive-safety-page.tsx` | M2 | DONE |
| M4 | Test Suite Alignment, Build Compilation & Zero-Regression Verification | Synchronize all 10 Vitest test files and 5 Pytest test files, run 100% passing tests, verify `npm run build` | M3 | DONE |
| M5 | Non-Disruptive VPS Deployment & Continuous Daemon Invariant | Deploy to Kainode VPS (`147.79.18.15`), reload web service, verify live HTTPS serving and trader daemon PID 87549 continuity | M4 | DONE |
| E2E | Opaque-Box Requirement-Driven E2E Test Track | Author comprehensive 4-tier E2E test suite (Tiers 1-4) published via TEST_READY.md | None | DONE |

## Interface Contracts
### Backend `GET /api/v1/canary/evolution`
- Response Schema:
  ```json
  {
    "status": "ok",
    "daemon_pid": 87549,
    "daemon_status": "ONLINE 24/7",
    "macro_gating_state": {
      "regime": "BEARISH",
      "explanation": "Long entries temporarily paused by BTC 1h/4h Bearish regime filter for capital protection (EMA 50 < EMA 200).",
      "explanation_ms": "Active BTC Macro Trend Filter: Long entries temporarily paused because BTC 1h/4h trend is in a Bearish regime (EMA 50 < EMA 200) to protect bot micro-capital.",
      "longs_allowed": false
    },
    "live_progress": {
      "current_cycle_stage": "INGRESS",
      "cycle_progress_pct": 20.0,
      "oos_gate": {
        "status": "WAITING_FOR_SAMPLES",
        "closed_trades_count": 0,
        "required_trades_count": 5,
        "sharpe_hurdle_pct": 15.0,
        "explanation": "Waiting for 5 completed trade samples to evaluate out-of-sample Sharpe (current: 0/5, hurdle >= 15.0%)."
      },
      "recent_events": [
        {
          "event_type": "HEARTBEAT_INGRESS",
          "title": "Heartbeat & Market Ingress",
          "detail": "Binance Futures 15m & 1h klines streaming synchronized (8 pairs: BTC, ETH, SOL, DOGE, BNB, XRP, SUI, AVAX)",
          "status": "HEALTHY"
        },
        {
          "event_type": "SOLVENCY_AUDIT",
          "title": "Continuous Double-Entry Ledger Audit",
          "detail": "Balance $100.12 USDT verified with zero mathematical drift (|Δ| = 0.00 < 10^-15 USDT)",
          "status": "VERIFIED"
        },
        {
          "event_type": "CANDIDATE_HEALTH",
          "title": "Candidate Strategy Health Evaluation",
          "detail": "BTCUSDT & ETHUSDT evaluated as ELITE; SOLUSDT evaluated as DEGRADED and routed to mutation",
          "status": "EVALUATED"
        },
        {
          "event_type": "MUTATION_STAGING",
          "title": "Parameter Genome Mutation (Gen #2)",
          "detail": "cand-ethusdt-evo-002 generated with Donchian period 24, ATR 2.5x, Hawkes 0.65",
          "status": "STAGED"
        },
        {
          "event_type": "SHADOW_OOS_GATE",
          "title": "Shadow Simulation & OOS Promotion Gate",
          "detail": "OOS Gate: 0/5 samples acquired, Sharpe hurdle >= 15.0% (WAITING)",
          "status": "WAITING"
        }
      ]
    },
    "solvency": {
      "drift_usdt": 0.0,
      "zero_balance_drift_verified": true
    }
  }
  ```

### Frontend Navigation Tab Contract
- Primary Tabs (`App.tsx`):
  1. `🚀 Executive Overview` (`#/` or `#/overview`)
  2. `📊 Live Positions & Markets` (`#/positions`)
  3. `⚡ Trade Log & Executions` (`#/trades`)
  4. `🛡️ Risk Controls & Solvency` (`#/safety`)
  5. `🧠 Strategy Evolution & Autopsy` (`#/evolution`)
  6. `📁 Research Archives (23 Phases)` (expandable drawer)

## Code Layout
- `src/autonomous_futures/api/canary.py`: Backend canary endpoints and evolution state machine
- `src/autonomous_futures/api/app.py`: Backend FastAPI routes
- `frontend/src/App.tsx`: Primary shell, navigation tabs, mobile drawer, footer
- `frontend/src/components/mission-control/mission-control-header.tsx`: Top bar, Telegram status, refresh button
- `frontend/src/components/mission-control/kpi-cards.tsx`: 4 executive KPI cards
- `frontend/src/components/mission-control/market-positions-card.tsx`: Market watch and active positions
- `frontend/src/components/mission-control/pair-candlestick-chart.tsx`: Interactive TradingView chart drawer
- `frontend/src/components/mission-control/order-feed-table.tsx`: Live order execution log
- `frontend/src/components/mission-control/research-archive-drawer.tsx`: 23 historical research phases drawer
- `frontend/src/components/mission-control/provenance-badge.tsx`: Data source provenance badges
- `frontend/src/components/mission-control/adapter.ts`: Frontend telemetry adapter and relative time formatter
- `frontend/src/components/mission-control/strategy-confluence-radar.tsx`: BTC macro filter, 15m scalper checklist, Hawkes hazard
- `frontend/src/components/mission-control/strategy-evolution-radar.tsx`: Strategy evolution radar, 5 OOS gates, autopsy gauges
- `frontend/src/components/evolution-page.tsx`: Dynamic 5-stage stepper, telemetry boxes, event timeline
- `frontend/src/components/executive-positions-page.tsx`: Detailed positions and bracket stop table
- `frontend/src/components/executive-trades-page.tsx`: Full execution history and autopsy methodology
- `frontend/src/components/executive-safety-page.tsx`: Double-entry invariant proof and circuit breakers
- `frontend/src/components/__tests__/`: 41 Vitest test suites
- `tests/`: 108 Pytest test suites
