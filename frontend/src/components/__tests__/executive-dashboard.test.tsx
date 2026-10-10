import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { MissionControlHeader } from '../mission-control/mission-control-header'
import { KpiCards } from '../mission-control/kpi-cards'
import { MarketPositionsCard } from '../mission-control/market-positions-card'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { ResearchArchiveDrawer, ARCHIVE_PHASES } from '../mission-control/research-archive-drawer'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import type { ExecutiveDashboardModel, PositionTelemetry } from '../mission-control/types'
import {
  buildProductionLaunchModel,
  buildLiveMarketModel,
  buildBracketPositionsModel,
  buildMicrostructureModel,
  buildAutoEvolutionModel,
  buildStrategyMiningModel,
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
    totalEquityUsdt: 100.0,
    cashUsdt: 100.0,
    allocatedMarginUsdt: 0.0,
    realizedPnlUsdt: 0.0,
    winRatePct: 100.0,
    totalTrades: 0,
    activeExposureUsdt: 0.0,
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
      state: 'SCANNING / STANDBY',
      entryPrice: 0.0,
      size: 0.0,
      notionalUsdt: 0.0,
      marginUsdt: 0.0,
      unrealizedPnlUsdt: 0.0,
      unrealizedPnlPct: 0.0,
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
      orderId: 'canary-p311-drill-sol-1791554786355',
      timestampMyt: '09 Oct 14:00:00',
      symbol: 'SOLUSDT',
      side: 'BUY',
      orderType: 'LIMIT MAKER',
      price: 185.0,
      quantity: 0.03,
      notionalUsdt: 5.55,
      makerFeeUsdt: 0.00111,
      realizedPnlUsdt: 0.0,
      status: 'FILLED',
    },
    {
      orderId: 'ord-p310-sol-0002',
      timestampMyt: '09 Oct 14:15:00',
      symbol: 'SOLUSDT',
      side: 'SELL',
      orderType: 'LIMIT MAKER',
      price: 177.9,
      quantity: 0.03,
      notionalUsdt: 5.337,
      makerFeeUsdt: 0.0010674,
      realizedPnlUsdt: 0.207,
      status: 'FILLED',
    },
  ],
  evolutionRadar: {
    activeStrategyFamily: '15m Macro-Confluence Liquidity Scalper',
    microstructureFilter: 'Hawkes Microstructure Filter',
    activeCandidateId: 'cand-macro-scalper-v1',
    candidateHealthTier: 'ELITE',
    generation: 'GEN #2',
    rollingSharpe: 2.45,
    winRatePct: 78.5,
    maxDrawdownPct: 4.2,
    hawkesResilienceScore: 0.94,
    gates: [
      {
        id: 'gate-return',
        name: 'Pulangan Purata OOS',
        thresholdLabel: '≥ 0.0%',
        actualValueLabel: '+14.8%',
        passed: true,
      },
      {
        id: 'gate-drawdown',
        name: 'Drawdown Maksimum OOS',
        thresholdLabel: '≤ 15.0%',
        actualValueLabel: '4.2%',
        passed: true,
      },
      {
        id: 'gate-profit-factor',
        name: 'Faktor Keuntungan OOS',
        thresholdLabel: '≥ 1.05',
        actualValueLabel: '1.84',
        passed: true,
      },
      {
        id: 'gate-trade-count',
        name: 'Jumlah Dagangan OOS',
        thresholdLabel: '≥ 5',
        actualValueLabel: '24',
        passed: true,
      },
      {
        id: 'gate-stress',
        name: 'Ketahanan Tekanan Ranap Kilat',
        thresholdLabel: '-20% Crash / 10% Shock',
        actualValueLabel: 'SURVIVED',
        passed: true,
      },
    ],
    allGatesPassed: true,
    attributionGauges: [
      {
        id: 'timing-error',
        label: 'Kesilapan Masa Kemasukan (Timing Error)',
        bps: 1.8,
        thresholdBps: 5.0,
        isOptimal: true,
        description: 'Kemasukan Maker Limit pada titik kecairan maksimum tanpa kelewatan eksekusi',
      },
      {
        id: 'adverse-selection',
        label: 'Pilihan Buruk (Adverse Selection)',
        bps: -0.6,
        thresholdBps: 3.0,
        isOptimal: true,
        description: 'Penapis intensiti Hawkes menghalang pengisian pesanan sewaktu aliran toksik',
      },
      {
        id: 'net-edge',
        label: 'Kelebihan Bersih Pelaksanaan (Net Edge)',
        bps: 8.4,
        thresholdBps: 5.0,
        isOptimal: true,
        description: 'Lebihan alfa bersih positif selepas yuran maker 0.02% dan seretan gelinciran',
      },
    ],
    totalAutopsies: 18,
    promotedCandidatesCount: 3,
  },
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
    expect(html).toContain('$100.00')
    expect(html).toContain('$100.00 (100.0%)')

    // Card 2: Net Realized PnL & Win Rate
    expect(html).toContain('Untung Bersih &amp; Kadar Kemenangan')
    expect(html).toContain('+$0.00')
    expect(html).toContain('100.0% Win Rate')
    expect(html).toContain('0 Dagangan Selesai')
    expect(html).toContain('100% Maker (0.02%)')

    // Card 3: Active Exposure & Sizing
    expect(html).toContain('Pendedahan Aktif &amp; Had Siling')
    expect(html).toContain('$0.00')
    expect(html).toContain('/ $25.00 Had Maksimum')
    expect(html).toContain('100.0% (Lantai ≥ 75%)')

    // Card 4: System Health & Zero-Drift Solvency
    expect(html).toContain('Kesihatan Sistem &amp; Ketulenan')
    expect(html).toContain('|Δ| &lt; 10⁻¹⁵')
    expect(html).toContain('Sifar Drift (Zero-Drift Solvency)')
    expect(html).toContain('12.4 ms')
    expect(html).toContain('1 Sekatan (0 Bahaya)')
  })
})

