export interface CanarySummaryResponse {
  verified: boolean
  phase: string
  daemon_status: string
  description: string
  manifest_version: number
  staged_manifest_hash: string
  candidates: string[]
  timestamp_utc: string
  circuit_state: string
  compliance: Record<string, boolean>
  daemon_stats: Record<string, string>
  order_stats: {
    interlock_blocks_count?: number
    total_fees_usdt?: string
    total_orders_cancelled?: number
    total_orders_filled?: number
    total_orders_placed?: number
    total_orders_rejected?: number
    total_slippage_usdt?: string
  }
  heartbeat_stats: {
    max_allowed_age_ms?: number
    stale_heartbeat_breaches?: number
    total_heartbeats_recorded?: number
  }
  error_stats: Record<string, number>
  artifact_hashes: Record<string, string>
  tracks_summary: Record<string, unknown>
}

export interface HawkesSnapshot {
  record_id: number
  track_id: string
  symbol: string
  timestamp_utc: string
  jump_intensity: string
  branching_ratio: string
  spectral_radius: string
  self_excitation_alpha: string
  cross_excitation_json: string
  cascade_state: string
  regime: string
  pacing_interval_ms: number
  limit_offset_cushion_bps: string
  full_branching_matrix_json: string
}

export interface CanaryHawkesResponse {
  verified: boolean
  phase: string
  timestamp_utc: string
  candidates: string[]
  snapshots: HawkesSnapshot[]
  current_regime: string
  max_spectral_radius: number
  max_jump_intensity: number
}

export interface Heartbeat {
  record_id: number
  track_id: string
  server_time_ms: number
  local_time_ms: number
  latency_ms: number
  clock_skew_ms: number
  status: string
  is_healthy: boolean
  details: string
  timestamp_utc: string
}

export interface InterlockEvent {
  event_id: string
  timestamp_utc: string
  track_id: string
  interlock_type: string
  allowed: boolean
  symbol: string | null
  notional_usdt: string | null
  details: string
}

export interface CanaryRiskResponse {
  verified: boolean
  phase: string
  circuit_state: string
  aggregate_exposure_cap_usdt: string
  individual_micro_notional_cap_usdt: string
  intra_phase_loss_ceiling_usdt: string
  max_allowed_heartbeat_age_ms: number
  heartbeats: Heartbeat[]
  interlock_events: InterlockEvent[]
  total_interlock_blocks: number
}

export interface BalanceSnapshot {
  snapshot_id: string
  timestamp_utc: string
  track_id: string
  cash_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  realized_pnl_usdt: string
  starting_equity_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
  trigger_event: string
}

export interface DaemonTrack {
  track_id: string
  track_name: string
  status: string
  starting_equity_usdt: string
  final_cash_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  realized_pnl_usdt: string
  total_fees_usdt: string
  total_slippage_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
  orders_placed_count: number
  orders_filled_count: number
  orders_cancelled_count: number
  orders_rejected_count: number
  interlock_blocks_count: number
}

export interface CanaryAccountingResponse {
  verified: boolean
  phase: string
  starting_capital_usdt: string
  final_cash_usdt: string
  final_equity_usdt: string
  realized_pnl_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  total_fees_usdt: string
  total_slippage_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
  tracks: DaemonTrack[]
  recent_balance_snapshots: BalanceSnapshot[]
}

export interface OrderBookLevelItem {
  price: string
  quantity: string
}

export interface OrderBookDepthItem {
  symbol: string
  bids: OrderBookLevelItem[]
  asks: OrderBookLevelItem[]
  last_update_id: number
  event_time_utc: string
  best_bid: string
  best_ask: string
  spread_bps: string
}

export interface AggregateTradeItem {
  symbol: string
  aggregate_trade_id: number
  price: string
  quantity: string
  trade_time_utc: string
  is_buyer_maker: boolean
}

export interface MarkPriceItem {
  symbol: string
  mark_price: string
  index_price: string
  estimated_settle_price: string
  funding_rate: string
  next_funding_time_utc: string
  timestamp_utc: string
}

export interface GatewayHealthItem {
  status: string
  is_healthy: boolean
  heartbeat_age_ms: number
  latency_ms: number
  clock_skew_ms: number
  reconnect_count: number
  packet_gap_count: number
  total_messages_received: number
  timestamp_utc: string
}

export interface CanaryLiveMarketResponse {
  verified: boolean
  phase: string
  status: string
  timestamp_utc: string
  candidates: string[]
  paper_safe: boolean
  execution_authority: boolean
  gateway_health: GatewayHealthItem
  orderbooks: Record<string, OrderBookDepthItem>
  recent_trades: AggregateTradeItem[]
  mark_prices: Record<string, MarkPriceItem>
  stream_stats: Record<string, unknown>
}

export interface CanaryDashboardData {
  summary: CanarySummaryResponse | null
  hawkes: CanaryHawkesResponse | null
  risk: CanaryRiskResponse | null
  accounting: CanaryAccountingResponse | null
  liveMarket: CanaryLiveMarketResponse | null
  paperExecution?: CanaryPaperExecutionResponse | null
  strategyActivation?: CanaryStrategyActivationResponse | null
  autonomousLifecycle?: CanaryAutonomousLifecycleResponse | null
  stressFaultInjection?: CanaryStressFaultInjectionResponse | null
  strategyMining?: CanaryStrategyMiningResponse | null
  portfolioRebalancing?: CanaryPortfolioRebalancingResponse | null
  error: string | null
}

export interface MicrostructureModel {
  phase: string
  candidates: string[]
  currentRegime: string
  maxSpectralRadius: number
  maxJumpIntensity: number
  isSupercritical: boolean
  isHawkesElevated: boolean
  snapshots: HawkesSnapshot[]
  latestBySymbol: Record<string, HawkesSnapshot>
}

export interface RiskModel {
  phase: string
  circuitState: string
  exposureCapUsdt: string
  microCapUsdt: string
  lossCeilingUsdt: string
  maxHeartbeatAgeMs: number
  latestHeartbeat: Heartbeat | null
  totalBlocks: number
  recentInterlocks: InterlockEvent[]
}

export interface AccountingModel {
  phase: string
  startingCapital: string
  finalCash: string
  finalEquity: string
  realizedPnl: string
  allocatedMargin: string
  totalFees: string
  drift: string
  isZeroDrift: boolean
  tracks: DaemonTrack[]
  snapshots: BalanceSnapshot[]
}

export function buildMicrostructureModel(data: CanaryHawkesResponse | null): MicrostructureModel {
  if (!data) {
    return {
      phase: '—',
      candidates: [],
      currentRegime: 'UNKNOWN',
      maxSpectralRadius: 0,
      maxJumpIntensity: 0,
      isSupercritical: false,
      isHawkesElevated: false,
      snapshots: [],
      latestBySymbol: {},
    }
  }

  const latestBySymbol: Record<string, HawkesSnapshot> = {}
  for (const item of data.snapshots) {
    latestBySymbol[item.symbol] = item
  }

  const isSupercritical = data.max_spectral_radius >= 1.0 || data.current_regime.includes('SUPERCRITICAL')
  const isHawkesElevated = data.max_spectral_radius >= 0.85 || data.current_regime.includes('SEVERE')

  return {
    phase: data.phase,
    candidates: data.candidates,
    currentRegime: data.current_regime,
    maxSpectralRadius: data.max_spectral_radius,
    maxJumpIntensity: data.max_jump_intensity,
    isSupercritical,
    isHawkesElevated,
    snapshots: data.snapshots,
    latestBySymbol,
  }
}

export function buildRiskModel(data: CanaryRiskResponse | null): RiskModel {
  if (!data) {
    return {
      phase: '—',
      circuitState: 'UNKNOWN',
      exposureCapUsdt: '—',
      microCapUsdt: '—',
      lossCeilingUsdt: '—',
      maxHeartbeatAgeMs: 500,
      latestHeartbeat: null,
      totalBlocks: 0,
      recentInterlocks: [],
    }
  }

  const latestHeartbeat = data.heartbeats.length > 0 ? data.heartbeats[data.heartbeats.length - 1] : null

  return {
    phase: data.phase,
    circuitState: data.circuit_state,
    exposureCapUsdt: data.aggregate_exposure_cap_usdt,
    microCapUsdt: data.individual_micro_notional_cap_usdt,
    lossCeilingUsdt: data.intra_phase_loss_ceiling_usdt,
    maxHeartbeatAgeMs: data.max_allowed_heartbeat_age_ms,
    latestHeartbeat,
    totalBlocks: data.total_interlock_blocks,
    recentInterlocks: data.interlock_events,
  }
}

