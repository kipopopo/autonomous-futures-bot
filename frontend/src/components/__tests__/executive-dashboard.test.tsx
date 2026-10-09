import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { MissionControlHeader } from '../mission-control/mission-control-header'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ResearchArchiveDrawer, ARCHIVE_PHASES } from '../mission-control/research-archive-drawer'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import type { ExecutiveDashboardModel } from '../mission-control/types'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
} from '@/lib/canary'

const MOCK_MODEL: ExecutiveDashboardModel = {
  botStatus: {
    state: 'ACTIVE 24/7',
    gatewayMode: 'BINANCE TESTNET GATEWAY',
    circuitBreaker: 'NORMAL',
    tripwiresCount: 0,
    lastSyncedAtMyt: '09 Oct 14:30:00',
    isStreaming: true,
  },
  kpis: {
    totalEquityUsdt: 100.2038,
    cashUsdt: 100.2038,
    allocatedMarginUsdt: 0.0,
    realizedPnlUsdt: 0.2038,
    winRatePct: 100.0,
    totalTrades: 18,
    activeExposureUsdt: 5.5,
    maxExposureCapUsdt: 25.0,
    cashReservePct: 100.0,
    minCashReserveFloorPct: 75.0,
    latencyMs: 12.4,
    interlockBlocksCount: 1,
    balanceDriftUsdt: 0.0,
    isZeroDriftVerified: true,
  },
  positions: [
    {
      symbol: 'SOLUSDT',
      currentPrice: 185.0,
      state: 'SCANNING / STANDBY',
      entryPrice: 0.0,
      size: 0.0,
      notionalUsdt: 0.0,
      marginUsdt: 0.0,
      unrealizedPnlUsdt: 0.0,
      unrealizedPnlPct: 0.0,
      takeProfitPrice: 190.3,
      stopLossPrice: 181.8,
      riskRewardRatio: '1.66 : 1',
    },
    {
      symbol: 'ETHUSDT',
      currentPrice: 2750.0,
      state: 'LONG',
      entryPrice: 2735.0,
      size: 0.002,
      notionalUsdt: 5.5,
      marginUsdt: 5.5,
      unrealizedPnlUsdt: 0.03,
      unrealizedPnlPct: 0.55,
      takeProfitPrice: 2820.0,
      stopLossPrice: 2693.0,
      riskRewardRatio: '1.66 : 1',
    },
    {
      symbol: 'BTCUSDT',
      currentPrice: 95000.0,
      state: 'SCANNING / STANDBY',
      entryPrice: 0.0,
      size: 0.0,
      notionalUsdt: 0.0,
      marginUsdt: 0.0,
      unrealizedPnlUsdt: 0.0,
      unrealizedPnlPct: 0.0,
      takeProfitPrice: 96700.0,
      stopLossPrice: 93980.0,
      riskRewardRatio: '1.66 : 1',
    },
  ],
  radar: {
    btcMacroTrend: {
      regime: 'BULLISH ALIGNED',
      ema50_1h: 95420.0,
      ema200_1h: 93810.0,
      ema50_4h: 94800.0,
      ema200_4h: 91200.0,
      explanation:
        'Longs enabled: Bitcoin macro trend aligned bullish across 1h & 4h timeframes.',
    },
    scalperCriteria: {
      priceBelowEma20Atr: 1.8,
      priceBelowEmaThreshold: 2.5,
      priceTriggered: false,
      relativeVolume: 1.4,
      volumeThreshold: 2.2,
      volumeTriggered: false,
      rsi14: 38.5,
      rsiThreshold: 26.0,
      rsiTriggered: false,
      makerFeePct: 0.02,
    },
    hawkesHazard: {
      spectralRadius: 0.4286,
      isNonToxic: true,
      thresholdWarning: 0.85,
      thresholdCritical: 1.0,
      recentHistory: [0.35, 0.38, 0.42, 0.4286],
    },
  },
  orders: [
    {
      orderId: 'ord-001',
      timestampMyt: '09 Oct 14:00:00',
      symbol: 'SOLUSDT',
      side: 'BUY',
      orderType: 'LIMIT MAKER',
      price: 171.0,
      quantity: 0.03,
      notionalUsdt: 5.13,
      makerFeeUsdt: 0.001,
      realizedPnlUsdt: 0.0,
      status: 'FILLED',
    },
    {
      orderId: 'ord-002',
      timestampMyt: '09 Oct 14:15:00',
      symbol: 'SOLUSDT',
      side: 'SELL',
      orderType: 'LIMIT MAKER',
      price: 177.9,
      quantity: 0.03,
      notionalUsdt: 5.337,
      makerFeeUsdt: 0.0011,
      realizedPnlUsdt: 0.207,
      status: 'FILLED',
    },
  ],
}

