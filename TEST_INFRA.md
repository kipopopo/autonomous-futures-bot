# E2E Test Infra: Autonomous Futures Bot — Phase 316

## Test Philosophy
- **Opaque-Box, Requirement-Driven**: Tests derive strictly from `ORIGINAL_REQUEST.md` (Phase 316) and `PROJECT.md` without reliance on undocumented private internals.
- **Institutional English Standardization**: Complete purge of Malay and Indonesian phrasings across all navigation, KPI cards, tables, charts, evolution steppers, autopsy logs, and backend telemetry descriptors, establishing professional financial English contracts.
- **Progressive Testability & Zero-Mock Integrity**: Tests evaluate concrete observable behaviors across backend FastAPI ingress, telemetry models, frontend adapter normalization, component views, macro gating state machines, and out-of-sample (OOS) qualification gates.
- **Mathematical Exactness**: Continuous double-entry mathematical balance conservation:
  $$\text{Cash} + \text{Allocated Margin} + \text{Unrealized PnL} = \text{Starting Equity} + \text{Realized PnL}$$
  holding absolute zero-drift tolerance $|\Delta| = 0.00 < 10^{-15}\text{ USDT}$.
- **Non-Interference Guarantee**: Strict isolation ensuring the 24/7 background trader daemon on Kainode Linux VPS (`147.79.18.15`, Main PID 87549) remains completely uninterrupted with zero restarts (`NRestarts=0`).

---

## 4-Tier Test Methodology

### Tier 1 — Feature Coverage (Category-Partition Equivalence Classes)
Each core Phase 316 feature is partitioned into functional equivalence classes with at least 5 isolated test cases per feature (>= 30 tests total):

1. **Feature 1: Primary Navigation Shell & Routing English Contracts**:
   - Equivalence classes:
     * Primary desktop navigation tabs: `🚀 Executive Overview`, `📊 Live Positions & Markets`, `⚡ Trade Log & Executions`, `🛡️ Risk Controls & Solvency`, `🧠 Strategy Evolution & Autopsy`.
     * Mobile drawer & bottom menu labels: `Overview`, `Positions`, `Trade Log`, `Safety`, `Evolution`, `Archives`.
     * Research archives drawer: `📁 Research Archives (23 Phases)`, `23 Historical Phases`, `Phase 250` through `Phase 309`.
     * Hash routes resolution: `#/`, `#/overview`, `#/positions`, `#/trades`, `#/safety`, `#/evolution`, `#/research`.
     * Loading & empty state banners in English: `"Synchronizing live data & telemetry"`, `"No verified dataset currently available."`.

2. **Feature 2: Executive KPI Cards Telemetry & Contracts**:
   - Equivalence classes:
     * Card 1: `"Total Balance & Equity"` with breakdown of `"Available Cash:"` and `"Allocated Margin:"`.
     * Card 2: `"Net Realized PnL & Win Rate"` with `"{N} Closed Trades"`, dynamic win rate percentage, and PnL coloring.
     * Card 3: `"Active Exposure & Capital Sizing"` with `"/ $25.00 Max Cap"` and `"(Floor ≥ 75%)"`.
     * Card 4: `"System Health & Solvency"` with `"{N} Interlock Blocks (0 Hazards)"`, latency badge, and `"Zero-Drift Solvency"`.
     * Top bar elements: instant refresh button (`"Refresh"` / `"Syncing..."`), Telegram status (`"Telegram: Active"`).

3. **Feature 3: Live Market Positions & Interactive Candlestick Drawer**:
   - Equivalence classes:
     * Active universe coverage across all 8 perpetual pairs (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `DOGEUSDT`, `BNBUSDT`, `XRPUSDT`, `SUIUSDT`, `AVAXUSDT`).
     * Market watch header: `"Live Positions & Markets"`, `"8 Perpetual Pairs"`.
     * Standby state when flat: `"STANDBY / SCANNING"`, 0.00 exposure, 100% cash reserve.
     * Active trade details: `"Entry Price:"`, `"Unrealized PnL:"`, `"1.66 : 1 R:R Ratio"`.
     * Candlestick drawer toggle: `"Interactive Chart"`, `"Collapsed"`, timeframes (`15m`, `1h`), indicators (`EMA 50`, `EMA 200`, `Volume`).

