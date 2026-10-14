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
  lastPrice?: number
  markPrice?: number
  indexPrice?: number
  fundingRate?: number
  basis?: number
  basisPct?: number
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

export interface PairTicker {
  symbol: string
  lastPrice: number
  markPrice: number
  indexPrice: number
  fundingRate: number
  basis: number
  basisPct: number
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
  relativeTime?: string
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

export interface QualificationGateItem {
  id: string
  name: string
  thresholdLabel: string
  actualValueLabel: string
  passed: boolean
}

export interface AutopsyAttributionGaugeItem {
  id: string
  label: string
  bps: number
  thresholdBps: number
  isOptimal: boolean
  description: string
}

export interface StrategyEvolutionRadarData {
  activeStrategyFamily: string
  microstructureFilter: string
  activeCandidateId: string
  candidateHealthTier: 'ELITE' | 'HEALTHY' | 'DEGRADED' | 'PROBATIONARY'
  generation: string
  rollingSharpe: number
  winRatePct: number
  maxDrawdownPct: number
  hawkesResilienceScore: number
  gates: QualificationGateItem[]
  allGatesPassed: boolean
  attributionGauges: AutopsyAttributionGaugeItem[]
  totalAutopsies: number
  promotedCandidatesCount: number
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
  pairTickers?: PairTicker[]
  radar: {
    btcMacroTrend: BtcMacroTrend
    scalperCriteria: ScalperCriteria
    hawkesHazard: HawkesHazard
  }
  orders: OrderFeedItem[]
  evolutionRadar: StrategyEvolutionRadarData
}

// ============================================================================
// Phase 317 ICT Market Maker Model & Twins Reversal Types
// ============================================================================

export type IctTwinsStepName =
  | 'IDLE'
  | 'STEP_1_HTF_HIT'
  | 'STEP_2_M5_CISD'
  | 'STEP_3_TWINS_FVG'
  | 'STEP_4_OTE_RETRACE'
  | 'STEP_5_M1_CISD'
  | 'STEP_6_READY'
  | 'DISPATCHED'
  | 'INVALIDATED'

export type IctSide = 'BUY' | 'SELL' | 'NEUTRAL'
export type IctHealthTier = 'HEALTHY' | 'INCUBATING' | 'DEGRADED' | 'ELITE' | 'PROBATIONARY'
export type IctPdArrayType =
  | 'ORDER_BLOCK'
  | 'BREAKER_BLOCK'
  | 'FVG_BISI'
  | 'FVG_SIBI'
  | 'INVERSION_FVG'
  | 'OLD_HIGH'
  | 'OLD_LOW'

export interface IctPdArrayInfo {
  array_type: IctPdArrayType
  timeframe: '4h' | '1h' | '15m' | '5m' | '1m'
  top: number
  bottom: number
  mean_threshold: number
  direction: 'BULLISH' | 'BEARISH'
  is_mitigated: boolean
  creation_ts?: number
}

export interface IctCisdInfo {
  m5_cisd_price: number | null
  m1_cisd_price: number | null
}

export interface IctExecutionTargets {
  ote_lower: number | null
  ote_sweet_spot: number | null
  ote_upper: number | null
  stop_loss: number | null
  stdv_2_0: number | null
  stdv_4_0: number | null
  take_profit_partial: number | null
  take_profit_final: number | null
  risk_reward_ratio?: string
}

export interface IctCandidateGenomeInfo {
  candidate_id: string
  health_tier: IctHealthTier
  generation: number
  ote_bounds: string
  stdv_tp1: number
  stdv_tp2: number
  swing_lookback: number
  fvg_threshold_pct: string
}

export interface IctPairSignal {
  symbol: string
  step: IctTwinsStepName
  step_number: number
  steps: {
    step_1_htf_hit: boolean
    step_2_m5_cisd: boolean
    step_3_twins_fvg: boolean
    step_4_ote_retrace: boolean
    step_5_m1_cisd: boolean
    step_6_ready: boolean
  }
  side: IctSide
  active_pda: IctPdArrayInfo | null
  cisd: IctCisdInfo
  targets: IctExecutionTargets
  candidate: IctCandidateGenomeInfo
  invalidation_reason: string
}

export interface IctSignalsResponse {
  verified: boolean
  timestamp_ms: number
  active_family: string
  latency_ms?: number
  signals: Record<string, IctPairSignal>
}
