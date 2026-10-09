# Project: Autonomous Futures Bot — Phase 310

## Architecture
Phase 310 transitions Autonomous Futures Bot from simulated matching into real exchange execution, deploying the verified 15m Macro-Confluence Liquidity Dip Scalper across SOLUSDT and ETHUSDT, closing the continuous trade-autopsy self-learning loop, enforcing strict double-entry zero-drift solvency and micro-capital bounds, and establishing 24/7 background execution on the Kainode Linux VPS (147.79.18.15) with Telegram trade alerts.

```
+-----------------------------------------------------------------------------------+
|                            External Exchange Boundary                             |
|  Binance Futures REST API (Dual-Mode: Testnet / Live)   Binance User Data Stream  |
|  - POST /fapi/v1/order (LIMIT/MARKET/STOP_MARKET)       - listenKey keepalive 30m |
|  - GET /fapi/v1/positionRisk                            - ORDER_TRADE_UPDATE      |
|  - GET /fapi/v1/account                                 - ACCOUNT_UPDATE          |
|  - DELETE /fapi/v1/order                                                          |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     BinanceFuturesGateway & Dispatch Bridge                       |
|  - HMAC-SHA256 signature generator       - Clock drift sync (|dt| <= 1000ms)      |
|  - Monotonic nonce manager               - Idempotent c=canary-p310-{sym}-{ts}-id |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                         MacroLiquidityDipScalper Engine                           |
|  - BTC 1h/4h EMA 50 > EMA 200 Macro Trend Filter (Gated on market regime)         |
|  - 15m Entry: Price > 2.5x ATR below 20 EMA, Vol > 2.2x 20 SMA, RSI 14 < 26       |
|  - Trade Structuring: Maker Limit Order at sweep price (0.02% maker fee)          |
|  - Risk Bounds: SL 1.2x ATR below, dynamic TP 2.0x ATR above (1.66:1 R:R)         |
|  - Momentum Decay Stop: Auto-exit after 8 bars (120 mins) if trade stalls         |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     CentralizedSolvencyLedger & Risk Interlocks                   |
|  - Double-Entry Invariant: Cash + Margin + UnrealizedPnL == Equity + RealizedPnL   |
|  - Absolute Drift Tolerance: |drift| < 10^-15 USDT                                |
|  - Micro-Capital Bounds: <= 5.00 USDT child, <= 25.00 USDT aggregate              |
|  - Liquid Cash Reserve Floor >= 75.0%                                             |
|  - Hawkes Supercritical Cascade Cutoff: rho >= 1.0 -> freeze new entries          |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|              Closed-Loop Self-Learning & Strategy Autopsy Feedback                |
|  - Ingest real execution fills, realized PnL, slippage, hold duration             |
|  - StrategyAutopsyEngine: deconstruct into timing error, adverse selection, edge  |
|  - ContinuousSelfLearningDaemon: health classification (ELITE/HEALTHY/DEGRADED)   |
|  - Circuit Breaker: Fail-closed halt if daily drawdown > 3.00 USDT                |
|  - Persistence: canary-lifecycle-telemetry.sqlite3 & canary-lifecycle-events.jsonl|
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|               24/7 VPS Deployment, Telemetry & Cryptographic Merkle DAG           |
|  - Kainode VPS (147.79.18.15): autonomous-futures-trader.service systemd unit    |
|  - Telegram Alerts: scripts/run_telegram_notifier.py (orders, fills, TP/SL, PnL) |
|  - Merkle DAG Root: Linked to Phase 309 root:                                     |
|    5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844              |
|  - Persistent research artifacts in artifacts/research/phase310/                  |
+-----------------------------------------------------------------------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Dual-Mode Binance Futures Gateway Bridge | Authenticated REST endpoints (POST /fapi/v1/order, GET /fapi/v1/positionRisk, GET /fapi/v1/account, DELETE /fapi/v1/order) with testnet/live toggle, HMAC-SHA256, monotonic nonce, clock drift compensation (<=1000ms), and idempotent client order IDs | M1 | Survey 1 (R1) |
| 2 | WebSocket User Data Stream & listenKey Keepalive | Automatic listenKey creation, 30m background keepalive (PUT /fapi/v1/listenKey), real-time ORDER_TRADE_UPDATE and ACCOUNT_UPDATE ingestion | M1 | Survey 1 (R1) |
| 3 | Macro Trend Filter & Entry Trigger | BTC 1h/4h EMA 50 > EMA 200 macro trend gate; 15m entry trigger (Price > 2.5x ATR below 20 EMA, vol > 2.2x 20 SMA, RSI 14 < 26) on SOLUSDT & ETHUSDT | M2 | Survey 2 (R2) |
| 4 | Trade Structuring & Momentum Decay Stop | Maker Limit Orders at sweep price (0.02% maker fee); SL 1.2x ATR; TP 2.0x ATR (1.66:1 R:R); 8-bar (120m) time decay stop | M2 | Survey 2 (R2) |
| 5 | Closed-Loop Strategy Autopsy Feedback | Ingest real fills/PnL/slippage into SQLite & JSONL; StrategyAutopsyEngine decomposition; candidate health classification (ELITE/HEALTHY/DEGRADED) | M3 | Survey 2 (R3) |
| 6 | Fail-Closed Daily Drawdown Pause | Automatic trading halt and position flattening if daily drawdown breaches 3.00 USDT ceiling | M3 | Survey 2 (R3) |
| 7 | Double-Entry Solvency & Micro-Capital Bounds | Invariant |drift| < 10^-15 USDT; child slice <= 5.00 USDT; aggregate exposure <= 25.00 USDT; cash reserve >= 75.0% | M4 | Survey 3 (R4) |
| 8 | Continuous 24/7 VPS Deployment | systemd user service autonomous-futures-trader.service on Kainode VPS (147.79.18.15) with auto-restart on network interruption | M4 | Survey 3 (R4) |
| 9 | Real-Time Telegram Alerts | scripts/run_telegram_notifier.py alerts on order placement, fill confirmation, TP/SL realization, and daily PnL summaries | M4 | Survey 3 (R4) |
| 10 | Cryptographic Merkle DAG Chain | Upstream parent root 5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844; 5 research artifacts in artifacts/research/phase310/ | M5 | Survey 3 (Context) |
| 11 | Observational API & Dashboard | GET /api/v1/canary/autonomous-trading endpoint; React DaisyUI 5.7.42 dashboard component | M5 | Survey 3 (Architecture) |
| 12 | Opaque-Box E2E Test Suite | 4-tier comprehensive test suite derived from ORIGINAL_REQUEST.md; TEST_READY.md publication | M6 | Survey 3 (Dual Track) |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Real Binance Futures Order Dispatch & Gateway Bridge | `src/autonomous_futures/execution/binance_gateway.py`, signed REST, WebSocket user data stream, clock drift, client order IDs | none | DONE |
| M2 | Macro Liquidity Sweep Scalper Engine | `src/autonomous_futures/strategy/macro_liquidity_scalper.py`, BTC macro filter, SOL/ETH 15m triggers, Maker orders, SL/TP, 8-bar decay stop | M1 | DONE |
| M3 | Closed-Loop Self-Learning & Strategy Autopsy Feedback | Autopsy pipeline integration, telemetry persistence (`canary-lifecycle-telemetry.sqlite3`), health classification, 3.00 USDT daily drawdown circuit breaker | M2 | DONE |
| M4 | VPS Deployment, Telegram Telemetry & Solvency Governance | `autonomous-futures-trader.service`, `scripts/run_telegram_notifier.py`, double-entry zero-drift invariant, micro-capital bounds | M1, M2, M3 | DONE |
| M5 | Cryptographic Merkle DAG Chain & Observational API | `artifacts/research/phase310/`, `scripts/run_phase_310_real_autonomous_trading.py`, FastAPI endpoints, dashboard integration | M4 | DONE |
| M6 | 100% E2E Verification & Adversarial Hardening | Comprehensive 4-tier test suite passing, TEST_READY.md published, challenger verification, clean forensic audit | M1-M5 | DONE |

## Interface Contracts

### BinanceFuturesGateway ↔ SelfDrivingTradingEngine
```python
class BinanceFuturesGateway:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True): ...
    async def create_order(self, symbol: str, side: str, order_type: str, quantity: Decimal, price: Optional[Decimal] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]: ...
    async def cancel_order(self, symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]: ...
    async def get_position_risk(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]: ...
    async def get_account_balance(self) -> Dict[str, Any]: ...
    async def start_user_data_stream(self, callback: Callable[[Dict[str, Any]], Awaitable[None]]) -> str: ...
    async def keepalive_user_data_stream(self, listen_key: str) -> bool: ...
    async def close_user_data_stream(self, listen_key: str) -> bool: ...