4. **Feature 4: Strategy Confluence Radar & Hawkes Hazard**:
   - Equivalence classes:
     * BTC Macro Trend Filter: `"BTC Macro Trend Filter"`, regimes (`"BULLISH ALIGNED"`, `"BEARISH"`, `"SIDEWAYS"`).
     * 15m Scalper Checklist: `"15m Scalper Checklist"`, trigger conditions (`Price > 2.5x ATR below 20 EMA`, `Volume > 2.2x 20 SMA`, `RSI 14 < 26`), `"0.02% Fee"`.
     * Microstructure Hazard: `"Microstructure & Hawkes Hazard"`, spectral radius $\rho$ gauge, safe status (`"SAFE / NON-TOXIC"`), warning threshold (`ρ ≥ 0.85`), critical hazard (`ρ ≥ 1.00`).
     * Order feed table: `"Recent Orders & Execution Feed"`, symbol filter pills (`"ALL"`, `"SOL"`, `"ETH"`, etc.), maker limit tags.

5. **Feature 5: Dynamic Evolution State Machine & OOS Qualification Telemetry**:
   - Equivalence classes:
     * 5 discrete pipeline stages in institutional English: `1. Market Ingress`, `2. Candidate Health Evaluation`, `3. Trade Autopsy & Attribution`, `4. Genome Mutation Staging`, `5. OOS Qualification Gate & Promotion`.
     * Stage progress indicators: `{N}% COMPLETE`, active scan indicator.
     * OOS Qualification Scorecard: `"5 OOS Qualification Gates"`, `"Average Return OOS"`, `"Maximum Drawdown OOS"`, `"Profit Factor OOS"`, `"Trade Count OOS"`, `"Flash Crash Stress Resilience"`.
     * Dynamic sample counter: `"{N} / 5 required trades"`, Sharpe hurdle (`"≥ 15.0% improvement"`).
     * Macro gating banner: `"BTC Macro Trend Gating (1h Regime)"`, `"LONGS: PERMITTED"` vs `"LONGS: PAUSED"`, capital protection rationale.

6. **Feature 6: Backend Telemetry Endpoints & Event Descriptions**:
   - Equivalence classes:
     * `GET /api/v1/canary/evolution`: English event titles (`"Heartbeat & Market Ingress"`, `"Continuous Double-Entry Ledger Audit"`, `"Candidate Strategy Health Evaluation"`, `"Parameter Genome Mutation (Gen #2)"`, `"Shadow Simulation & OOS Promotion Gate"`).
     * `GET /api/v1/execution/status`: Truthful flat positions (`0.00` exposure, null targets), authentic recent order IDs (`canary-p310-`, `canary-p311-`), zero drift.
     * `GET /api/v1/canary/summary`: Daemon status `"ONLINE 24/7"`, verified solvency flag, English descriptions.
     * Backwards-compatible schema fields: preservation of `explanation_ms` alongside `explanation`.
     * English relative timestamp formatter (`"Just now"`, `"{N}s ago"`, `"{N}m ago"`, `"{N}h ago"`).

---

## Tier 2 — Boundary & Corner Cases (Boundary Value Analysis)
BVA targets extreme operating boundaries, edge conditions, and null/disconnected inputs (>= 5 test cases per category, >= 25 tests total):

1. **Empty States & Zero Completed Trades**:
   - 0 completed trades: win rate displays exactly `0.0%` with label `"0 Completed Trades"`.
   - Empty order feed: renders clean empty banner `"No order records for this filter."` without table breakage.
   - 0 active positions: renders `"0 Open / 8 Monitored"`, flat standby cards with 0.00 exposure.

2. **Negative PnL & Sub-Zero Currency Formatting**:
   - Realized losses format strictly with leading negative symbol (`-$0.1200` or `-0.1200 USDT`).
   - Elimination of formatting collisions (no `+-`, no `+$-`, no duplicate symbols).
   - Color coding verifies rose red for losses and emerald green for gains.

