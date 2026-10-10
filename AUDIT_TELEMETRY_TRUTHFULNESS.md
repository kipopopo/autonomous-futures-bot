# Comprehensive Web Dashboard Telemetry Truthfulness Audit & Provenance Verification

**Project**: Autonomous Futures Bot  
**Audit Phase**: Phase 314  
**Audit Target**: `https://futures.semua.dev/`  
**Daemon Environment**: Kainode Linux VPS (`147.79.18.15`), `systemd --user`  
**Trader Daemon Status**: `autonomous-futures-trader.service` (Main PID **87549**, Continuous Uptime)  
**Web Telemetry Service**: `autonomous-futures-web.service` (FastAPI + Uvicorn Port 8000)  
**Date**: October 2026  
**Audit Standard**: Zero Synthetic Leaks, Truth in Telemetry, Strict Provenance Badging, Double-Entry Zero-Drift Solvency ($|\Delta| < 10^{-15}\text{ USDT}$)

---

## 1. Executive Summary & Audit Objective

The purpose of this audit is to systematically verify, reconcile, and guarantee the absolute truthfulness of every metric, status indicator, card, chart, and table rendered on the owner's web dashboard (`https://futures.semua.dev/`).

Prior to Phase 314, when the bot was flat on Binance Futures Testnet (zero active positions), parts of the web dashboard fell back to historical simulation artifacts from Phase 309 research (which had recorded simulated short ETH and long SOL positions, along with static placeholder trades and linear price multipliers). 

Phase 314 completely purges all synthetic mock fallbacks, enforces strict **Truth in Labeling**, and introduces screen-by-screen **Provenance Badging** across all 5 primary views:
1. `LIVE EXCHANGE`: Real-time data queried directly from Binance Futures USDⓈ-M public API and authentic Testnet account state.
2. `DAEMON 24/7`: Live telemetry originating from the autonomous 24/7 trading daemon running continuously on the Kainode Linux VPS (PID 87549).
3. `RESEARCH ARTIFACT / SIMULATION`: Historical research and walk-forward backtest simulations (Phases 250 through 309), cleanly quarantined within the expandable **📁 Arkib Penyelidikan** drawer.

---

## 2. Comprehensive Inventory of Discrepancies & Remediations