describe('MissionControlHeader component', () => {
  it('renders bot status, gateway mode, circuit state, and streaming indicator', () => {
    const html = renderToString(
      <MissionControlHeader
        status={MOCK_MODEL.botStatus}
        onRefresh={() => {}}
        isLoading={false}
      />,
    )

    expect(html).toContain('Autonomous Futures')
    expect(html).toContain('ACTIVE 24/7')
    expect(html).toContain('BINANCE TESTNET GATEWAY')
    expect(html).toContain('CIRCUIT: NORMAL')
    expect(html).toContain('STREAMING')
    expect(html).toContain('MYT (UTC+8)')
    expect(html).toContain('Segar Semula')
  })
})

describe('KpiCards component', () => {
  it('renders all 4 Key Owner KPI Cards with genuine metrics and zero-drift verification', () => {
    const html = renderToString(<KpiCards kpis={MOCK_MODEL.kpis} />)

    // Card 1: Balance & Equity
    expect(html).toContain('Jumlah Ekuiti &amp; Baki')
    expect(html).toContain('$100.2038')
    expect(html).toContain('$100.20 (100.0%)')

    // Card 2: Net Realized PnL & Win Rate
    expect(html).toContain('Untung Bersih &amp; Kadar Kemenangan')
    expect(html).toContain('+$0.2038')
    expect(html).toContain('100.0% Win Rate')
    expect(html).toContain('18 Dagangan Selesai')
    expect(html).toContain('100% Maker (0.02%)')

    // Card 3: Active Exposure & Sizing
    expect(html).toContain('Pendedahan Aktif &amp; Had Siling')
    expect(html).toContain('$5.50')
    expect(html).toContain('/ $25.00 Had Maksimum')
    expect(html).toContain('Lantai ≥ 75%')

    // Card 4: System Health & Zero-Drift Solvency
    expect(html).toContain('Kesihatan Sistem &amp; Ketulenan')
    expect(html).toContain('|Δ| &lt; 10⁻¹⁵')
    expect(html).toContain('Sifar Drift (Zero-Drift Solvency)')
    expect(html).toContain('12.4 ms')
    expect(html).toContain('1 Sekatan (0 Bahaya)')
  })
})

describe('MarketPositionsCard component', () => {
  it('renders staged pairs (SOLUSDT, ETHUSDT, BTCUSDT) with TP/SL and 1.66:1 R:R', () => {
    const html = renderToString(<MarketPositionsCard positions={MOCK_MODEL.positions} />)

    expect(html).toContain('Pasaran Langsung &amp; Posisi Aktif')
    expect(html).toContain('1.66 : 1 Nisbah R:R')

    // Pairs
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('BTCUSDT')

    // States
    expect(html).toContain('SCANNING / STANDBY')
    expect(html).toContain('LONG')

    // TP/SL targets
    expect(html).toContain('190.30')
    expect(html).toContain('181.80')
  })
})

describe('StrategyConfluenceRadar component', () => {
  it('renders BTC macro trend regime, 15m scalper checklist, and Hawkes hazard gauge', () => {
    const html = renderToString(
      <StrategyConfluenceRadar
        btcMacroTrend={MOCK_MODEL.radar.btcMacroTrend}
        scalperCriteria={MOCK_MODEL.radar.scalperCriteria}
        hawkesHazard={MOCK_MODEL.radar.hawkesHazard}
      />,
    )

    // Panel 1: BTC Macro Trend
    expect(html).toContain('Penapis Trend Makro BTC')
    expect(html).toContain('BULLISH ALIGNED')
    expect(html).toContain('EMA50: $95,420')
    expect(html).toContain('EMA200: $93,810')

    // Panel 2: 15m Scalper Checklist
    expect(html).toContain('Senarai Semak Skalper 15m')
    expect(html).toContain('1.8x ATR')
    expect(html).toContain('1.4x SMA')
    expect(html).toContain('38.5')
    expect(html).toContain('0.02% Yuran')

    // Panel 3: Hawkes Hazard
    expect(html).toContain('Bahaya Mikrostruktur &amp; Hawkes')
    expect(html).toContain('SELAMAT / TIDAK TOKSIK')
    expect(html).toContain('ρ = 0.4286')
    expect(html).toContain('Amaran: ρ ≥ 0.85')
    expect(html).toContain('Kritikal: ρ ≥ 1.00')
  })
})

