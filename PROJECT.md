# Project: Phase 312 — High-Performance Live Interactive Candlestick Charting for Mission Control Dashboard

## Architecture
- **Backend**: FastAPI (`src/autonomous_futures/api/app.py`) exposing `GET /api/v1/market/klines?symbol={symbol}&interval={15m|1h}&limit={100}` with 5.0s in-memory TTL caching, querying Binance Futures public REST (`https://fapi.binance.com/fapi/v1/klines`) with fallback to local Parquet archives (`research/immutable-data/`) and deterministic synthetic candles.
- **Frontend Core**: React 19 + TypeScript + Vite (`frontend/`) integrating `lightweight-charts@5.2.1` using custom Obsidian Dark Theme tokens (`#0a0f1d`, `#10b981`, `#f43f5e`, `#06b6d4`, `#f59e0b`, `#38bdf8`).
- **Resilient Ingress Client**: `frontend/src/lib/api.ts` implementing `fetchMarketKlines()` with 3-tier fallback (FastAPI -> Binance public REST -> synthetic).
- **Indicators Engine**: `frontend/src/lib/chart-indicators.ts` calculating EMA 50, EMA 200, volume histogram with `scaleMargins`, and synthetic candles.
- **UI & Visualization**: `frontend/src/components/mission-control/pair-candlestick-chart.tsx` (chart component) and `frontend/src/components/mission-control/market-positions-card.tsx` (collapsible drawer with "📈 Carta Interaktif" button, timeframe pills 15m/1h, indicator pills, OHLC badge, 24h high/low, and visual TP/SL target lines).
- **Quality Gates**: Vitest test suite (`npm test --prefix frontend`), Pytest suite (`uv run pytest tests/unit/test_api.py`), static typing (`tsc`, `mypy`), and linter (`ruff`).
- **Deployment**: Zero-disruption deployment to Kainode VPS (`147.79.18.15`) static directory `/opt/autonomous-futures-bot/frontend/dist` and restart of `autonomous-futures-web.service`, preserving 24/7 continuous trader daemon `autonomous-futures-trader.service`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Backend Kline Ingress API | `GET /api/v1/market/klines` with 5s TTL cache and normalized OHLCV output | M1 | Survey / R1 |
| 2 | Backend Ingress Fallback Cascade | 3-tier fallback (Binance REST -> Parquet -> Synthetic) | M1 | Survey / R1 |
| 3 | Pytest Coverage for Klines API | Unit tests in `tests/unit/test_api.py` covering cache, params, and offline modes | M1 | Survey / R5 |
| 4 | Frontend Package Installation | Install `lightweight-charts@^5.2.1` with clean React 19 compatibility | M2 | Survey / R2 |
| 5 | Indicators Math Module | Pure functions for EMA 50, EMA 200, Volume colors, and Synthetic generation | M2 | Survey / R3 |
| 6 | Resilient Frontend API Client | `fetchMarketKlines()` with direct browser fallback to Binance public REST | M2 | Survey / R1 |
| 7 | Unit Tests for Math & Client | Vitest tests in `chart-indicators.test.ts` and `api.test.ts` | M2 | Survey / R5 |
| 8 | Lightweight Charts Component | `PairCandlestickChart` with Obsidian dark theme, auto-resize, and crosshair | M3 | Survey / R2 |
| 9 | Trend & Volume Overlays | Dynamic EMA 50 (cyan), EMA 200 (amber), and volume histogram (lower 20%) | M3 | Survey / R3 |
| 10 | Visual Bracket Price Lines | Horizontal lines for Entry (sky-blue), TP (+2.0x ATR green), SL (-1.2x ATR red) | M3 | Survey / R3 |
| 11 | Collapsible Chart Drawer UI | "📈 Carta Interaktif" toggle button on each pair card (`SOLUSDT`, `ETHUSDT`, `BTCUSDT`) | M4 | Survey / R4 |
| 12 | Drawer Header Controls | Timeframe pills (`15m` default, `1h`), indicator pills, OHLC badge, 24h high/low | M4 | Survey / R4 |
| 13 | Responsive Grid Adaptation | Auto-resize smoothly adapting across mobile, tablet, and desktop | M4 | Survey / R2 |
| 14 | Component Tests for Mission Control | Vitest tests verifying SSR safety (`renderToString`), drawer toggle, and badges | M4 | Survey / R5 |
| 15 | Comprehensive Test & Gate Verification | 100% pass rate on Vitest, Pytest, `npm run build`, Ruff, Mypy | M5 | Survey / R5 |
| 16 | Kainode VPS Deployment | Deploy frontend bundle & sync backend API to Kainode VPS (`147.79.18.15`) | M6 | Survey / R5 |
| 17 | Continuous Trader Daemon Invariant | Verify zero disruption to `autonomous-futures-trader.service` and live HTTPS serving | M6 | Survey / R5 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Kline Ingress API | Implement `GET /api/v1/market/klines` with 5s TTL cache, fallback, and pytest suite | None | DONE |
| M2 | Frontend Dependencies & Indicators Math | Install `lightweight-charts@^5.2.1`, implement `chart-indicators.ts` and `fetchMarketKlines()` | None | DONE |
| M3 | Interactive Candlestick Chart Component | Build `pair-candlestick-chart.tsx` with Obsidian dark theme, EMA 50/200, volume, and brackets | M2 | DONE |
| M4 | Executive Dashboard Drawer Integration | Integrate chart drawer into `market-positions-card.tsx` with timeframe/indicator pills | M3 | READY |
| M5 | Quality Gates & E2E Test Suite | Verify Vitest (100%), Pytest (100%), TypeScript, Ruff, and Mypy | M1, M4 | PLANNED |
| M6 | Production Build & VPS Zero-Disruption Deploy | Build production bundle, deploy to Kainode VPS (`147.79.18.15`), verify live serving | M5 | PLANNED |