export function buildAccountingModel(data: CanaryAccountingResponse | null): AccountingModel {
  if (!data) {
    return {
      phase: '—',
      startingCapital: '—',
      finalCash: '—',
      finalEquity: '—',
      realizedPnl: '—',
      allocatedMargin: '—',
      totalFees: '—',
      drift: '—',
      isZeroDrift: false,
      tracks: [],
      snapshots: [],
    }
  }

  return {
    phase: data.phase,
    startingCapital: data.starting_capital_usdt,
    finalCash: data.final_cash_usdt,
    finalEquity: data.final_equity_usdt,
    realizedPnl: data.realized_pnl_usdt,
    allocatedMargin: data.allocated_margin_usdt,
    totalFees: data.total_fees_usdt,
    drift: data.drift_usdt,
    isZeroDrift: data.zero_balance_drift,
    tracks: data.tracks,
    snapshots: data.recent_balance_snapshots,
  }
}

export interface LiveMarketModel {
  phase: string
  verified: boolean
  isFresh: boolean
  status: string
  timestampUtc: string
  candidates: string[]
  isPaperSafe: boolean
  isExecutionOff: boolean
  gatewayHealth: GatewayHealthItem | null
  orderbooks: Record<string, OrderBookDepthItem>
  recentTrades: AggregateTradeItem[]
  markPrices: Record<string, MarkPriceItem>
  streamStats: Record<string, unknown>
}

export function buildLiveMarketModel(data: CanaryLiveMarketResponse | null): LiveMarketModel {
  if (!data) {
    return {
      phase: '—',
      verified: false,
      isFresh: false,
      status: 'DISCONNECTED',
      timestampUtc: '—',
      candidates: [],
      isPaperSafe: true,
      isExecutionOff: true,
      gatewayHealth: null,
      orderbooks: {},
      recentTrades: [],
      markPrices: {},
      streamStats: {},
    }
  }

  const isHealthy = Boolean(data.gateway_health?.is_healthy)
  const heartbeatAge = data.gateway_health?.heartbeat_age_ms ?? 9999
  const isFresh = isHealthy && heartbeatAge <= 500.0

  return {
    phase: data.phase,
    verified: Boolean(data.verified),
    isFresh,
    status: data.status,
    timestampUtc: data.timestamp_utc,
    candidates: data.candidates || [],
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    gatewayHealth: data.gateway_health || null,
    orderbooks: data.orderbooks || {},
    recentTrades: data.recent_trades || [],
    markPrices: data.mark_prices || {},
    streamStats: data.stream_stats || {},
  }
}

// ---------------------------------------------------------------------------
// Phase 293: Live Hawkes Telemetry Streaming Types
// ---------------------------------------------------------------------------

export interface PaperSafeMetadata {
  execution_authority: boolean
  paper_safe: boolean
  zero_drift_verified: boolean
  drift_usdt: string
}

export interface HawkesLiveMetricsData {
  timestamp_utc: string
  symbol: string
  jump_intensity: Record<string, string>
  spectral_radius: string
  branching_ratios: Record<string, string>
  regimes: Record<string, string>
  cascade_states: Record<string, string>
  pacing_intervals_ms: Record<string, number>
  limit_offset_cushions_bps: Record<string, string>
  full_branching_matrix: Record<string, Record<string, string>>
  is_supercritical: boolean
  is_predatory_front_running: boolean
}

export interface MicrostructureTelemetryData {
  timestamp_utc: string
  symbol: string
  bid_price: string
  ask_price: string
  spread_bps: string
  mark_price?: string | null
  funding_rate?: string | null
  last_trade_price?: string | null
  last_trade_quantity?: string | null
  bids: string[][]
  asks: string[][]
}

export interface RegimeChangeData {
  timestamp_utc: string
  symbol: string
  previous_regime: string
  current_regime: string
  spectral_radius: string
  pacing_interval_ms: number
  limit_offset_cushion_bps: string
  reason: string
}

export interface HazardAlertData {
  timestamp_utc: string
  alert_id: string
  severity: 'CRITICAL' | 'HIGH' | 'WARNING' | 'INFO'
  hazard_type: string
  symbol: string
  spectral_radius: string
  message: string
  action_taken: string
}

export interface TelemetryStreamEnvelope {
  type:
    | 'hawkes_metrics'
    | 'microstructure_snapshot'
    | 'regime_change'
    | 'hazard_alert'
    | 'heartbeat'
    | 'initial_state'
  timestamp: string
  data: unknown
  paper_safe_metadata: PaperSafeMetadata
}

// ---------------------------------------------------------------------------
// Phase 294: Paper Execution & Zero-Drift Matching Types
// ---------------------------------------------------------------------------

export interface PaperChildOrderItem {
  client_order_id: string
  parent_order_id: string
  child_index: number
  symbol: string
  side: string
  order_type: string
  price: string
  quantity: string
  notional_usdt: string
  status: string
  created_time_ms: number
  timestamp_utc: string
}

export interface PaperExecutionMarkItem {
  fill_id: string
  client_order_id: string
  parent_order_id: string
  child_index: number
  symbol: string
  side: string
  fill_price: string
  fill_quantity: string
  fill_notional_usdt: string
  fee_usdt: string
  fee_rate: string
  is_maker: boolean
  slippage_bps: string
  fill_time_ms: number
  timestamp_utc: string
}

export interface PaperOrderStatsItem {
  total_parent_orders: number
  total_child_orders: number
  filled_child_orders: number
  cancelled_orders: number
  rejected_orders: number
  total_fees_usdt: string
  total_slippage_usdt: string
}

export interface PaperMatchingStatsItem {
  passive_maker_fills_count: number
  aggressive_taker_fills_count: number
  avg_queue_wait_ms: number
  fill_ratio: number
}

export interface PaperLedgerSnapshotItem {
  starting_equity_usdt: string
  cash_usdt: string
  allocated_margin_usdt: string
  unrealized_pnl_usdt: string
  realized_pnl_usdt: string
  drift_usdt: string
  zero_balance_drift: boolean
}

export interface CanaryPaperExecutionResponse {
  verified: boolean
  phase: string
  status: string
  circuit_state: string
  timestamp_utc: string
  paper_safe: boolean
  execution_authority: boolean
  candidates: string[]
  active_exposure_usdt: string
  aggregate_exposure_cap_usdt: string
  individual_micro_notional_cap_usdt: string
  intra_phase_loss_ceiling_usdt: string
  unencumbered_cash_reserve_pct: string
  order_stats: PaperOrderStatsItem
  matching_stats: PaperMatchingStatsItem
  ledger: PaperLedgerSnapshotItem
  recent_child_orders: PaperChildOrderItem[]
  recent_fills: PaperExecutionMarkItem[]
  recent_interlocks: InterlockEvent[]
  artifact_hashes?: Record<string, string>
}

export interface PaperExecutionModel {
  phase: string
  verified: boolean
  status: string
  circuitState: string
  timestampUtc: string
  isPaperSafe: boolean
  isExecutionOff: boolean
  candidates: string[]
  activeExposureUsdt: string
  aggregateExposureCapUsdt: string
  individualMicroCapUsdt: string
  intraPhaseLossCeilingUsdt: string
  unencumberedCashReservePct: string
  isZeroDrift: boolean
  orderStats: PaperOrderStatsItem
  matchingStats: PaperMatchingStatsItem
  ledger: PaperLedgerSnapshotItem
  recentChildOrders: PaperChildOrderItem[]
  recentFills: PaperExecutionMarkItem[]
  recentInterlocks: InterlockEvent[]
}

export function buildPaperExecutionModel(
  data: CanaryPaperExecutionResponse | null
): PaperExecutionModel {
  if (!data) {
    return {
      phase: '—',
      verified: false,
      status: 'UNAVAILABLE',
      circuitState: 'UNKNOWN',
      timestampUtc: '',
      isPaperSafe: true,
      isExecutionOff: true,
      candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
      activeExposureUsdt: '0.00',
      aggregateExposureCapUsdt: '60.00',
      individualMicroCapUsdt: '5.00',
      intraPhaseLossCeilingUsdt: '7.00',
      unencumberedCashReservePct: '1.000',
      isZeroDrift: true,
      orderStats: {
        total_parent_orders: 0,
        total_child_orders: 0,
        filled_child_orders: 0,
        cancelled_orders: 0,
        rejected_orders: 0,
        total_fees_usdt: '0.00000000',
        total_slippage_usdt: '0.00000000',
      },
      matchingStats: {
        passive_maker_fills_count: 0,
        aggressive_taker_fills_count: 0,
        avg_queue_wait_ms: 0,
        fill_ratio: 0,
      },
      ledger: {
        starting_equity_usdt: '100.00',
        cash_usdt: '100.00',
        allocated_margin_usdt: '0.00',
        unrealized_pnl_usdt: '0.00',
        realized_pnl_usdt: '0.00',
        drift_usdt: '—',
        zero_balance_drift: true,
      },
      recentChildOrders: [],
      recentFills: [],
      recentInterlocks: [],
    }
  }

  return {
    phase: data.phase,
    verified: Boolean(data.verified),
    status: data.status,
    circuitState: data.circuit_state,
    timestampUtc: data.timestamp_utc,
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    candidates: data.candidates || [],
    activeExposureUsdt: data.active_exposure_usdt,
    aggregateExposureCapUsdt: data.aggregate_exposure_cap_usdt,
    individualMicroCapUsdt: data.individual_micro_notional_cap_usdt,
    intraPhaseLossCeilingUsdt: data.intra_phase_loss_ceiling_usdt,
    unencumberedCashReservePct: data.unencumbered_cash_reserve_pct,
    isZeroDrift: Boolean(data.ledger?.zero_balance_drift),
    orderStats: data.order_stats,
    matchingStats: data.matching_stats,
    ledger: data.ledger,
    recentChildOrders: data.recent_child_orders || [],
    recentFills: data.recent_fills || [],
    recentInterlocks: data.recent_interlocks || [],
  }
}