describe('OrderFeedTable component', () => {
  it('renders recent orders with MYT timestamps and maker fees', () => {
    const html = renderToString(<OrderFeedTable orders={MOCK_MODEL.orders} />)

    expect(html).toContain('Suapan Pesanan &amp; Log Pelaksanaan Langsung')
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('BUY')
    expect(html).toContain('SELL')
    expect(html).toContain('+$0.2070')
    expect(html).toContain('09 Oct 14:00:00')
    expect(html).toContain('0.02%')
  })
})

describe('ResearchArchiveDrawer component', () => {
  it('enumerates all 23 historical phases and categories', () => {
    expect(ARCHIVE_PHASES.length).toBe(23)

    const htmlOpen = renderToString(
      <ResearchArchiveDrawer
        isOpen={true}
        onClose={() => {}}
        onSelectPhase={() => {}}
      />,
    )

    expect(htmlOpen).toContain('Arkib Penyelidikan (Research Archives)')
    expect(htmlOpen).toContain('23 Fasa Sejarah')

    // Key historical phases
    expect(htmlOpen).toContain('Fasa 250')
    expect(htmlOpen).toContain('Fasa 291')
    expect(htmlOpen).toContain('Fasa 309')
    expect(htmlOpen).toContain('Avellaneda-Stoikov')

    const htmlClosed = renderToString(
      <ResearchArchiveDrawer
        isOpen={false}
        onClose={() => {}}
        onSelectPhase={() => {}}
      />,
    )
    expect(htmlClosed).toBe('')
  })
})

describe('ExecutiveDashboard component', () => {
  it('assembles the full executive landing page cleanly', () => {
    const html = renderToString(
      <ExecutiveDashboard
        model={MOCK_MODEL}
        onRefresh={() => {}}
        isLoading={false}
      />,
    )

    expect(html).toContain('Autonomous Futures')
    expect(html).toContain('Jumlah Ekuiti &amp; Baki')
    expect(html).toContain('Pasaran Langsung &amp; Posisi Aktif')
    expect(html).toContain('Radar Konfluens Strategi &amp; Skalper 15m')
    expect(html).toContain('Suapan Pesanan &amp; Log Pelaksanaan Langsung')
  })
})

describe('buildExecutiveDashboardModel adapter', () => {
  it('correctly adapts live canary models into verified ExecutiveDashboardModel', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const telemetry = {
      status: 'open' as const,
      error: null,
      snapshot: null,
      hawkesMetrics: null,
      spectralRadiusHistory: [{ timestamp: 1, spectralRadius: 0.42 }],
      latencyMs: 15.0,
      lastMessageAt: new Date(),
    }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
    )

    expect(adapted.botStatus.state).toBe('ACTIVE 24/7')
    expect(adapted.botStatus.gatewayMode).toBe('BINANCE TESTNET GATEWAY')
    expect(adapted.botStatus.circuitBreaker).toBe('NORMAL')
    expect(adapted.botStatus.isStreaming).toBe(true)

    expect(adapted.kpis.totalEquityUsdt).toBeGreaterThanOrEqual(100.0)
    expect(adapted.kpis.isZeroDriftVerified).toBe(true)
    expect(adapted.kpis.winRatePct).toBe(100.0)
    expect(adapted.kpis.maxExposureCapUsdt).toBe(25.0)
    expect(adapted.kpis.minCashReserveFloorPct).toBe(75.0)

    expect(adapted.positions.length).toBe(3)
    expect(adapted.positions[0].symbol).toBe('SOLUSDT')
    expect(adapted.positions[1].symbol).toBe('ETHUSDT')
    expect(adapted.positions[2].symbol).toBe('BTCUSDT')

    expect(adapted.radar.btcMacroTrend.regime).toBe('BULLISH ALIGNED')
    expect(adapted.radar.hawkesHazard.isNonToxic).toBe(true)
    expect(adapted.orders.length).toBeGreaterThan(0)
  })
})
