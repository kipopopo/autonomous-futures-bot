import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { PairDetailPage } from '../pair-detail-page'
import type {
  BtcMacroTrend,
  HawkesHazard,
  OrderFeedItem,
  PositionTelemetry,
  ScalperCriteria,
  StrategyEvolutionRadarData,
} from '../mission-control/types'

const MOCK_POSITIONS: PositionTelemetry[] = [
  {
    symbol: 'SOLUSDT',
    currentPrice: 110.2,
    lastPrice: 110.2,
    markPrice: 110.23,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 114.5,
    stopLossPrice: 107.8,
    riskRewardRatio: '1.66:1',
    fundingRate: 0.00005,
    basisPct: 0.02,
  },
  {
    symbol: 'ETHUSDT',
    currentPrice: 2528.0,
    lastPrice: 2528.0,
    markPrice: 2528.6,
    state: 'SCANNING / STANDBY',
    entryPrice: 0.0,
    size: 0.0,
    notionalUsdt: 0.0,
    marginUsdt: 0.0,
    unrealizedPnlUsdt: 0.0,
    unrealizedPnlPct: 0.0,
    takeProfitPrice: 2600.0,
    stopLossPrice: 2470.0,
    riskRewardRatio: '1.66:1',
    fundingRate: 0.00001,
    basisPct: -0.01,
  },
]

const MOCK_BTC_TREND: BtcMacroTrend = {
  regime: 'BULLISH ALIGNED',
  ema50_1h: 83300.0,
  ema200_1h: 82500.0,
  ema50_4h: 82900.0,
  ema200_4h: 81400.0,
  explanation: 'Bitcoin 1h & 4h trend bullish aligned.',
}

const MOCK_SCALPER: ScalperCriteria = {
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
}

const MOCK_HAWKES: HawkesHazard = {
  spectralRadius: 0.4286,
  isNonToxic: true,
  thresholdWarning: 0.85,
  thresholdCritical: 1.0,
  recentHistory: [0.35, 0.42],
}

const MOCK_ORDERS: OrderFeedItem[] = [
  {
    orderId: '4219971232',
    timestampMyt: '12 Oct 18:30:00',
    symbol: 'SOLUSDT',
    side: 'BUY',
    orderType: 'LIMIT',
    price: 109.85,
    quantity: 0.05,
    notionalUsdt: 5.4925,
    makerFeeUsdt: 0.001099,
    realizedPnlUsdt: 0.0,
    status: 'FILLED',
  },
]

const MOCK_EVOLUTION: StrategyEvolutionRadarData = {
  activeStrategyFamily: '15m Macro-Confluence Liquidity Scalper',
  microstructureFilter: 'Hawkes Microstructure Filter',
  activeCandidateId: 'cand-solusdt-ict-001',
  candidateHealthTier: 'HEALTHY',
  generation: 'GEN #1',
  rollingSharpe: 1.85,
  winRatePct: 65.0,
  maxDrawdownPct: 5.2,
  hawkesResilienceScore: 0.92,
  gates: [],
  allGatesPassed: true,
  attributionGauges: [],
  totalAutopsies: 12,
  promotedCandidatesCount: 2,
}

describe('PairDetailPage component', () => {
  it('renders dedicated terminal with pair header, navigation, and all system info for that pair', () => {
    const html = renderToString(
      <PairDetailPage
        symbol="SOLUSDT"
        positions={MOCK_POSITIONS}
        orders={MOCK_ORDERS}
        btcMacroTrend={MOCK_BTC_TREND}
        scalperCriteria={MOCK_SCALPER}
        hawkesHazard={MOCK_HAWKES}
        evolutionRadar={MOCK_EVOLUTION}
      />,
    )

    // Header & Back Button
    expect(html).toContain('Back to Overview')
    expect(html).toContain('SOL')
    expect(html).toContain('USDT Perpetual')
    expect(html).toContain('$110.20')

    // Quick Pair Switcher tabs
    expect(html).toContain('BTC')
    expect(html).toContain('ETH')
    expect(html).toContain('DOGE')

    // Position & Risk Telemetry
    expect(html).toContain('Position State')
    expect(html).toContain('SCANNING / STANDBY')
    expect(html).toContain('Bracket Protective Orders')
    expect(html).toContain('1.66:1 R:R')

    // Candlestick Chart container
    expect(html).toContain('Interactive Candlestick Chart &amp; Technical Structure')
    expect(html).toContain('data-testid="pair-candlestick-chart-solusdt"')

    // Dual Strategy Confluence
    expect(html).toContain('15m Macro-Confluence Scalper')
    expect(html).toContain('BTC Macro Trend Filter')
    expect(html).toContain('ICT Market Maker Model (MMXM)')
    expect(html).toContain('6-Step Twins Reversal State Machine')

    // Strategy Evolution & Genome
    expect(html).toContain('Pair Strategy Evolution &amp; Genome Autopsy')
    expect(html).toContain('cand-solusdt-ict-001')

    // Recent Orders for this pair
    expect(html).toContain('Recent Orders &amp; Executions (SOL)')
    expect(html).toContain('4219971232')
  })

  it('renders active position state with live entry price and PnL when populated', () => {
    const activePosition: PositionTelemetry = {
      ...MOCK_POSITIONS[0],
      state: 'LONG',
      entryPrice: 109.85,
      size: 0.05,
      notionalUsdt: 5.4925,
      marginUsdt: 5.4925,
      unrealizedPnlUsdt: 0.0175,
      unrealizedPnlPct: 0.32,
    }

    const html = renderToString(
      <PairDetailPage
        symbol="SOLUSDT"
        positions={[activePosition, MOCK_POSITIONS[1]]}
        orders={MOCK_ORDERS}
        btcMacroTrend={MOCK_BTC_TREND}
        scalperCriteria={MOCK_SCALPER}
        hawkesHazard={MOCK_HAWKES}
        evolutionRadar={MOCK_EVOLUTION}
      />,
    )

    expect(html).toContain('LONG')
    expect(html).toContain('$109.85')
    expect(html).toContain('+$0.0175 USDT')
  })
})