## Interface Contracts
### Backend `GET /api/v1/market/klines`
- Parameters: `symbol: str = "SOLUSDT"`, `interval: str = "15m"`, `limit: int = 100`
- Response Schema (`MarketKlinesResponse`):
  ```json
  {
    "symbol": "SOLUSDT",
    "interval": "15m",
    "source": "binance_futures_live",
    "timestamp_ms": 1791570599000,
    "count": 100,
    "candles": [
      {
        "timestamp": 1791569700,
        "open": 109.72,
        "high": 109.79,
        "low": 109.52,
        "close": 109.53,
        "volume": 65965.9
      }
    ]
  }
  ```

### Frontend `fetchMarketKlines(symbol, interval, limit)`
- Returns: `Promise<MarketKline[]>` where `MarketKline` has `{ timestamp: number, open: number, high: number, low: number, close: number, volume: number }`.
- Behavior: Tries `/api/v1/market/klines` -> falls back to `https://fapi.binance.com/fapi/v1/klines` -> falls back to `generateSyntheticKlines()`.

### Chart Component `PairCandlestickChart`
- Props:
  ```typescript
  interface PairCandlestickChartProps {
    symbol: string
    interval: '15m' | '1h'
    activeIndicators: {
      ema50: boolean
      ema200: boolean
      volume: boolean
    }
    position?: PositionTelemetry
    onOhlcUpdate?: (ohlc: { open: number; high: number; low: number; close: number; volume: number; high24h: number; low24h: number } | null) => void
  }
  ```

## Code Layout
- `src/autonomous_futures/api/app.py`: Backend FastAPI routes and models
- `tests/unit/test_api.py`: Backend API test suite
- `frontend/package.json`: Frontend npm dependencies
- `frontend/src/lib/chart-indicators.ts`: Pure indicator calculations and synthetic data
- `frontend/src/lib/chart-indicators.test.ts`: Indicator tests
- `frontend/src/lib/api.ts`: API client functions
- `frontend/src/components/mission-control/pair-candlestick-chart.tsx`: TradingView Lightweight Charts canvas component
- `frontend/src/components/mission-control/market-positions-card.tsx`: Pair cards and interactive chart collapsible drawer
- `frontend/src/components/__tests__/executive-dashboard.test.tsx`: Mission Control component tests