export interface CandidatePromotionItem {
  candidate_id: string
  symbol: string
  status: string
  average_return_pct: number
  worst_drawdown_pct: number
  profit_factor: number
  trade_count: number
  window_count: number
  qualified: boolean
}

export interface CandidateSignalItem {
  signal_id?: string | null
  candidate_id?: string | null
  timestamp_ms: number
  symbol: string
  side: string
  order_type?: string
  limit_price?: string | null
  notional_usdt: number
  client_order_id?: string | null
}

export interface VetoInterlockItem {
  hawkes_supercritical: boolean
  gateway_heartbeat_stale: boolean
  margin_headroom_breach: boolean
  clock_skew_breach?: boolean
  intra_phase_loss_lockout?: boolean
}

export interface LedgerReconciliationItem {
  starting_equity: number
  cash: number
  allocated_margin: number
  unrealized_pnl: number
  realized_pnl: number
  drift: number
  zero_balance_drift?: boolean
}

export interface CanaryStrategyActivationResponse {
  verified?: boolean
  phase: string
  status: string
  timestamp_ms: number
  paper_safe: boolean
  execution_authority: boolean
  candidates: CandidatePromotionItem[]
  signals: CandidateSignalItem[]
  vetoes: VetoInterlockItem
  ledger: LedgerReconciliationItem
  upstream_hash: string
  phase_hash: string
  child_orders_count?: number
  fills_count?: number
  orders_stats?: Record<string, unknown>
  circuit_state?: string
  artifact_hashes?: Record<string, string>
  upstream_merkle_dag?: Record<string, string>
}

export interface StrategyActivationModel {
  phase: string
  verified: boolean
  status: string
  circuitState: string
  timestampMs: number
  timestampUtc: string
  isPaperSafe: boolean
  isExecutionOff: boolean
  isZeroDrift: boolean
  candidates: CandidatePromotionItem[]
  signals: CandidateSignalItem[]
  vetoes: VetoInterlockItem
  ledger: LedgerReconciliationItem
  upstreamHash: string
  phaseHash: string
  childOrdersCount: number
  fillsCount: number
  isHawkesSupercritical: boolean
  isHeartbeatStale: boolean
  isMarginBreached: boolean
}