| # | Discrepancy Identified | Prior Behavior | Remediated Behavior (Phase 314) | Provenance Tier |
|---|------------------------|----------------|---------------------------------|-----------------|
| **1** | **Phantom Position Display When Flat** | When Binance Testnet position quantity was `0.00`, the adapter fell back to Phase 309 simulation showing ETH Short @ 2750 & SOL Long @ 185. | Truthfully renders `STANDBY / SCANNING (0.00 exposure)` across all pairs. Zero phantom positions displayed. | `LIVE EXCHANGE` |
| **2** | **Hypothetical Bracket TP/SL When Flat** | When position was flat (`0.00 exposure`), Take-Profit (+2.0x ATR) and Stop-Loss (-1.2x ATR) target lines were rendered using hypothetical calculations. | TP/SL target lines and price values are strictly suppressed (`takeProfitPrice = 0.0`, `stopLossPrice = 0.0`) when position is flat. Active brackets render only when a real position is held. | `DAEMON 24/7` |
| **3** | **Linear Multipliers on BTC Macro Trend** | `/api/v1/market/prices` and `adapter.ts` computed macro trend EMAs using synthetic linear multipliers (`btc_price * 1.004` and `btc_price * 0.988`). | Eliminated synthetic multipliers entirely. Computes authentic EMA 50 & EMA 200 from live Binance Futures 1h & 4h klines with 5-second in-memory caching. | `LIVE EXCHANGE` |
| **4** | **Hardcoded Scalper Trigger Criteria** | `adapter.ts` fallback had hardcoded numbers: `1.8x ATR`, `1.4x Vol`, and `38.5 RSI`. | Binds dynamically to live 15m candle indicators: distance below 20 EMA ($> 2.5\times$ ATR), volume ratio ($> 2.2\times$ 20 SMA), and RSI 14 ($< 26$). | `DAEMON 24/7` |
| **5** | **Executive Trades Page Win Rate & Trades** | Defaulted to hardcoded `100.0% Win Rate` and `0.00 bps slippage` even when 0 trades were completed. | Dynamically computes win rate from authentic executed orders (`canary-p310-`, `canary-p311-`), strictly defaulting to `0.0%` when completed trades is 0. | `LIVE EXCHANGE` |
| **6** | **Realized PnL Sign Formatter Bug** | Negative realized PnL rendered with confusing double signs: `+-0.2038 USDT`. | Fixed format string logic: properly renders `+$0.5000 USDT` or `-$0.2038 USDT` without sign collision. | `LIVE EXCHANGE` |
| **7** | **Executive Safety Page Stale Fallbacks** | Solvency metrics fell back to stale Phase 309 constants (`100.2038`, `0.2038`, `0.0032`, 0 tripwires). | Binds directly to `/api/v1/execution/status` live solvency state with zero-balance drift verification. | `DAEMON 24/7` |
| **8** | **Timezone Inconsistencies** | Mixed UTC strings and raw ISO dates across different widgets. | Standardized all display timestamps to **Malaysia Time (MYT, GMT+8)** with dynamic relative elapsed time indicators (e.g. `Baru sahaja`, `15s yang lalu`). | `DAEMON 24/7` |
| **9** | **Historical Archive Drawer Quarantining** | Historical research phases (250-309) were mixed into the main application navigation. | All 23 historical canary phases are neatly tucked into the secondary **📁 Arkib Penyelidikan** drawer with explicit `RESEARCH ARTIFACT / SIMULATION` provenance banners. | `RESEARCH ARTIFACT` |

---

## 3. Screen-by-Screen Telemetry Truthfulness Matrix

### 3.1. Dashboard Utama (Executive Overview — `#/` or `#overview`)

| UI Section / Card | Metric Displayed | Exact Data Source | Refresh Rate | Provenance Badge | Verification Method |
|-------------------|------------------|-------------------|--------------|------------------|---------------------|
| **Mission Control Header** | Bot State (`ACTIVE 24/7`) | `autonomous-futures-trader.service` systemd status & heartbeat | 1s tick / 10s polling | `DAEMON 24/7` | Checked against VPS systemd process table |
| **Mission Control Header** | Gateway Mode | `TestnetOrderDispatchBridge` configuration | Static / 10s polling | `DAEMON 24/7` | Validated in bot runtime config |
| **Mission Control Header** | Circuit Breaker | Fail-closed tripwire monitor | Instant WebSocket push / 10s | `DAEMON 24/7` | Verified 0 active tripwires |
| **KPI Card 1** | Total Equity & Cash Balance | Binance Futures Account balance (`/api/v1/execution/status`) | 10s auto-refresh | `LIVE EXCHANGE` | Reconciled against Binance Testnet API (`/fapi/v2/account`) |
| **KPI Card 2** | Net Realized PnL & Win Rate | Realized PnL from filled orders (`canary-p310/311`) | 10s auto-refresh | `LIVE EXCHANGE` | Reconciled from SQLite execution ledger |
| **KPI Card 3** | Active Exposure & Sizing Cap | Aggregate notional exposure vs \$25.00 ceiling | 10s auto-refresh | `DAEMON 24/7` | Enforced by micro-capital sizing engine |
| **KPI Card 4** | System Health & Solvency | Double-entry drift ($|\Delta| < 10^{-15}\text{ USDT}$) & latency | 10s auto-refresh | `DAEMON 24/7` | Mathematical invariant proof |
| **Market Positions Card** | Mark Prices (SOL, ETH, BTC) | Binance Futures public ticker (`/api/v1/market/prices`) | 5s TTL cache | `LIVE EXCHANGE` | Direct query to `fapi.binance.com` |
| **Market Positions Card** | Position States | Live positions from exchange (`/api/v1/execution/status`) | 10s auto-refresh | `LIVE EXCHANGE` | Reports `STANDBY / SCANNING (0.00 exposure)` when flat |
| **Market Positions Card** | Interactive Kline Charts | TradingView Lightweight Charts (15m & 1h) | 5s TTL cache / local fallback | `LIVE EXCHANGE` | Binance Futures public klines (`fapi.binance.com/fapi/v1/klines`) |
| **Strategy Radar Card** | BTC Macro Trend (EMA 50/200) | Live 1h & 4h candle EMA calculation | 10s auto-refresh | `DAEMON 24/7` | Computed dynamically from klines |
| **Strategy Radar Card** | 15m Scalper Checklist | ATR distance, volume ratio, RSI 14 | 10s auto-refresh | `DAEMON 24/7` | Evaluated dynamically on 15m candle bar |
| **Strategy Radar Card** | Hawkes Microstructure Hazard | Real-time spectral radius $\rho < 1.0$ gauge | WebSocket / 10s polling | `DAEMON 24/7` | Verified non-toxic regime |
| **Strategy Evolution Radar** | Active Strategy Family | High-expectancy 15m Macro Scalper | 10s auto-refresh | `DAEMON 24/7` | Active strategy registry |
| **Strategy Evolution Radar** | 5 Walk-Forward OOS Gates | Retrospective validation scorecards | 10s auto-refresh | `RESEARCH ARTIFACT` | Grounded in Phase 298/306 research artifacts |
| **Order Feed Table** | Recent Executions & Fills | Authentic Testnet drill orders (`canary-p310/311`) | 10s auto-refresh | `LIVE EXCHANGE` | Grounded in `canary-orders.jsonl` |

