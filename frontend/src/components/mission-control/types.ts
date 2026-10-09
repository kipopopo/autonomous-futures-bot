export type BotState = 'ACTIVE 24/7' | 'PAUSED' | 'DEGRADED'
export type GatewayMode = 'BINANCE TESTNET GATEWAY' | 'BINANCE LIVE GATEWAY'
export type CircuitState = 'NORMAL' | 'TRIPPED'
export type PositionState = 'LONG' | 'SHORT' | 'SCANNING / STANDBY'
export type MacroRegime = 'BULLISH ALIGNED' | 'BEARISH' | 'SIDEWAYS'
export type OrderSide = 'BUY' | 'SELL'
export type OrderStatus = 'FILLED' | 'NEW' | 'CANCELED'

export interface PositionTelemetry {
  symbol: string
  currentPrice: number
  state: PositionState
  entryPrice: number
  size: number
  notionalUsdt: number
  marginUsdt: number
  unrealizedPnlUsdt: number
  unrealizedPnlPct: number
  takeProfitPrice: number
  stopLossPrice: number
  riskRewardRatio: string
  atrDistanceSlPct?: number
  atrDistanceTpPct?: number
}

export interface BtcMacroTrend {
  regime: MacroRegime
  ema50_1h: number
  ema200_1h: number
  ema50_4h: number
  ema200_4h: number
  explanation: string
}

export interface ScalperCriteria {
  priceBelowEma20Atr: number
  priceBelowEmaThreshold: number
  priceTriggered: boolean
  relativeVolume: number
  volumeThreshold: number
  volumeTriggered: boolean
  rsi14: number
  rsiThreshold: number
  rsiTriggered: boolean
  makerFeePct: number
}

export interface HawkesHazard {
  spectralRadius: number
  isNonToxic: boolean
  thresholdWarning: number
  thresholdCritical: number
  recentHistory: number[]
}

export interface OrderFeedItem {
  orderId: string
  timestampMyt: string
  symbol: string
  side: OrderSide
  orderType: string
  price: number
  quantity: number
  notionalUsdt: number
  makerFeeUsdt: number
  realizedPnlUsdt: number
  status: OrderStatus
}

export interface ExecutiveDashboardModel {
  botStatus: {
    state: BotState
    gatewayMode: GatewayMode
    circuitBreaker: CircuitState
    tripwiresCount: number
    lastSyncedAtMyt: string
    isStreaming: boolean
  }
  kpis: {
    totalEquityUsdt: number
    cashUsdt: number
    allocatedMarginUsdt: number
    realizedPnlUsdt: number
    winRatePct: number
    totalTrades: number
    activeExposureUsdt: number
    maxExposureCapUsdt: number
    cashReservePct: number
    minCashReserveFloorPct: number
    latencyMs: number
    interlockBlocksCount: number
    balanceDriftUsdt: number
    isZeroDriftVerified: boolean
  }
  positions: PositionTelemetry[]
  radar: {
    btcMacroTrend: BtcMacroTrend
    scalperCriteria: ScalperCriteria
    hawkesHazard: HawkesHazard
  }
  orders: OrderFeedItem[]
}