```

### MacroLiquidityDipScalper ↔ SelfDrivingTradingEngine
```python
class MacroTrendFilter:
    def evaluate(self, btc_1h_candles: List[Candle], btc_4h_candles: List[Candle]) -> bool:
        """Returns True iff BTC 1h EMA 50 > EMA 200 AND BTC 4h EMA 50 > EMA 200 (fails closed if <200 bars)."""

class MacroLiquidityDipScalper:
    def evaluate_15m_bar(self, symbol: str, bar: Candle, history: List[Candle], macro_trend_allowed: bool) -> Optional[ScalperSignal]:
        """Returns ScalperSignal for allowed symbols (SOLUSDT, ETHUSDT) or None."""
```

### StrategyAutopsyEngine ↔ CanaryTelemetry
```python
class StrategyAutopsyEngine:
    def decompose_trade(self, fill_record: RealizedFillRecord) -> TradeAutopsyReport: ...
    def update_candidate_health(self, candidate_id: str, autopsies: List[TradeAutopsyReport]) -> CandidateHealthStatus:
        """Returns ELITE, HEALTHY, or DEGRADED (triggering mutation)."""
```

## Code Layout
- `src/autonomous_futures/execution/binance_gateway.py`: Binance Futures dual-mode signed REST & WebSocket gateway.
- `src/autonomous_futures/strategy/macro_liquidity_scalper.py`: Macro trend filter and 15m liquidity sweep scalper.
- `src/autonomous_futures/execution/self_driving.py`: Integrated self-driving trading engine with live gateway, scalper, solvency ledger, and autopsy loop.
- `src/autonomous_futures/notify/telegram.py`: Enhanced Telegram notifier with trade event templates.
- `deploy/systemd/autonomous-futures-trader.service`: Production systemd service unit for Kainode VPS.
- `scripts/run_telegram_notifier.py`: Telegram notifier daemon runner.
- `scripts/run_phase_310_real_autonomous_trading.py`: Phase 310 master verification and execution runner.
- `artifacts/research/phase310/`: Cryptographic Merkle DAG research artifacts bound to parent root `5e3435be2f701021263dbace99d64b2180e03630f10b5356c4aabe96f846c844`.
- `tests/unit/test_phase_310_*.py`: Targeted unit and challenger tests (115 tests).
- `tests/integration/test_phase_310_*.py`: Opaque-box E2E integration tests (102 tests).

## Phase 311: Executive Trading Mission Control Web Dashboard Overhaul
- **Overview**: Complete overhaul of the Autonomous Futures Bot web interface (`https://futures.semua.dev/`) from an overwhelming 23-tab research view into a 4-tab executive Trading Mission Control with a collapsible Research Archive drawer preserving all 23 historical phases (250–309).
- **Frontend Architecture**:
  - `frontend/src/components/mission-control/types.ts`: Interface models for executive dashboard, KPIs, positions, radar, orders.
  - `frontend/src/components/mission-control/mission-control-header.tsx` (R1): Header bar with ACTIVE 24/7 pulse, BINANCE TESTNET GATEWAY badge, CIRCUIT: NORMAL state, MYT ticking clock, refresh button.
  - `frontend/src/components/mission-control/kpi-cards.tsx` (R1): 4 Key Owner KPI Cards (Total equity & cash reserve, Realized PnL & win rate %, Active exposure vs $25 cap, System health & zero-drift $|Δ| < 10^{-15}$).
  - `frontend/src/components/mission-control/market-positions-card.tsx` (R2): SOLUSDT, ETHUSDT, BTCUSDT staged pairs with mark prices, LONG/SCANNING state, TP/SL dynamic ATR brackets, and 1.66:1 Risk:Reward ratio chip.
  - `frontend/src/components/mission-control/strategy-confluence-radar.tsx` (R3): BTC 1h/4h EMA 50/200 macro trend filter, 15m scalper checklist (ATR distance, volume surge, RSI 14, 0.02% maker fee), Hawkes hazard gauge ($\rho$) with SVG sparkline.
  - `frontend/src/components/mission-control/order-feed-table.tsx` (R4): Real-time order execution table with MYT timestamps, maker fee 0.02%, and realized PnL.
  - `frontend/src/components/mission-control/research-archive-drawer.tsx` (R5): Collapsible drawer organizing all 23 historical phases into 4 groups with hash preservation.
  - `frontend/src/components/mission-control/executive-dashboard.tsx`: Assembled container component for Tab 1 (Dashboard Utama).
  - `frontend/src/components/mission-control/adapter.ts`: Data adapter bridging live Canary models into the executive dashboard model.
  - `frontend/src/components/executive-positions-page.tsx`: Subpage for Tab 2 (Pasaran & Posisi).
  - `frontend/src/components/executive-trades-page.tsx`: Subpage for Tab 3 (Log Perdagangan).
  - `frontend/src/components/executive-safety-page.tsx`: Subpage for Tab 4 (Kawalan Keselamatan).
- **Design & Layout** (R6): DaisyUI 5.7.42 + Tailwind CSS v4 OLED dark theme with responsive mobile navigation (top header, slide-down drawer menu, and bottom navigation bar for viewports < 768px).
- **Verification & Deployment** (R7):
  - Vitest automated test suite: 28 test files, 173 tests passing (0 regressions).
  - Production build: `npm run build` compiled cleanly.
  - Deployment: Deployed to Kainode VPS (`147.79.18.15`) at `/opt/autonomous-futures-bot/frontend/dist`.
  - Live Verification: Verified HTTP 200 OK on `https://futures.semua.dev/` serving `index-DEQro7aV.js` and `index-8oSs-Ynt.css`; verified `autonomous-futures-trader.service` and `autonomous-futures-web.service` active.
