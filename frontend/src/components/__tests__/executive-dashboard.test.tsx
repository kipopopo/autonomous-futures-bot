import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import { MissionControlHeader } from '../mission-control/mission-control-header'
import { KpiCards } from '../mission-control/kpi-cards'
import { StrategyConfluenceRadar } from '../mission-control/strategy-confluence-radar'
import { StrategyEvolutionRadar } from '../mission-control/strategy-evolution-radar'
import { OrderFeedTable } from '../mission-control/order-feed-table'
import { PairPriceTickersCard } from '../mission-control/pair-price-tickers-card'
import { ResearchArchiveDrawer, ARCHIVE_PHASES } from '../mission-control/research-archive-drawer'
import { ExecutiveDashboard } from '../mission-control/executive-dashboard'
import { buildExecutiveDashboardModel } from '../mission-control/adapter'
import type { ExecutiveDashboardModel } from '../mission-control/types'
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
        name: 'Average Return OOS',
        thresholdLabel: '≥ 0.0%',
        actualValueLabel: '+14.8%',
        passed: true,
      },
      {
        id: 'gate-drawdown',
        name: 'Maximum Drawdown OOS',
        thresholdLabel: '≤ 15.0%',
        actualValueLabel: '4.2%',
        passed: true,
      },
      {
        id: 'gate-profit-factor',
        name: 'Profit Factor OOS',
        thresholdLabel: '≥ 1.05',
        actualValueLabel: '1.84',
        passed: true,
      },
      {
        id: 'gate-trade-count',
        name: 'Trade Count OOS',
        thresholdLabel: '≥ 5',
        actualValueLabel: '24',
        passed: true,
      },
      {
        id: 'gate-stress',
        name: 'Flash Crash Stress Resilience',
        thresholdLabel: '-20% Crash / 10% Shock',
        actualValueLabel: 'SURVIVED',
        passed: true,
      },
    ],
    allGatesPassed: true,
    attributionGauges: [
      {
        id: 'timing-error',
        label: 'Timing Error (Entry Timing)',
        bps: 1.8,
        thresholdBps: 5.0,
        isOptimal: true,
        description: 'Maker limit entry execution at maximum liquidity without execution delay',
      },
      {
        id: 'adverse-selection',
        label: 'Adverse Selection',
        bps: -0.6,
        thresholdBps: 3.0,
        isOptimal: true,
        description: 'Hawkes intensity filter blocks order fills during toxic order flow',
      },
      {
        id: 'net-edge',
        label: 'Net Edge (Execution Edge)',
        bps: 8.4,
        thresholdBps: 5.0,
        isOptimal: true,
        description: 'Positive net alpha surplus after 0.02% maker fee and slippage drag',
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
    expect(html).toContain('Refresh')
  })
})

describe('KpiCards component', () => {
  it('renders all 4 Key Owner KPI Cards with genuine metrics and zero-drift verification', () => {
    const html = renderToString(<KpiCards kpis={MOCK_MODEL.kpis} />)

    // Card 1: Balance & Equity
    expect(html).toContain('Total Balance &amp; Equity')
    expect(html).toContain('$100.00')
    expect(html).toContain('$100.00 (100.0%)')

    // Card 2: Net Realized PnL & Win Rate
    expect(html).toContain('Net Realized PnL &amp; Win Rate')
    expect(html).toContain('+$0.00')
    expect(html).toContain('100.0% Win Rate')
    expect(html).toContain('0 Completed Trades')
    expect(html).toContain('100% Maker (0.02%)')

    // Card 3: Active Exposure & Sizing
    expect(html).toContain('Active Exposure &amp; Capital Sizing')
    expect(html).toContain('$0.00')
    expect(html).toContain('/ $25.00 Max Cap')
    expect(html).toContain('100.0% (Floor ≥ 75%)')

    // Card 4: System Health & Zero-Drift Solvency
    expect(html).toContain('System Health &amp; Solvency')
    expect(html).toContain('|Δ| &lt; 10⁻¹⁵')
    expect(html).toContain('Zero-Drift Solvency')
    expect(html).toContain('12.4 ms')
    expect(html).toContain('1 Interlock Blocks (0 Hazards)')
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
    expect(html).toContain('BTC Macro Trend Filter')
    expect(html).toContain('BULLISH ALIGNED')
    expect(html).toContain('EMA50: $95,420')
    expect(html).toContain('EMA200: $93,810')

    // Panel 2: 15m Scalper Checklist
    expect(html).toContain('15m Scalper Checklist')
    expect(html).toContain('1.8x ATR')
    expect(html).toContain('1.4x SMA')
    expect(html).toContain('38.5')
    expect(html).toContain('0.02% Fee')

    // Panel 3: Hawkes Hazard
    expect(html).toContain('Microstructure &amp; Hawkes Hazard')
    expect(html).toContain('SAFE / NON-TOXIC')
    expect(html).toContain('ρ = 0.4286')
    expect(html).toContain('Warning: ρ ≥ 0.85')
    expect(html).toContain('Critical: ρ ≥ 1.00')
  })
})