describe('MarketPositionsCard component', () => {
  it('renders staged pairs (SOLUSDT, ETHUSDT, BTCUSDT) with TP/SL and 1.66:1 R:R in clean standby state', () => {
    const html = renderToString(<MarketPositionsCard positions={MOCK_MODEL.positions} />)

    expect(html).toContain('Pasaran Langsung &amp; Posisi Aktif')
    expect(html).toContain('1.66 : 1 Nisbah R:R')

    // Pairs
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('BTCUSDT')

    // States
    expect(html).toContain('SCANNING / STANDBY')

    // TP/SL targets
    expect(html).toContain('190.30')
    expect(html).toContain('181.80')
  })

  it('renders active LONG position with entry price and unrealized PnL when populated', () => {
    const activePositions: PositionTelemetry[] = [
      {
        ...MOCK_MODEL.positions[0],
        state: 'LONG',
        entryPrice: 180.0,
        size: 0.03,
        notionalUsdt: 5.55,
        marginUsdt: 5.55,
        unrealizedPnlUsdt: 0.15,
        unrealizedPnlPct: 2.7,
      },
    ]
    const html = renderToString(<MarketPositionsCard positions={activePositions} />)
    expect(html).toContain('LONG')
    expect(html).toContain('Harga Masuk:')
    expect(html).toContain('180.00')
    expect(html).toContain('PnL Belum Direalisasi:')
    expect(html).toContain('0.150')
  })

  it('renders "📈 Carta Interaktif" toggle button with collapsed state by default on each candidate pair card', () => {
    const html = renderToString(<MarketPositionsCard positions={MOCK_MODEL.positions} />)

    // Button presence on all staged candidate pair cards
    expect(html).toContain('Carta Interaktif')
    expect(html).toContain('data-testid="toggle-chart-solusdt"')
    expect(html).toContain('data-testid="toggle-chart-ethusdt"')
    expect(html).toContain('data-testid="toggle-chart-btcusdt"')

    // Badges indicate collapsed state by default
    expect(html).toContain('Dikecilkan')
    expect(html).toContain('data-testid="toggle-all-charts-button"')

    // Drawer is collapsed by default (not rendered)
    expect(html).not.toContain('data-testid="chart-drawer-solusdt"')
    expect(html).not.toContain('data-testid="chart-drawer-ethusdt"')
    expect(html).not.toContain('data-testid="chart-drawer-btcusdt"')
  })

  it('renders collapsible chart drawer with timeframe tabs, indicator pills, OHLC badge, and PairCandlestickChart when expanded', () => {
    const html = renderToString(
      <MarketPositionsCard positions={MOCK_MODEL.positions} initialExpanded={true} />,
    )

    // Drawer container rendered for all pairs
    expect(html).toContain('data-testid="chart-drawer-solusdt"')
    expect(html).toContain('data-testid="chart-drawer-ethusdt"')
    expect(html).toContain('data-testid="chart-drawer-btcusdt"')
    expect(html).toContain('Dibuka')

    // Timeframe pills (15m default scalper, 1h macro trend)
    expect(html).toContain('data-testid="timeframe-15m-solusdt"')
    expect(html).toContain('data-testid="timeframe-1h-solusdt"')
    expect(html).toContain('15m')
    expect(html).toContain('1h')

    // Quick indicator toggle pills
    expect(html).toContain('data-testid="indicator-ema50-solusdt"')
    expect(html).toContain('data-testid="indicator-ema200-solusdt"')
    expect(html).toContain('data-testid="indicator-volume-solusdt"')
    expect(html).toContain('EMA 50')
    expect(html).toContain('EMA 200')
    expect(html).toContain('Volume')

    // Current OHLC badge and 24h High/Low markers
    expect(html).toContain('data-testid="ohlc-badge-solusdt"')
    expect(html).toContain('OHLC')
    expect(html).toContain('24h High')
    expect(html).toContain('24h Low')

    // Embedded PairCandlestickChart canvas container
    expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')
    expect(html).toContain('data-testid="pair-candlestick-chart-ethusdt"')
    expect(html).toContain('data-testid="pair-candlestick-chart-btcusdt"')
  })

  it('supports selective per-symbol chart drawer expansion', () => {
    const html = renderToString(
      <MarketPositionsCard
        positions={MOCK_MODEL.positions}
        initialExpanded={{ ETHUSDT: true }}
      />,
    )

    // ETHUSDT drawer is expanded
    expect(html).toContain('data-testid="chart-drawer-ethusdt"')
    expect(html).toContain('data-testid="pair-candlestick-chart-ethusdt"')

    // SOLUSDT and BTCUSDT remain collapsed
    expect(html).not.toContain('data-testid="chart-drawer-solusdt"')
    expect(html).not.toContain('data-testid="chart-drawer-btcusdt"')
  })

  it('supports defaultInterval prop override for macro trend view', () => {
    const html = renderToString(
      <MarketPositionsCard
        positions={MOCK_MODEL.positions}
        initialExpanded={true}
        defaultInterval="1h"
      />,
    )

    // PairCandlestickChart receives interval 1h
    expect(html).toContain('data-interval="1h"')
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
    expect(html).toContain('Status Pembelajaran &amp; Autopsi Strategi')
    expect(html).toContain('Suapan Pesanan &amp; Log Pelaksanaan Langsung')
  })
})