3. **Zero and Negative Cycle Timers**:
   - Countdown timer at 0s: displays `'0s'` and `'Next Cycle'` cleanly clamped.
   - Countdown timer negative input (`-10s`): clamped safely to non-negative window without crash or drift.
   - Undefined timer: defaults safely to 15s window (`'15s'` and `'/ 15s window'`).

4. **Disconnected Feeds, Latency Spikes & Tripped Circuit Breakers**:
   - Latency > 500ms: displays degraded / stale status banner and trips heartbeat interlock.
   - Supercritical Hawkes hazard ($\rho \ge 1.0$): displays `"TOXIC HAZARD"` and `"⚠️ APPROVAL WITHHELD"`.
   - Continuous audit alert: if drift flag is false, displays amber warning `"Continuous Audit"`.

5. **Flat Positions & Target Line Suppression**:
   - Position size 0.00: Take-Profit and Stop-Loss price targets are strictly suppressed (`null` / 0.00), Risk:Reward ratio displays `'—'`.
   - Interactive chart suppresses horizontal bracket price lines when position is flat.

6. **Micro-Capital Boundary Constraints**:
   - Micro child order cap: $\le \$5.00$ USDT strictly enforced.
   - Aggregate exposure ceiling: $\le \$25.00$ USDT portfolio-wide.
   - Cash reserve floor: $\ge 75.0\%$ liquid cash balance.
   - Daily loss ceiling: $\le \$3.00$ USDT fail-closed circuit breaker.

---

## Tier 3 — Cross-Feature Combinations (Pairwise Combinatorial)
Testing pairwise and multi-feature interaction surfaces (>= 15 tests total):

1. **Macro Filter Bearish Regime + Scalper Dip Scanning + Evolution Stepper Interaction**:
   - BTC 1h/4h macro filter in Bearish regime (`EMA 50 < EMA 200`): long entry dip triggers on candidate pairs are suppressed, Evolution page displays `"LONGS: PAUSED"` banner, cycle stepper continues executing.
2. **Macro Filter Bullish Regime + Multi-Pair Concurrent Dips + Order Execution**:
   - BTC macro regime Bullish: candidate dips on `SOLUSDT` and `ETHUSDT` trigger maker limit order creation respecting child cap ($\le \$5$) and aggregate exposure ($\le \$25$).
3. **Continuous Double-Entry Balance Invariant with Multi-Pair Telemetry**:
   - Simultaneous positions across multiple pairs undergoing fill, margin reservation, and fee deductions hold exact zero balance drift ($|\Delta| = 0.00 < 10^{-15}$ USDT).
4. **Multi-Pair Mark Price Telemetry + Kline Cache Coherence**:
   - Live mark prices across all 8 pairs synchronize with 15m and 1h klines without cache stale reads or decimal truncation.
5. **Exchange Filter Step-Up + Solvency Margin Reservation**:
   - Sub-dollar pairs (`DOGEUSDT`, `XRPUSDT`, `SUIUSDT`) step up to meet $5.00 min notional floor while reserving exact margin in ledger.
6. **Dynamic Evolution State Transitions during Active Trading**:
   - Advancing cycle stages (`INGRESS` -> `HEALTH_EVALUATION` -> `TRADE_AUTOPSY` -> `MUTATION_STAGING` -> `SHADOW_OOS_GATE`) while positions are open maintains ledger solvency and updates English stage banners.
7. **Interactive Candlestick Drawer Expansion + Timeframe Switch + Active Brackets**:
   - Expanding chart drawer for active pair updates OHLCV, computes EMA 50/200, renders bracket target lines at $+2.0\times$ ATR and $-1.2\times$ ATR, and switches between 15m and 1h.
8. **Supercritical Hawkes Hazard + Solvency Audit Log**:
   - Hawkes $\rho \ge 1.0$ blocks order dispatch, logs audit event, while double-entry ledger verifies zero drift.

---

## Tier 4 — Real-World Workload Scenarios (End-to-End Workflows)
Comprehensive multi-step end-to-end operational workflows (>= 5 scenarios):