describe('OrderFeedTable component', () => {
  it('renders recent orders with MYT timestamps and maker fees', () => {
    const html = renderToString(<OrderFeedTable orders={MOCK_MODEL.orders} />)

    expect(html).toContain('Recent Orders &amp; Execution Feed')
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

    expect(htmlOpen).toContain('Research Archives')
    expect(htmlOpen).toContain('23 Historical Phases')

    // Key historical phases
    expect(htmlOpen).toContain('Phase 250')
    expect(htmlOpen).toContain('Phase 291')
    expect(htmlOpen).toContain('Phase 309')
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
  it('assembles the simplified executive landing page cleanly', () => {
    const html = renderToString(
      <ExecutiveDashboard
        model={MOCK_MODEL}
        onRefresh={() => {}}
        isLoading={false}
      />,
    )

    expect(html).toContain('Autonomous Futures')
    expect(html).toContain('Total Balance &amp; Equity')
    expect(html).toContain('Live Pair Tickers &amp; Opportunity Radar')
    expect(html).toContain('Recent Orders &amp; Execution Feed')
  })
})

describe('PairPriceTickersCard component', () => {
  it('renders pair tickers grid with dynamic entry badges across pairs', () => {
    const html = renderToString(
      <PairPriceTickersCard
        positions={MOCK_MODEL.positions}
        scalperCriteria={MOCK_MODEL.radar.scalperCriteria}
        btcMacroTrend={MOCK_MODEL.radar.btcMacroTrend}
      />,
    )

    expect(html).toContain('Live Pair Tickers &amp; Opportunity Radar')
    expect(html).toContain('12 Perpetual Pairs')
    expect(html).toContain('SOLUSDT')
    expect(html).toContain('ETHUSDT')
    expect(html).toContain('BTCUSDT')
    expect(html).toContain('STANDBY / SCANNING')
    expect(html).toContain('Terminal')
  })
})

describe('StrategyEvolutionRadar component', () => {
  it('renders executive Strategy Evolution Radar card with 3 panels, OOS gates, and autopsy attribution', () => {
    const html = renderToString(
      <StrategyEvolutionRadar evolutionRadar={MOCK_MODEL.evolutionRadar} />,
    )

    // Title and daemon status
    expect(html).toContain('Strategy Evolution &amp; Autopsy Status')
    expect(html).toContain('⚡ ACTIVE DAEMON LOOP')
    expect(html).toContain('GEN #2')

    // Deep dive links
    expect(html).toContain('href="#/evolution"')
    expect(html).toContain('Full Autopsy &amp; Evolution')
    expect(html).toContain('href="#/mining"')
    expect(html).toContain('Strategy Mining')

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
    expect(html).toContain('5 OOS Qualification Gates')
    expect(html).toContain('5 / 5 GATES PASSED')
    expect(html).toContain('Average Return OOS')
    expect(html).toContain('+14.8%')
    expect(html).toContain('Maximum Drawdown OOS')
    expect(html).toContain('Profit Factor OOS')
    expect(html).toContain('1.84')
    expect(html).toContain('Trade Count OOS')
    expect(html).toContain('24')
    expect(html).toContain('Flash Crash Stress Resilience')
    expect(html).toContain('SURVIVED')

    // Panel 3: Trade Autopsy Attribution Gauges
    expect(html).toContain('Trade Autopsy Attribution Gauges')
    expect(html).toContain('Timing Error (Entry Timing)')
    expect(html).toContain('+1.8 bps')
    expect(html).toContain('Adverse Selection')
    expect(html).toContain('-0.6 bps')
    expect(html).toContain('Net Edge (Execution Edge)')
    expect(html).toContain('+8.4 bps')
    expect(html).toContain('OPTIMAL')
    expect(html).toContain('18 Autopsies')
    expect(html).toContain('3 Active Promoted Candidates')
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
    expect(adapted.kpis.winRatePct).toBe(0.0)
    expect(adapted.kpis.maxExposureCapUsdt).toBe(25.0)
    expect(adapted.kpis.minCashReserveFloorPct).toBe(75.0)

    expect(adapted.positions.length).toBe(12)
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
    expect(adapted.orders.some((o) => o.orderId.startsWith('canary-p310-'))).toBe(true)
  })

  it('maps and renders live runtime_health and verified ACCOUNT daily_risk from executionStatus', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      {},
      new Date(),
      null,
      null,
      {
        verified: true,
        status: 'ACCOUNT_RECONCILED',
        engine_state: 'QUALIFIED_PORTFOLIO_ACTIVE',
        timestamp_ms: 1792034072664,
        solvency: {
          total_equity_usdt: 4224.0988,
          cash_usdt: 4224.0988,
          available_balance_usdt: 4224.0988,
          allocated_margin_usdt: 0.0,
          realized_pnl_usdt: 0.0,
          cash_reserve_pct: 100.0,
          zero_balance_drift_verified: true,
        },
        positions: {},
        candidate_allocations: [],
        aggregate_exposure_usdt: 0.0,
        recent_orders: [],
        total_orders: 0,
        interlock_blocks_count: 0,
        daily_risk: {
          verified: true,
          day_start_equity_usdt: 4224.0988,
          limit_pct: 5.0,
          limit_usdt: 211.2049,
          loss_usdt: 0.0,
          remaining_usdt: 211.2049,
          breached: false,
          equity_basis: 'ACCOUNT',
        },
        runtime_health: {
          observed: true,
          timestamp_ms: 1792034072664,
          market_connected: true,
          user_stream_connected: true,
          arrival_count: 36930,
          spectral_radius: 0.5456,
        },
        watchdog: {
          status: 'HEALTHY',
          healthy: true,
          evaluated_at_ms: 1792034072664,
          critical_alerts: [],
          warning_alerts: [],
          systemd_passed: true,
          runtime_main_pid: 63408,
          runtime_restarts: 0,
        },
      },
    )

    expect(adapted.botStatus.isStreaming).toBe(true)
    expect(adapted.kpis.dailyRiskVerified).toBe(true)
    expect(adapted.kpis.dailyRiskRemainingUsdt).toBeCloseTo(211.2049, 4)
    expect(adapted.kpis.engineState).toBe('QUALIFIED_PORTFOLIO_ACTIVE')
    expect(adapted.kpis.runtimeArrivalCount).toBe(36930)
    expect(adapted.kpis.watchdogStatus).toBe('HEALTHY')
    expect(adapted.kpis.watchdogMainPid).toBe(63408)
    expect(adapted.radar.hawkesHazard.spectralRadius).toBeCloseTo(0.5456, 4)
    expect(adapted.radar.hawkesHazard.arrivalCount).toBe(36930)

    const kpiHtml = renderToString(<KpiCards kpis={adapted.kpis} />)
    expect(kpiHtml).toContain('$211.20 / $211.20')
    expect(kpiHtml).toContain('QUALIFIED_PORTFOLIO_ACTIVE (36,930 arrivals)')
    expect(kpiHtml).toContain('HEALTHY (PID 63408 · 0 restarts)')

    const radarHtml = renderToString(
      <StrategyConfluenceRadar hawkesHazard={adapted.radar.hawkesHazard} />,
    )
    expect(radarHtml).toContain('ρ = 0.5456')
    expect(radarHtml).toContain('36,930 Arrivals (30m)')
    expect(radarHtml).toContain('Streams Live · Stable')
  })

  it('maps and renders live portfolio_scanner 6-variant checklist and scalper_criteria', () => {
    const prodLaunch = buildProductionLaunchModel(null)
    const liveMarket = buildLiveMarketModel(null)
    const brackets = buildBracketPositionsModel(null)
    const micro = buildMicrostructureModel(null)
    const autoEvo = {
      ...buildAutoEvolutionModel(null),
      qualifiedPortfolios: [
        {
          portfolio_id: 'macro-scalper-uninspected-3sym-medium-frequency-v1',
          family: 'macro_liquidity_dip_scalper',
          symbols: ['AVAXUSDT', 'ETHUSDT', 'SOLUSDT'],
          member_count: 6,
          member_ids: [
            'avax-1-deep',
            'avax-2-hf',
            'eth-1-deep',
            'eth-2-hf',
            'sol-1-deep',
            'sol-2-hf',
          ],
          members_by_symbol_counts: { AVAXUSDT: 2, ETHUSDT: 2, SOLUSDT: 2 },
          decision: 'QUALIFIED',
          report_hash: '66041778a22430eb7bf44a625732d635d06fa5d2772cc6ac2de887839c70be6d',
          trades: 42,
          profitable_windows: 6,
          windows: 6,
          profit_factor: '1.68',
          net_pnl_usdt: '18.40',
          stress_net_pnl_usdt: '12.10',
          drawdown_pct: '3.2',
          execution_authority: false,
        },
      ],
    }

    const adapted = buildExecutiveDashboardModel(
      prodLaunch,
      liveMarket,
      brackets,
      micro,
      {},
      new Date(),
      autoEvo,
      null,
      {
        verified: true,
        status: 'ACCOUNT_RECONCILED',
        engine_state: 'QUALIFIED_PORTFOLIO_ACTIVE',
        timestamp_ms: 1792034072664,
        solvency: {
          total_equity_usdt: 4224.0988,
          cash_usdt: 4224.0988,
          available_balance_usdt: 4224.0988,
          allocated_margin_usdt: 0.0,
          realized_pnl_usdt: 0.0,
          cash_reserve_pct: 100.0,
          zero_balance_drift_verified: true,
        },
        positions: {},
        candidate_allocations: [],
        aggregate_exposure_usdt: 0.0,
        recent_orders: [],
        total_orders: 0,
        interlock_blocks_count: 0,
        runtime_health: {
          observed: true,
          timestamp_ms: 1792034072664,
          market_connected: true,
          user_stream_connected: true,
          arrival_count: 10500,
          spectral_radius: 0.52,
        },
        scalper_criteria: {
          symbol: 'SOLUSDT',
          variant_id: 'sol-2-hf',
          price_below_ema20_atr: 0.65,
          price_below_ema_threshold: 0.8,
          price_triggered: false,
          relative_volume: 1.35,
          volume_threshold: 1.2,
          volume_triggered: true,
          rsi_14: 39.4,
          rsi_threshold: 42.0,
          rsi_triggered: true,
          maker_fee_pct: 0.02,
        },
        portfolio_scanner: {
          observed: true,
          portfolio_id: 'macro-scalper-uninspected-3sym-medium-frequency-v1',
          evaluated_at_ms: 1792034072664,
          source: 'binance_futures_live',
          btc_regime: 'BULLISH ALIGNED',
          ema50_1h: 74500.0,
          ema200_1h: 72100.0,
          ema50_4h: 73900.0,
          ema200_4h: 71500.0,
          variants: [
            {
              member_id: 'sol-2-hf',
              symbol: 'SOLUSDT',
              tier: 'HF',
              close_price: 83.2,
              ema20: 84.1,
              atr14: 1.38,
              dist_atr: -0.65,
              price_below_ema20_atr: 0.65,
              distance_threshold: -0.8,
              dist_triggered: false,
              relative_volume: 1.35,
              vol_spike_multiplier: 1.2,
              vol_triggered: true,
              rsi_14: 39.4,
              rsi_threshold: 42.0,
              rsi_triggered: true,
              macro_regime: 'BULLISH ALIGNED',
              macro_aligned: true,
              gates_passed: 3,
              gates_total: 4,
              signal_ready: false,
            },
          ],
        },
      },
    )

    expect(adapted.radar.scalperCriteria.variantId).toBe('sol-2-hf')
    expect(adapted.radar.scalperCriteria.priceBelowEma20Atr).toBeCloseTo(0.65, 2)
    expect(adapted.radar.scalperCriteria.volumeTriggered).toBe(true)
    expect(adapted.radar.btcMacroTrend.ema50_4h).toBeCloseTo(73900.0, 1)
    expect(adapted.evolutionRadar.qualifiedPortfolios?.[0].executionAuthority).toBe(true)
    expect(adapted.evolutionRadar.qualifiedPortfolios?.[0].liveVariants?.length).toBe(1)

    const confluenceHtml = renderToString(
      <StrategyConfluenceRadar
        btcMacroTrend={adapted.radar.btcMacroTrend}
        scalperCriteria={adapted.radar.scalperCriteria}
        hawkesHazard={adapted.radar.hawkesHazard}
      />,
    )
    expect(confluenceHtml).toContain('Liquidity Sweep · sol-2-hf')
    expect(confluenceHtml).toContain('0.7x ATR')
    expect(confluenceHtml).toContain('1.4x SMA')
    expect(confluenceHtml).toContain('39.4')

    const evoHtml = renderToString(
      <StrategyEvolutionRadar evolutionRadar={adapted.evolutionRadar} />,
    )
    expect(evoHtml).toContain('EXECUTION AUTHORIZED')
    expect(evoHtml).toContain('Live 6-Variant Causal Scanner Checklist')
    expect(evoHtml).toContain('sol-2-hf')
    expect(evoHtml).toContain('3/4 GATES')
  })
})