### 3.2. Pasaran & Posisi (Live Positions & Depth — `#/positions`)

| UI Section | Metric Displayed | Exact Data Source | Provenance Badge | Verification Method |
|------------|------------------|-------------------|------------------|---------------------|
| **Positions Table** | Active Quantity, Notional, Margin | `/api/v1/execution/status` positions map | `LIVE EXCHANGE` | Displays `0.00` quantity and exposure when flat |
| **Bracket Target Monitor** | Entry Price, TP Target, SL Target | ATR bracket protective orders | `LIVE EXCHANGE` | Suppressed when flat; active upon fill |
| **Exchange Fee Monitor** | 0.02% Maker Fee Efficiency | Authenticated trade execution records | `LIVE EXCHANGE` | Maker orders confirmed by Binance exchange |

### 3.3. Log Perdagangan (Trade History & Autopsies — `#/trades`)

| UI Section | Metric Displayed | Exact Data Source | Provenance Badge | Verification Method |
|------------|------------------|-------------------|------------------|---------------------|
| **Trade Execution Feed** | Timestamp (MYT), Side, Price, Notional | Authentic Phase 310/311 executions | `LIVE EXCHANGE` | Read from SQLite & JSONL orders feed |
| **Maker Fee Savings** | Fee Paid vs Taker Benchmark | Calculated cumulative maker fees (0.02%) | `LIVE EXCHANGE` | Verifies 60% fee saving vs 0.05% taker |
| **Execution Quality Autopsy**| Timing error & adverse selection | Strategy autopsy attribution engine | `DAEMON 24/7` | Computed dynamically per trade fill |

### 3.4. Kawalan Keselamatan (Risk Controls & Solvency — `#/safety`)

| UI Section | Metric Displayed | Exact Data Source | Provenance Badge | Verification Method |
|------------|------------------|-------------------|--------------|------------------|
| **Double-Entry Solvency** | Cash + Margin + PnL = Equity + PnL | Real-time double-entry ledger | `DAEMON 24/7` | Absolute tolerance $|\Delta| < 10^{-15}\text{ USDT}$ |
| **Micro-Capital Confinement**| \$25.00 exposure ceiling, 75% cash floor | Risk interlocks engine | `DAEMON 24/7` | Hard constraints checked before order dispatch |
| **Circuit Breakers** | Drawdown limit, Hawkes $\rho$, Clock skew | Continuous daemon monitoring | `DAEMON 24/7` | Fail-closed tripwires verified active |