1. **Scenario 1: End-to-End User Navigation & Responsive Tab Switching**:
   - User navigates across all 5 primary views (`Executive Overview` $\rightarrow$ `Live Positions & Markets` $\rightarrow$ `Trade Log & Executions` $\rightarrow$ `Risk Controls & Solvency` $\rightarrow$ `Strategy Evolution & Autopsy`) and opens the `Research Archives (23 Phases)` drawer. Verifies 100% institutional English rendering, active tab styling, and zero layout shift.
2. **Scenario 2: Responsive Candlestick Drawer Expansion & Bracket Overlays**:
   - User inspects active pairs on `Live Positions & Markets`, expands the candlestick chart drawer for `SOLUSDT` and `DOGEUSDT`, toggles from 15m to 1h timeframe, verifies EMA 50/200 overlays and TP/SL bracket lines, then collapses drawer.
3. **Scenario 3: Full Trade Lifecycle, Bracket Realization & Solvency Audit**:
   - Macro trend Bullish $\rightarrow$ 15m liquidity dip detected on `SOLUSDT` $\rightarrow$ maker limit order dispatched $\rightarrow$ fill confirmed $\rightarrow$ bracket TP/SL placed $\rightarrow$ Take-Profit realized $\rightarrow$ double-entry ledger audits zero balance drift.
4. **Scenario 4: Out-of-Sample Qualification Progression from 0 to 5 Samples**:
   - System starts at 0 closed trades (`WAITING_FOR_SAMPLES (0/5)`), ingests closed trade records 1 through 4 advancing cycle progress, completes 5th trade transitioning to `EVALUATING`, and assesses Sharpe hurdle ($\ge 15.0\%$).
5. **Scenario 5: Macro Regime Flip from Bearish to Bullish with Scalper Reactivation**:
   - Bot operates in Bearish regime with longs paused $\rightarrow$ BTC breaks above 200 EMA with EMA 50 > EMA 200 $\rightarrow$ macro filter flips to `BULLISH_ALIGNED` $\rightarrow$ UI updates banner to `"LONGS: PERMITTED"` $\rightarrow$ scalper evaluates candidate universe and resumes entry dispatch.

---

## Feature Inventory & Test Mapping

| # | Feature | Requirement Source | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|-------------------|:------:|:------:|:------:|:------:|
| 1 | Navigation & Routing English Contracts | ORIGINAL_REQUEST §R1, PROJECT §F5 | 5 | 5 | ✓ | ✓ |
| 2 | Executive KPI Cards Telemetry & Contracts | ORIGINAL_REQUEST §R1, PROJECT §F7 | 5 | 5 | ✓ | ✓ |
| 3 | Market Positions & Candlestick Drawer | ORIGINAL_REQUEST §R1, PROJECT §F8 | 5 | 5 | ✓ | ✓ |
| 4 | Strategy Confluence Radar & Hawkes Hazard | ORIGINAL_REQUEST §R2, PROJECT §F12 | 5 | 5 | ✓ | ✓ |
| 5 | Evolution State Machine & OOS Telemetry | ORIGINAL_REQUEST §R2, PROJECT §F14 | 5 | 5 | ✓ | ✓ |
| 6 | Backend Telemetry Endpoints & Event Contracts | ORIGINAL_REQUEST §R3, PROJECT §F1-F4 | 5 | 5 | ✓ | ✓ |

---

## Test Architecture & Execution

### Test Suite Locations
- Backend E2E Test Suite: `tests/e2e/test_phase_316_english_localization_e2e.py`
- Frontend E2E Test Suite: `frontend/src/components/__tests__/phase316-e2e-english-localization.test.tsx`

### Test Runner Commands
```powershell
# Backend Pytest E2E Suite
.venv\Scripts\python -m pytest tests/e2e/test_phase_316_english_localization_e2e.py -v

# Frontend Vitest E2E Suite
npm test --prefix frontend -- phase316-e2e-english-localization.test.tsx --run
```

### Coverage Thresholds
- **Tier 1**: $\ge 30$ feature tests (6 core features $\times \ge 5$ tests)
- **Tier 2**: $\ge 25$ boundary and corner tests
- **Tier 3**: $\ge 15$ pairwise interaction tests
- **Tier 4**: $\ge 5$ real-world workload scenario tests
- **Total Target**: $\ge 75$ tests covering all Phase 316 specifications.