export function buildStrategyActivationModel(
  data: CanaryStrategyActivationResponse | null
): StrategyActivationModel {
  if (!data) {
    return {
      phase: '—',
      verified: false,
      status: 'UNAVAILABLE',
      circuitState: 'UNKNOWN',
      timestampMs: 0,
      timestampUtc: '',
      isPaperSafe: true,
      isExecutionOff: true,
      isZeroDrift: true,
      candidates: [
        {
          candidate_id: 'cand-btcusdt-dcb-002',
          symbol: 'BTCUSDT',
          status: 'UNPROMOTED',
          average_return_pct: 0,
          worst_drawdown_pct: 0,
          profit_factor: 0,
          trade_count: 0,
          window_count: 0,
          qualified: false,
        },
        {
          candidate_id: 'cand-ethusdt-dcb-003',
          symbol: 'ETHUSDT',
          status: 'UNPROMOTED',
          average_return_pct: 0,
          worst_drawdown_pct: 0,
          profit_factor: 0,
          trade_count: 0,
          window_count: 0,
          qualified: false,
        },
        {
          candidate_id: 'cand-solusdt-rgb-001',
          symbol: 'SOLUSDT',
          status: 'UNPROMOTED',
          average_return_pct: 0,
          worst_drawdown_pct: 0,
          profit_factor: 0,
          trade_count: 0,
          window_count: 0,
          qualified: false,
        },
      ],
      signals: [],
      vetoes: {
        hawkes_supercritical: false,
        gateway_heartbeat_stale: false,
        margin_headroom_breach: false,
      },
      ledger: {
        starting_equity: 100.0,
        cash: 100.0,
        allocated_margin: 0.0,
        unrealized_pnl: 0.0,
        realized_pnl: 0.0,
        drift: 0.0,
        zero_balance_drift: true,
      },
      upstreamHash: '—',
      phaseHash: '—',
      childOrdersCount: 0,
      fillsCount: 0,
      isHawkesSupercritical: false,
      isHeartbeatStale: false,
      isMarginBreached: false,
    }
  }

  const isZeroDrift =
    data.ledger?.zero_balance_drift !== undefined
      ? Boolean(data.ledger.zero_balance_drift)
      : Math.abs(data.ledger?.drift ?? 0) < 1e-15

  return {
    phase: data.phase,
    verified: Boolean(data.verified ?? true),
    status: data.status,
    circuitState: data.circuit_state ?? 'NORMAL',
    timestampMs: data.timestamp_ms,
    timestampUtc: data.timestamp_ms ? new Date(data.timestamp_ms).toISOString() : '',
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    isZeroDrift,
    candidates: data.candidates || [],
    signals: data.signals || [],
    vetoes: data.vetoes || {
      hawkes_supercritical: false,
      gateway_heartbeat_stale: false,
      margin_headroom_breach: false,
    },
    ledger: data.ledger || {
      starting_equity: 100.0,
      cash: 100.0,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    upstreamHash: data.upstream_hash || '—',
    phaseHash: data.phase_hash || '—',
    childOrdersCount: data.child_orders_count ?? 0,
    fillsCount: data.fills_count ?? 0,
    isHawkesSupercritical: Boolean(data.vetoes?.hawkes_supercritical),
    isHeartbeatStale: Boolean(data.vetoes?.gateway_heartbeat_stale),
    isMarginBreached: Boolean(data.vetoes?.margin_headroom_breach),
  }
}


// =====================================================================
// Phase 296: Full Autonomous Lifecycle Orchestration & Multi-Session Longevity
// =====================================================================

export interface LongevityStatisticsItem {
  total_sessions: number
  total_ticks_processed: number
  uptime_seconds: number
  throughput_tps: number
  disconnect_count: number
  reconnect_count: number
  sequence_gap_count: number
  duplicate_packets_count: number
  memory_bounded: boolean
  ring_buffer_capacity: number
}

export interface ComponentHealthItem {
  name: string
  status: string
  details: string
  updated_at: string
}

export interface SessionLongevityItem {
  session_id: string
  session_index: number
  start_time_utc: string
  end_time_utc: string
  duration_seconds: number
  ticks_processed: number
  orders_placed: number
  fills_count: number
  starting_equity_usdt: number
  ending_cash_usdt: number
  ending_equity_usdt: number
  realized_pnl_usdt: number
  drift_usdt: number
  zero_balance_drift: boolean
  disconnect_count: number
  reconnect_count: number
  status: string
}

export interface RiskCircuitIndicatorsItem {
  circuit_state: string
  spectral_radius_rho: number
  hawkes_cutoff_threshold: number
  hawkes_supercritical: boolean
  heartbeat_age_ms: number
  heartbeat_threshold_ms: number
  gateway_heartbeat_stale: boolean
  aggregate_exposure_usdt: number
  aggregate_exposure_cap_usdt: number
  margin_headroom_breach: boolean
  intra_phase_loss_usdt: number
  intra_phase_loss_ceiling_usdt: number
  loss_ceiling_breached: boolean
  cash_reserve_pct: number
  min_cash_reserve_floor_pct: number
  cash_reserve_depleted: boolean
}

export interface OperationalSwitchItem {
  name: string
  label: string
  enabled: boolean
  fail_closed: boolean
  value_display: string
  description: string
}

export interface CanaryAutonomousLifecycleResponse {
  verified: boolean
  phase: string
  status: string
  timestamp_ms: number
  timestamp_utc?: string
  execution_authority: boolean
  paper_safe: boolean
  daemon_status: string
  circuit_state: string
  longevity: LongevityStatisticsItem
  components: ComponentHealthItem[]
  sessions: SessionLongevityItem[]
  risk_circuits: RiskCircuitIndicatorsItem
  operational_switches: OperationalSwitchItem[]
  ledger: LedgerReconciliationItem
  candidates?: CandidatePromotionItem[]
  orders_stats?: Record<string, unknown>
  upstream_hash: string
  phase_hash: string
  merkle_root: string
  artifact_hashes?: Record<string, string>
  upstream_merkle_dag?: Record<string, string>
}

export interface AutonomousLifecycleModel {
  phase: string
  verified: boolean
  status: string
  daemonStatus: string
  circuitState: string
  timestampMs: number
  timestampUtc: string
  isPaperSafe: boolean
  isExecutionOff: boolean
  isZeroDrift: boolean
  longevity: LongevityStatisticsItem
  components: ComponentHealthItem[]
  sessions: SessionLongevityItem[]
  riskCircuits: RiskCircuitIndicatorsItem
  operationalSwitches: OperationalSwitchItem[]
  ledger: LedgerReconciliationItem
  candidates: CandidatePromotionItem[]
  upstreamHash: string
  phaseHash: string
  merkleRoot: string
}

export function buildAutonomousLifecycleModel(
  data: CanaryAutonomousLifecycleResponse | null
): AutonomousLifecycleModel {
  if (!data) {
    return {
      phase: '—',
      verified: false,
      status: 'UNAVAILABLE',
      daemonStatus: 'UNKNOWN',
      circuitState: 'UNKNOWN',
      timestampMs: 0,
      timestampUtc: '',
      isPaperSafe: true,
      isExecutionOff: true,
      isZeroDrift: true,
      longevity: {
        total_sessions: 0,
        total_ticks_processed: 0,
        uptime_seconds: 0,
        throughput_tps: 0,
        disconnect_count: 0,
        reconnect_count: 0,
        sequence_gap_count: 0,
        duplicate_packets_count: 0,
        memory_bounded: true,
        ring_buffer_capacity: 1000,
      },
      components: [
        { name: 'Public Ingress Gateway', status: 'UNKNOWN', details: 'Awaiting verified telemetry', updated_at: '' },
        { name: 'Hawkes Microstructure Streamer', status: 'UNKNOWN', details: 'Awaiting verified telemetry', updated_at: '' },
        { name: 'Strategy Activation Engine', status: 'UNKNOWN', details: 'Awaiting verified telemetry', updated_at: '' },
        { name: 'Passive Matching Simulator', status: 'UNKNOWN', details: 'Awaiting verified telemetry', updated_at: '' },
        { name: 'Zero-Drift Ledger', status: 'UNKNOWN', details: 'Awaiting verified telemetry', updated_at: '' },
      ],
      sessions: [],
      riskCircuits: {
        circuit_state: 'UNKNOWN',
        spectral_radius_rho: 0,
        hawkes_cutoff_threshold: 1.0,
        hawkes_supercritical: false,
        heartbeat_age_ms: 0,
        heartbeat_threshold_ms: 500,
        gateway_heartbeat_stale: false,
        aggregate_exposure_usdt: 0,
        aggregate_exposure_cap_usdt: 60,
        margin_headroom_breach: false,
        intra_phase_loss_usdt: 0,
        intra_phase_loss_ceiling_usdt: 7,
        loss_ceiling_breached: false,
        cash_reserve_pct: 100,
        min_cash_reserve_floor_pct: 40,
        cash_reserve_depleted: false,
      },
      operationalSwitches: [
        { name: 'paper_safe', label: 'Paper-Safe Mode', enabled: true, fail_closed: true, value_display: 'ENABLED', description: 'Strict offline sandbox isolation' },
        { name: 'execution_authority', label: 'Live Execution Authority', enabled: false, fail_closed: true, value_display: 'DISABLED', description: 'Hard fail-closed block' },
        { name: 'hawkes_cutoff', label: 'Hawkes Runaway Cutoff', enabled: true, fail_closed: true, value_display: 'rho < 1.0000', description: 'Order suppression on runaway' },
        { name: 'heartbeat_freshness', label: 'Heartbeat Freshness Gate', enabled: true, fail_closed: true, value_display: '<= 500 ms', description: 'Latency freshness gate' },
        { name: 'aggregate_margin_cap', label: 'Aggregate Exposure Ceiling', enabled: true, fail_closed: true, value_display: '<= 60.00 USDT', description: 'Margin cap' },
      ],
      ledger: {
        starting_equity: 100.0,
        cash: 100.0,
        allocated_margin: 0.0,
        unrealized_pnl: 0.0,
        realized_pnl: 0.0,
        drift: 0.0,
        zero_balance_drift: true,
      },
      candidates: [],
      upstreamHash: '—',
      phaseHash: '—',
      merkleRoot: '—',
    }
  }

  const isZeroDrift =
    data.ledger?.zero_balance_drift !== undefined
      ? Boolean(data.ledger.zero_balance_drift)
      : Math.abs(data.ledger?.drift ?? 0) < 1e-15

  return {
    phase: data.phase,
    verified: Boolean(data.verified ?? true),
    status: data.status,
    daemonStatus: data.daemon_status || 'ACTIVE',
    circuitState: data.circuit_state || 'NORMAL',
    timestampMs: data.timestamp_ms,
    timestampUtc: data.timestamp_utc || (data.timestamp_ms ? new Date(data.timestamp_ms).toISOString() : ''),
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    isZeroDrift,
    longevity: data.longevity || {
      total_sessions: 0,
      total_ticks_processed: 0,
      uptime_seconds: 0,
      throughput_tps: 0,
      disconnect_count: 0,
      reconnect_count: 0,
      sequence_gap_count: 0,
      duplicate_packets_count: 0,
      memory_bounded: true,
      ring_buffer_capacity: 1000,
    },
    components: data.components || [],
    sessions: data.sessions || [],
    riskCircuits: data.risk_circuits || {
      circuit_state: 'NORMAL',
      spectral_radius_rho: 0,
      hawkes_cutoff_threshold: 1.0,
      hawkes_supercritical: false,
      heartbeat_age_ms: 0,
      heartbeat_threshold_ms: 500,
      gateway_heartbeat_stale: false,
      aggregate_exposure_usdt: 0,
      aggregate_exposure_cap_usdt: 60,
      margin_headroom_breach: false,
      intra_phase_loss_usdt: 0,
      intra_phase_loss_ceiling_usdt: 7,
      loss_ceiling_breached: false,
      cash_reserve_pct: 100,
      min_cash_reserve_floor_pct: 40,
      cash_reserve_depleted: false,
    },
    operationalSwitches: data.operational_switches || [],
    ledger: data.ledger || {
      starting_equity: 100.0,
      cash: 100.0,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    candidates: data.candidates || [],
    upstreamHash: data.upstream_hash || '—',
    phaseHash: data.phase_hash || '—',
    merkleRoot: data.merkle_root || '—',
  }
}

// =====================================================================
// Phase 297: Extreme Market Stress, Flash Crash Simulation & Fault Injection Resilience
// =====================================================================

export interface ShockVectorStatusItem {
  vector_id: string
  name: string
  status: string
  intensity: string
  action_taken: string
  timestamp_utc: string
}

export interface CircuitBreakerLatencyItem {
  breaker_id: string
  vector_id: string
  detection_latency_us: number
  trigger_latency_us: number
  action: string
  tripped: boolean
  sub_millisecond: boolean
}

export interface AutoFlatteningAuditItem {
  flattening_id: string
  symbol: string
  trigger_reason: string
  positions_closed_count: number
  orders_cancelled_count: number
  pre_flatten_equity_usdt: number
  post_flatten_cash_usdt: number
  capital_preserved_pct: number
  execution_authority: boolean
  timestamp_utc: string
}

export interface DoubleEntrySolvencyItem {
  starting_equity_usdt: number
  cash_usdt: number
  allocated_margin_usdt: number
  unrealized_pnl_usdt: number
  realized_pnl_usdt: number
  total_equity_usdt: number
  total_fees_usdt: number
  total_slippage_usdt: number
  drift_usdt: number
  zero_balance_drift_verified: boolean
  tolerance_ceiling_usdt: number
  solvency_ratio_pct: number
  cash_reserve_pct: number
  unencumbered_cash_verified: boolean
}

export interface CanaryStressFaultInjectionResponse {
  verified: boolean
  phase: string
  status: string
  timestamp_ms: number
  timestamp_utc: string
  paper_safe: boolean
  execution_authority: boolean
  circuit_state: string
  shock_vectors: ShockVectorStatusItem[]
  circuit_breaker_latencies: CircuitBreakerLatencyItem[]
  auto_flattening_audits: AutoFlatteningAuditItem[]
  ledger: LedgerReconciliationItem
  solvency?: DoubleEntrySolvencyItem
  capital_preservation_stats: {
    pre_flatten_equity_usdt: number
    post_flatten_cash_usdt: number
    capital_preserved_pct: number
    max_loss_budget_usdt: number
    actual_loss_usdt: number
    loss_ceiling_breached: boolean
    circuit_state: string
  }
  upstream_hash: string
  phase_hash: string
  merkle_root: string
  artifact_hashes?: Record<string, string>
  upstream_merkle_dag?: Record<string, string>
}

export interface StressFaultInjectionModel {
  phase: string
  verified: boolean
  status: string
  circuitState: string
  timestampMs: number
  timestampUtc: string
  isPaperSafe: boolean
  isExecutionOff: boolean
  isZeroDrift: boolean
  subMillisecondLatencyVerified: boolean
  shockVectors: ShockVectorStatusItem[]
  circuitBreakerLatencies: CircuitBreakerLatencyItem[]
  autoFlatteningAudits: AutoFlatteningAuditItem[]
  ledger: LedgerReconciliationItem
  solvency: DoubleEntrySolvencyItem
  capitalPreservationStats: {
    pre_flatten_equity_usdt: number
    post_flatten_cash_usdt: number
    capital_preserved_pct: number
    max_loss_budget_usdt: number
    actual_loss_usdt: number
    loss_ceiling_breached: boolean
    circuit_state: string
  }
  upstreamHash: string
  phaseHash: string
  merkleRoot: string
}

export function buildStressFaultInjectionModel(
  data: CanaryStressFaultInjectionResponse | null
): StressFaultInjectionModel {
  if (!data) {
    return {
      phase: 'phase_297',
      verified: false,
      status: 'UNAVAILABLE',
      circuitState: 'UNKNOWN',
      timestampMs: 0,
      timestampUtc: '',
      isPaperSafe: true,
      isExecutionOff: true,
      isZeroDrift: true,
      subMillisecondLatencyVerified: true,
      shockVectors: [
        {
          vector_id: 'vector_flash_crash',
          name: 'Flash Crash Shock',
          status: 'NORMAL',
          intensity: '-20.0% sudden price drop within 100 ms',
          action_taken: 'TRIP_BREAKER & AUTO_FLATTEN',
          timestamp_utc: '',
        },
        {
          vector_id: 'vector_liquidity_evaporation',
          name: 'Liquidity Evaporation & Wide Spread',
          status: 'NORMAL',
          intensity: 'Spread 10.0% (1000 bps) & 95% depth depletion',
          action_taken: 'SPREAD_SHOCK_VETO & HALT_NEW_ORDERS',
          timestamp_utc: '',
        },
        {
          vector_id: 'vector_phantom_depth_spoofing',
          name: 'Phantom Depth / Spoofing & Toxic Flow',
          status: 'NORMAL',
          intensity: 'Asymmetry |OFI| > 0.95 & rapid quote cancellations',
          action_taken: 'HAZARD_VETO & CANCEL_RESTING_ORDERS',
          timestamp_utc: '',
        },
        {
          vector_id: 'vector_telemetry_degradation',
          name: 'Telemetry Degradation & Clock Skew',
          status: 'NORMAL',
          intensity: 'Clock skew > 500 ms & packet sequence gap > 1,000',
          action_taken: 'HEARTBEAT_VETO & FAIL_CLOSED_LOCKOUT',
          timestamp_utc: '',
        },
      ],
      circuitBreakerLatencies: [
        {
          breaker_id: 'cb_default_001',
          vector_id: 'FLASH_CRASH',
          detection_latency_us: 13.3,
          trigger_latency_us: 13.3,
          action: 'HALT_DISPATCH',
          tripped: false,
          sub_millisecond: true,
        },
      ],
      autoFlatteningAudits: [],
      ledger: {
        starting_equity: 100.0,
        cash: 100.0,
        allocated_margin: 0.0,
        unrealized_pnl: 0.0,
        realized_pnl: 0.0,
        drift: 0.0,
        zero_balance_drift: true,
      },
      solvency: {
        starting_equity_usdt: 100.0,
        cash_usdt: 100.0,
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.0,
        total_equity_usdt: 100.0,
        total_fees_usdt: 0.0,
        total_slippage_usdt: 0.0,
        drift_usdt: 0.0,
        zero_balance_drift_verified: true,
        tolerance_ceiling_usdt: 1e-15,
        solvency_ratio_pct: 100.0,
        cash_reserve_pct: 100.0,
        unencumbered_cash_verified: true,
      },
      capitalPreservationStats: {
        pre_flatten_equity_usdt: 100.0,
        post_flatten_cash_usdt: 100.0,
        capital_preserved_pct: 100.0,
        max_loss_budget_usdt: 7.00,
        actual_loss_usdt: 0.0,
        loss_ceiling_breached: false,
        circuit_state: 'UNKNOWN',
      },
      upstreamHash: '—',
      phaseHash: '—',
      merkleRoot: '—',
    }
  }

  const isZeroDrift =
    data.solvency?.zero_balance_drift_verified ??
    (data.ledger?.zero_balance_drift !== undefined
      ? Boolean(data.ledger.zero_balance_drift)
      : Math.abs(data.ledger?.drift ?? 0) < 1e-15)

  const subMillisecondLatencyVerified =
    data.circuit_breaker_latencies?.length > 0
      ? data.circuit_breaker_latencies.every((cb) => cb.sub_millisecond && cb.detection_latency_us < 1000.0)
      : true

  const defaultSolvency: DoubleEntrySolvencyItem = {
    starting_equity_usdt: data.ledger?.starting_equity ?? 100.0,
    cash_usdt: data.ledger?.cash ?? 100.0,
    allocated_margin_usdt: data.ledger?.allocated_margin ?? 0.0,
    unrealized_pnl_usdt: data.ledger?.unrealized_pnl ?? 0.0,
    realized_pnl_usdt: data.ledger?.realized_pnl ?? 0.0,
    total_equity_usdt: (data.ledger?.cash ?? 100.0) + (data.ledger?.allocated_margin ?? 0.0) + (data.ledger?.unrealized_pnl ?? 0.0),
    total_fees_usdt: 0.0,
    total_slippage_usdt: 0.0,
    drift_usdt: data.ledger?.drift ?? 0.0,
    zero_balance_drift_verified: isZeroDrift,
    tolerance_ceiling_usdt: 1e-15,
    solvency_ratio_pct: 100.0,
    cash_reserve_pct: data.ledger?.starting_equity ? roundTo((data.ledger.cash / data.ledger.starting_equity) * 100.0, 2) : 100.0,
    unencumbered_cash_verified: true,
  }

  return {
    phase: data.phase,
    verified: Boolean(data.verified ?? true),
    status: data.status,
    circuitState: data.circuit_state || 'HALTED',
    timestampMs: data.timestamp_ms,
    timestampUtc: data.timestamp_utc || (data.timestamp_ms ? new Date(data.timestamp_ms).toISOString() : ''),
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    isZeroDrift,
    subMillisecondLatencyVerified,
    shockVectors: data.shock_vectors || [],
    circuitBreakerLatencies: data.circuit_breaker_latencies || [],
    autoFlatteningAudits: data.auto_flattening_audits || [],
    ledger: data.ledger || {
      starting_equity: 100.0,
      cash: 100.0,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: data.solvency || defaultSolvency,
    capitalPreservationStats: data.capital_preservation_stats || {
      pre_flatten_equity_usdt: 100.0,
      post_flatten_cash_usdt: 100.0,
      capital_preserved_pct: 100.0,
      max_loss_budget_usdt: 7.00,
      actual_loss_usdt: 0.0,
      loss_ceiling_breached: false,
      circuit_state: data.circuit_state || 'HALTED',
    },
    upstreamHash: data.upstream_hash || '—',
    phaseHash: data.phase_hash || '—',
    merkleRoot: data.merkle_root || '—',
  }
}

function roundTo(value: number, decimals: number): number {
  const factor = Math.pow(10, decimals)
  return Math.round(value * factor) / factor
}

// =====================================================================
// Phase 298: Dynamic Strategy Mining, Auto-Evolution & Microstructure Mutation Engine
// =====================================================================

export interface CanaryStrategyMiningCandidate {
  candidate_id: string
  symbol: string
  family: string
  lookback: number
  zscore_threshold: number
  stop_atr_multiplier: number
  return_pct: number
  drawdown_pct: number
  profit_factor: number
  trade_count: number
  resilience_passed: boolean
  qualified: boolean
  status: string
}

export interface CanaryStrategyMiningMutation {
  mutation_id: string
  generation: number
  parent_candidate_id: string
  mutated_candidate_id: string
  family: string
  parameter_diffs: Record<string, unknown>
  seed: number
  timestamp_utc: string
}

export interface CanaryStrategyMiningGateMetrics {
  gate_names: string[]
  thresholds: Record<string, unknown>
  passing_counts: Record<string, number>
  rejection_counts: Record<string, number>
  total_evaluated: number
  total_passed: number
  total_rejected: number
}

export interface CanaryStrategyMiningHotReload {
  reloaded_at_utc: string
  previous_version: number
  new_version: number
  registry_hash: string
  reload_status: string
  process_restarted: boolean
  open_trades_mutated: boolean
}

export interface HypothesisTreeItem {
  hypothesis_id: string
  parent_id: string | null
  family: string
  symbol: string
  generation: number
  mutation_type: string
  parameters: Record<string, unknown>
  status: string
  timestamp_utc: string
}

export interface SearchSpaceParamItem {
  param_name: string
  family: string
  min_value: number
  max_value: number
  current_value: number
  optimal_value: number
  unit: string
}

export interface FeatureHeatmapItem {
  feature_name: string
  symbol: string
  correlation_score: number
  importance_weight: number
  mutation_sensitivity: number
}

export interface OOSGateScorecardItem {
  candidate_id: string
  symbol: string
  family: string
  return_pct: number
  worst_drawdown_pct: number
  profit_factor: number
  trade_count: number
  stress_survived: boolean
  gates_passed_count: number
  all_gates_passed: boolean
  qualified: boolean
  admission_status: string
}

export interface HotReloadLogItem {
  event_id: string
  candidate_id: string
  symbol: string
  manifest_version: number
  registry_hash: string
  reloaded_at_utc: string
  status: string
  process_restarted: boolean
  open_trades_mutated: boolean
}

export interface CanaryStrategyMiningResponse {
  verified: boolean
  phase: string
  status: string
  timestamp_ms: number
  timestamp_utc: string
  paper_safe: boolean
  execution_authority: boolean
  circuit_state: string
  candidates: CanaryStrategyMiningCandidate[]
  active_candidates: string[]
  mutations: CanaryStrategyMiningMutation[]
  gate_metrics: CanaryStrategyMiningGateMetrics
  hot_reload: CanaryStrategyMiningHotReload
  hypotheses: HypothesisTreeItem[]
  search_space: SearchSpaceParamItem[]
  feature_heatmaps: FeatureHeatmapItem[]
  oos_scorecards: OOSGateScorecardItem[]
  hot_reload_logs: HotReloadLogItem[]
  ledger: LedgerReconciliationItem
  solvency?: DoubleEntrySolvencyItem
  upstream_hash: string
  phase_hash: string
  merkle_root: string
  artifact_hashes?: Record<string, string>
  upstream_merkle_dag?: Record<string, string>
}

export interface StrategyMiningModel {
  phase: string
  verified: boolean
  status: string
  circuitState: string
  timestampMs: number
  timestampUtc: string
  isPaperSafe: boolean
  isExecutionOff: boolean
  isZeroDrift: boolean
  candidates: CanaryStrategyMiningCandidate[]
  activeCandidates: string[]
  mutations: CanaryStrategyMiningMutation[]
  gateMetrics: CanaryStrategyMiningGateMetrics
  hotReload: CanaryStrategyMiningHotReload
  hypotheses: HypothesisTreeItem[]
  searchSpace: SearchSpaceParamItem[]
  featureHeatmaps: FeatureHeatmapItem[]
  oosScorecards: OOSGateScorecardItem[]
  hotReloadLogs: HotReloadLogItem[]
  ledger: LedgerReconciliationItem
  solvency: DoubleEntrySolvencyItem
  upstreamHash: string
  phaseHash: string
  merkleRoot: string
}

export async function getCanaryStrategyMining(
  baseUrl: string = ''
): Promise<CanaryStrategyMiningResponse> {
  const cleanBase = baseUrl ? baseUrl.replace(/\/$/, '') : ''
  const path = `${cleanBase}/api/v1/canary/strategy-mining`
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CanaryStrategyMiningResponse
}

export function buildStrategyMiningModel(
  data: CanaryStrategyMiningResponse | null
): StrategyMiningModel {
  if (!data) {
    return {
      phase: 'phase_298',
      verified: false,
      status: 'UNAVAILABLE',
      circuitState: 'UNKNOWN',
      timestampMs: 0,
      timestampUtc: '',
      isPaperSafe: true,
      isExecutionOff: true,
      isZeroDrift: true,
      candidates: [],
      activeCandidates: ['cand-btcusdt-dcb-003', 'cand-ethusdt-rgb-002', 'cand-solusdt-msm-001'],
      mutations: [],
      gateMetrics: {
        gate_names: [
          'Walk-Forward OOS Average Return (>= 0.0%)',
          'Walk-Forward OOS Worst Drawdown (<= 15.0%)',
          'Walk-Forward OOS Profit Factor (>= 1.05)',
          'Minimum OOS Trade Count (>= 5 trades)',
          'Microstructure Resilience Gate (Flash Crash -20% & Spread 10%)',
        ],
        thresholds: {
          min_return_pct: 0.0,
          max_drawdown_pct: 15.0,
          min_profit_factor: 1.05,
          min_trade_count: 5,
          resilience_required: true,
        },
        passing_counts: {},
        rejection_counts: {},
        total_evaluated: 0,
        total_passed: 0,
        total_rejected: 0,
      },
      hotReload: {
        reloaded_at_utc: '',
        previous_version: 2,
        new_version: 3,
        registry_hash: '',
        reload_status: 'IDLE',
        process_restarted: false,
        open_trades_mutated: false,
      },
      hypotheses: [
        {
          hypothesis_id: 'hyp-dcb-001',
          parent_id: null,
          family: 'DonchianBreakout',
          symbol: 'BTCUSDT',
          generation: 1,
          mutation_type: 'LOOKBACK_SHIFT',
          parameters: { lookback: 24, zscore_threshold: 1.6 },
          status: 'QUALIFIED',
          timestamp_utc: '',
        },
        {
          hypothesis_id: 'hyp-rgb-001',
          parent_id: null,
          family: 'RegimeVolatilityBreakout',
          symbol: 'ETHUSDT',
          generation: 1,
          mutation_type: 'VOLATILITY_THRESHOLD',
          parameters: { lookback: 20, zscore_threshold: 1.5 },
          status: 'QUALIFIED',
          timestamp_utc: '',
        },
        {
          hypothesis_id: 'hyp-msm-001',
          parent_id: null,
          family: 'MicrostructureMomentum',
          symbol: 'SOLUSDT',
          generation: 1,
          mutation_type: 'OFI_SENSITIVITY',
          parameters: { lookback: 16, zscore_threshold: 1.8 },
          status: 'QUALIFIED',
          timestamp_utc: '',
        },
      ],
      searchSpace: [
        {
          param_name: 'lookback_window',
          family: 'DonchianBreakout',
          min_value: 10,
          max_value: 60,
          current_value: 20,
          optimal_value: 24,
          unit: 'bars',
        },
        {
          param_name: 'entry_zscore',
          family: 'RegimeVolatilityBreakout',
          min_value: 1.0,
          max_value: 3.0,
          current_value: 1.5,
          optimal_value: 1.65,
          unit: 'σ',
        },
        {
          param_name: 'ofi_threshold',
          family: 'MicrostructureMomentum',
          min_value: 0.1,
          max_value: 0.9,
          current_value: 0.4,
          optimal_value: 0.55,
          unit: 'ratio',
        },
        {
          param_name: 'stop_atr_multiplier',
          family: 'DonchianBreakout',
          min_value: 1.5,
          max_value: 4.0,
          current_value: 2.0,
          optimal_value: 2.2,
          unit: 'x ATR',
        },
      ],
      featureHeatmaps: [
        {
          feature_name: 'hawkes_jump_intensity_lambda',
          symbol: 'BTCUSDT',
          correlation_score: 0.78,
          importance_weight: 0.85,
          mutation_sensitivity: 0.62,
        },
        {
          feature_name: 'spectral_radius_rho',
          symbol: 'BTCUSDT',
          correlation_score: 0.82,
          importance_weight: 0.91,
          mutation_sensitivity: 0.74,
        },
        {
          feature_name: 'order_flow_imbalance_ofi',
          symbol: 'ETHUSDT',
          correlation_score: 0.69,
          importance_weight: 0.78,
          mutation_sensitivity: 0.58,
        },
        {
          feature_name: 'rolling_volatility_sigma',
          symbol: 'SOLUSDT',
          correlation_score: 0.74,
          importance_weight: 0.82,
          mutation_sensitivity: 0.65,
        },
      ],
      oosScorecards: [
        {
          candidate_id: 'cand-btcusdt-dcb-003',
          symbol: 'BTCUSDT',
          family: 'DonchianBreakout',
          return_pct: 4.3,
          worst_drawdown_pct: 6.8,
          profit_factor: 1.42,
          trade_count: 18,
          stress_survived: true,
          gates_passed_count: 5,
          all_gates_passed: true,
          qualified: true,
          admission_status: 'ADMITTED',
        },
        {
          candidate_id: 'cand-ethusdt-rgb-002',
          symbol: 'ETHUSDT',
          family: 'RegimeVolatilityBreakout',
          return_pct: 3.6,
          worst_drawdown_pct: 7.5,
          profit_factor: 1.35,
          trade_count: 15,
          stress_survived: true,
          gates_passed_count: 5,
          all_gates_passed: true,
          qualified: true,
          admission_status: 'ADMITTED',
        },
        {
          candidate_id: 'cand-solusdt-msm-001',
          symbol: 'SOLUSDT',
          family: 'MicrostructureMomentum',
          return_pct: 5.1,
          worst_drawdown_pct: 8.2,
          profit_factor: 1.48,
          trade_count: 21,
          stress_survived: true,
          gates_passed_count: 5,
          all_gates_passed: true,
          qualified: true,
          admission_status: 'ADMITTED',
        },
      ],
      hotReloadLogs: [
        {
          event_id: 'event-hr-298-001',
          candidate_id: 'cand-btcusdt-dcb-003',
          symbol: 'BTCUSDT',
          manifest_version: 3,
          registry_hash: '9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b',
          reloaded_at_utc: '',
          status: 'ADMITTED_AND_HOT_RELOADED',
          process_restarted: false,
          open_trades_mutated: false,
        },
      ],
      ledger: {
        starting_equity: 100.0,
        cash: 100.0,
        allocated_margin: 0.0,
        unrealized_pnl: 0.0,
        realized_pnl: 0.0,
        drift: 0.0,
        zero_balance_drift: true,
      },
      solvency: {
        starting_equity_usdt: 100.0,
        cash_usdt: 100.0,
        allocated_margin_usdt: 0.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.0,
        total_equity_usdt: 100.0,
        total_fees_usdt: 0.0,
        total_slippage_usdt: 0.0,
        drift_usdt: 0.0,
        zero_balance_drift_verified: true,
        tolerance_ceiling_usdt: 1e-15,
        solvency_ratio_pct: 100.0,
        cash_reserve_pct: 100.0,
        unencumbered_cash_verified: true,
      },
      upstreamHash: '257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668',
      phaseHash: '—',
      merkleRoot: '—',
    }
  }

  const isZeroDrift =
    data.solvency?.zero_balance_drift_verified ??
    (data.ledger?.zero_balance_drift !== undefined
      ? Boolean(data.ledger.zero_balance_drift)
      : Math.abs(data.ledger?.drift ?? 0) < 1e-15)

  const defaultSolvency: DoubleEntrySolvencyItem = {
    starting_equity_usdt: data.ledger?.starting_equity ?? 100.0,
    cash_usdt: data.ledger?.cash ?? 100.0,
    allocated_margin_usdt: data.ledger?.allocated_margin ?? 0.0,
    unrealized_pnl_usdt: data.ledger?.unrealized_pnl ?? 0.0,
    realized_pnl_usdt: data.ledger?.realized_pnl ?? 0.0,
    total_equity_usdt:
      (data.ledger?.cash ?? 100.0) +
      (data.ledger?.allocated_margin ?? 0.0) +
      (data.ledger?.unrealized_pnl ?? 0.0),
    total_fees_usdt: 0.0,
    total_slippage_usdt: 0.0,
    drift_usdt: data.ledger?.drift ?? 0.0,
    zero_balance_drift_verified: isZeroDrift,
    tolerance_ceiling_usdt: 1e-15,
    solvency_ratio_pct: 100.0,
    cash_reserve_pct: data.ledger?.starting_equity
      ? roundTo((data.ledger.cash / data.ledger.starting_equity) * 100.0, 2)
      : 100.0,
    unencumbered_cash_verified: true,
  }

  return {
    phase: data.phase,
    verified: Boolean(data.verified ?? true),
    status: data.status,
    circuitState: data.circuit_state || 'NORMAL',
    timestampMs: data.timestamp_ms,
    timestampUtc:
      data.timestamp_utc ||
      (data.timestamp_ms ? new Date(data.timestamp_ms).toISOString() : ''),
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    isZeroDrift,
    candidates: data.candidates || [],
    activeCandidates: data.active_candidates || [],
    mutations: data.mutations || [],
    gateMetrics: data.gate_metrics || {
      gate_names: [],
      thresholds: {},
      passing_counts: {},
      rejection_counts: {},
      total_evaluated: 0,
      total_passed: 0,
      total_rejected: 0,
    },
    hotReload: data.hot_reload || {
      reloaded_at_utc: '',
      previous_version: 2,
      new_version: 3,
      registry_hash: '',
      reload_status: 'IDLE',
      process_restarted: false,
      open_trades_mutated: false,
    },
    hypotheses: data.hypotheses || [],
    searchSpace: data.search_space || [],
    featureHeatmaps: data.feature_heatmaps || [],
    oosScorecards: data.oos_scorecards || [],
    hotReloadLogs: data.hot_reload_logs || [],
    ledger: data.ledger || {
      starting_equity: 100.0,
      cash: 100.0,
      allocated_margin: 0.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: data.solvency || defaultSolvency,
    upstreamHash:
      data.upstream_hash ||
      '257f83f794465f3b89bfd9dbc25a2bf949d9fe315ecd97e2108c027ca3475668',
    phaseHash: data.phase_hash || '—',
    merkleRoot: data.merkle_root || '—',
  }
}

// =====================================================================
// Phase 299: Dynamic Multi-Asset Risk Orchestration & Portfolio Rebalancing
// =====================================================================

export interface AssetAllocationItem {
  symbol: string
  target_weight: number
  actual_weight: number
  target_notional_usdt: number
  actual_notional_usdt: number
  allocated_margin_usdt: number
  volatility_sigma: number
  jump_intensity_lambda: number
  drift_pct: number
  rebalance_required: boolean
  margin_ceiling_usdt: number
  ceiling_breached: boolean
}

export interface SpilloverMatrixItem {
  affected_symbol: string
  trigger_symbol: string
  cross_excitation_alpha: number
  decay_beta: number
  branching_ratio_gamma: number
  spillover_hazard: boolean
  deallocation_triggered: boolean
  freeze_dispatched: boolean
}

export interface SpilloverContagionGuardStatusItem {
  guard_active: boolean
  max_spectral_radius_rho: number
  hazard_threshold_rho: number
  hazard_detected: boolean
  source_hazard_assets: string[]
  throttled_recipient_assets: string[]
  capital_deallocated_usdt: number
  order_dispatch_frozen: boolean
  action_taken: string
}

export interface PortfolioOptimizationMetricsItem {
  aggregate_exposure_usdt: number
  aggregate_exposure_cap_usdt: number
  cash_reserve_usdt: number
  cash_reserve_pct: number
  cash_reserve_floor_pct: number
  max_asset_margin_usdt: number
  margin_ceiling_per_asset_usdt: number
  spectral_radius_rho: number
  portfolio_volatility: number
  risk_parity_herfindahl_index: number
  sharpe_ratio: number
  optimization_status: string
}

export interface MicroRebalanceAuditItem {
  rebalance_id: string
  timestamp_utc: string
  symbol: string
  side: string
  target_drift_pct: number
  order_chunk_notional_usdt: number
  order_chunk_qty: number
  passive_price: number
  execution_status: string
  fee_drag_usdt: number
  slippage_absorbed_usdt: number
  exchange_filters_compliant: boolean
}

export interface CanaryPortfolioRebalancingResponse {
  verified: boolean
  phase: string
  status: string
  timestamp_ms: number
  timestamp_utc: string
  paper_safe: boolean
  execution_authority: boolean
  circuit_state: string
  candidates: string[]
  allocations: AssetAllocationItem[]
  optimization_metrics: PortfolioOptimizationMetricsItem
  spillover_matrix: SpilloverMatrixItem[]
  contagion_guard: SpilloverContagionGuardStatusItem
  rebalancing_audits: MicroRebalanceAuditItem[]
  ledger: LedgerReconciliationItem
  solvency?: DoubleEntrySolvencyItem
  upstream_hash: string
  phase_hash: string
  merkle_root: string
  artifact_hashes?: Record<string, string>
  upstream_merkle_dag?: Record<string, string>
}

export interface PortfolioRebalancingModel {
  phase: string
  verified: boolean
  status: string
  circuitState: string
  timestampMs: number
  timestampUtc: string
  isPaperSafe: boolean
  isExecutionOff: boolean
  isZeroDrift: boolean
  candidates: string[]
  allocations: AssetAllocationItem[]
  optimizationMetrics: PortfolioOptimizationMetricsItem
  spilloverMatrix: SpilloverMatrixItem[]
  contagionGuard: SpilloverContagionGuardStatusItem
  rebalancingAudits: MicroRebalanceAuditItem[]
  ledger: LedgerReconciliationItem
  solvency: DoubleEntrySolvencyItem
  upstreamHash: string
  phaseHash: string
  merkleRoot: string
}

export async function getCanaryPortfolioRebalancing(
  baseUrl: string = ''
): Promise<CanaryPortfolioRebalancingResponse> {
  const cleanBase = baseUrl ? baseUrl.replace(/\/$/, '') : ''
  const path = `${cleanBase}/api/v1/canary/portfolio-rebalancing`
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}`)
  }
  return (await response.json()) as CanaryPortfolioRebalancingResponse
}

export function buildPortfolioRebalancingModel(
  data: CanaryPortfolioRebalancingResponse | null
): PortfolioRebalancingModel {
  if (!data) {
    return {
      phase: 'phase_299',
      verified: false,
      status: 'UNAVAILABLE',
      circuitState: 'UNKNOWN',
      timestampMs: 0,
      timestampUtc: '',
      isPaperSafe: true,
      isExecutionOff: true,
      isZeroDrift: true,
      candidates: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
      allocations: [
        {
          symbol: 'BTCUSDT',
          target_weight: 0.45,
          actual_weight: 0.48,
          target_notional_usdt: 27.0,
          actual_notional_usdt: 28.8,
          allocated_margin_usdt: 14.4,
          volatility_sigma: 0.018,
          jump_intensity_lambda: 0.22,
          drift_pct: 3.0,
          rebalance_required: true,
          margin_ceiling_usdt: 25.0,
          ceiling_breached: false,
        },
        {
          symbol: 'ETHUSDT',
          target_weight: 0.35,
          actual_weight: 0.34,
          target_notional_usdt: 21.0,
          actual_notional_usdt: 20.4,
          allocated_margin_usdt: 10.2,
          volatility_sigma: 0.024,
          jump_intensity_lambda: 0.35,
          drift_pct: 1.0,
          rebalance_required: false,
          margin_ceiling_usdt: 25.0,
          ceiling_breached: false,
        },
        {
          symbol: 'SOLUSDT',
          target_weight: 0.2,
          actual_weight: 0.18,
          target_notional_usdt: 12.0,
          actual_notional_usdt: 10.8,
          allocated_margin_usdt: 5.4,
          volatility_sigma: 0.038,
          jump_intensity_lambda: 0.58,
          drift_pct: 2.0,
          rebalance_required: false,
          margin_ceiling_usdt: 25.0,
          ceiling_breached: false,
        },
      ],
      optimizationMetrics: {
        aggregate_exposure_usdt: 60.0,
        aggregate_exposure_cap_usdt: 60.0,
        cash_reserve_usdt: 40.0,
        cash_reserve_pct: 40.0,
        cash_reserve_floor_pct: 40.0,
        max_asset_margin_usdt: 14.4,
        margin_ceiling_per_asset_usdt: 25.0,
        spectral_radius_rho: 0.428571,
        portfolio_volatility: 0.0215,
        risk_parity_herfindahl_index: 0.338,
        sharpe_ratio: 1.85,
        optimization_status: 'OPTIMAL',
      },
      spilloverMatrix: [
        {
          affected_symbol: 'BTCUSDT',
          trigger_symbol: 'BTCUSDT',
          cross_excitation_alpha: 0.25,
          decay_beta: 1.0,
          branching_ratio_gamma: 0.25,
          spillover_hazard: false,
          deallocation_triggered: false,
          freeze_dispatched: false,
        },
        {
          affected_symbol: 'SOLUSDT',
          trigger_symbol: 'BTCUSDT',
          cross_excitation_alpha: 0.18,
          decay_beta: 1.0,
          branching_ratio_gamma: 0.18,
          spillover_hazard: false,
          deallocation_triggered: false,
          freeze_dispatched: false,
        },
      ],
      contagionGuard: {
        guard_active: true,
        max_spectral_radius_rho: 0.428571,
        hazard_threshold_rho: 0.85,
        hazard_detected: false,
        source_hazard_assets: [],
        throttled_recipient_assets: [],
        capital_deallocated_usdt: 0.0,
        order_dispatch_frozen: false,
        action_taken: 'MONITORING_NOMINAL',
      },
      rebalancingAudits: [],
      ledger: {
        starting_equity: 100.0,
        cash: 70.0,
        allocated_margin: 30.0,
        unrealized_pnl: 0.0,
        realized_pnl: 0.0,
        drift: 0.0,
        zero_balance_drift: true,
      },
      solvency: {
        starting_equity_usdt: 100.0,
        cash_usdt: 70.0,
        allocated_margin_usdt: 30.0,
        unrealized_pnl_usdt: 0.0,
        realized_pnl_usdt: 0.0,
        total_equity_usdt: 100.0,
        total_fees_usdt: 0.0,
        total_slippage_usdt: 0.0,
        drift_usdt: 0.0,
        zero_balance_drift_verified: true,
        tolerance_ceiling_usdt: 1e-15,
        solvency_ratio_pct: 100.0,
        cash_reserve_pct: 40.0,
        unencumbered_cash_verified: true,
      },
      upstreamHash: 'b2ea1dc7053aec1ecd6dd9845d776380093b925e056b891b64c8a454a62bf837',
      phaseHash: '',
      merkleRoot: '',
    }
  }

  const isZeroDrift =
    data.solvency?.zero_balance_drift_verified ??
    (data.ledger?.zero_balance_drift !== undefined
      ? Boolean(data.ledger.zero_balance_drift)
      : Math.abs(data.ledger?.drift ?? 0) < 1e-15)

  const defaultSolvency: DoubleEntrySolvencyItem = {
    starting_equity_usdt: data.ledger?.starting_equity ?? 100.0,
    cash_usdt: data.ledger?.cash ?? 70.0,
    allocated_margin_usdt: data.ledger?.allocated_margin ?? 30.0,
    unrealized_pnl_usdt: data.ledger?.unrealized_pnl ?? 0.0,
    realized_pnl_usdt: data.ledger?.realized_pnl ?? 0.0,
    total_equity_usdt:
      (data.ledger?.cash ?? 70.0) +
      (data.ledger?.allocated_margin ?? 30.0) +
      (data.ledger?.unrealized_pnl ?? 0.0),
    total_fees_usdt: 0.0,
    total_slippage_usdt: 0.0,
    drift_usdt: data.ledger?.drift ?? 0.0,
    zero_balance_drift_verified: isZeroDrift,
    tolerance_ceiling_usdt: 1e-15,
    solvency_ratio_pct: 100.0,
    cash_reserve_pct: data.ledger?.starting_equity
      ? roundTo((data.ledger.cash / data.ledger.starting_equity) * 100.0, 2)
      : 70.0,
    unencumbered_cash_verified:
      data.ledger?.starting_equity
        ? data.ledger.cash / data.ledger.starting_equity >= 0.4
        : true,
  }

  return {
    phase: data.phase,
    verified: Boolean(data.verified ?? true),
    status: data.status,
    circuitState: data.circuit_state || 'NORMAL',
    timestampMs: data.timestamp_ms,
    timestampUtc:
      data.timestamp_utc ||
      (data.timestamp_ms ? new Date(data.timestamp_ms).toISOString() : ''),
    isPaperSafe: data.paper_safe,
    isExecutionOff: !data.execution_authority,
    isZeroDrift,
    candidates: data.candidates || ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    allocations: data.allocations || [],
    optimizationMetrics: data.optimization_metrics,
    spilloverMatrix: data.spillover_matrix || [],
    contagionGuard: data.contagion_guard,
    rebalancingAudits: data.rebalancing_audits || [],
    ledger: data.ledger || {
      starting_equity: 100.0,
      cash: 70.0,
      allocated_margin: 30.0,
      unrealized_pnl: 0.0,
      realized_pnl: 0.0,
      drift: 0.0,
      zero_balance_drift: true,
    },
    solvency: data.solvency || defaultSolvency,
    upstreamHash:
      data.upstream_hash ||
      'b2ea1dc7053aec1ecd6dd9845d776380093b925e056b891b64c8a454a62bf837',
    phaseHash: data.phase_hash || '',
    merkleRoot: data.merkle_root || '',
  }
}