### 3.5. Pembelajaran & Autopsi (Continuous Evolution — `#/evolution`)

| UI Section | Metric Displayed | Exact Data Source | Provenance Badge | Verification Method |
|------------|------------------|-------------------|--------------|------------------|
| **Evolution Status Banner**| 24/7 Self-Learning Daemon Status | `autonomous-futures-trader.service` daemon | `DAEMON 24/7` | Real-time MYT/UTC clock & 15s heartbeat |
| **5-Stage Evolutionary Stepper**| Ingress -> Microstructure -> Paper -> OOS -> Promotion | Live daemon execution cycle | `DAEMON 24/7` | Real-time cycle progress meter |
| **Live Audit Timeline** | Heartbeat ingress, solvency audits, OOS evaluation | Dynamic event stream from daemon | `DAEMON 24/7` | Verified event stream with relative timestamps |
| **Walk-Forward Matrix** | Retrospective candidate comparisons | Research validation reports | `RESEARCH ARTIFACT` | Chained via cryptographic SHA-256 Merkle DAG |

---

## 4. Mathematical Solvency & Invariant Verification

Across all state transitions, simulated drills, and live exchange reconciliations, the bot enforces strict double-entry balance conservation:

$$\text{Total Equity} = \text{Unencumbered Cash} + \text{Allocated Margin} + \text{Unrealized PnL}$$
$$\text{Target Equity} = \text{Starting Equity} + \text{Realized PnL}$$
$$\text{Balance Drift } \Delta = |\text{Total Equity} - \text{Target Equity}| < 10^{-15}\text{ USDT}$$

### Micro-Capital Hard Boundaries
- **Child Order Cap**: $\le \$5.00\text{ USDT}$ per slice (with Binance `LOT_SIZE` precision and `ROUND_DOWN` step-up).
- **Aggregate Exposure Ceiling**: $\le \$25.00\text{ USDT}$ portfolio-wide.
- **Liquid Cash Reserve Floor**: $\ge 75.0\%$ unencumbered collateral at all times.
- **Intra-Day Loss Ceiling**: $\le \$3.00\text{ USDT}$ with automatic fail-closed position flattening.

---

## 5. Verification Suite & Quality Gate Status

1. **Frontend Vitest Test Suite**:
   - `39 test files passed` (100% pass rate)
   - `349 tests passed` (0 failures)
   - Verified adapter resilience, provenance badging, zero mock leakage, candlestick rendering, and navigation resilience.
2. **Backend Pytest Test Suite**:
   - `43 tests passed` in Phase 314 telemetry truthfulness and adversarial challenger suites (`test_phase_314_telemetry_truthfulness.py`, `test_phase_314_m1_adversarial_challenge.py`, `test_challenger_m1_2_execution_status.py`).
   - Verified `/api/v1/market/prices` eliminates linear multipliers.
   - Verified `/api/v1/execution/status` synchronizes live prices and preserves zero balance drift.
3. **Frontend Production Build**:
   - `npm run build` completed with **0 TypeScript errors** and **0 lint errors**.
   - Optimized assets compiled in `frontend/dist/`.

---

## 6. Zero-Downtime Deployment & Daemon Invariant Protocol

During deployment to the Kainode Linux VPS (`147.79.18.15`):
1. **Trader Daemon Isolation**: `autonomous-futures-trader.service` (Main PID **87549**) is completely independent of the web frontend. Its PID and memory space must remain untouched.
2. **Web Service Reload**: Only `autonomous-futures-web.service` is reloaded to serve updated API schemas and static bundle files.
3. **Post-Deployment Verification**: Verification of HTTP 200 at `https://futures.semua.dev/`, zero console errors, and continuous uptime of PID 87549.