describe('StrategyEvolutionRadar component', () => {
  it('renders executive Strategy Evolution Radar card with 3 panels, OOS gates, and autopsy attribution', () => {
    const html = renderToString(
      <StrategyEvolutionRadar evolutionRadar={MOCK_MODEL.evolutionRadar} />,
    )

    // Title and daemon status
    expect(html).toContain('Status Pembelajaran &amp; Autopsi Strategi')
    expect(html).toContain('GELUNG AKTIF (ACTIVE DAEMON)')
    expect(html).toContain('GEN #2')

    // Deep dive links
    expect(html).toContain('href="#/evolution"')
    expect(html).toContain('Autopsi &amp; Evolusi Penuh')
    expect(html).toContain('href="#/mining"')
    expect(html).toContain('Perlombongan Strategi')

    // Panel 1: Strategy family and candidate health tier
    expect(html).toContain('15m Macro-Confluence Liquidity Scalper')
    expect(html).toContain('Hawkes Microstructure Filter')
    expect(html).toContain('cand-macro-scalper-v1')
    expect(html).toContain('ELITE')
    expect(html).toContain('2.45') // Rolling Sharpe
    expect(html).toContain('78.5%') // Win rate
    expect(html).toContain('4.2%') // Drawdown
    expect(html).toContain('0.94') // Hawkes resilience

    // Panel 2: 5 Walk-Forward OOS Qualification Gates
    expect(html).toContain('5 Pintu Kelayakan OOS')
    expect(html).toContain('5 / 5 PINTU LULUS')
    expect(html).toContain('Pulangan Purata OOS')
    expect(html).toContain('+14.8%')
    expect(html).toContain('Drawdown Maksimum OOS')
    expect(html).toContain('Faktor Keuntungan OOS')
    expect(html).toContain('1.84')
    expect(html).toContain('Jumlah Dagangan OOS')
    expect(html).toContain('24')
    expect(html).toContain('Ketahanan Tekanan Ranap Kilat')
    expect(html).toContain('SURVIVED')

    // Panel 3: Trade Autopsy Attribution Gauges
    expect(html).toContain('Tolok Atribusi Autopsi Dagangan')
    expect(html).toContain('Kesilapan Masa Kemasukan (Timing Error)')
    expect(html).toContain('+1.8 bps')
    expect(html).toContain('Pilihan Buruk (Adverse Selection)')
    expect(html).toContain('-0.6 bps')
    expect(html).toContain('Kelebihan Bersih Pelaksanaan (Net Edge)')
    expect(html).toContain('+8.4 bps')
    expect(html).toContain('OPTIMAL')
    expect(html).toContain('18 Autopsi')
    expect(html).toContain('3 Calon Promosi Aktif')
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

    expect(adapted.evolutionRadar.activeStrategyFamily).toBe(
      '15m Macro-Confluence Liquidity Scalper',
    )
    expect(adapted.evolutionRadar.candidateHealthTier).toBe('ELITE')
    expect(adapted.evolutionRadar.allGatesPassed).toBe(true)
    expect(adapted.evolutionRadar.gates.length).toBe(5)
    expect(adapted.evolutionRadar.attributionGauges.length).toBe(3)
  })

  it('correctly adapts with live autoEvolution and strategyMining models', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const autoEvo = buildAutoEvolutionModel(null)
    const stratMining = buildStrategyMiningModel(null)
    const telemetry = {
      status: 'STREAMING' as const,
      error: null,
      snapshot: null,
      hawkesMetrics: null,
      spectralRadiusHistory: [],
      latencyMs: 10.0,
      lastMessageAt: new Date(),
    }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      telemetry,
      new Date(),
      autoEvo,
      stratMining,
    )

    expect(adapted.evolutionRadar.activeStrategyFamily).toBe(
      '15m Macro-Confluence Liquidity Scalper',
    )
    expect(adapted.evolutionRadar.candidateHealthTier).toBe('ELITE')
    expect(adapted.evolutionRadar.gates.length).toBe(5)
    expect(adapted.evolutionRadar.gates[4].actualValueLabel).toBe('SURVIVED')
  })

  it('preserves 0.00 active exposure and 100.0% cash reserve when flat', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const flatProdLaunch = {
      ...prodLaunch,
      aggregateExposureUsdt: 0.0,
      candidateAllocations: prodLaunch.candidateAllocations.map((a) => ({
        ...a,
        position_qty: 0.0,
        allocated_exposure_usdt: 0.0,
      })),
      solvency: {
        ...prodLaunch.solvency,
        total_equity_usdt: 100.0,
        cash_usdt: 100.0,
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        cash_reserve_pct: 100.0,
      },
    }
    const liveMarket = buildLiveMarketModel(null)
    const brackets = { ...buildBracketPositionsModel(null), positions: [] }
    const micro = buildMicrostructureModel(null)

    const adapted = buildExecutiveDashboardModel(
      flatProdLaunch,
      liveMarket,
      brackets,
      micro,
      {},
      new Date(),
    )

    expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
    expect(adapted.kpis.cashReservePct).toBe(100.0)
    expect(adapted.kpis.totalEquityUsdt).toBe(100.0)
    expect(adapted.kpis.cashUsdt).toBe(100.0)
    expect(adapted.positions.every((p) => p.state === 'SCANNING / STANDBY')).toBe(true)
    expect(
      adapted.positions.every(
        (p) => p.notionalUsdt === 0.0 && p.size === 0.0 && p.marginUsdt === 0.0,
      ),
    ).toBe(true)
  })

  it('purges Phase 309 simulation positions and prevents phantom positions when phase is phase_309', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const phase309ProdLaunch = {
      ...prodLaunch,
      phase: 'phase_309',
      aggregateExposureUsdt: 0.0,
      candidateAllocations: [
        {
          symbol: 'ETHUSDT',
          current_price: 2750.0,
          position_qty: -0.002,
          entry_price: 2750.0,
          allocated_exposure_usdt: 5.5,
          unrealized_pnl_usdt: 0.0,
          realized_pnl_usdt: 0.0,
          total_fees_usdt: 0.001,
          trades_count: 1,
        },
        {
          symbol: 'SOLUSDT',
          current_price: 185.0,
          position_qty: 0.03,
          entry_price: 185.0,
          allocated_exposure_usdt: 5.55,
          unrealized_pnl_usdt: 0.0,
          realized_pnl_usdt: 0.0,
          total_fees_usdt: 0.001,
          trades_count: 1,
        },
      ],
    }
    const liveMarket = buildLiveMarketModel(null)
    const brackets = { ...buildBracketPositionsModel(null), positions: [] }
    const micro = buildMicrostructureModel(null)

    const adapted = buildExecutiveDashboardModel(
      phase309ProdLaunch,
      liveMarket,
      brackets,
      micro,
      {},
      new Date(),
    )

    const ethPos = adapted.positions.find((p) => p.symbol === 'ETHUSDT')
    const solPos = adapted.positions.find((p) => p.symbol === 'SOLUSDT')

    expect(ethPos?.state).toBe('SCANNING / STANDBY')
    expect(ethPos?.size).toBe(0.0)
    expect(ethPos?.notionalUsdt).toBe(0.0)
    expect(ethPos?.marginUsdt).toBe(0.0)
    expect(ethPos?.unrealizedPnlUsdt).toBe(0.0)

    expect(solPos?.state).toBe('SCANNING / STANDBY')
    expect(solPos?.size).toBe(0.0)
    expect(solPos?.notionalUsdt).toBe(0.0)
    expect(solPos?.marginUsdt).toBe(0.0)
    expect(solPos?.unrealizedPnlUsdt).toBe(0.0)

    expect(adapted.kpis.activeExposureUsdt).toBe(0.0)
  })

  it('excludes ord-p309- records and renders authentic Phase 310 and Phase 311 orders', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const mixedOrdersLaunch = {
      ...prodLaunch,
      recentOrders: [
        {
          order_id: 'ord-p309-btcusdt-0001',
          symbol: 'BTCUSDT',
          side: 'BUY' as const,
          order_type: 'LIMIT',
          price: 95000.0,
          quantity: 0.001,
          notional_usdt: 95.0,
          status: 'FILLED',
          fill_price: 95000.0,
          fee_usdt: 0.02,
          realized_pnl_usdt: 0.0,
          timestamp_ms: 1790200000000,
        },
        {
          order_id: 'ord-p309-ethusdt-0002',
          symbol: 'ETHUSDT',
          side: 'SELL' as const,
          order_type: 'LIMIT',
          price: 2750.0,
          quantity: 0.002,
          notional_usdt: 5.5,
          status: 'FILLED',
          fill_price: 2750.0,
          fee_usdt: 0.0011,
          realized_pnl_usdt: 0.05,
          timestamp_ms: 1790200500000,
        },
        {
          order_id: 'ord-p310-sol-0001',
          symbol: 'SOLUSDT',
          side: 'BUY' as const,
          order_type: 'LIMIT',
          price: 171.0,
          quantity: 0.03,
          notional_usdt: 5.13,
          status: 'FILLED',
          fill_price: 171.0,
          fee_usdt: 0.001026,
          realized_pnl_usdt: 0.0,
          timestamp_ms: 1790250000000,
        },
        {
          order_id: 'canary-p311-drill-sol-1791554786355',
          symbol: 'SOLUSDT',
          side: 'BUY' as const,
          order_type: 'LIMIT MAKER',
          price: 185.0,
          quantity: 0.03,
          notional_usdt: 5.55,
          status: 'FILLED',
          fill_price: 185.0,
          fee_usdt: 0.00111,
          realized_pnl_usdt: 0.0,
          timestamp_ms: 1791554786355,
        },
      ],
    }
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)

    const adapted = buildExecutiveDashboardModel(
      mixedOrdersLaunch,
      liveMarket,
      brackets,
      micro,
      {},
      new Date(),
    )

    // Ensure no ord-p309- artifacts survive
    expect(adapted.orders.some((o) => o.orderId.startsWith('ord-p309-'))).toBe(false)
    expect(adapted.orders.some((o) => o.orderId === 'ord-p310-sol-0001')).toBe(true)
    expect(
      adapted.orders.some((o) => o.orderId === 'canary-p311-drill-sol-1791554786355'),
    ).toBe(true)
  })

  it('falls back to authentic Phase 310 and Phase 311 testnet drills when order feed is empty', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const emptyOrdersLaunch = {
      ...prodLaunch,
      recentOrders: [],
    }
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)

    const adapted = buildExecutiveDashboardModel(
      emptyOrdersLaunch,
      liveMarket,
      brackets,
      micro,
      {},
      new Date(),
    )

    expect(adapted.orders.length).toBeGreaterThanOrEqual(3)
    expect(adapted.orders.every((o) => !o.orderId.startsWith('ord-p309-'))).toBe(true)
    expect(adapted.orders.some((o) => o.orderId.startsWith('canary-p311-'))).toBe(true)
    expect(adapted.orders.some((o) => o.orderId.startsWith('ord-p310-'))).toBe(true)
  })
})
